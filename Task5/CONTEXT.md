# CONTEXT.md

Last updated: 2026-03-11 (revised after full planning conversation)

## 1) Purpose

This file is the working context for Task 5 planning, especially Task 5.1 (Hyperconnected Network Design), built from:

- `.claude/CLAUDE.md`
- `.claude/CLAUDE_Jupyter.md`
- `.claude/CLAUDE_PDF.md`
- `ISYE 6339 - BotWorld Export-to-Europe Supply Chain Casework 1-1 2026.pdf`
- Existing project artifacts in `Task2/`, `Task3/`, `Task4/`

## 2) Source-of-Truth Rules for This Repo

- Use `.claude/*.md` as working protocol.
- Do not read raw `.ipynb`/`.pdf` directly; use extraction methods.
- Prefer reusing existing simulator modules and data contracts before adding new logic.
- Treat this sequence as canonical data lineage for non-PI baseline:
  - `Task2` demand + OTD simulation
  - `Task3` production/autonomy estimation
  - `Task4` DC-level realized demand

## 3) Key Case Requirements Relevant to Task 5.1

From the case PDF (Task 5: Hyperconnected Transportation, pp. 11-13):

- Design an open hub and roadway network for:
  - Rotterdam port -> Euro DCs
  - Euro DC <-> Euro DC
  - Euro DCs -> hubs near metros and country boundaries
- Network goals:
  - Relay transportation
  - Daily shipments without full truckload constraints
  - Consolidation with other shippers
  - Fast O-D travel with limited detour
- Provide yearly roadmap (2027-2034), not full fine-grained continental network.
- Explain design rationale and show if goals are met.

Related PI assumptions to include in modeling:

- PI packaging and handling format (p-packs, p-boxes, p-pods).
- Hub dwell:
  - 1 hour for relay-only
  - 2 hours when consolidation is needed
- Improved downstream OTD assumptions in PI scenario.
- PI cost adders in Appendix B:
  - p-pack usage cost replaces non-PI EUR15 packaging
  - transload handling per visited center
  - hub relay/consolidation cost per unit per hub visit

## 4) Current Asset Map (What Exists)

## 4.1 Task2 (baseline demand/OTD simulation)

- Key notebook: `Task2/Simulator.ipynb`
- Core output directory: `Task3/sim_batches/`
- Important static inputs:
  - `Task2/dc_open_plan.csv`
  - `Task2/assignment_by_year_active.csv`
  - `Task2/assignment_with_otd_prob_reachable.csv`
  - `Task2/time_matrix.csv`
  - `Task2/weights_by_year.csv`

Main logic modules in `Task2/Simulator.ipynb`:

- Calendar builder with cyber week tagging
- Adoption-rate-by-scenario functions (`pes`, `mp`, `opt`)
- OTD conversion function
- Stochastic period-share and model-share generators
- Batched Monte Carlo simulator (`run_otd_simulator`)
- Batch flush and aggregation to Task3 artifacts

## 4.2 Task3 (production/autonomy estimation and validation)

- Main notebooks:
  - `Task3/Production_est.ipynb` (Task 3.1)
  - `Task3/Production_feasibility_simulator.ipynb` (Task 3.2 check)
- Uses `Task3/sim_batches/batch_*.csv.gz` from Task2.
- Produces:
  - `Task3/cluster_production_rates.csv`
  - `Task3/prior_start_days_corrected.csv`
  - `Task3/annual_summary.csv.gz`
  - `Task3/segment_summary.csv.gz`
  - `Task3/simulated_demand.csv.gz`

## 4.3 Task4 (DC-level realized demand)

- Key notebook: `Task4/DC_Demand_Simulator.ipynb`
- Current production outputs (actual):
  - `Task4/dc_output/batch_*.parquet`
  - `Task4/dc_output/dc_daily_demand.parquet`

Task4 simulator differences vs Task2:

- Reuses core stochastic demand logic from Task2.
- Adds geography-preserving demand pathing and DC routing.
- Uses pre-aggregated segment-to-DC weights to avoid city-level memory blow-up.
- Writes final schema directly at DC-day-model granularity.

## 5) Key Data Contracts (Observed in Files)

Only major datasets needed for Task5.1 planning are listed here.

