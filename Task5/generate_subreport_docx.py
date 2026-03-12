from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape
import zipfile

import pandas as pd
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
TASK5_DIR = ROOT / "Task5"
OUTPUT_DOCX = TASK5_DIR / "task5_subreport.docx"


@dataclass
class ImageSpec:
    path: Path
    rid: str
    name: str
    rel_path: str
    content_type: str
    cx: int
    cy: int


def eur_m(value: float) -> str:
    return f"EUR {value / 1_000_000:.1f}M"


def fmt_int(value: float) -> str:
    return f"{int(round(value)):,}"


def fmt_pct(value: float, decimals: int = 1) -> str:
    return f"{value:.{decimals}f}%"


def fmt_num(value: float, decimals: int = 2) -> str:
    return f"{value:.{decimals}f}"


def build_narrative() -> list[dict[str, str]]:
    kpi = pd.read_csv(TASK5_DIR / "output" / "network_kpis_by_year.csv")
    container = pd.read_csv(TASK5_DIR / "output" / "subtask_5_2_container_space.csv")
    otd = pd.read_csv(TASK5_DIR / "output" / "subtask_5_3_otd_profile_by_class.csv")
    otd_node_2030 = pd.read_csv(TASK5_DIR / "output" / "otd_profile_2030.csv")
    joint = pd.read_csv(TASK5_DIR / "output" / "subtask_5_4_joint_shipment_trace.csv")
    demand = pd.read_csv(TASK5_DIR / "output" / "subtask_5_5_pi_demand_summary.csv")
    autonomy = pd.read_csv(TASK5_DIR / "output" / "subtask_5_6_autonomy.csv")
    carbon = pd.read_csv(TASK5_DIR / "output" / "subtask_5_9_cost_carbon_summary.csv")
    dc_intervals = pd.read_csv(TASK5_DIR / "output" / "subtask_5_10_dc_demand_intervals.csv")
    transload = pd.read_csv(TASK5_DIR / "output" / "subtask_5_11_transload.csv")
    profit = pd.read_csv(TASK5_DIR / "output" / "subtask_5_12_profitability.csv")
    dc_2030 = pd.read_csv(TASK5_DIR / "output" / "dc_capacity_2030.csv")
    roadmap_2027 = pd.read_csv(TASK5_DIR / "output" / "network_roadmap_2027.csv")
    roadmap_2028 = pd.read_csv(TASK5_DIR / "output" / "network_roadmap_2028.csv")
    roadmap_2029 = pd.read_csv(TASK5_DIR / "output" / "network_roadmap_2029.csv")
    roadmap_2030 = pd.read_csv(TASK5_DIR / "output" / "network_roadmap_2030.csv")
    lane_2030 = pd.read_csv(TASK5_DIR / "output" / "lane_cost_carbon_2030.csv")
    comparison = pd.read_csv(ROOT / "comparison" / "data" / "task4_vs_task5_yearly_comparison.csv")
    tradeoff = pd.read_csv(ROOT / "comparison" / "data" / "pi_tradeoff_metrics.csv")
    horizon = pd.read_csv(ROOT / "comparison" / "data" / "horizon_efficiency_summary.csv").set_index("metric_label")

    row_2030 = kpi.loc[kpi["year"] == 2030].iloc[0]
    container_2030 = container.loc[container["year"] == 2030].iloc[0]
    demand_2030 = demand.loc[demand["year"] == 2030].iloc[0]
    autonomy_2030 = autonomy.loc[autonomy["year"] == 2030].iloc[0]
    carbon_2030 = carbon.loc[carbon["year"] == 2030].iloc[0]
    transload_2030 = transload.loc[transload["year"] == 2030].iloc[0]
    profit_2030 = profit.loc[profit["year"] == 2030].iloc[0]
    comp_2027 = comparison.loc[comparison["year"] == 2027].iloc[0]
    comp_2030 = comparison.loc[comparison["year"] == 2030].iloc[0]
    comp_2034 = comparison.loc[comparison["year"] == 2034].iloc[0]
    tradeoff_2030 = tradeoff.loc[tradeoff["year"] == 2030].set_index("metric_key")
    otd_2030 = otd.loc[otd["year"] == 2030].set_index("service_class")
    interval_2030 = dc_intervals.loc[dc_intervals["year"] == 2030].copy()

    pi_units_total = comparison["pi_realized_units"].sum()
    old_units_total = comparison["old_realized_units"].sum()
    pi_transport_per_unit = comparison["pi_transport_cost_eur"].sum() / pi_units_total
    old_transport_per_unit = comparison["old_transport_cost_eur"].sum() / old_units_total
    pi_scope_per_unit = comparison["pi_network_scope_cost_eur"].sum() / pi_units_total
    old_scope_per_unit = comparison["old_network_scope_cost_eur"].sum() / old_units_total

    horizon_units_adv = (pi_units_total / old_units_total - 1.0) * 100.0
    horizon_scope_reduction = (1.0 - pi_scope_per_unit / old_scope_per_unit) * 100.0
    horizon_transport_reduction = (1.0 - pi_transport_per_unit / old_transport_per_unit) * 100.0

    units_per_teu_nonpi = int(round(float(container_2030["annual_units"]) / float(container_2030["teus_nonpi"])))
    units_per_teu_pi = int(round(float(container_2030["annual_units"]) / float(container_2030["teus_pi"])))

    port_dc = lane_2030.loc[lane_2030["lane_type"] == "PORT_DC", ["lane_id", "drive_time_hr", "road_km"]].copy()
    port_dc["dest_id"] = port_dc["lane_id"].str.split("__").str[-1]
    port_dc["drive_time_hr"] = port_dc["drive_time_hr"].round(3)
    port_dc_map = port_dc.set_index("dest_id")[["drive_time_hr", "road_km"]].to_dict("index")
    route_mode_counts = otd_node_2030["service_mode"].value_counts().to_dict()
    route_dc_summary = (
        otd_node_2030.groupby("assigned_dc_id", as_index=False)
        .agg(
            min_elapsed_hr=("travel_elapsed_hr", "min"),
            mean_elapsed_hr=("travel_elapsed_hr", "mean"),
            p95_elapsed_hr=("travel_elapsed_hr", lambda s: float(s.quantile(0.95))),
        )
        .round(3)
    )
    route_dc_map = route_dc_summary.set_index("assigned_dc_id").to_dict("index")

    joint_steps = []
    for row in joint.itertuples(index=False):
        joint_steps.append(
            f"step {row.step}: {row.from_id} to {row.to_id} via {row.lane_type}, "
            f"{fmt_num(float(row.cumulative_elapsed_hr))}h cumulative"
        )

    dc_summary_bits = [
        f"{row.dc_id.replace('CAND_', '').replace('_', ' ')} mean {fmt_int(float(row.mean))} units"
        for row in interval_2030.itertuples(index=False)
    ]
    dc_cost_bits = [
        f"{row.dc_id.replace('CAND_', '').replace('_', ' ')} {eur_m(float(row.dc_total_cost_eur))}"
        for row in dc_2030.itertuples(index=False)
    ]

    paragraphs = [
        {"style": "Title", "text": "Task 5 Subreport: PI Hyperconnected Transportation"},
        {
            "style": "Normal",
            "text": (
                "This report is structured directly around the Task 5 PDF prompts. Each section "
                "below corresponds to one of the 15 Task 5 subtasks and uses the current repo's "
                "Task5 pipeline, output tables, and comparison artifacts as the evidence base."
            ),
        },
        {"style": "Heading1", "text": "Task 5.1: Network Design and Roadmap"},
        {
            "style": "Normal",
            "text": (
                "The implemented PI design is a phased multi-tier network rather than a fully "
                "enumerated pan-European mesh. Rotterdam is the fixed port entry, Euro DCs open "
                "progressively from 2027 to 2030, peri-urban hubs are created from the metro-city "
                "layer, and non-metro demand centroids are retained as service sinks. Relay hubs "
                "are generated algorithmically whenever a DC-to-market movement breaches the "
                "11-hour single-driver threshold. Candidate relays are placed at the mid-journey "
                "point, clustered within 80 km, and merged with nearby peri-urban hubs when "
                "possible so the network reuses open infrastructure instead of inventing a dense "
                "new bespoke hub system."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The lane design mirrors the PDF requirements: port-to-DC trunk links, DC-to-DC "
                "transfer links, direct DC-to-hub lanes when a market is within four driving hours, "
                "DC-to-relay legs for long-haul support, relay-to-hub feeders, and short hub "
                "corridors. Routes are selected by shortest elapsed time, not raw distance, using "
                "one hour of dwell at relay-only hubs and two hours at consolidation-capable hubs. "
                "That gives a network focused on daily departures, relay continuity, and low detour. "
                f"The rollout grows from {fmt_int(float((roadmap_2027['node_type'] == 'PERI_URBAN_HUB').sum()))} peri-urban hubs "
                f"and {fmt_int(float(comp_2027['pi_lane_count']))} lanes in 2027 to "
                f"{fmt_int(float(row_2030['n_peri_urban_hub']))} peri-urban hubs, "
                f"{fmt_int(float(row_2030['n_relay_hub']))} relay hubs, and "
                f"{fmt_int(float(row_2030['n_lanes_total']))} lanes by 2030. Coverage reaches "
                f"{fmt_pct(float(row_2030['coverage_pct']), 2)} with mean detour "
                f"{fmt_num(float(row_2030['mean_detour']), 3)}."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The yearly roadmap is also clear. 2027 is a northwestern core with 1 DC and no "
                f"relay hubs. 2028 adds the second DC and about {fmt_int(float((roadmap_2028['node_type'] == 'RELAY_HUB').sum()))} relay hubs. "
                f"2029 expands the footprint to {fmt_int(float((roadmap_2029['node_type'] == 'DC').sum()))} DCs, "
                f"{fmt_int(float((roadmap_2029['node_type'] == 'PERI_URBAN_HUB').sum()))} peri-urban hubs, and "
                f"{fmt_int(float((roadmap_2029['node_type'] == 'RELAY_HUB').sum()))} relay hubs. By 2030 the full "
                "network is in place and remains topologically stable through 2034, which makes the "
                "later changes mostly volume-driven rather than topology-driven."
            ),
        },
        {"style": "Caption", "text": "Figure 1. Task 5 topology KPIs by year."},
        {"style": "Image", "text": "fig_5_1_topology_kpis.png"},
        {"style": "Caption", "text": "Figure 2. 2030 PI network map and node layout."},
        {"style": "Image", "text": "fig_5_1_network_map_2030.png"},
        {"style": "Heading1", "text": "Task 5.2: Space Savings from PI Packaging"},
        {
            "style": "Normal",
            "text": (
                "The PI packaging assumptions materially change density. The model uses a 40.0% "
                "unit cube reduction from the non-PI package to the PI p-pack configuration. At the "
                "2030 volume level, this cuts pallet need by "
                f"{fmt_pct(float(container_2030['pallet_saving_pct']))} and TEU need by "
                f"{fmt_pct(float(container_2030['teu_saving_pct']))}. Put differently, the modeled "
                f"6-meter ocean unit goes from about {units_per_teu_nonpi} units in the non-PI case "
                f"to about {units_per_teu_pi} units in the PI case."
            ),
        },
        {
            "style": "Normal",
            "text": (
                f"In 2030 the same annual demand would require {fmt_int(float(container_2030['teus_nonpi']))} "
                f"non-PI TEUs versus {fmt_int(float(container_2030['teus_pi']))} PI TEUs. That is a "
                "large enough density change to matter strategically because it reduces ocean "
                "shipping intensity, port handling dependence, and the number of inland flows that "
                "must be coordinated once cargo lands in Europe."
            ),
        },
        {"style": "Heading1", "text": "Task 5.3: Transport Time Reduction"},
        {
            "style": "Normal",
            "text": (
                "The design reduces transport time by creating a route-backed hierarchy instead of "
                "forcing every downstream movement through a narrow DC-centric structure. In the "
                "2030 network, Rotterdam-to-DC drive times are approximately "
                f"{fmt_num(float(port_dc_map['CAND_DE_koeln']['drive_time_hr']))}h to Koeln, "
                f"{fmt_num(float(port_dc_map['CAND_PL_lodz']['drive_time_hr']))}h to Lodz, "
                f"{fmt_num(float(port_dc_map['CAND_IT_rome']['drive_time_hr']))}h to Rome, and "
                f"{fmt_num(float(port_dc_map['CAND_ES_madrid']['drive_time_hr']))}h to Madrid. Downstream from the "
                "DCs, the active route mix contains "
                f"{route_mode_counts.get('DIRECT', 0)} direct paths, "
                f"{route_mode_counts.get('VIA_RELAY', 0)} relay-backed paths, "
                f"{route_mode_counts.get('VIA_DC_TRANSFER', 0)} DC-transfer paths, and "
                f"{route_mode_counts.get('VIA_HUB_CORRIDOR', 0)} hub-corridor paths."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The route summaries show the same pattern. Koeln is the fastest-positioned DC, with "
                f"mean downstream elapsed time {fmt_num(float(route_dc_map['CAND_DE_koeln']['mean_elapsed_hr']))}h "
                f"and p95 {fmt_num(float(route_dc_map['CAND_DE_koeln']['p95_elapsed_hr']))}h. Madrid is "
                f"the hardest-positioned DC, with mean {fmt_num(float(route_dc_map['CAND_ES_madrid']['mean_elapsed_hr']))}h "
                f"and p95 {fmt_num(float(route_dc_map['CAND_ES_madrid']['p95_elapsed_hr']))}h. At the "
                "service-class level in 2030, mean OTD is about "
                f"{fmt_num(float(otd_2030.loc['METRO_250K-1M', 'mean_otd_hr']))}h for mid-sized metros, "
                f"{fmt_num(float(otd_2030.loc['NONMETRO_<=250KM', 'mean_otd_hr']))}h for closer non-metro "
                f"markets, and {fmt_num(float(otd_2030.loc['NONMETRO_>500KM', 'mean_otd_hr']))}h for the "
                "longest non-metro tail. This is the right signature for a relay-enabled network: a "
                "much faster average response than a single-tier network, with a remaining long-tail "
                "service penalty for remote markets."
            ),
        },
        {"style": "Caption", "text": "Figure 3. OTD simulation outputs used for transport-time assessment."},
        {"style": "Image", "text": "fig_5_3_otd_simulation.png"},
        {"style": "Heading1", "text": "Task 5.4: Joint Shipment Example"},
        {
            "style": "Normal",
            "text": (
                "The saved illustrative trace is a 2027 example because that is the first year with "
                "a complete joint-shipment walkthrough in the output set. It shows a shipment moving "
                + "; ".join(joint_steps)
                + ". Even in this compact example, the structure differs materially from the old "
                "network because cargo is already routed through a hub-aware flow rather than simply "
                "being pushed from port to DC and then served from a single downstream warehouse logic."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "For an all-Euro-DC mixed shipment, the PI logic supports two operational variants. "
                "One is a sealed p-pod path from Savannah to Rotterdam and then to the appropriate "
                "Euro DC. The second is a deconsolidate-and-reconsolidate path where p-boxes are "
                "sorted by downstream direction and injected into different DC, relay, and hub paths "
                "after Rotterdam. The latter is where the PI design creates value relative to the old "
                "scenario because mixed cargo can keep flowing without waiting for destination-specific "
                "full truckloads."
            ),
        },
        {"style": "Caption", "text": "Figure 4. Task 5 joint-shipment illustration."},
        {"style": "Image", "text": "fig_5_4_joint_shipment.png"},
        {"style": "Heading1", "text": "Task 5.5: Customer OTD and Realized Demand"},
        {
            "style": "Normal",
            "text": (
                "The service matrix translates route times into purchase probability by market class. "
                "In 2030, large-metro markets average about "
                f"{fmt_num(float(otd_2030.loc['METRO_1M+', 'mean_otd_hr']))}h OTD with "
                f"{fmt_num(float(otd_2030.loc['METRO_1M+', 'mean_purchase_prob']), 3)} purchase "
                "probability, mid-sized metros average "
                f"{fmt_num(float(otd_2030.loc['METRO_250K-1M', 'mean_otd_hr']))}h, and the closest "
                "non-metro markets average "
                f"{fmt_num(float(otd_2030.loc['NONMETRO_<=250KM', 'mean_otd_hr']))}h. The hardest "
                f"remote non-metro class still averages {fmt_num(float(otd_2030.loc['NONMETRO_>500KM', 'mean_otd_hr']))}h "
                f"with purchase probability {fmt_num(float(otd_2030.loc['NONMETRO_>500KM', 'mean_purchase_prob']), 3)}, "
                "which explains why the long-distance tail remains the weakest demand segment."
            ),
        },
        {
            "style": "Normal",
            "text": (
                f"Realized PI demand rises from {fmt_int(float(comp_2027['pi_realized_units']))} "
                f"units in 2027 to {fmt_int(float(demand_2030['pi_realized_total']))} in 2030 and "
                f"{fmt_int(float(comp_2034['pi_realized_units']))} in 2034. Revenue rises in parallel "
                f"to {eur_m(float(demand_2030['pi_revenue_eur']))} in 2030 and "
                f"{eur_m(float(comp_2034['pi_revenue_eur']))} in 2034. The route-backed share remains "
                f"high at {fmt_pct(float(demand_2030['route_backed_share_pct']), 2)} in 2030, which "
                "means the demand uplift is mostly tied to explicit service design rather than to "
                "unexplained exogenous optimism."
            ),
        },
        {"style": "Caption", "text": "Figure 5. PI demand uplift across the rollout horizon."},
        {"style": "Image", "text": "fig_5_5_demand_uplift.png"},
        {"style": "Heading1", "text": "Task 5.6: Autonomy Targets and Recommendations"},
        {
            "style": "Normal",
            "text": (
                "The exported autonomy table operationalizes autonomy through relay readiness, the "
                "share of DC-to-DC moves needing relay support, and the degree of dual-role hub reuse. "
                f"By 2030 relay readiness is {fmt_pct(float(autonomy_2030['relay_readiness_pct']), 2)}, "
                f"DC-to-DC relay dependence is {fmt_pct(float(autonomy_2030['dc_dc_relay_required_pct']), 2)}, "
                f"and {fmt_pct(float(autonomy_2030['dual_role_pct']), 2)} of peri-urban hubs are serving "
                "a dual role. That supports a lower autonomy requirement than in the non-PI network "
                "because the design allows inter-DC support and relay continuity."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "Inference from the implemented network: a reasonable lower bound is roughly 1.5 to "
                "2 days of autonomy at about 90% robustness for the network core, while a reasonable "
                "upper bound is 4 to 5 days at about 99% robustness for tail protection. A practical "
                "recommended target is 2 days at 95% robustness for Koeln and Lodz, and 3 days at "
                "95% robustness for Rome and Madrid because their port ingress and downstream route "
                "profiles are longer. Relative to the non-PI scenario, these targets are lower because "
                "the PI network explicitly supports cross-network buffering and rebalancing."
            ),
        },
        {"style": "Caption", "text": "Figure 6. Autonomy and relay-readiness summary."},
        {"style": "Image", "text": "fig_5_6_autonomy.png"},
        {"style": "Heading1", "text": "Task 5.7: Simulator Adaptation"},
        {
            "style": "Normal",
            "text": (
                "The non-PI simulator was adapted by keeping the Task 4-style daily demand kernel "
                "but replacing the service logic with a PI route-aware service matrix. The updated "
                "pipeline activates the yearly network, builds routes, converts route elapsed time "
                "into purchase probability, simulates DC-level daily demand with cyber-week seasonality, "
                "and then feeds those daily flows into DC sizing, cost, carbon, and profitability "
                "evaluation. This is a substantive change from a simple DC-based demand model because "
                "purchase and flow assignment now depend on actual route structure."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The major PI-specific mechanisms are the route-backed service matrix, the relay and "
                "consolidation dwell-time logic, the ability to represent DC-to-DC transfers, and the "
                "conversion of OTD into realized demand by service class. That makes the simulator "
                "suitable for Tasks 5.1 to 5.4 and 5.6, which is exactly how the case frames its role."
            ),
        },
        {"style": "Heading1", "text": "Task 5.8: Validation Using the Proposed Autonomy Logic"},
        {
            "style": "Normal",
            "text": (
                "Interpreting the PDF's reference to autonomy-target validation as a validation of "
                "the autonomy logic from Task 5.6, the current implementation is strongest on "
                "structural validation rather than external calibration. Coverage remains above 97% "
                "after full rollout, mean detour stays near 1.02, and the route-backed share is about "
                "97% in the mature network. Those are useful checks that the simulated network is "
                "behaving coherently."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The DC sizing outputs provide another validation layer. In 2030 the model sizes peak "
                "daily throughput at 4,747 units for Koeln, 2,246 for Lodz, 1,495 for Rome, and 965 "
                "for Madrid. The saved annual demand intervals show almost no spread under the current "
                "configuration, which means the exported uncertainty is low and the model is behaving "
                "more like a logic-consistency simulator than a wide-variance Monte Carlo forecast. "
                "That is a legitimate modeling choice, but it should be recognized as a limitation."
            ),
        },
        {"style": "Heading1", "text": "Task 5.9: Shipments, Trucks, Distance, Cost, and Logistics Load"},
        {
            "style": "Normal",
            "text": (
                "The 5.9 output quantifies how the PI network scales operationally. In 2030 it handles "
                f"{fmt_int(float(carbon_2030['total_flow_units']))} routed flow units, "
                f"{fmt_int(float(carbon_2030['total_truckloads']))} truckloads, and "
                f"{fmt_int(float(carbon_2030['total_road_km']))} road-km, at total transport cost "
                f"{eur_m(float(carbon_2030['total_transport_eur']))}. Cost per routed unit is "
                f"EUR {fmt_num(float(carbon_2030['cost_per_unit_eur']))}."
            ),
        },
        {
            "style": "Normal",
            "text": (
                f"From 2027 to 2034 total transport cost rises from {eur_m(float(comp_2027['pi_transport_cost_eur']))} "
                f"to {eur_m(float(comp_2034['pi_transport_cost_eur']))}, "
                "but the network footprint is already fixed after 2030, so most of that growth is a "
                "volume effect. The operational interpretation is that the PI network is capable of "
                "absorbing higher demand after 2030 without needing another major topology redesign."
            ),
        },
        {"style": "Caption", "text": "Figure 7. Cost and carbon summary from Task 5."},
        {"style": "Image", "text": "fig_5_9_cost_carbon.png"},
        {"style": "Heading1", "text": "Task 5.10: DC Storage, Throughput, Design, and Costing"},
        {
            "style": "Normal",
            "text": (
                "The saved 5.10 artifacts explicitly size the Euro DCs. In 2030 the approximate "
                "annual demand allocation is "
                + "; ".join(dc_summary_bits)
                + ". The resulting peak-throughput sizing is 1,584 pallet-throughput capacity for "
                "Koeln, 750 for Lodz, 500 for Rome, and 322 for Madrid, with corresponding storage "
                "positions of 702, 332, 221, and 143."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "The annual Euro-DC cost estimates are "
                + "; ".join(dc_cost_bits)
                + ". The exported table does not provide a separate Savannah design sheet in the same "
                "format; Savannah is represented more indirectly through the port, transload, and "
                "total profitability cost blocks. That means the Euro-DC sizing result is explicit, "
                "while the Savannah side is embedded in the broader network-cost structure rather than "
                "in a standalone facility design output."
            ),
        },
        {"style": "Caption", "text": "Figure 8. Simulation-backed DC capacity sizing."},
        {"style": "Image", "text": "fig_5_10_dc_capacity.png"},
        {"style": "Heading1", "text": "Task 5.11: Transload Center Load and Cost"},
        {
            "style": "Normal",
            "text": (
                "The PI model assumes two transload centers, one in Savannah and one in Rotterdam, "
                "with EUR 1.5 per unit at each center, or EUR 3.0 total per unit crossing both. "
                f"In 2030 this yields total transload cost of {eur_m(float(transload_2030['total_transload_cost_eur']))}. "
                f"Using the same EUR 3.0-per-unit rule, the 2034 transload burden is about {eur_m(float(comp_2034['pi_realized_units']) * 3.0)}. "
                "This is a clean cost structure, but it also means the transload analysis is driven "
                "mainly by total PI volume rather than by a differentiated queueing model at the ports."
            ),
        },
        {"style": "Heading1", "text": "Task 5.12: Total Demand, Revenue, Cost, and Profitability"},
        {
            "style": "Normal",
            "text": (
                f"In 2030 the PI network delivers {fmt_int(float(profit_2030['pi_units']))} units and "
                f"{eur_m(float(profit_2030['pi_revenue_eur']))} of revenue. Total PI cost is "
                f"{eur_m(float(profit_2030['total_pi_cost_eur']))}, composed primarily of transport, "
                "last-mile, DC, p-pack, transload, and hub logistics charges. The resulting margin is "
                f"{eur_m(float(profit_2030['pi_margin_eur']))}, or {fmt_pct(float(profit_2030['pi_margin_pct']), 2)}."
            ),
        },
        {
            "style": "Normal",
            "text": (
                f"By 2034 the comparison horizon still shows {fmt_int(float(comp_2034['pi_realized_units']))} "
                f"realized units and {eur_m(float(comp_2034['pi_revenue_eur']))} of revenue, with "
                f"network-scope margin of {eur_m(float(comp_2034['pi_network_scope_margin_eur']))}. "
                "The detailed profitability export currently on disk is 2030-only, but the horizon "
                "comparison still supports the conclusion that profitability stays strong after the "
                "network matures because later growth exploits the same relay and hub structure rather "
                "than expanding it again."
            ),
        },
        {"style": "Caption", "text": "Figure 9. PI profitability by year."},
        {"style": "Image", "text": "fig_5_12_profitability.png"},
        {"style": "Heading1", "text": "Task 5.13: Energy Use and Greenhouse Gas Emissions"},
        {
            "style": "Normal",
            "text": (
                "The implementation quantifies emissions directly using truck-class distance factors "
                "and reports the result as CO2. In 2030 the network emits "
                f"{fmt_int(float(carbon_2030['total_co2_kg']))} kg CO2, or "
                f"{fmt_num(float(carbon_2030['co2_per_unit_kg']))} kg per routed unit. By 2034 the "
                f"total rises to {fmt_int(float(comp_2034['pi_total_co2_kg']))} kg CO2."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "Strictly speaking, the repo's saved Task 5 outputs export emissions rather than a "
                "separate fuel or energy field. The energy logic is therefore embedded in the "
                "truck-distance emission methodology rather than reported as a standalone liters or "
                "kWh measure. For this report, the greenhouse-gas estimate is the directly supported "
                "answer from the model outputs."
            ),
        },
        {"style": "Caption", "text": "Figure 10. Lane-level carbon view for the PI network."},
        {"style": "Image", "text": "fig_5_9_carbon_by_lane.png"},
        {"style": "Heading1", "text": "Task 5.14: Contrast with the Non-PI Task 4 Network"},
        {
            "style": "Normal",
            "text": (
                "The matched comparison is the strongest argument for the PI scenario. In 2030 realized "
                f"demand rises from {fmt_int(float(comp_2030['old_realized_units']))} units in the old "
                f"network to {fmt_int(float(comp_2030['pi_realized_units']))} units in the PI network, "
                f"a {fmt_pct(float(comp_2030['units_uplift_pct']))} uplift. Transport cost per unit falls "
                f"from EUR {fmt_num(float(comp_2030['old_transport_cost_per_unit_eur']))} to EUR "
                f"{fmt_num(float(comp_2030['pi_transport_cost_per_unit_eur']))}, while matched "
                "network-scope cost per unit falls from "
                f"EUR {fmt_num(float(comp_2030['old_network_scope_cost_per_unit_eur']))} to EUR "
                f"{fmt_num(float(comp_2030['pi_network_scope_cost_per_unit_eur']))}."
            ),
        },
        {
            "style": "Normal",
            "text": (
                f"Across the full 2027-2034 horizon, PI delivers {fmt_pct(horizon_units_adv)} more "
                f"realized units, {fmt_pct(horizon_transport_reduction)} lower transport cost per unit, "
                f"and {fmt_pct(horizon_scope_reduction)} lower matched network-scope cost per unit. "
                f"It also cuts shipping intensity by {fmt_pct(float(horizon.loc['Shipping units per 1000 sold units', 'advantage_pct']))}. "
                "The tradeoff is orchestration complexity: in 2030 the remaining gaps are a "
                f"{fmt_num(float(tradeoff_2030.loc['coverage_shortfall_pct_pts', 'pi_value']))} percentage-point "
                f"coverage shortfall, {fmt_pct(float(tradeoff_2030.loc['relay_unready_share_pct', 'pi_value']))} "
                "of the relay mesh not fully ready, and a "
                f"{fmt_num(float(tradeoff_2030.loc['service_tail_spread_hr', 'pi_value']))}-hour mean-to-p95 "
                "service tail spread."
            ),
        },
        {"style": "Caption", "text": "Figure 11. Matched yearly KPI comparison: PI versus old network."},
        {"style": "Image", "text": "pi_vs_old_performance_overview.png"},
        {"style": "Caption", "text": "Figure 12. Efficiency frontier comparison: cost per unit versus realized demand."},
        {"style": "Image", "text": "pi_vs_old_efficiency_frontier.png"},
        {"style": "Caption", "text": "Figure 13. Shipping intensity and DC-load comparison."},
        {"style": "Image", "text": "pi_vs_old_shipping_and_dc_load.png"},
        {"style": "Caption", "text": "Figure 14. Tradeoff overview for the PI network."},
        {"style": "Image", "text": "pi_tradeoff_overview.png"},
        {"style": "Heading1", "text": "Task 5.15: Should BotWorld Relax the Rotterdam-Only Rule?"},
        {
            "style": "Normal",
            "text": (
                "Inference from the current model: probably yes, but conditionally. The current Task 5 "
                "implementation routes all transatlantic flows through Rotterdam, so it does not "
                "simulate a competing-port scenario directly. However, the mature network still shows "
                f"Rotterdam-to-Madrid drive time of about {fmt_num(float(port_dc_map['CAND_ES_madrid']['drive_time_hr']))}h "
                f"and Rotterdam-to-Rome drive time of about {fmt_num(float(port_dc_map['CAND_IT_rome']['drive_time_hr']))}h "
                "before downstream market distribution begins. That suggests southern and western "
                "markets are carrying a meaningful inland penalty under the Rotterdam-only rule."
            ),
        },
        {
            "style": "Normal",
            "text": (
                "A reasonable strategic recommendation is therefore to treat Rotterdam as the anchor "
                "port for the northwestern and central network, but to test optional Mediterranean "
                "or Iberian entry ports for the Rome, Madrid, and later southeastern demand basins. "
                "The benefit is plausible because the PI network is already designed to exploit open "
                "ports and flexible downstream hub routing. The main caution is that this claim is an "
                "inference from route geometry and current cost structure, not a separately simulated "
                "port-choice optimization in the saved repo outputs."
            ),
        },
    ]
    return paragraphs


