"""
evaluator.py — Multi-subtask evaluation engine for Task 5 PI network.

Aligned to PDF Task 5 subtasks.  Structure:
  5.1  Network topology KPIs
  5.2  Container / p-pack space requirements
  5.3  Transport time reduction  (numpy Monte Carlo simulation)
  5.4  Joint shipment illustrative trace
  5.5  OTD + reachable demand uplift
  5.6  Autonomy & relay readiness
  5.9  Shipment / truck / distance / cost / carbon emissions
  5.10 DC capacity sizing  (numpy simulation-backed)
  5.11 Transload cost analysis
  5.12 Overall profitability projection

Numpy-first pattern: pandas-in → numpy-compute → pandas-out.
Pure numpy kernels hold simulation inner loops; pandas used only for I/O + joins.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    # Geometry
    DETOUR_FACTOR, DRIVE_SPEED_KMH, MAX_SINGLE_DRIVER_HR, DETOUR_RATIO_MAX,
    DRIVE_SPEED_SIGMA_FRAC, DWELL_UNCERTAINTY_FRAC, DEFAULT_N_SIM, RANDOM_SEED,
    HUB_RELAY_DWELL_HR, HUB_CONSOL_DWELL_HR,
    # Costs
    TRUCK_L_EUR_KM, TRUCK_M_EUR_KM, TRUCK_S_EUR_KM,
    DC_FIXED_EUR_YEAR, DC_STORAGE_EUR, DC_THROUGHPUT_EUR,
    DC_INBOUND_PALLET_EUR, DC_OUTBOUND_PALLET_EUR, DC_UNIT_PICK_EUR,
    LASTMILE_METRO_1M_EUR, LASTMILE_METRO_250K_EUR, LASTMILE_METRO_SMALL_EUR,
    LASTMILE_NONMETRO_250KM_EUR, LASTMILE_NONMETRO_500KM_EUR, LASTMILE_NONMETRO_BEYOND_EUR,
    PI_PACK_COST_EUR, NON_PI_PACK_COST_EUR,
    HUB_RELAY_COST_EUR, HUB_CONSOL_COST_EUR,
    TRANSLOAD_COST_EUR, OCEAN_CONTAINER_EUR, OCEAN_SAVANNAH_ROTTERDAM_KM,
    # Carbon
    CO2_TRUCK_L_KG_KM, CO2_TRUCK_M_KG_KM, CO2_TRUCK_S_KG_KM, CO2_OCEAN_KG_KM_TEU,
    # p-pack / containers
    UNITS_PER_PALLET_NONPI, UNITS_PER_PALLET_PI,
    UNITS_PER_TEU_NONPI, UNITS_PER_TEU_PI,
    BOT_NONPI_VOL_CM3, BOT_PI_PACK_VOL_CM3,
    NONPI_PALLET_UTIL, PI_PALLET_UTIL,
    CONTAINER_VOL_CM3,
    # Demand / sizing
    CYBER_WEEK_ANNUAL_SHARE, CYBER_WEEK_DAYS, PEAK_DAILY_SHARE,
    # Revenue
    REVENUE_PER_UNIT_EUR,
)
from .hub_network import haversine_km, drive_time_hr


# ============================================================================
# PART 1 — Geometry helpers (re-exported for convenience)
# ============================================================================

def _co2_per_km(truck_class: str) -> float:
    return {"L": CO2_TRUCK_L_KG_KM, "M": CO2_TRUCK_M_KG_KM, "S": CO2_TRUCK_S_KG_KM}.get(
        truck_class, CO2_TRUCK_L_KG_KM
    )


def extract_dc_daily_totals(dc_daily_sim: pd.DataFrame) -> pd.DataFrame:
    if dc_daily_sim.empty:
        return pd.DataFrame(columns=["sim", "date", "dc_id", "daily_units"])
    daily = (
        dc_daily_sim.groupby(["sim", "date", "euro_dc_id"], as_index=False)["realized_units"]
        .sum()
        .rename(columns={"euro_dc_id": "dc_id", "realized_units": "daily_units"})
    )
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


# ============================================================================
# PART 2 — Task 5.1: Network topology KPIs
# ============================================================================

def compute_coverage(active_nodes: pd.DataFrame, lanes: pd.DataFrame) -> dict:
    """
    Coverage = % of DC/PORT → PERI_URBAN_HUB pairs reachable via lane graph (BFS).
    DEMAND_NONMETRO excluded: served directly from DC, not via hub network.
    Target ≥ 95%.
    """
    origin_nodes = set(active_nodes.loc[active_nodes["node_type"].isin({"PORT", "DC"}), "node_id"])
    dest_nodes   = set(active_nodes.loc[active_nodes["node_type"] == "PERI_URBAN_HUB", "node_id"])

    if not dest_nodes or not origin_nodes or lanes.empty:
        return {"coverage_pct": 0.0, "feasible_pairs": 0, "total_pairs": 0}

    adj: dict[str, set[str]] = {}
    for row in lanes[["origin_id", "dest_id"]].itertuples(index=False):
        adj.setdefault(row.origin_id, set()).add(row.dest_id)

    total = len(origin_nodes) * len(dest_nodes)
    feasible = 0
    for origin in origin_nodes:
        visited: set[str] = set()
        stack = [origin]
        while stack:
            n = stack.pop()
            if n in visited:
                continue
            visited.add(n)
            stack.extend(adj.get(n, set()) - visited)
        feasible += sum(1 for d in dest_nodes if d in visited)

    return {
        "coverage_pct":   round(feasible / total * 100, 2),
        "feasible_pairs": feasible,
        "total_pairs":    total,
    }


def compute_relay_readiness(lanes: pd.DataFrame) -> dict:
    """% lanes with relay_flag True. Target ≥ 80%."""
    if lanes.empty:
        return {"relay_readiness_pct": 0.0, "relay_lanes": 0, "total_lanes": 0}
    total = len(lanes)
    relay = int(lanes["relay_flag"].sum())
    return {
        "relay_readiness_pct": round(relay / total * 100, 2),
        "relay_lanes": relay,
        "total_lanes": total,
    }


def compute_dc_dc_connectivity(active_nodes: pd.DataFrame, lanes: pd.DataFrame) -> dict:
    """DC pairs with a direct DC_DC lane. Target 100% by 2028."""
    dcs = active_nodes.loc[active_nodes["node_type"] == "DC", "node_id"].tolist()
    if len(dcs) < 2:
        return {"dc_dc_connectivity_pct": 100.0, "connected_pairs": 0, "total_dc_pairs": 0}
    dc_dc = lanes[lanes["lane_type"] == "DC_DC"]
    connected = 0
    total = 0
    for i, a in enumerate(dcs):
        for b in dcs[i + 1:]:
            total += 1
            has = ((dc_dc["origin_id"] == a) & (dc_dc["dest_id"] == b)).any() or \
                  ((dc_dc["origin_id"] == b) & (dc_dc["dest_id"] == a)).any()
            if has:
                connected += 1
    return {
        "dc_dc_connectivity_pct": round(connected / total * 100, 2) if total else 100.0,
        "connected_pairs": connected,
        "total_dc_pairs": total,
    }


def compute_detour_summary(route_table: pd.DataFrame) -> dict:
    if route_table.empty or "detour_ratio" not in route_table.columns:
        return {"mean_detour": None, "max_detour": None, "pct_within_limit": None}
    dr = route_table["detour_ratio"].dropna()
    return {
        "mean_detour":       round(float(dr.mean()), 3),
        "median_detour":     round(float(dr.median()), 3),
        "max_detour":        round(float(dr.max()), 3),
        "pct_within_limit":  round(float((dr <= DETOUR_RATIO_MAX).mean() * 100), 2),
    }


# ============================================================================
# PART 3 — Task 5.2: Container / p-pack space requirements
# ============================================================================

def eval_52_container_requirements(annual_units: float) -> dict:
    """
    Task 5.2: Compare non-PI vs PI container/pallet requirements.

    Returns:
      - pallet counts (non-PI vs PI)
      - TEU counts (non-PI vs PI)
      - volume saved (cm³ and %)
      - cost saved on packaging (€)
      - container savings (€)
    """
    # Pallet counts
    pallets_nonpi = int(np.ceil(annual_units / UNITS_PER_PALLET_NONPI))
    pallets_pi    = int(np.ceil(annual_units / UNITS_PER_PALLET_PI))
    pallet_saving_pct = (pallets_nonpi - pallets_pi) / pallets_nonpi * 100

    # TEU counts (ocean shipment)
    teus_nonpi = int(np.ceil(annual_units / UNITS_PER_TEU_NONPI))
    teus_pi    = int(np.ceil(annual_units / UNITS_PER_TEU_PI))
    teu_saving_pct = (teus_nonpi - teus_pi) / max(teus_nonpi, 1) * 100

    # Volume per unit
    vol_saving_per_unit_cm3 = BOT_NONPI_VOL_CM3 - BOT_PI_PACK_VOL_CM3
    vol_saving_pct = vol_saving_per_unit_cm3 / BOT_NONPI_VOL_CM3 * 100

    # Packaging cost saving (€)
    pack_cost_saving_eur = (NON_PI_PACK_COST_EUR - PI_PACK_COST_EUR) * annual_units

    # Container cost saving (€)
    container_saving_eur = (teus_nonpi - teus_pi) * OCEAN_CONTAINER_EUR

    return {
        "annual_units":             annual_units,
        "pallets_nonpi":            pallets_nonpi,
        "pallets_pi":               pallets_pi,
        "pallet_saving_pct":        round(pallet_saving_pct, 1),
        "teus_nonpi":               teus_nonpi,
        "teus_pi":                  teus_pi,
        "teu_saving_pct":           round(teu_saving_pct, 1),
        "vol_per_unit_nonpi_cm3":   BOT_NONPI_VOL_CM3,
        "vol_per_unit_pi_cm3":      BOT_PI_PACK_VOL_CM3,
        "vol_saving_per_unit_cm3":  vol_saving_per_unit_cm3,
        "vol_saving_pct":           round(vol_saving_pct, 1),
        "pack_cost_saving_eur":     round(pack_cost_saving_eur, 0),
        "container_saving_eur":     round(container_saving_eur, 0),
    }


# ============================================================================
# PART 4 — Task 5.3: Route-backed OTD profile
# ============================================================================

def build_otd_profile(service_matrix: pd.DataFrame) -> pd.DataFrame:
    """
    Task 5.3: Deterministic end-to-end PI OTD profile.

    This uses the exact service-matrix OTD that drives demand conversion:
      OTD = route travel elapsed + relay/consolidation dwell + PI last mile

    No separate attainment/promise layer is computed.
    """
    if service_matrix.empty:
        return pd.DataFrame()

    profile = service_matrix.copy()
    if "last_mile_band" not in profile.columns:
        profile["last_mile_band"] = pd.NA

    profile["service_class"] = np.where(
        profile["node_type"].astype(str).str.lower() == "metro",
        "METRO_" + profile["pop_bracket"].fillna("UNKNOWN").astype(str),
        profile["last_mile_band"].fillna("NONMETRO_UNKNOWN").astype(str),
    )

    cols = [
        "year",
        "node_id",
        "node_type",
        "service_class",
        "pop_bracket",
        "country",
        "assigned_dc_id",
        "route_id",
        "service_mode",
        "route_backed",
        "n_relay_hubs",
        "n_consol_hubs",
        "route_drive_hr",
        "total_hub_dwell_hr",
        "travel_elapsed_hr",
        "last_mile_hr",
        "otd_hours",
        "otd_bucket",
        "purchase_prob",
        "annual_potential_units",
        "annual_realized_units",
    ]
    return profile[[c for c in cols if c in profile.columns]].reset_index(drop=True)


def summarise_otd_by_class(otd_df: pd.DataFrame) -> pd.DataFrame:
    if otd_df.empty:
        return pd.DataFrame()

    grp = otd_df.groupby("service_class", dropna=False).agg(
        node_type=("node_type", "first"),
        n_nodes=("node_id", "count"),
        route_backed_pct=("route_backed", "mean"),
        mean_travel_elapsed_hr=("travel_elapsed_hr", "mean"),
        mean_last_mile_hr=("last_mile_hr", "mean"),
        mean_otd_hr=("otd_hours", "mean"),
        p50_otd_hr=("otd_hours", "median"),
        p95_otd_hr=("otd_hours", lambda s: float(np.percentile(s, 95))),
        mean_purchase_prob=("purchase_prob", "mean"),
        annual_realized_units=("annual_realized_units", "sum"),
    ).reset_index()
    grp["route_backed_pct"] = (grp["route_backed_pct"] * 100).round(2)
    for col in [
        "mean_travel_elapsed_hr",
        "mean_last_mile_hr",
        "mean_otd_hr",
        "p50_otd_hr",
        "p95_otd_hr",
        "mean_purchase_prob",
        "annual_realized_units",
    ]:
        grp[col] = grp[col].round(3)
    return grp


# ============================================================================
# PART 5 — Task 5.4: Joint shipment illustrative trace
# ============================================================================

def trace_joint_shipment(
    origin_id: str,
    dest_id: str,
    lanes: pd.DataFrame,
    active_nodes: pd.DataFrame,
) -> list[dict]:
    """
    Task 5.4: Build a step-by-step shipment trace from origin to dest.

    Finds the shortest-elapsed-time path via BFS (priority by elapsed time),
    returns list of steps: {step, from_id, to_id, lane_type, drive_hr, dwell_hr,
    cumulative_elapsed_hr, truck_class, road_km, co2_kg}.
    """
    if lanes.empty:
        return []

    import heapq
    # Build adjacency: node → [(elapsed, dest, lane_row)]
    adj: dict[str, list] = {}
    for row in lanes.itertuples(index=False):
        adj.setdefault(row.origin_id, []).append((
            row.elapsed_hr, row.dest_id, row
        ))

    # Dijkstra on elapsed time
    dist: dict[str, float] = {origin_id: 0.0}
    prev: dict[str, tuple | None] = {origin_id: None}
    heap = [(0.0, origin_id)]

    while heap:
        d, u = heapq.heappop(heap)
        if d > dist.get(u, float("inf")):
            continue
        for elapsed_edge, v, lane_row in adj.get(u, []):
            nd = d + elapsed_edge
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = (u, lane_row)
                heapq.heappush(heap, (nd, v))

    if dest_id not in dist:
        return []

    # Reconstruct path
    path: list[tuple] = []
    cur = dest_id
    while prev.get(cur) is not None:
        u, lr = prev[cur]
        path.append((u, cur, lr))
        cur = u
    path.reverse()

    steps = []
    cumulative = 0.0
    for step_no, (frm, to, lr) in enumerate(path, 1):
        dt  = lr.drive_time_hr
        dw  = lr.elapsed_hr - lr.drive_time_hr
        co2 = lr.road_km * _co2_per_km(lr.truck_class)
        cumulative += lr.elapsed_hr
        steps.append({
            "step":               step_no,
            "from_id":            frm,
            "to_id":              to,
            "lane_type":          lr.lane_type,
            "drive_hr":           round(dt, 3),
            "dwell_hr":           round(dw, 3),
            "cumulative_elapsed_hr": round(cumulative, 3),
            "truck_class":        lr.truck_class,
            "road_km":            round(lr.road_km, 1),
            "co2_kg":             round(co2, 2),
        })
    return steps


# ============================================================================
# PART 6 — Task 5.5: OTD + reachable demand uplift
# ============================================================================

def eval_55_demand_uplift(
    baseline_assignment: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """
    Task 5.5: Compute PI purchase probability and reachable-demand uplift
    versus non-PI baseline per metro segment.

    PI purchase_prob ≈ 1.00 for all metro, 0.99 for non-metro.
    Non-PI purchase_prob comes from assignment CSV.

    Returns DataFrame: node_id, pop_bracket, units, nonpi_purchase_prob,
      pi_purchase_prob, nonpi_reachable, pi_reachable, uplift_pct
    """
    base = baseline_assignment[
        (baseline_assignment["year"] == year)
        & (baseline_assignment["node_type"].isin(["metro", "non_metro"]))
    ].copy()
    if base.empty:
        return pd.DataFrame()

    # Assign PI purchase prob by segment
    def _pi_prob(row) -> float:
        if row["node_type"] == "metro":
            return 1.00
        else:
            otd_bucket = row.get("otd_bucket", 2)
            if otd_bucket <= 1:
                return 0.99
            return 0.99

    base["pi_purchase_prob"] = base.apply(_pi_prob, axis=1)
    base["pi_reachable"]     = base["units"] * base["pi_purchase_prob"]
    base = base.rename(columns={
        "purchase_prob":    "nonpi_purchase_prob",
        "reachable_units":  "nonpi_reachable",
    })

    base["uplift_pct"] = (
        (base["pi_reachable"] - base["nonpi_reachable"])
        / base["nonpi_reachable"].clip(lower=1) * 100
    ).round(2)

    cols = ["node_id", "node_type", "units",
            "nonpi_purchase_prob", "pi_purchase_prob",
            "nonpi_reachable", "pi_reachable", "uplift_pct"]
    return base[[c for c in cols if c in base.columns]].reset_index(drop=True)


def summarise_demand_uplift(uplift_df: pd.DataFrame) -> dict:
    if uplift_df.empty:
        return {}
    total_nonpi = float(uplift_df["nonpi_reachable"].sum())
    total_pi    = float(uplift_df["pi_reachable"].sum())
    return {
        "nonpi_reachable_total":  round(total_nonpi, 0),
        "pi_reachable_total":     round(total_pi, 0),
        "demand_uplift_pct":      round((total_pi - total_nonpi) / total_nonpi * 100, 2),
        "revenue_uplift_eur":     round((total_pi - total_nonpi) * REVENUE_PER_UNIT_EUR, 0),
    }


# ============================================================================
# PART 7 — Task 5.6: Autonomy & relay readiness
# ============================================================================

def eval_56_autonomy(active_nodes: pd.DataFrame, lanes: pd.DataFrame, year: int) -> dict:
    """
    Task 5.6: Evaluate relay readiness and driver-autonomy targets.
    - Relay readiness: % lanes with relay_flag True
    - Driver continuity: % DC-DC lanes that require a relay stop (>11hr single leg)
    - Hub dual-role: % PERI_URBAN_HUBs that also serve as relay stops
    """
    rr = compute_relay_readiness(lanes)

    dc_dc = lanes[lanes["lane_type"] == "DC_DC"]
    relay_needed = int(dc_dc["relay_flag"].sum()) if not dc_dc.empty else 0
    driver_relay_pct = (
        relay_needed / len(dc_dc) * 100 if len(dc_dc) > 0 else 0
    )

    # Hubs that appear as relay stops in any RELAY_HUB lane
    relay_hub_lane = lanes[lanes["lane_type"] == "RELAY_HUB"]
    relay_dest_ids = set(relay_hub_lane["dest_id"]) if not relay_hub_lane.empty else set()
    total_hubs = int((active_nodes["node_type"] == "PERI_URBAN_HUB").sum())
    dual_role_count = len(
        relay_dest_ids & set(active_nodes.loc[active_nodes["node_type"] == "PERI_URBAN_HUB", "node_id"])
    )

    return {
        "year": year,
        "relay_readiness_pct":        rr["relay_readiness_pct"],
        "dc_dc_relay_required_pct":   round(driver_relay_pct, 2),
        "dual_role_hubs":             dual_role_count,
        "total_hubs":                 total_hubs,
        "dual_role_pct":              round(dual_role_count / max(total_hubs, 1) * 100, 2),
    }


# ============================================================================
# PART 8 — Task 5.9: Shipment / truck / distance / cost / carbon
# ============================================================================

def _lastmile_cost_per_unit(node_type: str, pop_bracket: str | float, last_mile_hr: float) -> float:
    if str(node_type).lower() == "metro":
        if pd.isna(pop_bracket):
            return LASTMILE_METRO_SMALL_EUR
        if pop_bracket == "1M+":
            return LASTMILE_METRO_1M_EUR
        if pop_bracket == "250K-1M":
            return LASTMILE_METRO_250K_EUR
        return LASTMILE_METRO_SMALL_EUR

    if last_mile_hr <= 2.5:
        return LASTMILE_NONMETRO_250KM_EUR
    if last_mile_hr <= 5.0:
        return LASTMILE_NONMETRO_500KM_EUR
    return LASTMILE_NONMETRO_BEYOND_EUR


def _service_units_column(service_matrix: pd.DataFrame) -> str:
    if "pi_realized_units" in service_matrix.columns:
        return "pi_realized_units"
    return "annual_realized_units"


def _estimate_dc_operating_costs(
    annual_units_by_dc: dict[str, float],
    units_per_pallet: int,
) -> pd.DataFrame:
    records = []
    for dc_id, annual_units in annual_units_by_dc.items():
        peak_daily_units = annual_units * PEAK_DAILY_SHARE
        throughput_cap = int(np.ceil(peak_daily_units / max(units_per_pallet, 1))) * 2
        storage_positions = int(np.ceil((annual_units / 365.0) * 14.0 / max(units_per_pallet, 1)))

        storage_cost = storage_positions * DC_STORAGE_EUR
        throughput_cost = throughput_cap * DC_THROUGHPUT_EUR
        inbound_cost = int(np.ceil(annual_units / max(units_per_pallet, 1))) * DC_INBOUND_PALLET_EUR
        outbound_cost = int(np.ceil(annual_units / max(units_per_pallet, 1))) * DC_OUTBOUND_PALLET_EUR
        pick_cost = annual_units * DC_UNIT_PICK_EUR
        dc_total_cost = (
            DC_FIXED_EUR_YEAR
            + storage_cost
            + throughput_cost
            + inbound_cost
            + outbound_cost
            + pick_cost
        )

        records.append(
            {
                "dc_id": dc_id,
                "annual_units": annual_units,
                "throughput_cap_pallets": throughput_cap,
                "storage_positions": storage_positions,
                "dc_total_cost_eur": dc_total_cost,
            }
        )

    return pd.DataFrame(records)


def estimate_service_lastmile_cost(service_matrix: pd.DataFrame) -> float:
    if service_matrix.empty:
        return 0.0
    units_col = _service_units_column(service_matrix)

    per_unit_cost = service_matrix.apply(
        lambda row: _lastmile_cost_per_unit(
            row.get("node_type", ""),
            row.get("pop_bracket", np.nan),
            float(row.get("last_mile_hr", 0.0)),
        ),
        axis=1,
    )
    return float((per_unit_cost * service_matrix[units_col]).sum())


def estimate_nonpi_baseline_costs(
    baseline_assignment: pd.DataFrame,
    nodes: pd.DataFrame | None = None,
) -> dict:
    if baseline_assignment.empty:
        return {}

    base = baseline_assignment.copy()
    if nodes is not None and not nodes.empty and "pop_bracket" in nodes.columns:
        node_lookup = (
            nodes[["node_id", "pop_bracket"]]
            .drop_duplicates(subset=["node_id"])
            .set_index("node_id")["pop_bracket"]
        )
        base["pop_bracket"] = base["node_id"].map(node_lookup)
    else:
        base["pop_bracket"] = np.nan

    base["annual_units"] = base["reachable_units"].fillna(0.0)
    base["road_km"] = base["drive_time_hr"].fillna(0.0) * DRIVE_SPEED_KMH / max(DETOUR_FACTOR, 1e-9)
    base["truckloads"] = np.ceil(base["annual_units"] / max(UNITS_PER_PALLET_NONPI, 1))
    base["middle_mile_cost_eur"] = base["road_km"] * TRUCK_M_EUR_KM * base["truckloads"]
    base["lastmile_unit_cost_eur"] = base.apply(
        lambda row: _lastmile_cost_per_unit(
            row.get("node_type", ""),
            row.get("pop_bracket", np.nan),
            float(row.get("last_mile_hours_final", row.get("last_mile_hours", 0.0)) or 0.0),
        ),
        axis=1,
    )
    base["lastmile_cost_eur"] = base["lastmile_unit_cost_eur"] * base["annual_units"]

    annual_units_by_dc = base.groupby("assigned_cand")["annual_units"].sum().to_dict()
    ocean_cost_eur = sum(
        np.ceil(units / max(UNITS_PER_TEU_NONPI, 1)) * OCEAN_CONTAINER_EUR
        for units in annual_units_by_dc.values()
    )
    dc_cost_df = _estimate_dc_operating_costs(annual_units_by_dc, units_per_pallet=UNITS_PER_PALLET_NONPI)

    total_units = float(base["annual_units"].sum())
    middle_mile_cost = float(base["middle_mile_cost_eur"].sum())
    lastmile_cost = float(base["lastmile_cost_eur"].sum())
    packaging_cost = total_units * NON_PI_PACK_COST_EUR
    dc_cost = float(dc_cost_df["dc_total_cost_eur"].sum()) if not dc_cost_df.empty else 0.0
    total_transport = middle_mile_cost + ocean_cost_eur

    return {
        "annual_nonpi_units": total_units,
        "nonpi_middle_mile_cost_eur": middle_mile_cost,
        "nonpi_ocean_cost_eur": ocean_cost_eur,
        "nonpi_transport_eur": total_transport,
        "nonpi_lastmile_cost_eur": lastmile_cost,
        "nonpi_pack_cost_eur": packaging_cost,
        "nonpi_dc_cost_eur": dc_cost,
        "nonpi_total_cost_eur": total_transport + lastmile_cost + packaging_cost + dc_cost,
    }


def _allocate_lane_flows(
    lanes: pd.DataFrame,
    routes: pd.DataFrame,
    service_matrix: pd.DataFrame,
    annual_units_by_dc: dict[str, float],
) -> dict[str, float]:
    lane_flow: dict[str, float] = {}
    if not service_matrix.empty and not routes.empty:
        units_col = _service_units_column(service_matrix)
        route_flow = (
            service_matrix.dropna(subset=["route_id"])
            .groupby("route_id")[units_col]
            .sum()
        )
        route_lookup = routes.set_index("route_id")["path_lane_ids"].to_dict()
        for route_id, flow_units in route_flow.items():
            lane_ids = str(route_lookup.get(route_id, "")).split("|")
            for lane_id in lane_ids:
                if lane_id:
                    lane_flow[lane_id] = lane_flow.get(lane_id, 0.0) + float(flow_units)

    for dc_id, annual_units in annual_units_by_dc.items():
        port_lane = f"PORT_NL_rotterdam__{dc_id}"
        if port_lane in set(lanes["lane_id"]):
            lane_flow[port_lane] = lane_flow.get(port_lane, 0.0) + float(annual_units)

    return lane_flow


def eval_59_lane_cost_carbon(
    lanes: pd.DataFrame,
    routes: pd.DataFrame,
    service_matrix: pd.DataFrame,
    annual_units_by_dc: dict[str, float],
    year: int,
) -> pd.DataFrame:
    """
    Task 5.9: Cost the actual routed PI flows instead of splitting each DC's
    annual demand uniformly across all outbound lanes.
    """
    if lanes.empty:
        return pd.DataFrame()

    df = lanes.copy()
    lane_flow = _allocate_lane_flows(lanes, routes, service_matrix, annual_units_by_dc)
    df["annual_flow"] = df["lane_id"].map(lane_flow).fillna(0.0)
    df = df[df["annual_flow"] > 0].copy()
    if df.empty:
        return pd.DataFrame()

    cost_per_km_map = {"L": TRUCK_L_EUR_KM, "M": TRUCK_M_EUR_KM, "S": TRUCK_S_EUR_KM}
    df["cost_per_km"] = df["truck_class"].map(cost_per_km_map).fillna(TRUCK_L_EUR_KM)
    df["truckloads"] = np.ceil(df["annual_flow"] / max(UNITS_PER_PALLET_PI, 1))
    df["transport_cost_eur"] = (
        df["road_km"] * df["cost_per_km"] * df["truckloads"]
    ).round(2)

    co2_map = {"L": CO2_TRUCK_L_KG_KM, "M": CO2_TRUCK_M_KG_KM, "S": CO2_TRUCK_S_KG_KM}
    df["co2_kg_per_km"] = df["truck_class"].map(co2_map).fillna(CO2_TRUCK_L_KG_KM)
    df["co2_kg"] = (df["road_km"] * df["co2_kg_per_km"] * df["truckloads"]).round(1)

    ocean_mask = df["lane_type"] == "PORT_DC"
    if ocean_mask.any():
        teus = np.ceil(df.loc[ocean_mask, "annual_flow"] / max(UNITS_PER_TEU_PI, 1))
        df.loc[ocean_mask, "co2_kg"] = (
            OCEAN_SAVANNAH_ROTTERDAM_KM * CO2_OCEAN_KG_KM_TEU * teus
        ).round(1)
        df.loc[ocean_mask, "transport_cost_eur"] = (
            teus * OCEAN_CONTAINER_EUR
        ).round(2)
        df.loc[ocean_mask, "truckloads"] = teus  # show TEU count, not pallet-derived count

    df["year"] = year
    return df[[
        "year", "lane_id", "lane_type", "truck_class",
        "road_km", "drive_time_hr", "relay_flag",
        "annual_flow", "truckloads", "transport_cost_eur", "co2_kg",
    ]]


def summarise_cost_carbon(
    lane_cost_df: pd.DataFrame,
    total_units: float | None = None,
) -> dict:
    """Aggregate cost and carbon totals from eval_59_lane_cost_carbon output.

    total_units: delivered PI units (from service_matrix), used as per-unit
    denominator.  Falls back to sum of lane-level annual_flow when not supplied
    (legacy behaviour, but incorrect for multi-leg routes).
    """
    if lane_cost_df.empty:
        return {}
    total_cost = float(lane_cost_df["transport_cost_eur"].sum())
    total_co2  = float(lane_cost_df["co2_kg"].sum())
    total_flow = float(lane_cost_df["annual_flow"].sum())
    unit_denom = total_units if (total_units and total_units > 0) else max(total_flow, 1)
    by_type = lane_cost_df.groupby("lane_type")[["transport_cost_eur", "co2_kg"]].sum()
    return {
        "total_transport_cost_eur":  round(total_cost, 0),
        "total_co2_kg":              round(total_co2, 0),
        "co2_per_unit_kg":           round(total_co2 / unit_denom, 3),
        "cost_per_unit_eur":         round(total_cost / unit_denom, 3),
        "by_lane_type":              by_type.to_dict(),
    }


# ============================================================================
# PART 9 — Task 5.10: DC capacity sizing (simulation-backed)
# ============================================================================

def eval_510_dc_capacity_sizing(
    dc_daily_sim: pd.DataFrame,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    Task 5.10: Size DC capacity from simulator-backed daily demand instead of
    annual shortcuts.
    """
    daily = extract_dc_daily_totals(dc_daily_sim)
    if daily.empty:
        return pd.DataFrame()

    annual = (
        daily.groupby(["sim", "dc_id"], as_index=False)["daily_units"]
        .sum()
        .rename(columns={"daily_units": "annual_units"})
    )
    peak = (
        daily.groupby(["sim", "dc_id"], as_index=False)["daily_units"]
        .max()
        .rename(columns={"daily_units": "peak_daily_units"})
    )
    merged = annual.merge(peak, on=["sim", "dc_id"], how="left")

    records = []
    for dc_id, grp in merged.groupby("dc_id"):
        annual_samples = grp["annual_units"].to_numpy(dtype=float)
        peak_samples = grp["peak_daily_units"].to_numpy(dtype=float)

        annual_units = float(annual_samples.mean())
        p50_units = float(np.percentile(peak_samples, 50))
        p95_units = float(np.percentile(peak_samples, 95))
        p99_units = float(np.percentile(peak_samples, 99))

        p95_pallets = int(np.ceil(p95_units / max(UNITS_PER_PALLET_PI, 1)))
        throughput_cap = p95_pallets * 2
        storage_positions = int(
            np.ceil(np.percentile(annual_samples, 95) / 365.0 * 14.0 / max(UNITS_PER_PALLET_PI, 1))
        )

        storage_cost = storage_positions * DC_STORAGE_EUR
        throughput_cost = throughput_cap * DC_THROUGHPUT_EUR
        inbound_cost = int(np.ceil(annual_units / max(UNITS_PER_PALLET_PI, 1))) * DC_INBOUND_PALLET_EUR
        outbound_cost = int(np.ceil(annual_units / max(UNITS_PER_PALLET_PI, 1))) * DC_OUTBOUND_PALLET_EUR
        pick_cost = annual_units * DC_UNIT_PICK_EUR
        dc_total_cost = (
            DC_FIXED_EUR_YEAR
            + storage_cost
            + throughput_cost
            + inbound_cost
            + outbound_cost
            + pick_cost
        )

        records.append(
            {
                "dc_id": dc_id,
                "annual_units": round(annual_units, 0),
                "mean_peak_daily_units": round(float(peak_samples.mean()), 0),
                "p50_peak_daily_units": round(p50_units, 0),
                "p95_peak_daily_units": round(p95_units, 0),
                "p99_peak_daily_units": round(p99_units, 0),
                "throughput_cap_pallets": throughput_cap,
                "storage_positions": storage_positions,
                "dc_fixed_cost_eur": DC_FIXED_EUR_YEAR,
                "dc_storage_cost_eur": round(storage_cost, 0),
                "dc_throughput_cost_eur": round(throughput_cost, 0),
                "dc_pick_cost_eur": round(pick_cost, 0),
                "dc_total_cost_eur": round(dc_total_cost, 0),
            }
        )

    return pd.DataFrame(records)