| Dataset | Producer | Consumer | Grain | Key Columns |
|---|---|---|---|---|
| `Task2/dc_open_plan.csv` | Task2 network decision | Task4/Task5 planning | DC | `cand_id`, `country`, `city`, `first_open_year`, lat/lng |
| `Task2/assignment_with_otd_prob_reachable.csv` | Task2 OTD/reachability | Task2/Task4/Task5 | node-year assignment | `year`, `node_id`, `assigned_cand`, `node_type`, `otd_days_promise`, `purchase_prob`, `reachable_units` |
| `Task3/sim_batches/batch_00.csv.gz` (+ siblings) | Task2 simulator | Task3 | sim-date-model | `sim`, `date`, `model`, `sales_units` |
| `Task3/annual_summary.csv.gz` | Task2 post-agg | Task3/Task5 costing | sim-year | `demand_units`, `sales_units`, `revenue`, `lost_units`, `conversion_pct` |
| `Task3/segment_summary.csv.gz` | Task2 post-agg | Task3/Task5 calibration | sim-year-segment | `segment`, `otd_days`, `conversion_pct` |
| `Task3/simulated_demand.csv.gz` | Task2 post-agg | Task3 | date-model stats | `mean`, `std`, `p05`, `p50`, `p95` |
| `Task4/dc_output/dc_daily_demand.parquet` | Task4 simulator | Task5/Task6 | sim-date-dc-model | `sim`, `date`, `year`, `euro_dc_id`, `model`, `realized_units` |

Observed scale snapshot:

- `Task3/sim_batches/batch_00.csv.gz`: 292,200 rows
- `Task3/annual_summary.csv.gz`: 800 rows
- `Task3/segment_summary.csv.gz`: 1,600 rows
- `Task3/simulated_demand.csv.gz`: 58,440 rows
- `Task4/dc_output/dc_daily_demand.parquet`: 18,992,000 rows

## 6) Data Flow (Current Non-PI Baseline)

```
Task2 inputs (DC plan, assignment, OTD, time matrix, populations/models)
  -> Task2 Simulator.ipynb
  -> Task3/sim_batches/batch_*.csv.gz  (sim-date-model sales)
  -> Task3/annual_summary.csv.gz
  -> Task3/segment_summary.csv.gz
  -> Task3/simulated_demand.csv.gz

Task3 notebooks consume sim_batches
  -> production rates + prior-start estimates + feasibility checks

Task4 notebook reuses Task2 logic + assignment geography
  -> Task4/dc_output/dc_daily_demand.parquet (sim-date-DC-model realized demand)
```

## 7) What Is Transferable to Task 5

Directly transferable modules:

- Demand generation hierarchy and stochastic controls (Task2/Task4)
- Adoption scenarios and calendar/cyber-week logic
- Existing DC landscape and yearly open schedule from Task2
- OTD conversion framework
- Output grain conventions (sim/date/year/model, then DC add-on)

Needs adaptation or extension for PI Task 5:

- Containerization logic must move from non-PI pallet/box framing to PI p-pack/p-box/p-pod framing.
- Transport network model must become explicit hub-and-lane graph with relay/consolidation dwell.
- Costing must switch to PI Appendix-B rules.
- Inter-DC transfer capability must be enabled.

## 8) Conflict and Mismatch Policy

- If workbook assumptions, old notebook constants, or markdown docs conflict with case requirements, the PDF is authoritative.
- Keep a `data_issue_log.csv` in Task5 outputs whenever a mismatch is found.
- For each mismatch, record:
  - source artifact and field
  - PDF reference section/page
  - correction applied
  - impact on outputs

## 9) Task 5 Implementation Plan Summary

> **Full implementation detail in `Task5/PLAN.md`.** This section is a compact reference only.

## 9.1 Node Taxonomy

| node_type | Count | Source | Role |
|---|---|---|---|
| `PORT` | 1 | Rotterdam split from metro sheet | Ocean freight entry; no demand |
| `DC` | 4 | `dc_open_plan.csv` | Storage + consolidation; also local peri-urban hub |
| `PERI_URBAN_HUB` | 272 | `Metro cities_location` sheet | PI delivery handoff; 4/2/1hr OTD by pop bracket; dual relay role if on corridor |
| `BORDER_RELAY_HUB` | ~25–30 | Derived: midpoint of adjacent-country centroids | Transit relay at borders; non-metro service handoff |
| `DEMAND_NONMETRO` | 28 | `non_metro_hub` sheet | Demand centroid only; NOT a transit hub |

- All hubs assumed already existing in PI world (PDF p.12).
- DC cities deduplicated from metro list (type=DC only).
- Rotterdam: `PORT_NL_rotterdam` + retained in `PERI_URBAN_HUB` (pop 1.03M, 1M+ bracket).
- Known data fixes: alias `ing`→`lng`, forward-fill `Countries`, log all in `data_issue_log.csv`.

## 9.2 PI Demand Generation