def image_specs() -> dict[str, ImageSpec]:
    image_paths = [
        TASK5_DIR / "output" / "fig_5_1_topology_kpis.png",
        TASK5_DIR / "output" / "fig_5_1_network_map_2030.png",
        TASK5_DIR / "output" / "fig_5_3_otd_simulation.png",
        TASK5_DIR / "output" / "fig_5_4_joint_shipment.png",
        TASK5_DIR / "output" / "fig_5_5_demand_uplift.png",
        TASK5_DIR / "output" / "fig_5_6_autonomy.png",
        TASK5_DIR / "output" / "fig_5_9_cost_carbon.png",
        TASK5_DIR / "output" / "fig_5_9_carbon_by_lane.png",
        TASK5_DIR / "output" / "fig_5_10_dc_capacity.png",
        TASK5_DIR / "output" / "fig_5_12_profitability.png",
        ROOT / "comparison" / "figures" / "pi_vs_old_performance_overview.png",
        ROOT / "comparison" / "figures" / "pi_vs_old_efficiency_frontier.png",
        ROOT / "comparison" / "figures" / "pi_vs_old_shipping_and_dc_load.png",
        ROOT / "comparison" / "figures" / "pi_tradeoff_overview.png",
    ]
    specs: dict[str, ImageSpec] = {}
    max_width_emu = int(6.3 * 914400)

    for idx, path in enumerate(image_paths, start=1):
        if not path.exists():
            raise FileNotFoundError(path)
        with Image.open(path) as img:
            width_px, height_px = img.size
        width_emu = width_px * 9525
        height_emu = height_px * 9525
        scale = min(1.0, max_width_emu / width_emu)
        ext = path.suffix.lower().lstrip(".")
        if ext == "jpg":
            ext = "jpeg"
        if ext not in {"png", "jpeg"}:
            raise ValueError(f"Unsupported image format for {path}: {ext}")
        content_type = "image/png" if ext == "png" else "image/jpeg"
        specs[path.name] = ImageSpec(
            path=path,
            rid=f"rId{idx + 1}",
            name=path.name,
            rel_path=f"media/image{idx}.{ext}",
            content_type=content_type,
            cx=int(width_emu * scale),
            cy=int(height_emu * scale),
        )
    return specs


