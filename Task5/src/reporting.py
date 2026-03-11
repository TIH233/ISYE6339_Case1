"""
reporting.py — Build and export roadmap tables, activation logs, KPI summaries,
and non-PI comparison table for Task 5.1.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from pathlib import Path

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"


# ---------------------------------------------------------------------------
# Roadmap table (per-year snapshot)
# ---------------------------------------------------------------------------

def build_roadmap_table(year: int, active_nodes: pd.DataFrame, lanes: pd.DataFrame) -> pd.DataFrame:
    """
    One row per node showing activation year and network role.
    Written to network_roadmap_{year}.csv.
    """
    tbl = active_nodes.copy()
    tbl["activation_year"] = tbl["first_open_year"].fillna(year).astype(int)
    tbl["network_year"] = year

    # Attach lane counts per node
    if not lanes.empty:
        outbound = lanes.groupby("origin_id")["lane_id"].count().rename("outbound_lanes")
        inbound  = lanes.groupby("dest_id")["lane_id"].count().rename("inbound_lanes")
        tbl = tbl.merge(outbound, left_on="node_id", right_index=True, how="left")
        tbl = tbl.merge(inbound,  left_on="node_id", right_index=True, how="left")
        tbl[["outbound_lanes", "inbound_lanes"]] = tbl[["outbound_lanes", "inbound_lanes"]].fillna(0).astype(int)
    else:
        tbl["outbound_lanes"] = 0
        tbl["inbound_lanes"] = 0

    return tbl[[
        "network_year", "node_id", "node_type", "country", "city",
        "lat", "lng", "pop_2026", "pop_bracket",
        "activation_year", "outbound_lanes", "inbound_lanes",
    ]]


# ---------------------------------------------------------------------------
# Activation decisions log
# ---------------------------------------------------------------------------

def build_activation_log(pipeline_results: list[dict]) -> pd.DataFrame:
    """
    Create activation_decisions_log.csv.
    For each newly activated node per year, log:
      node_id, activation_year, coverage_gain_pct,
      drive_time_reduction_hr (vs previous year best), detour_ratio
    """
    records: list[dict] = []
    prev_nodes: set[str] = set()
    prev_kpis: dict = {}

    for res in sorted(pipeline_results, key=lambda r: r["year"]):
        year = res["year"]
        active = res["active_nodes"]
        lanes  = res["lanes"]
        kpis   = res["kpis"]

        current_nodes = set(active["node_id"])
        new_nodes = current_nodes - prev_nodes

        coverage_gain = kpis.get("coverage_pct", 0) - prev_kpis.get("coverage_pct", 0)
        time_red = (
            prev_kpis.get("mean_time_saving_hr", 0)
            - kpis.get("mean_time_saving_hr", 0)
        ) if "mean_time_saving_hr" in kpis and "mean_time_saving_hr" in prev_kpis else 0

        for nid in new_nodes:
            node_row = active[active["node_id"] == nid]
            node_type = node_row["node_type"].values[0] if not node_row.empty else "UNKNOWN"

            # Best outbound lane detour ratio for this node
            best_det = np.nan
            if not lanes.empty:
                node_lanes = lanes[lanes["origin_id"] == nid]
                if not node_lanes.empty:
                    best_det = round(float(node_lanes["detour_ratio"].min()), 3)

            records.append({
                "node_id": nid,
                "node_type": node_type,
                "activation_year": year,
                "coverage_gain_pct": round(coverage_gain, 3) if len(prev_nodes) > 0 else None,
                "drive_time_reduction_hr": round(time_red, 3) if prev_kpis else None,
                "best_outbound_detour_ratio": best_det,
            })

        prev_nodes = current_nodes
        prev_kpis = kpis

    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# KPI summary table
# ---------------------------------------------------------------------------

def build_kpi_table(pipeline_results: list[dict]) -> pd.DataFrame:
    """
    One row per year with all KPI columns.
    Written to network_kpis_by_year.csv.
    """
    rows = [res["kpis"] for res in sorted(pipeline_results, key=lambda r: r["year"])]
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Non-PI comparison table
# ---------------------------------------------------------------------------

def build_nonpi_comparison(pipeline_results: list[dict], baseline: pd.DataFrame) -> pd.DataFrame:
    """
    Compare PI network topology KPIs vs non-PI baseline.
    Baseline: from assignment_with_otd_prob_reachable.csv.
    Columns: year, metric, pi_value, nonpi_value, delta, delta_pct
    """
    rows: list[dict] = []

    for res in sorted(pipeline_results, key=lambda r: r["year"]):
        year = res["year"]
        kpis = res["kpis"]
        base_yr = baseline[baseline["year"] == year] if not baseline.empty else pd.DataFrame()

        # Metric: mean travel elapsed hr
        pi_elapsed = None
        nonpi_elapsed = None

        elapsed_comp = res.get("elapsed_comparison")
        if elapsed_comp is not None and not elapsed_comp.empty:
            pi_elapsed   = round(float(elapsed_comp["pi_otd_hr"].mean()), 3)
            nonpi_elapsed = round(float(elapsed_comp["nonpi_otd_hr"].mean()), 3)
        elif not base_yr.empty:
            nonpi_elapsed = round(float(base_yr["travel_elapsed_hr"].mean()), 3)

        for metric, pi_val, nonpi_val in [
            ("coverage_pct",          kpis.get("coverage_pct"),      None),
            ("relay_readiness_pct",   kpis.get("relay_readiness_pct"), None),
            ("mean_travel_elapsed_hr", pi_elapsed,                    nonpi_elapsed),
            ("mean_detour_ratio",     kpis.get("mean_detour"),        1.2),   # DETOUR_FACTOR as non-PI baseline
        ]:
            delta = None
            delta_pct = None
            if pi_val is not None and nonpi_val is not None:
                delta = round(pi_val - nonpi_val, 3)
                delta_pct = round(delta / nonpi_val * 100, 2) if nonpi_val != 0 else None

            rows.append({
                "year": year,
                "metric": metric,
                "pi_value": pi_val,
                "nonpi_value": nonpi_val,
                "delta": delta,
                "delta_pct": delta_pct,
            })

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Write all outputs
# ---------------------------------------------------------------------------

def write_subtask_summaries(
    pipeline_results: list[dict],
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """
    Write one consolidated summary CSV per subtask, named subtask_5_X_<description>.csv.

    Subtask → file mapping
    ----------------------
    5.1  network_kpis_by_year.csv, network_roadmap_{year}.csv, activation_decisions_log.csv
    5.2  subtask_5_2_container_space.csv
    5.3  subtask_5_3_otd_attainment_by_bracket.csv  (+  otd_simulation_{year}.csv per year)
    5.4  subtask_5_4_joint_shipment_trace.csv
    5.5  subtask_5_5_demand_uplift.csv
    5.6  subtask_5_6_autonomy.csv
    5.9  subtask_5_9_cost_carbon_summary.csv  (+  lane_cost_carbon_{year}.csv per year)
    5.10 subtask_5_10_dc_demand_intervals.csv  (+  dc_capacity_{year}.csv per year)
    5.11 subtask_5_11_transload.csv
    5.12 subtask_5_12_profitability.csv  (alias of profitability_by_year.csv)
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    sorted_results = sorted(pipeline_results, key=lambda r: r["year"])

    # --- 5.2  Container / p-pack space requirements ---
    rows_52 = []
    for res in sorted_results:
        row = {"year": res["year"]}
        row.update(res["container_analysis"])
        rows_52.append(row)
    if rows_52:
        pd.DataFrame(rows_52).set_index("year").to_csv(
            output_dir / "subtask_5_2_container_space.csv"
        )
        print(f"  [5.2]  subtask_5_2_container_space.csv")

    # --- 5.3  OTD attainment by bracket (all years consolidated) ---
    rows_53 = []
    for res in sorted_results:
        if not res["otd_by_bracket"].empty:
            sub = res["otd_by_bracket"].copy()
            sub.insert(0, "year", res["year"])
            rows_53.append(sub)
    if rows_53:
        pd.concat(rows_53, ignore_index=True).to_csv(
            output_dir / "subtask_5_3_otd_attainment_by_bracket.csv", index=False
        )
        print(f"  [5.3]  subtask_5_3_otd_attainment_by_bracket.csv")

    # --- 5.4  Joint shipment illustrative trace (first available year) ---
    for res in sorted_results:
        jst = res.get("joint_shipment_trace", [])
        if jst:
            jst_df = pd.DataFrame(jst)
            jst_df.insert(0, "year", res["year"])
            jst_df.to_csv(output_dir / "subtask_5_4_joint_shipment_trace.csv", index=False)
            print(f"  [5.4]  subtask_5_4_joint_shipment_trace.csv  (year={res['year']})")
            break

    # --- 5.5  Demand uplift summary (all years) ---
    rows_55 = []
    for res in sorted_results:
        us = res.get("pi_demand", {}).get("uplift_summary", {})
        if us:
            rows_55.append(us)
    if rows_55:
        pd.DataFrame(rows_55).set_index("year").to_csv(
            output_dir / "subtask_5_5_demand_uplift.csv"
        )
        print(f"  [5.5]  subtask_5_5_demand_uplift.csv")

    # --- 5.6  Autonomy & relay readiness (all years) ---
    rows_56 = [res["autonomy"] for res in sorted_results]
    if rows_56:
        pd.DataFrame(rows_56).set_index("year").to_csv(
            output_dir / "subtask_5_6_autonomy.csv"
        )
        print(f"  [5.6]  subtask_5_6_autonomy.csv")

    # --- 5.9  Cost + carbon aggregate by year ---
    rows_59 = []
    for res in sorted_results:
        lc = res["lane_cost_df"]
        if not lc.empty:
            total_flow = lc["annual_flow"].sum()
            rows_59.append({
                "year":                res["year"],
                "total_transport_eur": round(float(lc["transport_cost_eur"].sum()), 0),
                "total_co2_kg":        round(float(lc["co2_kg"].sum()), 0),
                "total_road_km":       round(float(lc["road_km"].sum()), 0),
                "total_flow_units":    round(float(total_flow), 0),
                "cost_per_unit_eur":   round(float(lc["transport_cost_eur"].sum()) / max(float(total_flow), 1), 4),
                "co2_per_unit_kg":     round(float(lc["co2_kg"].sum()) / max(float(total_flow), 1), 4),
            })
    if rows_59:
        pd.DataFrame(rows_59).set_index("year").to_csv(
            output_dir / "subtask_5_9_cost_carbon_summary.csv"
        )
        print(f"  [5.9]  subtask_5_9_cost_carbon_summary.csv")

    # --- 5.10  DC demand intervals (all years consolidated) ---
    rows_510 = []
    for res in sorted_results:
        di = res["dc_demand_intervals"]
        if not di.empty:
            sub = di.copy()
            sub.insert(0, "year", res["year"])
            rows_510.append(sub)
    if rows_510:
        pd.concat(rows_510, ignore_index=True).to_csv(
            output_dir / "subtask_5_10_dc_demand_intervals.csv", index=False
        )
        print(f"  [5.10] subtask_5_10_dc_demand_intervals.csv")

    # --- 5.11  Transload cost (all years) ---
    rows_511 = []
    for res in sorted_results:
        row = {"year": res["year"]}
        row.update(res["transload"])
        rows_511.append(row)
    if rows_511:
        pd.DataFrame(rows_511).set_index("year").to_csv(
            output_dir / "subtask_5_11_transload.csv"
        )
        print(f"  [5.11] subtask_5_11_transload.csv")

    # --- 5.12  Profitability (subtask-named alias) ---
    rows_512 = [res["profitability"] for res in sorted_results]
    if rows_512:
        pd.DataFrame(rows_512).set_index("year").to_csv(
            output_dir / "subtask_5_12_profitability.csv"
        )
        print(f"  [5.12] subtask_5_12_profitability.csv")


