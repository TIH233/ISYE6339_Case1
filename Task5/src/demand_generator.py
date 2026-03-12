"""
demand_generator.py — PI-only demand generation for Task5.

Data flow:
  Task4 population/model inputs + Task2 assignment weights
  -> Task4-style daily demand kernel at (country, segment)
  -> node-level PI service matrix from active routes
  -> route-aware DC daily demand

The old multi-scenario and baseline-comparison branches have been removed.
Task5 now computes PI-network outputs only.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from .config import (
    COUNTRY_NAME_TO_CODE,
    COUNTRY_OPEN_SCHEDULE,
    CYBER_WEEK_ANNUAL_SHARE,
    DEFAULT_N_SIM,
    DETOUR_FACTOR,
    RANDOM_SEED,
    REVENUE_PER_UNIT_EUR,
)
from .data_loader import load_assignment
from .hub_network import haversine_km


_REPO_ROOT = Path(__file__).resolve().parents[2]
_TASK4_INPUTS = _REPO_ROOT / "Task4" / "Pop_inputs.xlsx"

_DOW_WEIGHTS = {
    0: 0.12,
    1: 0.12,
    2: 0.23,
    3: 0.25,
    4: 0.15,
    5: 0.10,
    6: 0.03,
}

_SEGMENT_LABELS = {
    "metro": "Metro",
    "non_metro": "Non-Metro",
}

_PI_ADOPTION_RATES = [0.00025, 0.00045, 0.00055, 0.00060, 0.00065, 0.00070, 0.00075, 0.00080]


@lru_cache(maxsize=1)
def _cached_task4_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metro = pd.read_excel(_TASK4_INPUTS, sheet_name="Metro")
    nonmetro = pd.read_excel(_TASK4_INPUTS, sheet_name="NonMetro")
    model = pd.read_excel(_TASK4_INPUTS, sheet_name="Model")

    metro["country_code"] = metro["Country"].map(COUNTRY_NAME_TO_CODE)
    metro["city_key"] = (
        metro["City"].astype(str).str.lower().str.replace(" ", "_", regex=False)
    )
    nonmetro["country_code"] = nonmetro["Country"].map(COUNTRY_NAME_TO_CODE)
    model["Share_MP"] = model["Share_MP"] / model["Share_MP"].sum()
    return metro, nonmetro, model


def _task4_inputs() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    metro, nonmetro, model = _cached_task4_inputs()
    return metro.copy(), nonmetro.copy(), model.copy()


def _entry_year_map() -> dict[str, int]:
    entry_year: dict[str, int] = {}
    for year, countries in COUNTRY_OPEN_SCHEDULE.items():
        for country in countries:
            entry_year.setdefault(country, year)
    return entry_year


def build_year_calendar(year: int) -> pd.DataFrame:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    dates = pd.date_range(start, end, freq="D")

    cal = pd.DataFrame({"date": dates})
    cal["day_of_week"] = cal["date"].dt.dayofweek

    nov_days = [d for d in dates if d.month == 11]
    fridays = [d for d in nov_days if d.dayofweek == 4]
    black_friday = fridays[3] if len(fridays) >= 4 else fridays[-1]
    cyber_week_dates = {black_friday + timedelta(days=i) for i in range(5)}
    cal["is_cyber_week"] = cal["date"].isin(cyber_week_dates)

    first_monday = start
    while first_monday.weekday() != 0:
        first_monday += timedelta(days=1)
    cal["period"] = (
        ((cal["date"] - pd.Timestamp(first_monday)).dt.days.clip(lower=0) // 28) + 1
    ).clip(upper=13)
    return cal


def adoption_rate_by_year(market_year: int) -> float:
    idx = min(max(market_year - 1, 0), len(_PI_ADOPTION_RATES) - 1)
    return _PI_ADOPTION_RATES[idx]


PERIOD_BASE_MEANS = np.array(
    [0.05, 0.07, 0.09, 0.09, 0.09, 0.05, 0.04, 0.06, 0.13, 0.09, 0.06, 0.07, 0.11]
)
PERIOD_CV = 0.25


def simulate_period_shares(n_sim: int, seed: int = RANDOM_SEED) -> np.ndarray:
    rng = np.random.default_rng(seed)
    draws = rng.normal(
        loc=PERIOD_BASE_MEANS,
        scale=PERIOD_BASE_MEANS * PERIOD_CV,
        size=(n_sim, len(PERIOD_BASE_MEANS)),
    )
    draws = np.clip(draws, 1e-9, None)
    return draws / draws.sum(axis=1, keepdims=True)


MODEL_SHARE_BOUNDS = {
    "F10": (10.0, 17.0, 20.0),
    "K10": (5.0, 13.0, 18.0),
    "S10": (5.0, 10.0, 15.0),
    "W10": (5.0, 9.0, 15.0),
    "F20": (4.0, 8.0, 12.0),
    "K20": (3.0, 6.0, 10.0),
    "L20": (3.0, 5.0, 10.0),
    "S20": (2.0, 5.0, 10.0),
    "W20": (2.0, 4.0, 8.0),
    "X20": (2.0, 4.0, 8.0),
    "F30": (2.0, 3.0, 8.0),
    "K30": (1.0, 3.0, 6.0),
    "S30": (1.0, 3.0, 6.0),
    "W30": (1.0, 2.0, 6.0),
    "F50": (0.5, 2.0, 6.0),
    "K50": (0.5, 2.0, 4.0),
    "L50": (0.5, 1.0, 4.0),
    "S50": (0.5, 1.0, 4.0),
    "W50": (0.5, 1.0, 4.0),
    "X50": (0.5, 1.0, 4.0),
}


def triangular_model_shares(
    model_codes: np.ndarray,
    base_shares: np.ndarray,
    sim: int,
    year: int,
) -> np.ndarray:
    rng = np.random.default_rng(sim * 10000 + year)
    shares = np.empty(len(model_codes), dtype=float)

    for idx, model_code in enumerate(model_codes):
        if model_code in MODEL_SHARE_BOUNDS:
            lo, mode, hi = MODEL_SHARE_BOUNDS[model_code]
            shares[idx] = rng.triangular(lo, mode, hi)
        else:
            mode = base_shares[idx] * 100.0
            shares[idx] = rng.triangular(mode * 0.8, mode, mode * 1.2)

    return shares / shares.sum()


def get_otd_conversion_rate(segment: str, otd_hours: float) -> float:
    otd_days = otd_hours / 24.0
    if otd_days <= 1.0:
        bucket = 0
    elif otd_days <= 2.0:
        bucket = 1
    elif otd_days <= 3.0:
        bucket = 2
    else:
        bucket = 3

    conversion_matrix = {
        "Metro": [1.00, 0.95, 0.85, 0.70],
        "Non-Metro": [1.00, 0.98, 0.93, 0.85],
    }
    return conversion_matrix[segment][bucket]


def _otd_bucket(otd_hours: float) -> int:
    if otd_hours <= 24.0:
        return 0
    if otd_hours <= 48.0:
        return 1
    if otd_hours <= 72.0:
        return 2
    return 3


def _prepare_assignment_reference(year: int) -> pd.DataFrame:
    assignment = load_assignment(years=[year]).copy()
    if assignment.empty:
        return assignment

    assignment["country"] = assignment["node_id"].str.split("_").str[1]
    assignment["segment"] = assignment["node_type"].map(_SEGMENT_LABELS)
    group_total = assignment.groupby(["year", "country", "segment"])["units"].transform("sum")
    assignment["node_weight"] = assignment["units"] / group_total.clip(lower=1.0)
    fallback_last_mile = (
        assignment["otd_hours"].fillna(0.0) - assignment["travel_elapsed_hr"].fillna(0.0)
    ).clip(lower=0.0)
    assignment["baseline_last_mile_hr"] = assignment["last_mile_hours_final"].fillna(fallback_last_mile)
    return assignment


def _pi_last_mile_for_metro(pop_bracket: str | float) -> tuple[float, str]:
    bracket = str(pop_bracket) if pd.notna(pop_bracket) else ""
    if bracket == "1M+":
        return 4.0, "METRO_1M+"
    if bracket == "250K-1M":
        return 2.0, "METRO_250K-1M"
    return 1.0, "METRO_<250K"


def _pi_last_mile_for_nonmetro(
    baseline_last_mile_hr: float,
    distance_km: float | None = None,
) -> tuple[float, str]:
    if distance_km is not None and np.isfinite(distance_km):
        if distance_km <= 250.0:
            return 8.0, "NONMETRO_<=250KM"
        if distance_km <= 500.0:
            return 16.0, "NONMETRO_<=500KM"
        return 32.0, "NONMETRO_>500KM"

    if baseline_last_mile_hr <= 24.0:
        return 8.0, "NONMETRO_<=250KM"
    if baseline_last_mile_hr <= 48.0:
        return 16.0, "NONMETRO_<=500KM"
    return 32.0, "NONMETRO_>500KM"


def _segment_annual_demand(
    year: int,
    metro_df: pd.DataFrame,
    nonmetro_df: pd.DataFrame,
) -> dict[tuple[str, str], float]:
    entry_year = _entry_year_map()
    segment_annual: dict[tuple[str, str], float] = {}

    for row in metro_df.itertuples(index=False):
        country = row.country_code
        if pd.isna(country) or country not in entry_year:
            continue
        market_year = year - entry_year[country] + 1
        if market_year < 1:
            continue
        pop = float(getattr(row, f"Pop_{year}", 0.0))
        segment_annual[(country, "Metro")] = (
            segment_annual.get((country, "Metro"), 0.0)
            + pop * adoption_rate_by_year(market_year)
        )

    for row in nonmetro_df.itertuples(index=False):
        country = row.country_code
        if pd.isna(country) or country not in entry_year:
            continue
        market_year = year - entry_year[country] + 1
        if market_year < 1:
            continue
        pop = float(getattr(row, f"NonMetroPop_{year}", 0.0))
        segment_annual[(country, "Non-Metro")] = pop * adoption_rate_by_year(market_year)

    return segment_annual


def _best_route_for_node(
    assignment_row: pd.Series,
    active_nodes: pd.DataFrame,
    routes: pd.DataFrame,
    active_dc_ids: set[str],
) -> dict:
    baseline_last_mile_hr = float(assignment_row.get("baseline_last_mile_hr", 0.0) or 0.0)
    assigned_dc = str(assignment_row["assigned_cand"])
    base_travel = float(assignment_row["travel_elapsed_hr"])
    node_id = str(assignment_row["node_id"])
    node_type = str(assignment_row["node_type"])
    country = str(assignment_row["country"])
    node_lookup = (
        active_nodes[["node_id", "node_type", "lat", "lng", "pop_bracket"]]
        .drop_duplicates(subset=["node_id"])
        .set_index("node_id")
        .to_dict("index")
    )

    def _candidate_lastmile(candidate_dest_hub: str) -> tuple[float, str]:
        hub_info = node_lookup.get(candidate_dest_hub, {})
        if node_type == "metro":
            return _pi_last_mile_for_metro(hub_info.get("pop_bracket", pd.NA))

        demand_info = node_lookup.get(node_id, {})
        if hub_info and demand_info:
            road_km = float(
                haversine_km(
                    np.array([float(hub_info["lat"])]),
                    np.array([float(hub_info["lng"])]),
                    np.array([float(demand_info["lat"])]),
                    np.array([float(demand_info["lng"])]),
                )[0]
            ) * DETOUR_FACTOR
            return _pi_last_mile_for_nonmetro(baseline_last_mile_hr, distance_km=road_km)

        return _pi_last_mile_for_nonmetro(baseline_last_mile_hr)

    fallback_last_mile_hr, fallback_last_mile_band = (
        _pi_last_mile_for_nonmetro(baseline_last_mile_hr)
        if node_type != "metro"
        else _pi_last_mile_for_metro(node_lookup.get(node_id, {}).get("pop_bracket", pd.NA))
    )

    if node_type == "metro" and node_id not in set(active_nodes["node_id"]):
        if assigned_dc in active_dc_ids:
            return {
                "assigned_dc_id": assigned_dc,
                "route_id": f"SELF::{assigned_dc}",
                "path_lane_ids": "",
                "service_mode": "DC_LOCAL",
                "travel_elapsed_hr": 0.0,
                "route_drive_hr": 0.0,
                "total_hub_dwell_hr": 0.0,
                "last_mile_hr": fallback_last_mile_hr,
                "last_mile_band": fallback_last_mile_band,
                "n_relay_hubs": 0,
                "n_consol_hubs": 1,
                "route_backed": True,
            }

    if routes.empty:
        return {
            "assigned_dc_id": assigned_dc,
            "route_id": pd.NA,
            "path_lane_ids": "",
            "service_mode": "BASELINE_FALLBACK",
            "travel_elapsed_hr": base_travel,
            "route_drive_hr": base_travel,
            "total_hub_dwell_hr": 0.0,
            "last_mile_hr": fallback_last_mile_hr,
            "last_mile_band": fallback_last_mile_band,
            "n_relay_hubs": 0,
            "n_consol_hubs": 0,
            "route_backed": False,
        }

    candidates = pd.DataFrame()
    if node_type == "metro" and node_id in set(active_nodes["node_id"]):
        candidates = routes[routes["dest_hub"] == node_id].copy()
    elif node_type != "metro":
        country_hubs = active_nodes[
            (active_nodes["node_type"] == "PERI_URBAN_HUB")
            & (active_nodes["country"] == country)
        ]["node_id"]
        candidates = routes[routes["dest_hub"].isin(country_hubs)].copy()

    if candidates.empty:
        return {
            "assigned_dc_id": assigned_dc,
            "route_id": pd.NA,
            "path_lane_ids": "",
            "service_mode": "BASELINE_FALLBACK",
            "travel_elapsed_hr": base_travel,
            "route_drive_hr": base_travel,
            "total_hub_dwell_hr": 0.0,
            "last_mile_hr": fallback_last_mile_hr,
            "last_mile_band": fallback_last_mile_band,
            "n_relay_hubs": 0,
            "n_consol_hubs": 0,
            "route_backed": False,
        }

    lastmile_meta = candidates["dest_hub"].map(_candidate_lastmile)
    candidates["pi_last_mile_hr"] = lastmile_meta.map(lambda x: x[0])
    candidates["last_mile_band"] = lastmile_meta.map(lambda x: x[1])
    candidates["service_otd_hr"] = candidates["total_elapsed_hr"] + candidates["pi_last_mile_hr"]
    chosen = candidates.sort_values(
        ["service_otd_hr", "detour_ratio", "total_elapsed_hr", "route_id"]
    ).iloc[0]
    return {
        "assigned_dc_id": str(chosen["origin_dc"]),
        "route_id": str(chosen["route_id"]),
        "path_lane_ids": str(chosen.get("path_lane_ids", "")),
        "service_mode": str(chosen["service_mode"]),
        "travel_elapsed_hr": float(chosen["total_elapsed_hr"]),
        "route_drive_hr": float(chosen.get("total_drive_hr", chosen["total_elapsed_hr"])),
        "total_hub_dwell_hr": float(
            chosen.get("total_hub_dwell_hr", chosen["total_elapsed_hr"] - chosen.get("total_drive_hr", 0.0))
        ),
        "last_mile_hr": float(chosen["pi_last_mile_hr"]),
        "last_mile_band": str(chosen["last_mile_band"]),
        "n_relay_hubs": int(chosen.get("n_relay_stops", 0)),
        "n_consol_hubs": int(chosen.get("n_consol_stops", 0)),
        "route_backed": True,
    }


def build_service_matrix(
    year: int,
    nodes: pd.DataFrame,
    routes: pd.DataFrame,
    assignment_reference: pd.DataFrame,
    segment_annual: dict[tuple[str, str], float],
) -> pd.DataFrame:
    if assignment_reference.empty:
        return pd.DataFrame()

    active_nodes = nodes.copy()
    active_dc_ids = set(active_nodes.loc[active_nodes["node_type"] == "DC", "node_id"])
    node_lookup = {}
    if not active_nodes.empty:
        node_lookup = (
            active_nodes[["node_id", "pop_bracket"]]
            .drop_duplicates(subset=["node_id"])
            .set_index("node_id")["pop_bracket"]
            .to_dict()
        )
    rows: list[dict] = []

    for assignment_row in assignment_reference.itertuples(index=False):
        assignment_series = pd.Series(assignment_row._asdict())
        route_service = _best_route_for_node(
            assignment_series,
            active_nodes=active_nodes,
            routes=routes,
            active_dc_ids=active_dc_ids,
        )
        otd_hours = float(route_service["travel_elapsed_hr"]) + float(route_service["last_mile_hr"])
        segment = str(assignment_series["segment"])
        purchase_prob = get_otd_conversion_rate(segment, otd_hours)
        annual_potential = (
            segment_annual.get((str(assignment_series["country"]), segment), 0.0)
            * float(assignment_series["node_weight"])
        )

        rows.append({
            "year": year,
            "node_id": str(assignment_series["node_id"]),
            "node_type": str(assignment_series["node_type"]),
            "pop_bracket": node_lookup.get(str(assignment_series["node_id"]), pd.NA),
            "country": str(assignment_series["country"]),
            "segment": segment,
            "assigned_dc_id": route_service["assigned_dc_id"],
            "route_id": route_service["route_id"],
            "path_lane_ids": route_service["path_lane_ids"],
            "service_mode": route_service["service_mode"],
            "route_backed": bool(route_service["route_backed"]),
            "n_relay_hubs": int(route_service["n_relay_hubs"]),
            "n_consol_hubs": int(route_service["n_consol_hubs"]),
            "route_drive_hr": float(route_service["route_drive_hr"]),
            "total_hub_dwell_hr": float(route_service["total_hub_dwell_hr"]),
            "travel_elapsed_hr": float(route_service["travel_elapsed_hr"]),
            "last_mile_hr": float(route_service["last_mile_hr"]),
            "last_mile_band": str(route_service["last_mile_band"]),
            "otd_hours": otd_hours,
            "otd_bucket": _otd_bucket(otd_hours),
            "purchase_prob": purchase_prob,
            "units": float(assignment_series["units"]),
            "node_weight": float(assignment_series["node_weight"]),
            "annual_potential_units": annual_potential,
            "annual_realized_units": annual_potential * purchase_prob,
            "effective_weight_component": float(assignment_series["node_weight"]) * purchase_prob,
        })

    return pd.DataFrame(rows)


def _daily_total_demand(
    total_annual: float,
    calendar: pd.DataFrame,
    period_shares: np.ndarray,
) -> np.ndarray:
    daily = np.zeros(len(calendar), dtype=float)
    regular_mask = ~calendar["is_cyber_week"]
    cyber_mask = calendar["is_cyber_week"]

    regular_total = total_annual * (1.0 - CYBER_WEEK_ANNUAL_SHARE)
    cyber_total = total_annual * CYBER_WEEK_ANNUAL_SHARE

    for period in range(1, 14):
        period_mask = regular_mask & (calendar["period"] == period)
        if not period_mask.any():
            continue
        dow_weights = calendar.loc[period_mask, "day_of_week"].map(_DOW_WEIGHTS).to_numpy(dtype=float)
        dow_weights = dow_weights / dow_weights.sum()
        daily[period_mask.to_numpy()] = regular_total * period_shares[period - 1] * dow_weights

    if cyber_mask.any():
        cyber_weights = calendar.loc[cyber_mask, "day_of_week"].map(_DOW_WEIGHTS).to_numpy(dtype=float)
        cyber_weights = cyber_weights / cyber_weights.sum()
        daily[cyber_mask.to_numpy()] = cyber_total * cyber_weights

    return daily


def simulate_dc_daily_demand(
    year: int,
    segment_annual: dict[tuple[str, str], float],
    service_matrix: pd.DataFrame,
    model_df: pd.DataFrame,
    n_sim: int,
    seed: int,
) -> pd.DataFrame:
    if service_matrix.empty or not segment_annual:
        return pd.DataFrame(columns=["sim", "date", "year", "euro_dc_id", "model", "realized_units"])

    dc_ids = sorted(service_matrix["assigned_dc_id"].dropna().unique())
    dc_to_idx = {dc_id: idx for idx, dc_id in enumerate(dc_ids)}
    model_codes = model_df["Model"].to_numpy()
    model_shares_base = model_df["Share_MP"].to_numpy(dtype=float)
    calendar = build_year_calendar(year)
    total_annual = float(sum(segment_annual.values()))
    segment_keys = list(segment_annual.keys())
    segment_weights = {
        key: value / total_annual for key, value in segment_annual.items() if total_annual > 0
    }

    effective_weights = (
        service_matrix.groupby(["country", "segment", "assigned_dc_id"], as_index=False)
        .agg(effective_weight=("effective_weight_component", "sum"))
    )

    group_to_dc: dict[tuple[str, str], list[tuple[int, float]]] = {}
    for row in effective_weights.itertuples(index=False):
        group_to_dc.setdefault((str(row.country), str(row.segment)), []).append(
            (dc_to_idx[str(row.assigned_dc_id)], float(row.effective_weight))
        )

    rng = np.random.default_rng(seed)
    frames: list[pd.DataFrame] = []

    for sim in range(n_sim):
        period_shares = simulate_period_shares(1, seed=int(rng.integers(0, 1_000_000)))[0]
        model_shares = triangular_model_shares(model_codes, model_shares_base, sim, year)
        daily_total = _daily_total_demand(total_annual, calendar, period_shares)
        accum = np.zeros((len(calendar), len(dc_ids), len(model_codes)), dtype=np.float32)

        for date_idx, total_units in enumerate(daily_total):
            if total_units <= 0:
                continue
            for group_key in segment_keys:
                dc_list = group_to_dc.get(group_key)
                if not dc_list:
                    continue
                model_units = total_units * segment_weights[group_key] * model_shares
                for dc_idx, effective_weight in dc_list:
                    accum[date_idx, dc_idx] += model_units * effective_weight

        day_idx, dc_idx, model_idx = np.where(accum > 1e-6)
        if len(day_idx) == 0:
            continue

        frames.append(
            pd.DataFrame({
                "sim": np.full(len(day_idx), sim, dtype=np.int32),
                "date": calendar["date"].to_numpy()[day_idx],
                "year": np.full(len(day_idx), year, dtype=np.int32),
                "euro_dc_id": np.asarray(dc_ids, dtype=object)[dc_idx],
                "model": model_codes[model_idx],
                "realized_units": accum[day_idx, dc_idx, model_idx].astype(np.float64),
            })
        )

    if not frames:
        return pd.DataFrame(columns=["sim", "date", "year", "euro_dc_id", "model", "realized_units"])
    return pd.concat(frames, ignore_index=True)


def summarise_route_flows(service_matrix: pd.DataFrame) -> pd.DataFrame:
    if service_matrix.empty:
        return pd.DataFrame()

    routed = service_matrix[service_matrix["route_id"].notna()].copy()
    if routed.empty:
        return pd.DataFrame()

    return (
        routed.groupby(
            ["route_id", "assigned_dc_id", "service_mode", "n_relay_hubs", "n_consol_hubs"],
            as_index=False,
        )
        .agg(
            annual_realized_units=("annual_realized_units", "sum"),
            served_nodes=("node_id", "count"),
        )
        .rename(columns={"assigned_dc_id": "origin_dc"})
    )


def run_pi_demand_pipeline(
    year: int,
    nodes: pd.DataFrame,
    routes: pd.DataFrame | None = None,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> dict:
    assignment_reference = _prepare_assignment_reference(year)
    if assignment_reference.empty:
        return {
            "dc_daily_sim": pd.DataFrame(),
            "annual_by_dc": {},
            "service_matrix": pd.DataFrame(),
            "route_flow_summary": pd.DataFrame(),
            "demand_summary": {},
        }

    metro_df, nonmetro_df, model_df = _task4_inputs()
    segment_annual = _segment_annual_demand(year, metro_df, nonmetro_df)
    routes = routes if routes is not None else pd.DataFrame()

    service_matrix = build_service_matrix(
        year=year,
        nodes=nodes,
        routes=routes,
        assignment_reference=assignment_reference,
        segment_annual=segment_annual,
    )
    dc_daily_sim = simulate_dc_daily_demand(
        year=year,
        segment_annual=segment_annual,
        service_matrix=service_matrix,
        model_df=model_df,
        n_sim=n_sim,
        seed=seed,
    )
    annual_by_dc = (
        service_matrix.groupby("assigned_dc_id")["annual_realized_units"].sum().round(0).to_dict()
        if not service_matrix.empty
        else {}
    )
    route_flow_summary = summarise_route_flows(service_matrix)

    demand_summary = {}
    if not service_matrix.empty:
        total_pi = float(service_matrix["annual_realized_units"].sum())
        demand_summary = {
            "year": year,
            "pi_realized_total": round(total_pi, 0),
            "pi_revenue_eur": round(total_pi * REVENUE_PER_UNIT_EUR, 0),
            "active_service_nodes": int(service_matrix["node_id"].nunique()),
            "route_backed_nodes": int(service_matrix["route_backed"].sum()),
            "route_backed_share_pct": round(float(service_matrix["route_backed"].mean() * 100), 2),
            "mean_purchase_prob": round(float(service_matrix["purchase_prob"].mean()), 4),
        }

    return {
        "dc_daily_sim": dc_daily_sim,
        "annual_by_dc": annual_by_dc,
        "service_matrix": service_matrix,
        "route_flow_summary": route_flow_summary,
        "demand_summary": demand_summary,
    }