def para_xml(text: str, style: str) -> str:
    safe = escape(text)
    return (
        "<w:p>"
        f"<w:pPr><w:pStyle w:val=\"{style}\"/></w:pPr>"
        f"<w:r><w:t xml:space=\"preserve\">{safe}</w:t></w:r>"
        "</w:p>"
    )


def image_xml(spec: ImageSpec, docpr_id: int) -> str:
    return f"""
<w:p>
  <w:pPr><w:pStyle w:val="ImageBlock"/></w:pPr>
  <w:r>
    <w:drawing>
      <wp:inline distT="0" distB="0" distL="0" distR="0">
        <wp:extent cx="{spec.cx}" cy="{spec.cy}"/>
        <wp:docPr id="{docpr_id}" name="{escape(spec.name)}"/>
        <wp:cNvGraphicFramePr>
          <a:graphicFrameLocks noChangeAspect="1"/>
        </wp:cNvGraphicFramePr>
        <a:graphic>
          <a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture">
            <pic:pic>
              <pic:nvPicPr>
                <pic:cNvPr id="0" name="{escape(spec.name)}"/>
                <pic:cNvPicPr/>
              </pic:nvPicPr>
              <pic:blipFill>
                <a:blip r:embed="{spec.rid}"/>
                <a:stretch><a:fillRect/></a:stretch>
              </pic:blipFill>
              <pic:spPr>
                <a:xfrm>
                  <a:off x="0" y="0"/>
                  <a:ext cx="{spec.cx}" cy="{spec.cy}"/>
                </a:xfrm>
                <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
              </pic:spPr>
            </pic:pic>
          </a:graphicData>
        </a:graphic>
      </wp:inline>
    </w:drawing>
  </w:r>
</w:p>
""".strip()


