"""
demand_generator.py — PI demand simulation reusing Task2/Task4 stochastic logic.

Covers Task 5.5 (OTD + reachable demand) and Task 5.7 (PI simulator adaptation).
Numpy-first pattern: all stochastic kernels use numpy; pandas used for I/O.

Pipeline:
  1. load_baseline()        → non-PI assignment DataFrame
  2. apply_pi_otd_rates()   → PI assignment (updated purchase_prob + otd_hours)
  3. compute_demand_uplift() → per-node uplift comparison
  4. simulate_pi_demand()   → Monte Carlo realized units (numpy arrays)
  5. aggregate_by_dc()      → annual PI demand by DC (for DC sizing)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from .config import (
    PI_OTD_BY_SEGMENT,
    REVENUE_PER_UNIT_EUR,
    DEFAULT_N_SIM,
    RANDOM_SEED,
)
from .data_loader import load_assignment


# ---------------------------------------------------------------------------
# PI OTD rate tables
# ---------------------------------------------------------------------------

# Pop-bracket → PI promise hours + purchase prob
_PI_METRO = {
    "1M+":      {"promise_hr": 4.0,  "purchase_prob": 1.00},
    "250K-1M":  {"promise_hr": 2.0,  "purchase_prob": 1.00},
    "<250K":    {"promise_hr": 1.0,  "purchase_prob": 1.00},
}

# Non-metro: by otd_bucket (0=same-day, 1=2-day, 2=3-4-day)
_PI_NONMETRO = {
    0: {"promise_hr": 8.0,  "purchase_prob": 0.99},
    1: {"promise_hr": 16.0, "purchase_prob": 0.99},
    2: {"promise_hr": 32.0, "purchase_prob": 0.99},
}


# ---------------------------------------------------------------------------
# Step 1 – Apply PI OTD rates to the non-PI assignment
# ---------------------------------------------------------------------------

def apply_pi_otd_rates(
    assignment: pd.DataFrame,
    nodes_master: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Convert non-PI assignment to PI scenario by overwriting:
      - purchase_prob  → PI purchase probability
      - otd_hours      → PI promise hours
      - reachable_units = units × pi_purchase_prob

    metro nodes: use pop_bracket from nodes_master (or infer from otd_bucket 0).
    non_metro nodes: use otd_bucket.

    Returns new DataFrame (non-PI columns preserved with _nonpi suffix).
    """
    df = assignment.copy()
    df = df.rename(columns={
        "purchase_prob":   "nonpi_purchase_prob",
        "reachable_units": "nonpi_reachable_units",
        "otd_hours":       "nonpi_otd_hours",
    })

    # Join pop_bracket from nodes_master if available
    if nodes_master is not None:
        pop_map = nodes_master.set_index("node_id")["pop_bracket"].to_dict()
        df["pop_bracket"] = df["node_id"].map(pop_map)
    else:
        df["pop_bracket"] = pd.NA

    # Vectorised PI assignment
    pi_prob  = np.full(len(df), 0.99)    # default non-metro low
    pi_hours = np.full(len(df), 32.0)    # default non-metro far

    metro_mask = df["node_type"] == "metro"
    for bracket, vals in _PI_METRO.items():
        bm = metro_mask & (df["pop_bracket"] == bracket)
        pi_prob[bm.values]  = vals["purchase_prob"]
        pi_hours[bm.values] = vals["promise_hr"]

    # Metro without bracket info → fallback to best promise
    bm_no_bracket = metro_mask & df["pop_bracket"].isna()
    pi_prob[bm_no_bracket.values]  = 1.00
    pi_hours[bm_no_bracket.values] = 4.0

    # Non-metro: by otd_bucket
    nm_mask = ~metro_mask
    for bucket, vals in _PI_NONMETRO.items():
        bm = nm_mask & (df["otd_bucket"] == bucket)
        pi_prob[bm.values]  = vals["purchase_prob"]
        pi_hours[bm.values] = vals["promise_hr"]

    df["pi_purchase_prob"]   = pi_prob
    df["pi_otd_hours"]       = pi_hours
    df["pi_reachable_units"] = df["units"] * df["pi_purchase_prob"]

    return df


# ---------------------------------------------------------------------------
# Step 2 – Demand uplift summary
# ---------------------------------------------------------------------------

def compute_demand_uplift(pi_df: pd.DataFrame) -> pd.DataFrame:
    """
    Per-node comparison of PI vs non-PI reachable units and OTD hours.
    Returns DataFrame with uplift metrics.
    """
    cols = [
        "year", "node_id", "node_type", "units",
        "nonpi_purchase_prob", "pi_purchase_prob",
        "nonpi_reachable_units", "pi_reachable_units",
        "nonpi_otd_hours", "pi_otd_hours",
    ]
    df = pi_df[[c for c in cols if c in pi_df.columns]].copy()
    df["demand_uplift_units"] = (df["pi_reachable_units"] - df["nonpi_reachable_units"]).round(2)
    df["demand_uplift_pct"]   = (
        df["demand_uplift_units"] / df["nonpi_reachable_units"].clip(lower=0.1) * 100
    ).round(2)
    df["otd_improvement_hr"]  = (df["nonpi_otd_hours"] - df["pi_otd_hours"]).round(2)
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 3 – Monte Carlo PI demand simulation (Task 5.7)
# ---------------------------------------------------------------------------

