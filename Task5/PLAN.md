# Task5 Modification Plan

Last updated: 2026-03-12
Status: 4th Edition - PI-only correction pass completed for demand, routing, flow, cost, and profitability.

---

## 1) Goal

Repair Task5 in-place.

Primary objective:
- preserve the current framework (`src/` modules, notebook runner, outputs)
- replace broken internals with logic that matches the Task2 / Task4 simulator contract and the Task 5 case requirements

This is not a greenfield plan. It is a correction plan.

### Progress Summary (3rd Edition)

**Completed Workstreams:**
- ✅ Workstream A: Demand Generator (DG-1, DG-2, SIM-1) - 2026-03-11 AM
- ✅ Workstream B (Partial): Network Semantics (HUB-1, NET-2, NET-3, NET-4) - 2026-03-11 PM

**Current Scope State:**
- ✅ NET-1 fixed with physical-leg route building and route-backed OTD evaluation
- ✅ FLOW-1 fixed with `dc_daily_sim`-driven stress and interval logic
- ✅ COST-1 fixed with routed lane flows instead of equal lane splits
- ✅ REP-1 closed by scope: PI-only reporting, no non-PI comparison output
- ✅ FIN-1 closed by scope: PI-only profitability, no non-PI baseline calculation

---

## 2) Required Reading Before Editing

Read in this order:
1. `Task5/CONTEXT.md`
2. `Task5/ACTIVE_FIXES.md`
3. extracted Task2 simulator logic from `Task2/Simulator.ipynb`
4. extracted Task4 DC-demand simulator logic from `Task4/DC_Demand_Simulator.ipynb`
5. only then edit Task5 source files

---

## 3) Workstream A: Demand Generator First

### 3.1 Target State

`Task5/src/demand_generator.py` must become a Task4-style PI simulator adapter.

It must:
- retain Task2 / Task4 stochastic mechanics
- produce DC-day-model demand at simulation grain
- apply PI demand uplift through the same demand path, not by replacing the path
- become network-aware at the service layer so yearly hub design can change effective assignment and route time

### 3.2 Required Mechanics to Port / Reuse

The corrected demand module must include or reuse equivalents of:
- `build_year_calendar(...)`
- `adoption_rate_by_scenario(...)`
- `simulate_period_shares(...)`
- triangular model-share logic
- OTD conversion logic
- cyber-week split logic
- DC-routing logic at Task4 grain

Keep this integrity rule:
- preserve the prior-task OTD conversion contract and data schema
- network changes should change route-time inputs and service-path selection, not replace the conversion logic with ad hoc probabilities
- default to reusing the same Task2 / Task4 OTD conversion table or function interface unless the case PDF explicitly requires a PI-only overlay

### 3.3 Allowed PI Changes

PI-specific changes belong here:
- PI OTD promise / purchase-probability mapping
- PI scenario uplift assumptions
- PI-specific routing adjustments if they do not break output grain
- hub-mediated consolidation / relay state if it is represented as a route-service overlay

Current implementation rule:
- use one PI OTD concept only: end-to-end service OTD
- `OTD = route elapsed + relay/consolidation dwell + PI last mile`
- feed that OTD directly into purchase-probability conversion
- do not add a second attainment / promise-comparison layer in evaluator or notebook reporting

### 3.4 Explicit Do-Not-Do Rules

Do not:
- replace the simulator with annual node-level probability sampling
- compute downstream DC annual demand directly from `pi_reachable_units`
- use summary distributions as a substitute for daily simulated demand
- treat `assignment_with_otd_prob_reachable.csv` as final PI demand output
- assume the old direct `node -> assigned_cand` relationship remains valid after the PI network is activated
- copy Task4's segment-to-DC weighting shortcut unchanged if network routing now creates node-specific OTD differences

### 3.5 Required Outputs From Demand Generator