- Reuse Task2 stochastic pipeline exactly.
- PI OTD rates collapse hours vs days → purchase probability near 100% all segments.
- Sub-DC city split: `pop_city / sum(pop_country_metros)` weight (same as Task2 logic).
- Non-metro residual → `DEMAND_NONMETRO` node for country.
- DC assignment from `assignment_with_otd_prob_reachable.csv` (unchanged).
- Output grain: `sim × date × year × dc_id × model → realized_units`.

## 9.3 Hub Activation and Lane Generation

**Hub activation:** Activate all peri-urban hubs in countries open per BotWorld roadmap. Border relay hubs derived algorithmically at country-pair midpoints; merge if within 80km of existing peri-urban hub.

**Lane time formula:** `drive_time_hr = haversine_km × 1.2 / 100`; `elapsed_hr = drive_time + hub_dwell`

**Lane types:**
- `PORT→DC`: always; truck L
- `DC↔DC`: all 6 pairs; relay_flag if >11hr drive; truck L
- `DC→PERI_URBAN_HUB`: direct if ≤4hr; via border relay if 4–10hr; via DC-DC if >10hr; truck M/L
- `DC→BORDER_RELAY`: within 1000km; detour_ratio ≤ 1.35; truck L
- `BORDER_RELAY→PERI_URBAN`: within 300km; truck M
- `HUB↔HUB corridor`: adjacent hubs ≤300km; detour_ratio ≤ 1.35; truck M

## 9.4 NumPy-First Simulation

- pandas: I/O, filtering, joins.
- numpy: routing-time and KPI computation (integer indices, vectorized masking, `np.add.at`).
- Pattern: pandas-in → numpy-compute → pandas-out.

## 9.5 Year-by-Year Roadmap

| Year | DCs | Peri-urban hubs | Border relay hubs | DC-DC lanes |
| --- | --- | --- | --- | --- |
| 2027 | Koeln | ~30 | ~5 | none |
| 2028 | +Lodz | +60 | +10 | Koeln↔Lodz |
| 2029 | +Madrid | +80 | +10 | +Madrid↔Koeln, Madrid↔Lodz |
| 2030 | +Rome | +100 | +8 | full 6-lane mesh |
| 2031–34 | all 4 | all 272 | ~28–30 | full mesh |

Activation log: `(node_id, activation_year, coverage_gain_pct, drive_time_reduction_hr, detour_ratio)`

## 9.6 DC-DC Flow and Cyber Week

**Normal periods:** rolling-7-day stress trigger (demand > 1.3× median) → transfer ≤10% of excess to nearest DC with slack. Cap: 10% of any DC's annual throughput.

**Cyber week (override):** All DCs stressed simultaneously (15% annual demand / 5 days). DC-DC transfers = 0. Each DC handles own demand. Demand > capacity → lost sales.

**DC capacity sizing:** `peak_daily_pallets = annual_demand × 0.03 / UNITS_PER_PALLET`; throughput cost = `peak_daily_pallets × 2 × €25/year`.

## 9.7 KPI Definitions

| KPI | Target |
| --- | --- |
| Coverage % of OD pairs with feasible path | ≥ 95% per year |
| Elapsed time vs non-PI baseline | Reduction demonstrated |
| Detour ratio (routed/direct) | ≤ 1.35 |
| Relay readiness (% lanes with relay flag) | ≥ 80% |
| DC-DC relay path coverage | 100% by 2028 |

## 9.8 Module Structure

```text
Task5/src/
  config.py           all Appendix A/B constants + route parameters
  data_loader.py      Task2-Task4 artifacts + Excel sheets + data fixes
  preprocess.py       nodes_master build; Rotterdam split; data_issue_log.csv
  demand_generator.py Task2 stochastic pipeline; PI OTD conversion
  hub_network.py      hub activation; border relay derivation; all lane types
  flow_model.py       DC-DC stress transfer; cyber week logic; DC capacity sizing
  evaluator.py        KPI computation vs non-PI baseline
  reporting.py        roadmap tables; activation log; map exports; profitability
  pipeline.py         2027–2034 year loop orchestrator
Task5/notebooks/
  task5_runner.ipynb  calls pipeline.py; displays outputs
```

## 9.9 Validation Checklist

1. Fixed seed → deterministic roadmap outputs.
2. Demand conservation across aggregation levels.
3. No orphan nodes (every demand node reachable via at least one path).
4. Every result traceable to a PDF requirement (p.11-13).
5. numpy kernel path benchmarked vs pandas-only.

## 10) Deliverables for Task 5.1

Required output bundle:

1. Network design maps (2027-2034 roadmap, phased).
2. Hub and lane master tables with activation years.
3. KPI evidence table proving coverage, speed, detour, and relay/consolidation goals.
4. Comparison table against non-PI baseline path times.
5. Modular source code in `Task5/src/`.
6. Runner notebook that calls module pipeline end-to-end.