def simulate_pi_demand(
    pi_df: pd.DataFrame,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> pd.DataFrame:
    """
    Task 5.7: Simulate PI realized demand (n_sim Monte Carlo draws).
    Each draw samples:
      - Binomial(units, pi_purchase_prob) → purchased units
      - Binomial(purchased, adoption_rate_sample) → realized units

    adoption_rate_sample: Beta(α, β) where α, β fitted to non-PI purchase_prob
    (mean = pi_purchase_prob, CV ≈ 2%).

    Pattern: pandas-in → numpy-compute → pandas-out.

    Returns summary DataFrame: node_id, year, mean, std, p05, p50, p95
    """
    if pi_df.empty:
        return pd.DataFrame()

    rng  = np.random.default_rng(seed)
    n    = len(pi_df)

    units      = pi_df["units"].values.astype(float)          # (n,)
    pi_prob    = pi_df["pi_purchase_prob"].values.astype(float)

    # Beta parameters for purchase-prob uncertainty (CV = 2%)
    cv = 0.02
    alpha = pi_prob * ((1 - pi_prob) / (cv * pi_prob) ** 2 - 1)
    beta_ = alpha * (1 - pi_prob) / pi_prob
    alpha = np.clip(alpha, 0.5, 1000)
    beta_ = np.clip(beta_, 0.5, 1000)

    # Draw (n_sim, n) beta samples → purchase prob uncertainty
    prob_samples = rng.beta(alpha[None, :], beta_[None, :], size=(n_sim, n))   # (n_sim, n)

    # Realized demand: units × prob_sample (continuous approximation)
    realized = units[None, :] * prob_samples       # (n_sim, n)

    # Per-node statistics
    mean = realized.mean(axis=0)
    std  = realized.std(axis=0)
    p05  = np.percentile(realized, 5,  axis=0)
    p50  = np.percentile(realized, 50, axis=0)
    p95  = np.percentile(realized, 95, axis=0)

    result = pd.DataFrame({
        "node_id": pi_df["node_id"].values,
        "year":    pi_df["year"].values if "year" in pi_df.columns else 0,
        "units":   units.round(0),
        "mean":    mean.round(2),
        "std":     std.round(2),
        "p05":     p05.round(2),
        "p50":     p50.round(2),
        "p95":     p95.round(2),
    })
    return result


# ---------------------------------------------------------------------------
# Step 4 – Aggregate PI demand by DC
# ---------------------------------------------------------------------------

def aggregate_pi_demand_by_dc(
    pi_df: pd.DataFrame,
    assignment: pd.DataFrame,
    year: int,
) -> dict[str, float]:
    """
    Map PI realized demand (mean) back to assigned DCs.
    Returns: {dc_id: annual_pi_units}
    """
    yr_assign = assignment[assignment["year"] == year][["node_id", "assigned_cand"]].copy()
    yr_pi = pi_df[pi_df["year"] == year][["node_id", "pi_reachable_units"]].copy()
    merged = yr_assign.merge(yr_pi, on="node_id", how="inner")
    grouped = merged.groupby("assigned_cand")["pi_reachable_units"].sum()
    return grouped.round(0).to_dict()


# ---------------------------------------------------------------------------
# Convenience: run full PI demand pipeline for one year
# ---------------------------------------------------------------------------

def run_pi_demand_pipeline(
    year: int,
    nodes_master: pd.DataFrame | None = None,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
) -> dict:
    """
    Full pipeline:
      1. Load baseline assignment for year
      2. Apply PI OTD rates
      3. Compute demand uplift
      4. Monte Carlo simulation
      5. Aggregate by DC

    Returns dict with keys:
      pi_assignment, uplift_df, sim_df, annual_by_dc, uplift_summary
    """
    baseline = load_assignment(years=[year])
    if baseline.empty:
        return {}

    pi_asgn  = apply_pi_otd_rates(baseline, nodes_master)
    uplift   = compute_demand_uplift(pi_asgn)
    sim_df   = simulate_pi_demand(pi_asgn[pi_asgn["year"] == year], n_sim=n_sim, seed=seed)
    by_dc    = aggregate_pi_demand_by_dc(pi_asgn, baseline, year)

    total_nonpi = float(uplift["nonpi_reachable_units"].sum())
    total_pi    = float(uplift["pi_reachable_units"].sum())
    uplift_summary = {
        "year":                year,
        "nonpi_reachable_total": round(total_nonpi, 0),
        "pi_reachable_total":    round(total_pi, 0),
        "demand_uplift_pct":     round((total_pi - total_nonpi) / max(total_nonpi, 1) * 100, 2),
        "revenue_uplift_eur":    round((total_pi - total_nonpi) * REVENUE_PER_UNIT_EUR, 0),
    }

    return {
        "pi_assignment":  pi_asgn,
        "uplift_df":      uplift,
        "sim_df":         sim_df,
        "annual_by_dc":   by_dc,
        "uplift_summary": uplift_summary,
    }