def write_all_outputs(
    pipeline_results: list[dict],
    baseline: pd.DataFrame,
    output_dir: Path = OUTPUT_DIR,
) -> None:
    """
    Write all Task 5 output CSVs/parquets.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Per-year roadmap tables  [5.1]
    for res in pipeline_results:
        year = res["year"]
        tbl = build_roadmap_table(year, res["active_nodes"], res["lanes"])
        tbl.to_csv(output_dir / f"network_roadmap_{year}.csv", index=False)
        print(f"  Written network_roadmap_{year}.csv ({len(tbl)} nodes)")

    # Lane candidates (all years combined)  [5.1]
    all_lanes = pd.concat(
        [res["lanes"] for res in pipeline_results if not res["lanes"].empty],
        ignore_index=True,
    )
    if not all_lanes.empty:
        all_lanes.to_parquet(
            Path(__file__).resolve().parent.parent / "data" / "lane_candidates.parquet",
            index=False,
        )
        print(f"  Written lane_candidates.parquet ({len(all_lanes)} rows)")

    # Activation log  [5.1]
    act_log = build_activation_log(pipeline_results)
    act_log.to_csv(output_dir / "activation_decisions_log.csv", index=False)
    print(f"  Written activation_decisions_log.csv ({len(act_log)} rows)")

    # KPI table  [5.1]
    kpi_tbl = build_kpi_table(pipeline_results)
    kpi_tbl.to_csv(output_dir / "network_kpis_by_year.csv", index=False)
    print(f"  Written network_kpis_by_year.csv ({len(kpi_tbl)} rows)")

    # Non-PI comparison  [5.1]
    comp_tbl = build_nonpi_comparison(pipeline_results, baseline)
    comp_tbl.to_csv(output_dir / "network_vs_nonpi_comparison.csv", index=False)
    print(f"  Written network_vs_nonpi_comparison.csv ({len(comp_tbl)} rows)")

    # Subtask summary files  [5.2–5.12]
    print("\nWriting subtask summary files...")
    write_subtask_summaries(pipeline_results, output_dir)