Minimum useful outputs after correction:
- `pi_assignment`: PI-adjusted assignment / uplift table if still needed
- `dc_daily_sim`: `sim, date, year, euro_dc_id, model, realized_units`
- `annual_by_dc`: derived by aggregating `dc_daily_sim`
- `uplift_summary`: derived from simulator-backed totals, not assignment-only totals

Recommended additional artifact:
- `service_matrix_{year}` or equivalent in-memory table with columns like:
  `year, node_id, assigned_dc_id, path_key, service_mode, n_relay_hubs, n_consol_hubs, travel_elapsed_hr, otd_hours, otd_bucket, purchase_prob`

Purpose:
- make network changes local to the service layer
- let the demand kernel stay stable while the network script changes

### 3.6 Recommended Correction Pattern

Use this two-layer structure:

1. Demand kernel layer:
   - keep Task2 / Task4 stochastic generation intact
   - generate pre-OTD demand at node-compatible geography

2. Service overlay layer:
   - consume active hubs / lanes / route logic from the network modules
   - choose the effective service path for each node-year
   - mark whether the path uses direct shipment, relay-only hubs, or consolidation hubs
   - compute route-based elapsed time
   - apply OTD conversion using the same logic family / schema as prior tasks
   - aggregate realized demand to DC output

This is the preferred way to support hub-mediated demand effects without rewriting the whole simulator again.

---

## 4) Workstream B: Network Semantics

### 4.1 Keep the Node / Module Framework

Keep:
- `preprocess.py` for node preparation
- `hub_network.py` for relay / lane generation
- `pipeline.py` as year orchestrator

### 4.2 Required Corrections

`hub_network.py` must be corrected so that:
- relay paths are explicit multi-leg paths, not pseudo-direct edges
- dwell is based on node type / lane semantics, not string matching on `dest_id`
- detour uses routed path distance divided by direct OD distance
- merged relay hubs remain usable as dual-role nodes
- hub corridor edges are not built as an uncontrolled dense mesh
- consolidation-capable hubs are represented explicitly instead of being treated as generic relay-only nodes

### 4.3 Practical Representation Rule

Acceptable pattern:
- keep lane tables as physical legs
- compute route/path tables separately if needed
- evaluate coverage, elapsed time, and OTD on route paths, not just on single physical lanes
- store service-state metadata on routes, including whether each intermediate stop is relay-only or consolidation-bearing

### 4.4 Consolidation Rule

Current Task5 does not model consolidation in a usable way.

Correct target:
- relay-only hub stop: adds relay dwell / relay handling semantics
- consolidation hub stop: adds consolidation dwell / consolidation handling semantics
- final service path to a demand node may include both

Minimum modeling requirement:
- route builder must count relay and consolidation stops separately
- demand / OTD logic must consume those route attributes
- cost logic must be able to price relay and consolidation visits separately

---

## 5) Workstream C: Flow / Capacity Logic

### 5.1 Target State

`flow_model.py` must consume simulator-derived demand, not synthetic annual approximations.

### 5.2 Required Corrections

- DC-DC stress logic should operate on daily DC demand arrays derived from the corrected demand simulator
- cyber-week logic should use simulator dates or simulator-derived daily demand concentration
- demand intervals should come from simulation output or daily simulation aggregates
- annual / peak uncertainty shortcuts are acceptable only if clearly secondary and explicitly labeled as approximations
- if consolidation changes which DC effectively supplies a demand node, capacity logic must use the post-service-overlay DC demand, not the old baseline assignment

### 5.3 Constraint

Do not let `flow_model.py` become another independent demand generator.

---

## 6) Workstream D: Cost, Carbon, and Profitability

### 6.1 Target State

`evaluator.py` and `reporting.py` must compute costs and comparisons from routed flows and actual baseline artifacts.

### 6.2 Required Corrections

- transport cost and carbon must use routed or allocated path flows, not equal splits across all outbound lanes
- non-PI elapsed-time comparison must be produced from real baseline fields and actual PI route outputs
- profitability must avoid arbitrary non-PI cost multipliers when baseline artifacts exist
- activation logs must use actually produced time / coverage deltas
- relay and consolidation hub visits must be costed separately if both are represented in the route service layer

