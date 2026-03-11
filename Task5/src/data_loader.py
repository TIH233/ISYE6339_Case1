"""
data_loader.py — Read Task2/Task4 artifacts and Excel sheets.
All data fixes (alias, ffill) applied here; callers receive clean DataFrames.
Uses partial/efficient read methods per project protocol.
"""

import pandas as pd
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths (relative to repo root)
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent
REPO_ROOT = _HERE.parent.parent          # ISYE6339_Case1/
EXCEL_PATH = REPO_ROOT / "Task2" / "task2 input.xlsx"
DC_PLAN_PATH = REPO_ROOT / "Task2" / "dc_open_plan.csv"
ASSIGNMENT_PATH = REPO_ROOT / "Task2" / "assignment_with_otd_prob_reachable.csv"
TIME_MATRIX_PATH = REPO_ROOT / "Task2" / "time_matrix.csv"
TASK4_DEMAND_PATH = REPO_ROOT / "Task4" / "dc_output" / "dc_daily_demand.parquet"


# ---------------------------------------------------------------------------
# Excel readers
# ---------------------------------------------------------------------------

def load_metro_sheet() -> pd.DataFrame:
    """
    Load Metro cities_location sheet.
    Fixes applied:
      - Forward-fill Countries (NaN run-down pattern)
      - Rename 'ing' → 'lng' (typo)
    Returns columns: Countries, Metropolitan cities, lat, lng, Pop_2026, last_mile_hours
    """
    df = pd.read_excel(EXCEL_PATH, sheet_name="Metro cities_location")
    df["Countries"] = df["Countries"].ffill()
    df = df.rename(columns={"ing": "lng"})
    df.columns = [c.strip() for c in df.columns]
    return df


def load_nonmetro_sheet() -> pd.DataFrame:
    """
    Load non_metro_hub sheet.
    Returns columns: country, lat, lng
    """
    return pd.read_excel(EXCEL_PATH, sheet_name="non_metro_hub")


# ---------------------------------------------------------------------------
# Task2 CSV artifacts
# ---------------------------------------------------------------------------

def load_dc_open_plan() -> pd.DataFrame:
    """
    Load Task2/dc_open_plan.csv.
    Columns: country, city, candidate, cca2, cand_id, lat, lng, first_open_year
    """
    return pd.read_csv(DC_PLAN_PATH)


def load_assignment(years: list[int] | None = None) -> pd.DataFrame:
    """
    Load Task2/assignment_with_otd_prob_reachable.csv.
    Optionally filter to specific years to reduce memory.
    Key columns for Task5: year, node_id, assigned_cand, node_type,
      travel_elapsed_hr, otd_days_promise, purchase_prob, reachable_units
    """
    cols = [
        "year", "node_id", "assigned_cand", "node_type",
        "units",
        "drive_time_hr", "travel_elapsed_hr",
        "otd_hours", "otd_days_promise", "otd_bucket", "purchase_prob",
        "reachable_units", "last_mile_hours", "last_mile_hours_final",
    ]
    df = pd.read_csv(ASSIGNMENT_PATH, usecols=cols)
    if years is not None:
        df = df[df["year"].isin(years)]
    return df


def load_time_matrix() -> pd.DataFrame:
    """Load Task2/time_matrix.csv (DC-to-node drive times)."""
    return pd.read_csv(TIME_MATRIX_PATH)


# ---------------------------------------------------------------------------
# Task4 parquet artifact
# ---------------------------------------------------------------------------

def load_task4_demand(
    columns: list[str] | None = None,
    filters=None,
) -> pd.DataFrame:
    """
    Partial read of Task4/dc_output/dc_daily_demand.parquet (18M+ rows).
    columns: subset of ['sim','date','year','euro_dc_id','model','realized_units']
    filters: pyarrow filter list, e.g. [('year', '==', 2027)]
    """
    kwargs: dict = {}
    if columns:
        kwargs["columns"] = columns
    if filters:
        kwargs["filters"] = filters
    return pd.read_parquet(TASK4_DEMAND_PATH, **kwargs)
