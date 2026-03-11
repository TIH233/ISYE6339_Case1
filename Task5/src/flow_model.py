"""
flow_model.py — DC-DC stress transfer, cyber week logic, capacity simulation.

Numpy-first inner loops.  Pandas only for I/O + final results.
Covers Task 5.6 (autonomy / relay continuity) and Task 5.10 (DC sizing).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import date, timedelta

from .config import (
    CYBER_WEEK_ANNUAL_SHARE, CYBER_WEEK_DAYS, PEAK_DAILY_SHARE,
    DC_STRESS_TRIGGER, DC_SLACK_THRESHOLD,
    DC_TRANSFER_SHARE, DC_ANNUAL_CAP_SHARE,
    HUB_RELAY_COST_EUR, UNITS_PER_PALLET_PI,
    DEFAULT_N_SIM, RANDOM_SEED,
)


# ---------------------------------------------------------------------------
# Cyber week detection
# ---------------------------------------------------------------------------

def is_cyber_week(sim_date: date) -> bool:
    """
    Return True if `sim_date` falls in the cyber week window.
    Cyber week = Black Friday (4th Thursday of November) through Cyber Monday + 2 days.
    """
    year = sim_date.year
    # 4th Thursday of November
    nov_1 = date(year, 11, 1)
    dow = nov_1.weekday()   # Mon=0 … Thu=3
    days_to_thu = (3 - dow) % 7
    first_thu = nov_1 + timedelta(days=days_to_thu)
    black_friday = first_thu + timedelta(weeks=3) + timedelta(days=1)   # Fri after 4th Thu
    cyber_monday = black_friday + timedelta(days=3)
    cyber_end    = cyber_monday + timedelta(days=2)
    return black_friday <= sim_date <= cyber_end


# ---------------------------------------------------------------------------
# DC-DC stress transfer model (normal periods only)
# ---------------------------------------------------------------------------

def simulate_dc_dc_transfer(
    daily_demand_by_dc: dict[str, np.ndarray],  # dc_id → 1-D array of daily units (365,)
    dc_lane_pairs: list[tuple[str, str]],        # (dc_a, dc_b) active DC-DC lanes
    rng_seed: int = RANDOM_SEED,
) -> dict[str, np.ndarray]:
    """
    Simulate weekly DC-DC stress transfers for a full year.

    Algorithm (PLAN.md §5):
      Rolling 7-day window per DC:
        if weekly_demand > DC_STRESS_TRIGGER × median_weekly_demand:
            excess = weekly_demand - median_weekly_demand
            find nearest DC where weekly_demand < DC_SLACK_THRESHOLD × its_median
            transfer = min(excess × DC_TRANSFER_SHARE, DC_TRANSFER_SHARE × nearest_DC.median_weekly)
        Cap: total transfer ≤ DC_ANNUAL_CAP_SHARE × DC annual throughput.
        No transfer during cyber week (day 325–332, approximate).

    Returns:
      transfers: dict dc_id → 1-D array of daily transferred-OUT units (negative = received)
    """
    dc_ids = list(daily_demand_by_dc.keys())
    n_days = 365

    # Pad/truncate all arrays to n_days
    demand = np.stack(
        [np.asarray(daily_demand_by_dc[d])[:n_days] for d in dc_ids], axis=0
    )  # shape (n_dc, n_days)

    annual   = demand.sum(axis=1)           # (n_dc,)
    transfer_log = np.zeros_like(demand)    # positive = transferred OUT

    # Approximate cyber week days (day-of-year ~325–332)
    cyber_days = set(range(323, 332))       # 0-indexed, approximate

    # Median weekly demand: slide week-at-a-time
    week_medians = np.array([
        np.median([demand[i, w:w+7].sum() for w in range(0, n_days, 7)])
        for i in range(len(dc_ids))
    ])  # (n_dc,)

    annual_cap = annual * DC_ANNUAL_CAP_SHARE   # (n_dc,)
    cumulative_out = np.zeros(len(dc_ids))

    for w_start in range(0, n_days, 7):
        w_end = min(w_start + 7, n_days)
        week_range = list(range(w_start, w_end))

        # Skip cyber week entirely
        if any(d in cyber_days for d in week_range):
            continue

        weekly_demand = demand[:, w_start:w_end].sum(axis=1)   # (n_dc,)

        for i, dc_a in enumerate(dc_ids):
            stress = weekly_demand[i] / max(week_medians[i], 1)
            if stress <= DC_STRESS_TRIGGER:
                continue

            # Find nearest DC with slack (demand < threshold × its_median)
            excess = weekly_demand[i] - week_medians[i]
            best_j, best_transfer = -1, 0.0

            for j, dc_b in enumerate(dc_ids):
                if j == i:
                    continue
                if (dc_a, dc_b) not in dc_lane_pairs and (dc_b, dc_a) not in dc_lane_pairs:
                    continue
                slack_ratio = weekly_demand[j] / max(week_medians[j], 1)
                if slack_ratio >= DC_SLACK_THRESHOLD:
                    continue
                transfer_amount = min(
                    excess * DC_TRANSFER_SHARE,
                    DC_TRANSFER_SHARE * week_medians[j],
                )
                # Respect annual cap
                remaining_cap = annual_cap[i] - cumulative_out[i]
                transfer_amount = min(transfer_amount, remaining_cap)
                if transfer_amount > best_transfer:
                    best_transfer = transfer_amount
                    best_j = j

            if best_j >= 0 and best_transfer > 0:
                # Distribute transfer evenly over week days
                daily_transfer = best_transfer / len(week_range)
                transfer_log[i, week_range] += daily_transfer
                transfer_log[best_j, week_range] -= daily_transfer
                cumulative_out[i] += best_transfer

    return {dc_ids[i]: transfer_log[i] for i in range(len(dc_ids))}


# ---------------------------------------------------------------------------
# Cyber week demand stress summary
# ---------------------------------------------------------------------------

def compute_cyber_week_stress(
    annual_units_by_dc: dict[str, float],
) -> pd.DataFrame:
    """
    Compute cyber week demand concentration metrics per DC.
    Returns: dc_id, annual_units, cyber_week_units, peak_daily_units,
             cyber_share_pct, throughput_required_pallets
    """
    records = []
    for dc_id, annual in annual_units_by_dc.items():
        cyber_total = annual * CYBER_WEEK_ANNUAL_SHARE
        peak_daily  = annual * PEAK_DAILY_SHARE
        pallet_req  = int(np.ceil(peak_daily / UNITS_PER_PALLET_PI))
        records.append({
            "dc_id":                dc_id,
            "annual_units":         round(annual, 0),
            "cyber_week_units":     round(cyber_total, 0),
            "peak_daily_units":     round(peak_daily, 0),
            "cyber_share_pct":      round(CYBER_WEEK_ANNUAL_SHARE * 100, 1),
            "throughput_req_pallets": pallet_req,
        })
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# DC utilisation simulation (numpy MC — used for sizing confidence intervals)
# ---------------------------------------------------------------------------

def simulate_annual_demand(
    annual_units_by_dc: dict[str, float],
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> dict[str, np.ndarray]:
    """
    Simulate n_sim realisations of annual DC demand.
    Uses lognormal distribution with CV=0.15 (±15% demand uncertainty).

    Returns: dc_id → array of shape (n_sim,)
    """
    rng = np.random.default_rng(seed)
    result: dict[str, np.ndarray] = {}
    for dc_id, mean_units in annual_units_by_dc.items():
        cv = 0.15
        sigma = np.sqrt(np.log(1 + cv**2))
        mu    = np.log(mean_units) - sigma**2 / 2
        result[dc_id] = rng.lognormal(mu, sigma, size=n_sim)
    return result


def compute_dc_demand_intervals(
    annual_units_by_dc: dict[str, float],
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    Compute P10/P50/P90/P99 annual demand intervals per DC from Monte Carlo.
    Used for DC capacity planning confidence bands.
    """
    sims = simulate_annual_demand(annual_units_by_dc, n_sim, seed)
    records = []
    for dc_id, samples in sims.items():
        records.append({
            "dc_id":    dc_id,
            "mean":     round(float(samples.mean()), 0),
            "p10":      round(float(np.percentile(samples, 10)), 0),
            "p50":      round(float(np.percentile(samples, 50)), 0),
            "p90":      round(float(np.percentile(samples, 90)), 0),
            "p99":      round(float(np.percentile(samples, 99)), 0),
        })
    return pd.DataFrame(records)
