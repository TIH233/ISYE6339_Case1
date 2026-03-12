"""
pipeline.py — Year-by-year orchestrator for the Task 5 PI network model.

Loop: 2027 → 2034, each year:
  1. Activate hubs (peri-urban + border relay) for open countries
  2. Generate all lane candidates
  3. PI demand pipeline (demand_generator)
  4. DC capacity simulation (flow_model)
  5. Compute all KPIs (evaluator: 5.1, 5.3, 5.6, 5.9, 5.10)
  6. Profitability (5.12)
  7. Accumulate + write outputs (reporting)
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from .config import (
    DEFAULT_N_SIM, RANDOM_SEED,
)
from .preprocess import run_preprocess
from .hub_network import (
    activate_hubs, generate_lanes,
    derive_relay_hubs_by_driving_distance, build_routes
)
from .evaluator import (
    compute_all_kpis,
    eval_52_container_requirements,
    eval_510_dc_capacity_sizing,
    eval_511_transload_cost,
    eval_512_profitability,
    eval_59_lane_cost_carbon,
    summarise_cost_carbon,
    simulate_otd_attainment,
    summarise_otd_by_bracket,
    eval_56_autonomy,
    trace_joint_shipment,
)
from .demand_generator import run_pi_demand_pipeline
from .flow_model import compute_dc_demand_intervals, compute_cyber_week_stress
from .reporting import write_all_outputs

DATA_DIR   = Path(__file__).resolve().parent.parent / "data"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

PIPELINE_YEARS = list(range(2027, 2035))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_pipeline(
    years: list[int] = PIPELINE_YEARS,
    force_rebuild: bool = False,
    n_sim: int = DEFAULT_N_SIM,
    seed: int = RANDOM_SEED,
    verbose: bool = True,
) -> list[dict]:
    """
    Full Task 5 pipeline.  Returns list of result dicts (one per year).
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Load / build nodes_master
    # ------------------------------------------------------------------
    nodes_path = DATA_DIR / "nodes_master.csv"
    if force_rebuild or not nodes_path.exists():
        if verbose:
            print("Building nodes_master...")
        nodes_base, _ = run_preprocess(DATA_DIR)
    else:
        nodes_base = pd.read_csv(nodes_path)
        if verbose:
            print(f"Loaded nodes_master ({len(nodes_base)} nodes)")

    # ------------------------------------------------------------------
    # Year loop
    # ------------------------------------------------------------------
    pipeline_results: list[dict] = []

    for year in years:
        if verbose:
            print(f"\n=== Year {year} ===")

        # First activate base nodes for this year
        active = activate_hubs(nodes_base, year)

        # Derive relay hubs based on driving-distance constraints (HUB-1 fix)
        relay_hubs = derive_relay_hubs_by_driving_distance(active, year)

        # Add relay hubs to active set
        if not relay_hubs.empty:
            # Align columns with active nodes
            for col in active.columns:
                if col not in relay_hubs.columns:
                    relay_hubs[col] = np.nan
            # Only add relay hubs with new IDs
            relay_new = relay_hubs[~relay_hubs["node_id"].isin(active["node_id"])].copy()
            if not relay_new.empty:
                active = pd.concat([active, relay_new[active.columns]], ignore_index=True)
        if verbose:
            print(f"  Nodes: {active['node_type'].value_counts().to_dict()}")

        lanes = generate_lanes(active, year)
        if verbose and not lanes.empty:
            print(f"  Lanes: {len(lanes)} ({lanes['lane_type'].value_counts().to_dict()})")

        # Build routes from lanes (HUB-1 fix)
        routes = build_routes(active, lanes, year) if not lanes.empty else pd.DataFrame()
        if verbose and not routes.empty:
            print(f"  Routes: {len(routes)} ({routes['service_mode'].value_counts().to_dict()})")

        # PI demand pipeline (pass routes for network-aware service overlay)
        pi_demand = run_pi_demand_pipeline(
            year, nodes=active, routes=routes, n_sim=n_sim, seed=seed
        )
        dc_daily_sim = pi_demand.get("dc_daily_sim", pd.DataFrame())
        annual_by_dc: dict[str, float] = pi_demand.get("annual_by_dc", {})
        service_matrix = pi_demand.get("service_matrix", pd.DataFrame())
        total_pi_units = float(sum(annual_by_dc.values())) if annual_by_dc else 0.0

        # DC capacity sizing + stress
        dc_capacity  = pd.DataFrame()
        cyber_stress = pd.DataFrame()
        dc_intervals = pd.DataFrame()
        if not dc_daily_sim.empty:
            dc_capacity  = eval_510_dc_capacity_sizing(dc_daily_sim, n_sim=n_sim, seed=seed)
            cyber_stress = compute_cyber_week_stress(dc_daily_sim)
            dc_intervals = compute_dc_demand_intervals(dc_daily_sim)

        # Container analysis (5.2)
        container_analysis = eval_52_container_requirements(total_pi_units)

        # Lane cost + carbon (5.9)
        lane_cost_df = pd.DataFrame()
        if annual_by_dc and not lanes.empty:
            lane_cost_df = eval_59_lane_cost_carbon(
                lanes=lanes,
                routes=routes,
                service_matrix=service_matrix,
                annual_units_by_dc=annual_by_dc,
                year=year,
            )

        # OTD Monte Carlo simulation (5.3)
        otd_sim_df    = pd.DataFrame()
        otd_by_bracket = pd.DataFrame()
        if not routes.empty:
            hub_brackets = active[active["node_type"] == "PERI_URBAN_HUB"][
                ["node_id", "pop_bracket"]
            ].copy()
            otd_sim_df     = simulate_otd_attainment(
                routes,
                hub_brackets,
                n_sim=n_sim,
                seed=seed,
            )
            otd_by_bracket = summarise_otd_by_bracket(otd_sim_df)
            if verbose and not otd_by_bracket.empty:
                print(
                    f"  OTD attainment: "
                    + "  ".join(
                        f"{r.pop_bracket}→{r.pi_promise_hr:.0f}hr attn={r.mean_attainment:.2%}"
                        for r in otd_by_bracket.itertuples()
                    )
                )

        # Autonomy (5.6)
        autonomy = eval_56_autonomy(active, lanes, year)

        # Transload (5.11)
        transload = eval_511_transload_cost(total_pi_units)

        # All KPIs
        kpis = compute_all_kpis(
            year, active, lanes,
            routes=routes,
            service_matrix=service_matrix if not service_matrix.empty else None,
            lane_cost_df=lane_cost_df if not lane_cost_df.empty else None,
        )

        # Profitability (5.12)
        profitability = eval_512_profitability(
            year=year,
            annual_pi_units=total_pi_units,
            dc_cost_df=dc_capacity,
            lane_cost_df=lane_cost_df,
            transload_dict=transload,
            service_matrix=service_matrix,
        )

        if verbose:
            print(
                f"  KPIs coverage={kpis.get('coverage_pct')}%  "
                f"relay={kpis.get('relay_readiness_pct')}%  "
                f"co2/unit={kpis.get('co2_per_unit_kg')} kg  "
                f"margin=€{profitability.get('pi_margin_eur', 0):,.0f}"
            )

        # Illustrative joint shipment trace (5.4)
        jst: list[dict] = []
        if not lanes.empty:
            port_nodes = active[active["node_type"] == "PORT"]["node_id"].tolist()
            hub_nodes  = active[active["node_type"] == "PERI_URBAN_HUB"]["node_id"].tolist()
            if port_nodes and hub_nodes:
                jst = trace_joint_shipment(port_nodes[0], hub_nodes[0], lanes, active)

        pipeline_results.append({
            "year":                year,
            "active_nodes":        active,
            "relay_hubs":          relay_hubs,
            "lanes":               lanes,
            "routes":              routes,  # HUB-1 fix: store routes for downstream use
            "kpis":                kpis,
            "pi_demand":           pi_demand,
            "dc_capacity":         dc_capacity,
            "cyber_stress":        cyber_stress,
            "dc_demand_intervals": dc_intervals,
            "container_analysis":  container_analysis,
            "lane_cost_df":        lane_cost_df,
            "otd_sim_df":          otd_sim_df,
            "otd_by_bracket":      otd_by_bracket,
            "autonomy":            autonomy,
            "transload":           transload,
            "profitability":       profitability,
            "joint_shipment_trace": jst,
        })

    # ------------------------------------------------------------------
    # Write outputs
    # ------------------------------------------------------------------
    if verbose:
        print("\nWriting outputs...")
    write_all_outputs(pipeline_results, OUTPUT_DIR)

    for res in pipeline_results:
        yr = res["year"]
        if not res["dc_capacity"].empty:
            res["dc_capacity"].to_csv(OUTPUT_DIR / f"dc_capacity_{yr}.csv", index=False)
        if not res["otd_sim_df"].empty:
            res["otd_sim_df"].to_csv(OUTPUT_DIR / f"otd_simulation_{yr}.csv", index=False)
        if not res["lane_cost_df"].empty:
            res["lane_cost_df"].to_csv(OUTPUT_DIR / f"lane_cost_carbon_{yr}.csv", index=False)

    pd.DataFrame([r["profitability"] for r in pipeline_results]).to_csv(
        OUTPUT_DIR / "profitability_by_year.csv", index=False
    )

    all_relays_list = [r["relay_hubs"] for r in pipeline_results if not r["relay_hubs"].empty]
    if all_relays_list:
        all_relays = pd.concat(all_relays_list, ignore_index=True)
        dedupe_cols = ["node_id"]
        if "derived_from_pair" in all_relays.columns:
            dedupe_cols.append("derived_from_pair")
        all_relays = all_relays.drop_duplicates(subset=dedupe_cols)
        all_relays.to_csv(DATA_DIR / "border_relay_hubs.csv", index=False)
        if verbose:
            print(f"  Written border_relay_hubs.csv ({len(all_relays)} rows)")

    return pipeline_results


# ---------------------------------------------------------------------------
# Summary helpers
# ---------------------------------------------------------------------------

def print_kpi_summary(pipeline_results: list[dict]) -> None:
    rows = []
    for res in sorted(pipeline_results, key=lambda r: r["year"]):
        k = res["kpis"]
        p = res["profitability"]
        rows.append({
            "Year":           k["year"],
            "DC":             k.get("n_dc", 0),
            "Hubs":           k.get("n_peri_urban_hub", 0),
            "Relays":         k.get("n_relay_hub", 0) + k.get("n_border_relay_hub", 0),
            "Lanes":          k.get("n_lanes_total", 0),
            "Coverage%":      k.get("coverage_pct"),
            "Relay%":         k.get("relay_readiness_pct"),
            "OTD attn":       k.get("mean_otd_attainment"),
            "Route hr":       k.get("mean_route_elapsed_hr"),
            "CO2 kg/unit":    k.get("co2_per_unit_kg"),
            "Margin €M":      round(p.get("pi_margin_eur", 0) / 1e6, 2),
        })
    print(pd.DataFrame(rows).set_index("Year").to_string())