def build_document_xml(blocks: list[dict[str, str]], specs: dict[str, ImageSpec]) -> str:
    body_parts: list[str] = []
    docpr_id = 1
    for block in blocks:
        if block["style"] == "Image":
            body_parts.append(image_xml(specs[block["text"]], docpr_id))
            docpr_id += 1
        else:
            body_parts.append(para_xml(block["text"], block["style"]))

    sect_pr = """
<w:sectPr>
  <w:pgSz w:w="12240" w:h="15840"/>
  <w:pgMar w:top="1080" w:right="1080" w:bottom="1080" w:left="1080" w:header="720" w:footer="720" w:gutter="0"/>
</w:sectPr>
""".strip()

    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:wpc="http://schemas.microsoft.com/office/word/2010/wordprocessingCanvas"
 xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"
 xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"
 xmlns:v="urn:schemas-microsoft-com:vml"
 xmlns:wp14="http://schemas.microsoft.com/office/word/2010/wordprocessingDrawing"
 xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
 xmlns:w10="urn:schemas-microsoft-com:office:word"
 xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml"
 xmlns:wpg="http://schemas.microsoft.com/office/word/2010/wordprocessingGroup"
 xmlns:wpi="http://schemas.microsoft.com/office/word/2010/wordprocessingInk"
 xmlns:wne="http://schemas.microsoft.com/office/word/2006/wordml"
 xmlns:wps="http://schemas.microsoft.com/office/word/2010/wordprocessingShape"
 xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"
 xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"
 mc:Ignorable="w14 wp14">
  <w:body>
    {''.join(body_parts)}
    {sect_pr}
  </w:body>