# ============================================================================
# PART 10 — Task 5.11: Transload cost
# ============================================================================

def eval_511_transload_cost(annual_units: float, n_transload_centers: int = 2) -> dict:
    """
    Task 5.11: Transload handling cost at PI transload centers
    (Savannah export + Rotterdam import = 2 centers).
    """
    cost_per_unit = TRANSLOAD_COST_EUR * n_transload_centers
    total_cost    = annual_units * cost_per_unit
    vs_nonpi_savings = 0   # transload cost is additive to PI; packaging saving offsets it
    return {
        "n_transload_centers":  n_transload_centers,
        "transload_cost_per_unit_eur": round(cost_per_unit, 2),
        "total_transload_cost_eur":    round(total_cost, 0),
    }


# ============================================================================
# PART 11 — Task 5.12: Overall profitability projection
# ============================================================================

def eval_512_profitability(
    year: int,
    annual_pi_units: float,
    dc_cost_df: pd.DataFrame,
    lane_cost_df: pd.DataFrame,
    transload_dict: dict,
    service_matrix: pd.DataFrame | None = None,
) -> dict:
    """
    Task 5.12: PI-only profitability summary.
    """
    pi_revenue = annual_pi_units * REVENUE_PER_UNIT_EUR

    total_dc_cost = float(dc_cost_df["dc_total_cost_eur"].sum()) if not dc_cost_df.empty else 0

    total_transport = float(lane_cost_df["transport_cost_eur"].sum()) if not lane_cost_df.empty else 0

    transload_total = transload_dict.get("total_transload_cost_eur", 0)
    pi_pack_cost = annual_pi_units * PI_PACK_COST_EUR

    pi_lastmile_cost = estimate_service_lastmile_cost(service_matrix) if service_matrix is not None else 0.0
    hub_relay_total = 0.0
    hub_consol_total = 0.0
    if service_matrix is not None and not service_matrix.empty:
        units_col = _service_units_column(service_matrix)
        hub_relay_total = float(
            (service_matrix[units_col] * service_matrix["n_relay_hubs"] * HUB_RELAY_COST_EUR).sum()
        )
        hub_consol_total = float(
            (service_matrix[units_col] * service_matrix["n_consol_hubs"] * HUB_CONSOL_COST_EUR).sum()
        )

    total_pi_cost = (
        total_dc_cost
        + total_transport
        + pi_pack_cost
        + transload_total
        + hub_relay_total
        + hub_consol_total
        + pi_lastmile_cost
    )

    pi_margin = pi_revenue - total_pi_cost

    return {
        "year": year,
        "pi_units": round(annual_pi_units, 0),
        "pi_revenue_eur": round(pi_revenue, 0),
        "total_dc_cost_eur": round(total_dc_cost, 0),
        "total_transport_eur": round(total_transport, 0),
        "pi_lastmile_cost_eur": round(pi_lastmile_cost, 0),
        "pi_pack_cost_eur": round(pi_pack_cost, 0),
        "transload_cost_eur": round(transload_total, 0),
        "hub_relay_cost_eur": round(hub_relay_total, 0),
        "hub_consol_cost_eur": round(hub_consol_total, 0),
        "total_pi_cost_eur": round(total_pi_cost, 0),
        "pi_margin_eur": round(pi_margin, 0),
        "pi_margin_pct": round(pi_margin / max(pi_revenue, 1.0) * 100, 2),
    }


