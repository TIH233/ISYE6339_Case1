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
from pathlib import Path

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
    LASTMILE_NONMETRO_250KM_EUR,
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
    # PI OTD
    PI_OTD_BY_SEGMENT,
)
from .hub_network import haversine_km, drive_time_hr


# ============================================================================
# PART 1 — Geometry helpers (re-exported for convenience)
# ============================================================================

def _co2_per_km(truck_class: str) -> float:
    return {"L": CO2_TRUCK_L_KG_KM, "M": CO2_TRUCK_M_KG_KM, "S": CO2_TRUCK_S_KG_KM}.get(
        truck_class, CO2_TRUCK_L_KG_KM
    )


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


def compute_detour_summary(lanes: pd.DataFrame) -> dict:
    if lanes.empty or "detour_ratio" not in lanes.columns:
        return {"mean_detour": None, "max_detour": None, "pct_within_limit": None}
    dr = lanes["detour_ratio"].dropna()
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
# PART 4 — Task 5.3: Transport time simulation (numpy Monte Carlo)
# ============================================================================

def simulate_otd_attainment(
    direct_lanes: pd.DataFrame,
    hub_brackets: pd.DataFrame,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    Task 5.3: Monte Carlo simulation of PI OTD promise attainment.

    For each DC→PERI_URBAN_HUB direct lane, simulate n_sim trips:
      - Drive speed: Normal(100 km/h, σ=10 km/h) → drive_time uncertainty
      - Hub dwell: Uniform(0.75, 1.25) × nominal dwell
    Check if total elapsed ≤ PI promise (4/2/1 hr by pop_bracket).

    Pattern: pandas-in → numpy-compute → pandas-out.

    Returns DataFrame: node_id, pop_bracket, pi_promise_hr, mean_drive_hr,
      attainment_rate, p5_elapsed_hr, p50_elapsed_hr, p95_elapsed_hr
    """
    if direct_lanes.empty or hub_brackets.empty:
        return pd.DataFrame()

    df = direct_lanes.merge(hub_brackets[["node_id", "pop_bracket"]], on="node_id", how="left")
    df = df.dropna(subset=["pop_bracket"])
    if df.empty:
        return pd.DataFrame()

    # PI promise lookup
    promise_map = {"1M+": 4.0, "250K-1M": 2.0, "<250K": 1.0}
    df["pi_promise_hr"] = df["pop_bracket"].map(promise_map).fillna(4.0)

    # ---- numpy kernel ----
    rng = np.random.default_rng(seed)
    n_hubs = len(df)

    base_drive  = df["drive_time_hr"].values                    # (n_hubs,)
    base_dwell  = np.full(n_hubs, HUB_RELAY_DWELL_HR)          # (n_hubs,)
    promises    = df["pi_promise_hr"].values                     # (n_hubs,)
    road_km     = df["road_km"].values                           # (n_hubs,)

    # Speed factor: Normal(1, sigma) — lower = slower → more time
    speed_factor  = rng.normal(1.0, DRIVE_SPEED_SIGMA_FRAC, size=(n_sim, n_hubs))
    speed_factor  = np.clip(speed_factor, 0.5, 1.8)

    # Dwell multiplier: Uniform(1-frac, 1+frac)
    dwell_factor  = rng.uniform(
        1.0 - DWELL_UNCERTAINTY_FRAC,
        1.0 + DWELL_UNCERTAINTY_FRAC,
        size=(n_sim, n_hubs),
    )

    # Simulated elapsed (n_sim, n_hubs)
    sim_drive   = base_drive[None, :] / speed_factor
    sim_dwell   = base_dwell[None, :] * dwell_factor
    sim_elapsed = sim_drive + sim_dwell                         # (n_sim, n_hubs)

    # Attainment: fraction of sims where elapsed ≤ promise
    attainment  = (sim_elapsed <= promises[None, :]).mean(axis=0)   # (n_hubs,)

    p5  = np.percentile(sim_elapsed, 5,  axis=0)
    p50 = np.percentile(sim_elapsed, 50, axis=0)
    p95 = np.percentile(sim_elapsed, 95, axis=0)

    # Non-PI baseline OTD: deterministic drive + 8hr last-mile (1M+ metro)
    nonpi_otd_mean = base_drive + 8.0    # approximate non-PI elapsed for comparison

    result = df[["node_id", "pop_bracket", "pi_promise_hr", "drive_time_hr"]].copy()
    result["mean_drive_hr"]    = base_drive.round(3)
    result["road_km"]          = road_km.round(1)
    result["attainment_rate"]  = attainment.round(4)
    result["p5_elapsed_hr"]    = p5.round(3)
    result["p50_elapsed_hr"]   = p50.round(3)
    result["p95_elapsed_hr"]   = p95.round(3)
    result["nonpi_otd_est_hr"] = nonpi_otd_mean.round(3)
    result["otd_saving_hr"]    = (nonpi_otd_mean - p50).round(3)

    return result.reset_index(drop=True)


def summarise_otd_by_bracket(otd_df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate OTD simulation results by pop_bracket."""
    if otd_df.empty:
        return pd.DataFrame()
    grp = otd_df.groupby("pop_bracket").agg(
        n_hubs=("node_id", "count"),
        pi_promise_hr=("pi_promise_hr", "first"),
        mean_attainment=("attainment_rate", "mean"),
        mean_p50_elapsed=("p50_elapsed_hr", "mean"),
        mean_nonpi_otd=("nonpi_otd_est_hr", "mean"),
        mean_saving_hr=("otd_saving_hr", "mean"),
    ).reset_index()
    grp["mean_attainment"] = grp["mean_attainment"].round(4)
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

def eval_59_lane_cost_carbon(
    lanes: pd.DataFrame,
    annual_units_by_dc: dict[str, float],
    year: int,
) -> pd.DataFrame:
    """
    Task 5.9: For each lane, compute annualised transport cost and CO₂ emissions.

    Annual flow per lane is estimated as:
      flow_units = annual_units_DC / (n_lanes_from_DC)   (uniform split)

    Returns per-lane DataFrame:
      lane_id, lane_type, truck_class, road_km, drive_time_hr,
      annual_flow_units, transport_cost_eur, co2_kg
    Plus aggregate: total cost, total CO2, avg cost per unit, CO2 per unit.
    """
    if lanes.empty:
        return pd.DataFrame()

    # Outbound lane count per DC
    outbound_counts = lanes.groupby("origin_id")["lane_id"].count().to_dict()

    df = lanes.copy()
    df["annual_units_DC"] = df["origin_id"].map(annual_units_by_dc).fillna(0)
    df["n_outbound"]      = df["origin_id"].map(outbound_counts).fillna(1)
    df["annual_flow"]     = (df["annual_units_DC"] / df["n_outbound"].clip(lower=1)).round(0)

    # Cost per lane per year
    cost_per_km_map = {"L": TRUCK_L_EUR_KM, "M": TRUCK_M_EUR_KM, "S": TRUCK_S_EUR_KM}
    df["cost_per_km"] = df["truck_class"].map(cost_per_km_map).fillna(TRUCK_L_EUR_KM)
    df["transport_cost_eur"] = (df["road_km"] * df["cost_per_km"] *
                                 np.ceil(df["annual_flow"] / UNITS_PER_PALLET_PI)).round(2)

    # CO₂ per lane per year (kg)
    co2_map = {"L": CO2_TRUCK_L_KG_KM, "M": CO2_TRUCK_M_KG_KM, "S": CO2_TRUCK_S_KG_KM}
    df["co2_kg_per_km"] = df["truck_class"].map(co2_map).fillna(CO2_TRUCK_L_KG_KM)
    df["co2_kg"] = (df["road_km"] * df["co2_kg_per_km"] *
                    np.ceil(df["annual_flow"] / UNITS_PER_PALLET_PI)).round(1)

    # Ocean leg CO₂ (PORT → DC lanes)
    ocean_mask = df["lane_type"] == "PORT_DC"
    if ocean_mask.any():
        teus = np.ceil(
            df.loc[ocean_mask, "annual_flow"] / UNITS_PER_TEU_PI
        )
        df.loc[ocean_mask, "co2_kg"] = (
            OCEAN_SAVANNAH_ROTTERDAM_KM * CO2_OCEAN_KG_KM_TEU * teus
        ).round(1)
        df.loc[ocean_mask, "transport_cost_eur"] = (
            teus * OCEAN_CONTAINER_EUR
        ).round(2)

    df["year"] = year
    return df[[
        "year", "lane_id", "lane_type", "truck_class",
        "road_km", "drive_time_hr", "relay_flag",
        "annual_flow", "transport_cost_eur", "co2_kg",
    ]]


def summarise_cost_carbon(lane_cost_df: pd.DataFrame) -> dict:
    """Aggregate cost and carbon totals from eval_59_lane_cost_carbon output."""
    if lane_cost_df.empty:
        return {}
    total_cost = float(lane_cost_df["transport_cost_eur"].sum())
    total_co2  = float(lane_cost_df["co2_kg"].sum())
    total_flow = float(lane_cost_df["annual_flow"].sum())
    by_type = lane_cost_df.groupby("lane_type")[["transport_cost_eur", "co2_kg"]].sum()
    return {
        "total_transport_cost_eur":  round(total_cost, 0),
        "total_co2_kg":              round(total_co2, 0),
        "co2_per_unit_kg":           round(total_co2 / max(total_flow, 1), 3),
        "cost_per_unit_eur":         round(total_cost / max(total_flow, 1), 3),
        "by_lane_type":              by_type.to_dict(),
    }


# ============================================================================
# PART 9 — Task 5.10: DC capacity sizing (simulation-backed)
# ============================================================================

def eval_510_dc_capacity_sizing(
    annual_units_by_dc: dict[str, float],
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    Task 5.10: Size DC capacity from annual demand using Monte Carlo simulation.

    Cyber week drives the constraint: 15% of annual demand over 5 days = 3%/day.
    Simulate demand volatility around this peak to get P95 daily pallet throughput.

    Pattern: numpy-first — draw daily demand samples, compute pallet needs.

    Returns per-DC DataFrame:
      dc_id, annual_units, peak_daily_units, p95_daily_pallets,
      throughput_cap_pallets, storage_positions, DC costs.
    """
    rng = np.random.default_rng(seed)
    records = []

    for dc_id, annual_units in annual_units_by_dc.items():
        # Cyber week daily demand: Normal(mean=3%, sigma=0.5%)
        mean_peak = annual_units * PEAK_DAILY_SHARE
        sigma_peak = mean_peak * 0.15   # 15% CV on peak day

        # (n_sim,) daily demand samples during cyber week
        peak_samples = rng.normal(mean_peak, sigma_peak, size=n_sim)
        peak_samples = np.maximum(peak_samples, mean_peak * 0.5)  # floor

        p50_units  = float(np.percentile(peak_samples, 50))
        p95_units  = float(np.percentile(peak_samples, 95))
        p99_units  = float(np.percentile(peak_samples, 99))

        p95_pallets = int(np.ceil(p95_units / UNITS_PER_PALLET_PI))
        throughput_cap = p95_pallets * 2   # inbound + outbound

        # Storage: cover 2 weeks of annual flow at average daily rate
        avg_daily = annual_units / 365
        storage_days = 14
        storage_positions = int(np.ceil(avg_daily * storage_days / UNITS_PER_PALLET_PI))

        # Annual DC costs (€)
        storage_cost    = storage_positions * DC_STORAGE_EUR
        throughput_cost = throughput_cap * DC_THROUGHPUT_EUR
        inbound_cost    = int(annual_units / UNITS_PER_PALLET_PI) * DC_INBOUND_PALLET_EUR
        outbound_cost   = int(annual_units / UNITS_PER_PALLET_PI) * DC_OUTBOUND_PALLET_EUR
        pick_cost       = annual_units * DC_UNIT_PICK_EUR
        dc_total_cost   = (DC_FIXED_EUR_YEAR + storage_cost + throughput_cost
                           + inbound_cost + outbound_cost + pick_cost)

        records.append({
            "dc_id":                dc_id,
            "annual_units":         round(annual_units, 0),
            "mean_peak_daily_units":round(mean_peak, 0),
            "p50_peak_daily_units": round(p50_units, 0),
            "p95_peak_daily_units": round(p95_units, 0),
            "p99_peak_daily_units": round(p99_units, 0),
            "throughput_cap_pallets": throughput_cap,
            "storage_positions":    storage_positions,
            "dc_fixed_cost_eur":    DC_FIXED_EUR_YEAR,
            "dc_storage_cost_eur":  round(storage_cost, 0),
            "dc_throughput_cost_eur": round(throughput_cost, 0),
            "dc_pick_cost_eur":     round(pick_cost, 0),
            "dc_total_cost_eur":    round(dc_total_cost, 0),
        })

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
    annual_nonpi_units: float,
    dc_cost_df: pd.DataFrame,
    lane_cost_df: pd.DataFrame,
    pack_savings: dict,
    transload_dict: dict,
    uplift_summary: dict,
) -> dict:
    """
    Task 5.12: P&L summary comparing PI vs non-PI scenario for a given year.

    Revenue uplift (more reachable units) + cost savings from PI vs
    PI-specific costs (transload, hub relay/consolidation fees).
    """
    # Revenue
    pi_revenue    = annual_pi_units    * REVENUE_PER_UNIT_EUR
    nonpi_revenue = annual_nonpi_units * REVENUE_PER_UNIT_EUR
    revenue_uplift = pi_revenue - nonpi_revenue

    # DC operating costs (sum across all DCs)
    total_dc_cost = float(dc_cost_df["dc_total_cost_eur"].sum()) if not dc_cost_df.empty else 0

    # Transport cost
    total_transport = float(lane_cost_df["transport_cost_eur"].sum()) if not lane_cost_df.empty else 0

    # Packaging: PI saves (NON_PI - PI) per unit
    pack_saving_total = pack_savings.get("pack_cost_saving_eur", 0)

    # PI-specific fees
    transload_total = transload_dict.get("total_transload_cost_eur", 0)
    hub_relay_total = annual_pi_units * HUB_RELAY_COST_EUR    # assume avg 1 relay hub

    # Approximate non-PI costs for comparison
    nonpi_pack_cost    = annual_nonpi_units * NON_PI_PACK_COST_EUR
    pi_pack_cost       = annual_pi_units    * PI_PACK_COST_EUR
    pack_cost_delta    = nonpi_pack_cost - pi_pack_cost  # positive = PI cheaper

    total_pi_cost   = total_dc_cost + total_transport + pi_pack_cost + transload_total + hub_relay_total
    total_nonpi_cost_approx = (
        total_dc_cost * 0.9 +      # non-PI has slightly lower DC cost (fewer hubs to serve)
        total_transport * 1.2 +    # non-PI transport higher (less relay efficiency)
        nonpi_pack_cost
    )

    pi_margin         = pi_revenue - total_pi_cost
    nonpi_margin      = nonpi_revenue - total_nonpi_cost_approx
    margin_uplift     = pi_margin - nonpi_margin

    return {
        "year":                  year,
        "pi_units":              round(annual_pi_units, 0),
        "nonpi_units":           round(annual_nonpi_units, 0),
        "pi_revenue_eur":        round(pi_revenue, 0),
        "nonpi_revenue_eur":     round(nonpi_revenue, 0),
        "revenue_uplift_eur":    round(revenue_uplift, 0),
        "total_dc_cost_eur":     round(total_dc_cost, 0),
        "total_transport_eur":   round(total_transport, 0),
        "pi_pack_cost_eur":      round(pi_pack_cost, 0),
        "transload_cost_eur":    round(transload_total, 0),
        "hub_relay_cost_eur":    round(hub_relay_total, 0),
        "total_pi_cost_eur":     round(total_pi_cost, 0),
        "pi_margin_eur":         round(pi_margin, 0),
        "nonpi_margin_approx_eur": round(nonpi_margin, 0),
        "margin_uplift_eur":     round(margin_uplift, 0),
    }


# ============================================================================
# PART 12 — Master compute function (called by pipeline.py)
# ============================================================================

def compute_all_kpis(
    year: int,
    active_nodes: pd.DataFrame,
    lanes: pd.DataFrame,
    baseline_assignment: pd.DataFrame | None = None,
    annual_units_by_dc: dict[str, float] | None = None,
    n_sim: int = DEFAULT_N_SIM,
) -> dict:
    """
    Compute all Task 5 KPIs for a given year.
    Returns flat dict for the KPI summary table.
    """
    kpis: dict = {"year": year}

    # ---- Node/lane counts ----
    kpis["n_nodes_total"] = len(active_nodes)
    for nt in ["PORT", "DC", "PERI_URBAN_HUB", "BORDER_RELAY_HUB", "DEMAND_NONMETRO"]:
        kpis[f"n_{nt.lower()}"] = int((active_nodes["node_type"] == nt).sum())
    kpis["n_lanes_total"] = len(lanes)

    # ---- 5.1 topology ----
    kpis.update(compute_coverage(active_nodes, lanes))
    kpis.update(compute_detour_summary(lanes))
    kpis.update(compute_relay_readiness(lanes))
    kpis.update(compute_dc_dc_connectivity(active_nodes, lanes))

    # ---- 5.3 OTD attainment (Monte Carlo) ----
    if baseline_assignment is not None and not baseline_assignment.empty:
        direct_lanes = lanes[lanes["lane_type"] == "DC_HUB_DIRECT"].copy()
        if "road_km" not in direct_lanes.columns:
            direct_lanes["road_km"] = direct_lanes["haversine_km"] * DETOUR_FACTOR
        hub_brackets = active_nodes[active_nodes["node_type"] == "PERI_URBAN_HUB"][
            ["node_id", "pop_bracket"]
        ].copy()
        direct_lanes = direct_lanes.rename(columns={"dest_id": "node_id"})
        otd_sim = simulate_otd_attainment(direct_lanes, hub_brackets, n_sim=n_sim)
        if not otd_sim.empty:
            kpis["mean_otd_attainment"]  = round(float(otd_sim["attainment_rate"].mean()), 4)
            kpis["pct_hubs_above_90pct"] = round(float((otd_sim["attainment_rate"] >= 0.9).mean() * 100), 2)
            kpis["mean_otd_saving_hr"]   = round(float(otd_sim["otd_saving_hr"].mean()), 3)

    # ---- 5.6 autonomy ----
    aut = eval_56_autonomy(active_nodes, lanes, year)
    kpis["dual_role_hubs"]   = aut["dual_role_hubs"]
    kpis["dual_role_pct"]    = aut["dual_role_pct"]

    # ---- 5.9 cost + carbon (requires demand) ----
    if annual_units_by_dc:
        lc = eval_59_lane_cost_carbon(lanes, annual_units_by_dc, year)
        cc = summarise_cost_carbon(lc)
        kpis["total_transport_cost_eur"] = cc.get("total_transport_cost_eur")
        kpis["total_co2_kg"]             = cc.get("total_co2_kg")
        kpis["co2_per_unit_kg"]          = cc.get("co2_per_unit_kg")
        kpis["transport_cost_per_unit"]  = cc.get("cost_per_unit_eur")

    return kpis
