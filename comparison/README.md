# Task4 vs Task5 Comparison

This folder compares the old network (Task4 baseline) with the PI network (Task5 output) using local repo artifacts only.

## Sources

- Task4 design: `Task4/4.5/*.csv`
- Task4 old-network performance: printed outputs saved inside `Task4/4.6 & 4.7.ipynb`
- Task4 demand checks: `report_bundle/data/task4_annual_demand_by_year.csv`, `report_bundle/data/task4_dc_demand_by_year.csv`
- Task5 PI performance: `Task5/output/*.csv`

## Alignment Rules

- Old-network realized demand, revenue, fill rate, and full baseline cost blocks come from Task4 notebook output.
- PI realized demand comes from `subtask_5_5_pi_demand_summary.csv`.
- PI per-unit transport and CO2 come from `network_kpis_by_year.csv`, not from `subtask_5_9_cost_carbon_summary.csv`.
  Reason: the Task5 5.9 summary file still uses lane-throughput as the denominator for per-unit metrics.
- The most defensible cross-network cost comparison is `network_scope_cost_eur`:
  - Task4 old network: transport + customer delivery + DC operating + fleet fixed
  - Task5 PI network: `total_pi_cost_eur`
- Task4 full operating profit includes production, packaging, and inventory.
  Task5 `pi_margin_eur` is a network-scope measure, so those two should not be treated as directly equivalent.

## Generated Files

- `data/task4_old_network_yearly.csv`
- `data/task5_pi_network_yearly.csv`
- `data/task4_vs_task5_yearly_comparison.csv`
- `data/design_comparison_yearly.csv`
- `data/dc_load_comparison_by_year.csv`
- `data/dc_load_comparison_2030.csv`
- `data/horizon_comparison.csv`
- `data/horizon_efficiency_summary.csv`
- `data/pi_dominance_scorecard.csv`
- `data/pi_tradeoff_metrics.csv`
- `figures/pi_vs_old_performance_overview.png`
- `figures/pi_vs_old_efficiency_frontier.png`
- `figures/pi_vs_old_shipping_and_dc_load.png`
- `figures/pi_vs_old_horizon_advantage.png`
- `figures/pi_tradeoff_overview.png`

## Visual Framing

- The plots are limited to matched metrics where the PI network outperforms the old network on a consistent basis and denominator.
- Higher-is-better plots: realized units, revenue.
- Lower-is-better plots: transport cost per unit, network-scope cost per unit, shipping units per 1000 sold units.
- `pi_dominance_scorecard.csv` confirms the PI network wins on each selected metric in every year from 2027 to 2034.

## PI Trade-Offs

- `pi_tradeoff_metrics.csv` tracks areas where the PI design is weaker or harder to run, even though its matched economic KPIs are better.
- 2030 coverage shortfall: 2.60 percentage points below full coverage.
- 2030 relay network not ready: 30.72%.
- 2030 service tail spread: 16.74 hours between mean and p95 service time.
- 2030 operating touchpoints vs old network: 88.0x.
- These are plausible side effects of the hyperconnected design: broader reach, more relay dependence, more multi-hop flows, and much higher orchestration complexity.

## 2030 Snapshot

- Old network: 73403 realized units, 354.05 EUR transport per unit, 1084.48 EUR network-scope cost per unit, 8515 ocean containers.
- PI network: 218466 realized units, 69.26 EUR transport per unit, 110.29 EUR network-scope cost per unit, 1194 TEUs.
- 2030 design overlay: 4 Euro DCs in both cases, plus 269 peri-urban hubs and 167 relay hubs in PI.
- 2030 demand uplift: 197.6% vs old network.
- 2030 network-scope cost per unit change: -89.8% vs old network.

## Validation Notes

- Task4 notebook totals were reconciled back to the report-bundle yearly demand file.
- Task4 full total cost was recomputed from its component blocks and matched the notebook profitability table.
- Task5 demand and profitability outputs differ by at most 2 units per year because of rounding; the comparison keeps exact demand from the Task5 demand summary.
- The case PDF is machine-readable in this environment and was used to confirm that Task 5 is the hyperconnected transportation workstream.
- The comparison avoids apples-to-oranges claims such as Task4 full operating profit versus Task5 network-scope margin.
- The trade-off metrics are intentionally labeled as trade-offs where no direct old-network KPI exists in the saved repo outputs.

## Horizon Check

- Task4 notebook horizon revenue: 258685366 EUR
- Task4 parsed yearly revenue total: 258685360 EUR
- PI cumulative realized-units advantage: 201.5%
- PI cumulative network-scope cost-per-unit reduction: 88.2%