# ============================================================================
# PART 12 — Master compute function (called by pipeline.py)
# ============================================================================

def compute_all_kpis(
    year: int,
    active_nodes: pd.DataFrame,
    lanes: pd.DataFrame,
    routes: pd.DataFrame | None = None,
    service_matrix: pd.DataFrame | None = None,
    lane_cost_df: pd.DataFrame | None = None,
    total_pi_units: float | None = None,
) -> dict:
    """
    Compute all Task 5 KPIs for a given year.
    Returns flat dict for the KPI summary table.
    """
    kpis: dict = {"year": year}

    # ---- Node/lane counts ----
    kpis["n_nodes_total"] = len(active_nodes)
    kpis["n_port"] = int((active_nodes["node_type"] == "PORT").sum())
    kpis["n_dc"] = int((active_nodes["node_type"] == "DC").sum())
    kpis["n_peri_urban_hub"] = int((active_nodes["node_type"] == "PERI_URBAN_HUB").sum())
    # Legacy BORDER_RELAY_HUB rows are folded into relay hub counts.
    kpis["n_relay_hub"] = int(active_nodes["node_type"].isin(["RELAY_HUB", "BORDER_RELAY_HUB"]).sum())
    kpis["n_demand_nonmetro"] = int((active_nodes["node_type"] == "DEMAND_NONMETRO").sum())
    kpis["n_lanes_total"] = len(lanes)

    # ---- 5.1 topology ----
    kpis.update(compute_coverage(active_nodes, lanes))
    kpis.update(compute_detour_summary(routes if routes is not None else lanes))
    kpis.update(compute_relay_readiness(lanes))
    kpis.update(compute_dc_dc_connectivity(active_nodes, lanes))

    # ---- 5.6 autonomy ----
    aut = eval_56_autonomy(active_nodes, lanes, year)
    kpis["dual_role_hubs"]   = aut["dual_role_hubs"]
    kpis["dual_role_pct"]    = aut["dual_role_pct"]

    if service_matrix is not None and not service_matrix.empty:
        kpis["mean_route_elapsed_hr"] = round(float(service_matrix["travel_elapsed_hr"].mean()), 3)
        kpis["mean_service_otd_hr"] = round(float(service_matrix["otd_hours"].mean()), 3)
        kpis["p95_service_otd_hr"] = round(float(np.percentile(service_matrix["otd_hours"], 95)), 3)
        kpis["mean_purchase_prob"] = round(float(service_matrix["purchase_prob"].mean()), 4)
        kpis["route_backed_service_pct"] = round(float(service_matrix["route_backed"].mean() * 100), 2)

    if lane_cost_df is not None and not lane_cost_df.empty:
        cc = summarise_cost_carbon(lane_cost_df, total_units=total_pi_units)
        kpis["total_transport_cost_eur"] = cc.get("total_transport_cost_eur")
        kpis["total_co2_kg"]             = cc.get("total_co2_kg")
        kpis["co2_per_unit_kg"]          = cc.get("co2_per_unit_kg")
        kpis["transport_cost_per_unit"]  = cc.get("cost_per_unit_eur")

    return kpis