### 6.3 Baseline Comparison Rule

When Task2 / Task4 baseline data exists, use it.
If a metric is estimated rather than measured, label it clearly as approximate.

---

## 7) Output Contract for the Corrected Task5

Expected maintained outputs:
- `output/network_roadmap_{year}.csv`
- `output/activation_decisions_log.csv`
- `output/network_kpis_by_year.csv`
- `output/network_vs_nonpi_comparison.csv`
- `output/subtask_5_*.csv`
- yearly supporting outputs such as `dc_capacity_{year}.csv`, `lane_cost_carbon_{year}.csv`, `otd_profile_{year}.csv`

Expected supporting data artifacts:
- `data/nodes_master.csv`
- `data/relay_hubs.csv` if relay generation remains materialized

Target logging artifact:
- `output/data_issue_log.csv`

---

## 8) Module-by-Module Intent

### `config.py`
Keep as constants only. Do not move business logic here.

### `data_loader.py`
Use for stable reads of Task2 / Task4 artifacts and Excel sheets.

### `preprocess.py`
Keep focused on node tables and issue logging.

### `demand_generator.py`
This is the first module to fix and the highest priority dependency for the rest of Task5.

### `hub_network.py`
Fix physical-leg generation and path semantics after demand is corrected.

### `flow_model.py`
Reconnect to real simulated demand.

### `evaluator.py`
Convert from shortcut metrics to route-backed / baseline-backed metrics.

### `reporting.py`
Only report what upstream modules actually produce; do not invent missing comparison fields.

### `pipeline.py`
Keep orchestration responsibility; avoid embedding new business logic here.

---

## 9) Recommended Modification Sequence

### ✅ Completed Steps
1. ✅ Correct `demand_generator.py` (DG-1, DG-2)
2. ✅ Add yearly service overlay (SIM-1)
3. ✅ Change `pipeline.py` to aggregate from simulator output and build routes (HUB-1)
4. ✅ Correct dwell / detour / consolidation behavior in `hub_network.py` (NET-2, NET-3, NET-4)

### ⏳ Remaining Steps
5. ⏳ Correct OTD evaluation in `pipeline.py` and `evaluator.py` to use routes instead of direct lanes (NET-1)
6. ⏳ Correct `flow_model.py` to use daily simulated demand from `dc_daily_sim` (FLOW-1)
7. ⏳ Correct `evaluator.py` cost logic to use routed demand flows (COST-1)
8. ⏳ Correct `evaluator.py` OTD / comparison / profitability logic (REP-1, FIN-1)
9. ⏳ Correct `reporting.py` to match real produced fields
10. ⏳ Regenerate outputs after all fixes are complete

---

## 10) Quick Acceptance Checks

### ✅ Passing Checks (3rd Edition)
1. ✅ Demand generator output grain is `sim, date, year, euro_dc_id, model, realized_units`
2. ✅ `annual_by_dc` is aggregated from simulator output
3. ✅ The service landscape can change when the active PI network changes
4. ✅ Routes are built from lanes with explicit service modes
5. ✅ Consolidation state is explicit (n_relay_stops, n_consol_stops in routes)
6. ✅ Detour ratio genuinely varies (computed as `actual_route_km / direct_km`)
7. ✅ DC dwell / relay dwell / consolidation dwell assigned by node type, not string matching

### ❌ Failing Checks (To Fix)
8. ❌ OTD evaluation still uses direct lanes only (NET-1)
9. ❌ Non-PI comparison table missing some PI elapsed metrics (REP-1)
10. ❌ Cost and carbon still use blanket equal lane splits (COST-1)
11. ❌ Capacity logic still uses synthetic distributions, not `dc_daily_sim` (FLOW-1)

---

## 11) Companion Reference

Use `Task5/ACTIVE_FIXES.md` as the fast index of what is currently wrong, where it lives, and what to inspect first.
