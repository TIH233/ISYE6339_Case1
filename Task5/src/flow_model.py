"""
flow_model.py — PI-only demand interval and stress summaries.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import (
    DC_ANNUAL_CAP_SHARE,
    DC_SLACK_THRESHOLD,
    DC_STRESS_TRIGGER,
    DC_TRANSFER_SHARE,
    RANDOM_SEED,
    UNITS_PER_PALLET_PI,
)


def is_cyber_week(sim_date: date) -> bool:
    year = sim_date.year
    nov_1 = date(year, 11, 1)
    days_to_thursday = (3 - nov_1.weekday()) % 7
    first_thursday = nov_1 + timedelta(days=days_to_thursday)
    black_friday = first_thursday + timedelta(weeks=3) + timedelta(days=1)
    cyber_end = black_friday + timedelta(days=4)
    return black_friday <= sim_date <= cyber_end


def _daily_dc_totals(dc_daily_sim: pd.DataFrame) -> pd.DataFrame:
    if dc_daily_sim.empty:
        return pd.DataFrame(columns=["sim", "date", "year", "dc_id", "daily_units"])

    daily = (
        dc_daily_sim.groupby(["sim", "date", "year", "euro_dc_id"], as_index=False)
        .agg(daily_units=("realized_units", "sum"))
        .rename(columns={"euro_dc_id": "dc_id"})
    )
    daily["date"] = pd.to_datetime(daily["date"])
    return daily


def extract_dc_daily_totals(dc_daily_sim: pd.DataFrame) -> pd.DataFrame:
    """
    Public alias for downstream modules that need the simulator-backed daily DC
    totals without reimplementing the grouping logic.
    """
    return _daily_dc_totals(dc_daily_sim)


def simulate_dc_dc_transfer(
    daily_demand_by_dc: dict[str, np.ndarray],
    dc_lane_pairs: list[tuple[str, str]],
    rng_seed: int = RANDOM_SEED,
) -> dict[str, np.ndarray]:
    dc_ids = list(daily_demand_by_dc.keys())
    n_days = 365
    demand = np.stack([np.asarray(daily_demand_by_dc[dc_id])[:n_days] for dc_id in dc_ids], axis=0)

    annual = demand.sum(axis=1)
    transfer_log = np.zeros_like(demand)
    annual_cap = annual * DC_ANNUAL_CAP_SHARE
    cumulative_out = np.zeros(len(dc_ids))

    week_medians = np.array([
        np.median([demand[idx, start:start + 7].sum() for start in range(0, n_days, 7)])
        for idx in range(len(dc_ids))
    ])

    for start in range(0, n_days, 7):
        end = min(start + 7, n_days)
        week_range = list(range(start, end))
        weekly_demand = demand[:, start:end].sum(axis=1)

        for i, dc_a in enumerate(dc_ids):
            if weekly_demand[i] / max(week_medians[i], 1.0) <= DC_STRESS_TRIGGER:
                continue
            excess = weekly_demand[i] - week_medians[i]

            best_j = -1
            best_transfer = 0.0
            for j, dc_b in enumerate(dc_ids):
                if j == i:
                    continue
                if (dc_a, dc_b) not in dc_lane_pairs and (dc_b, dc_a) not in dc_lane_pairs:
                    continue
                if weekly_demand[j] / max(week_medians[j], 1.0) >= DC_SLACK_THRESHOLD:
                    continue

                transfer_amount = min(
                    excess * DC_TRANSFER_SHARE,
                    DC_TRANSFER_SHARE * week_medians[j],
                    annual_cap[i] - cumulative_out[i],
                )
                if transfer_amount > best_transfer:
                    best_transfer = transfer_amount
                    best_j = j

            if best_j >= 0 and best_transfer > 0:
                daily_transfer = best_transfer / max(len(week_range), 1)
                transfer_log[i, week_range] += daily_transfer
                transfer_log[best_j, week_range] -= daily_transfer
                cumulative_out[i] += best_transfer

    return {dc_ids[idx]: transfer_log[idx] for idx in range(len(dc_ids))}


def compute_cyber_week_stress(dc_daily_sim: pd.DataFrame) -> pd.DataFrame:
    daily = _daily_dc_totals(dc_daily_sim)
    if daily.empty:
        return pd.DataFrame()

    daily["is_cyber_week"] = daily["date"].dt.date.map(is_cyber_week)

    annual = (
        daily.groupby(["sim", "dc_id"], as_index=False)
        .agg(annual_units=("daily_units", "sum"))
    )
    cyber = (
        daily[daily["is_cyber_week"]]
        .groupby(["sim", "dc_id"], as_index=False)
        .agg(
            cyber_week_units=("daily_units", "sum"),
            peak_daily_units=("daily_units", "max"),
        )
    )

    sim_metrics = annual.merge(cyber, on=["sim", "dc_id"], how="left").fillna(0.0)
    summary = (
        sim_metrics.groupby("dc_id", as_index=False)
        .agg(
            annual_units=("annual_units", "mean"),
            cyber_week_units=("cyber_week_units", "mean"),
            mean_peak_daily_units=("peak_daily_units", "mean"),
            p95_peak_daily_units=("peak_daily_units", lambda s: float(np.percentile(s, 95))),
        )
    )
    summary["cyber_share_pct"] = (
        summary["cyber_week_units"] / summary["annual_units"].clip(lower=1.0) * 100
    ).round(2)
    summary["throughput_req_pallets"] = np.ceil(
        summary["p95_peak_daily_units"] / UNITS_PER_PALLET_PI
    ).astype(int)
    return summary


def compute_dc_demand_intervals(dc_daily_sim: pd.DataFrame) -> pd.DataFrame:
    daily = _daily_dc_totals(dc_daily_sim)
    if daily.empty:
        return pd.DataFrame()

    annual = (
        daily.groupby(["sim", "dc_id"], as_index=False)
        .agg(annual_units=("daily_units", "sum"))
    )
    return (
        annual.groupby("dc_id", as_index=False)
        .agg(
            mean=("annual_units", "mean"),
            p10=("annual_units", lambda s: float(np.percentile(s, 10))),
            p50=("annual_units", lambda s: float(np.percentile(s, 50))),
            p90=("annual_units", lambda s: float(np.percentile(s, 90))),
            p99=("annual_units", lambda s: float(np.percentile(s, 99))),
        )
        .round(0)
    )