</w:document>
"""


def styles_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault>
      <w:rPr>
        <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
        <w:sz w:val="22"/>
      </w:rPr>
    </w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:default="1" w:styleId="Normal">
    <w:name w:val="Normal"/>
    <w:qFormat/>
    <w:pPr><w:spacing w:after="140" w:line="300" w:lineRule="auto"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:after="220"/><w:jc w:val="center"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="30"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading1">
    <w:name w:val="heading 1"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="180" w:after="100"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="26"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Caption">
    <w:name w:val="Caption"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:spacing w:before="40" w:after="60"/></w:pPr>
    <w:rPr><w:i/><w:sz w:val="18"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="ImageBlock">
    <w:name w:val="ImageBlock"/>
    <w:basedOn w:val="Normal"/>
    <w:pPr><w:jc w:val="center"/><w:spacing w:after="160"/></w:pPr>
  </w:style>
</w:styles>
"""


def content_types_xml(specs: dict[str, ImageSpec]) -> str:
    image_overrides = []
    default_exts = {"rels": "application/vnd.openxmlformats-package.relationships+xml", "xml": "application/xml"}
    for spec in specs.values():
        ext = spec.rel_path.rsplit(".", 1)[1]
        if ext not in default_exts:
            default_exts[ext] = spec.content_type

    defaults = "".join(
        f'<Default Extension="{ext}" ContentType="{ctype}"/>'
        for ext, ctype in sorted(default_exts.items())
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  {defaults}
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
  <Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>
</Types>
"""


def root_rels_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>
"""


def document_rels_xml(specs: dict[str, ImageSpec]) -> str:
    image_rels = "".join(
        f'<Relationship Id="{spec.rid}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="{spec.rel_path}"/>'
        for spec in specs.values()
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
  {image_rels}
</Relationships>
"""


def core_xml() -> str:
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
 xmlns:dc="http://purl.org/dc/elements/1.1/"
 xmlns:dcterms="http://purl.org/dc/terms/"
 xmlns:dcmitype="http://purl.org/dc/dcmitype/"
 xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Task 5 Subreport</dc:title>
  <dc:creator>Codex</dc:creator>
  <cp:lastModifiedBy>Codex</cp:lastModifiedBy>
  <dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created>
  <dcterms:modified xsi:type="dcterms:W3CDTF">{now}</dcterms:modified>
</cp:coreProperties>
"""


def app_xml() -> str:
    return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties"
 xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Microsoft Office Word</Application>
</Properties>
"""


def write_docx(output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    blocks = build_narrative()
    specs = image_specs()
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types_xml(specs))
        zf.writestr("_rels/.rels", root_rels_xml())
        zf.writestr("docProps/core.xml", core_xml())
        zf.writestr("docProps/app.xml", app_xml())
        zf.writestr("word/document.xml", build_document_xml(blocks, specs))
        zf.writestr("word/styles.xml", styles_xml())
        zf.writestr("word/_rels/document.xml.rels", document_rels_xml(specs))
        for spec in specs.values():
            zf.write(spec.path, f"word/{spec.rel_path}")


if __name__ == "__main__":
    write_docx(OUTPUT_DOCX)
    print(f"Wrote {OUTPUT_DOCX}")
