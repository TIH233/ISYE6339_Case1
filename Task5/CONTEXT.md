# CONTEXT.md

Last updated: 2026-03-12
Status: 4th Edition - PI-only data flow repaired end-to-end. Demand, routing, flow, cost, and profitability now run without non-PI comparison outputs.

## 1) Purpose

This file is the working context for Task5 maintenance and correction.

Scope:
- keep the current `Task5/src/` module framework
- treat the current Task5 implementation as partially incorrect
- use `Task5/ACTIVE_FIXES.md` as the indexed list of confirmed open issues and fix specifications
- modify Task5 by restoring the Task2/Task4 simulator contract first, then fixing downstream network / flow / reporting logic
- keep the current run PI-only; do not produce non-PI comparison tables unless the scope changes again

## 2) Source-of-Truth Order

Use this order whenever artifacts disagree:

1. Case PDF and Appendix B assumptions
2. Extracted logic from `Task2/Simulator.ipynb` and `Task4/DC_Demand_Simulator.ipynb`
3. Stable data contracts from Task2 / Task4 produced artifacts
4. This corrected `Task5/CONTEXT.md` and `Task5/PLAN.md`
5. Current Task5 code only where it agrees with items 1-4

Repo protocol:
- Use `.claude/*.md` as workflow protocol.
- Do not read raw `.ipynb` / `.pdf` directly when avoidable; use extraction methods.
- Do not treat current Task5 outputs as authoritative if they were produced by broken logic.
- Do not simplify daily / sim-level demand into annual node-level probability math.

## 3) Canonical Non-PI Baseline Lineage

The non-PI baseline lineage is:

- `Task2`: demand + OTD simulator at aggregate demand level
- `Task3`: production / autonomy analysis consuming Task2 simulation outputs
- `Task4`: DC-level realized demand simulator reusing Task2 stochastic logic and adding DC routing

Key implication for Task5:
- the demand-side source contract to preserve is the Task4-style output grain
- Task5 can adapt the simulator for PI assumptions, but it must not replace the simulator with a new annual shortcut
- unlike Task4, Task5 cannot assume the old fixed direct `node -> assigned_cand` landscape is still valid once hub-mediated routing and consolidation are introduced

## 4) Canonical Demand Contract for Task5

`Task5/src/demand_generator.py` is supposed to be a Task4-style simulator adaptation.

Required retained mechanics from Task2 / Task4:
- calendar with cyber week tagging
- adoption-rate-by-scenario functions
- stochastic period-share generation
- stochastic model-share generation
- OTD conversion logic
- daily allocation across the year
- output at DC-day-model granularity

Additional Task5 requirement:
- the demand side must become network-aware at the service layer
- yearly hub / lane design can change the effective `DC -> demand node` route, elapsed time, and therefore OTD-driven demand conversion
- this means Task5 cannot rely on the old Task2 direct assignment table as the final PI service landscape

Allowed PI modifications:
- updated PI OTD / purchase-probability mapping
- PI-specific downstream routing assumptions if needed
- PI-specific demand uplift logic, but only inside the same simulator contract
- hub-mediated service and consolidation effects, but implemented as a network/service overlay rather than as a replacement demand shortcut

Current OTD interpretation rule:
- use a single end-to-end PI OTD definition in Task5 demand and reporting
- `OTD = DC route elapsed + relay/consolidation dwell + PI last mile`
- do not maintain a separate "attainment vs promised OTD" reporting layer
- for PI last mile, use case parameters rather than Task2 baseline last-mile fields:
  - metro: `1M+ -> 4h`, `250K-1M -> 2h`, `<250K -> 1h`
  - non-metro: `<=250 km -> 8h`, `<=500 km -> 16h`, `>500 km -> 32h`

Required output grain:
- `sim, date, year, euro_dc_id, model, realized_units`

Required downstream rule:
- all annual demand totals used by `flow_model.py`, `evaluator.py`, and `reporting.py` must be aggregated from simulated DC output, not from `assignment_with_otd_prob_reachable.csv` expected values alone

Required network/service rule:
- build a yearly network-aware service view before final OTD conversion and DC aggregation
- service logic must allow `DC -> hub -> hub -> demand area` style routes where applicable
- consolidation state must be explicit because it changes elapsed time and potentially the chosen service path
- preserve prior-task data integrity by keeping the old OTD conversion contract / schema intact; network changes should alter route-time inputs, not invent an unrelated demand table
- default to the same Task2 / Task4 OTD conversion table or function interface unless the case PDF explicitly forces a separate PI overlay

Important correction:
- current demand and downstream modules were repaired to follow this contract in the PI-only scope

## 5) Important Existing Artifacts

### 5.1 Task2

Inputs / artifacts still relevant to Task5:
- `Task2/dc_open_plan.csv`
- `Task2/assignment_with_otd_prob_reachable.csv`
- `Task2/time_matrix.csv`
- `Task2/weights_by_year.csv`
- extracted Task2 simulator logic from `Task2/Simulator.ipynb`

### 5.2 Task3

Useful reference outputs:
- `Task3/annual_summary.csv.gz`
- `Task3/segment_summary.csv.gz`
- `Task3/simulated_demand.csv.gz`
- production / autonomy notebooks for capacity-thinking reference only

### 5.3 Task4

Primary demand reference for Task5:
- `Task4/dc_output/batch_*.parquet`
- `Task4/dc_output/dc_daily_demand.parquet`
- extracted Task4 simulator logic from `Task4/DC_Demand_Simulator.ipynb`

Task4 facts that matter:
- it reuses the Task2 stochastic kernel instead of inventing a new one
- it routes demand to DCs without losing simulator grain
- it is the closest functional template for `Task5/src/demand_generator.py`

## 6) Current Task5 State Assessment (3rd Edition)

The current Task5 framework is acceptable as a module layout. Core demand and network infrastructure fixes have been completed.

### ✅ Fixed Issues (3rd Edition)
- ✅ `DG-1`: Demand generator now follows Task2/Task4 simulator contract
- ✅ `DG-2`: Beta Monte Carlo math corrected (removed)
- ✅ `SIM-1`: Service overlay layer enables network-aware demand
- ✅ `HUB-1`: Hub consolidation integrated; routes built and passed to demand generator
- ✅ `NET-3`: Dwell logic uses node types, not string matching
- ✅ `NET-2`: Detour ratio genuinely computed at route level (tautology eliminated)
- ✅ `NET-4`: Merged relay hubs preserved (solved by HUB-1 new function)

### ❌ Remaining High-Priority Issues
- `NET-1`: OTD evaluation still uses direct lanes only (should use routes)
- `FLOW-1`: Capacity logic uses synthetic distributions (should use `dc_daily_sim`)
- `COST-1`: Cost based on equal lane splits (should use routed demand flows) - **CRITICAL**

### ⚠️ Remaining Medium-Priority Issues
- `REP-1`: Non-PI elapsed-time comparison fields missing in reporting
- `FIN-1`: Non-PI cost baseline uses approximations instead of Task2/Task4 artifacts

### Current Pipeline State
- ✅ Demand: `dc_daily_sim` with proper grain (sim, date, year, euro_dc_id, model, realized_units)
- ✅ Routes: Built from lanes with service_mode, n_relay_stops, n_consol_stops, detour_ratio
- ✅ Network: Relay hubs placed by driving-distance constraints
- ✅ Dwell: Correctly assigned by node type (consolidation vs relay)
- ✅ Sanity check: Pipeline runs successfully for year 2027

Use `Task5/ACTIVE_FIXES.md` for open issue list, root causes, and fix specifications.

## 7) Modification Boundaries

Accepted boundary for current maintenance:
- keep `preprocess.py`, `hub_network.py`, `flow_model.py`, `evaluator.py`, `reporting.py`, and `pipeline.py` as modules
- fix internals before adding new features
- do not redesign Task5 into a different folder architecture unless explicitly requested

Correction order (updated 2026-03-11 PM):
1. ✅ Restore the demand generator contract (DG-1, DG-2)
2. ✅ Add yearly network-aware service layer (SIM-1)
3. ✅ Reconnect downstream annual demand to simulated DC outputs (completed)
4. ✅ Fix network path semantics, dwell logic, detour logic, and consolidation state (HUB-1, NET-2, NET-3, NET-4)
5. ⏳ Fix OTD evaluation to use routes instead of direct lanes only (NET-1)
6. ⏳ Fix DC transfer / capacity logic to use simulator-derived daily demand (FLOW-1)
7. ⏳ Fix costing to use routed demand flows instead of equal lane splits (COST-1)
8. ⏳ Fix non-PI comparison and profitability based on routed / baseline-backed metrics (REP-1, FIN-1)

## 8) Data and Logging Conventions

Target convention for modification work:
- `Task5/data/` holds prepared reference tables such as `nodes_master.csv` and relay-node artifacts
- `Task5/output/` holds run outputs, KPI tables, comparisons, and issue logs
- `data_issue_log.csv` should be treated as an output artifact for task runs

Important note:
- the current code writes `data_issue_log.csv` under `Task5/data/`; this is a known mismatch and should be corrected when `preprocess.py` / reporting outputs are touched

## 9) AI Editing Guidance

Before editing Task5:
1. read `Task5/ACTIVE_FIXES.md`
2. confirm whether the change affects the canonical demand contract
3. if demand-related, compare against extracted Task2 / Task4 simulator logic before editing
4. prefer preserving data grain over adding shortcuts
5. if a planned change conflicts with the case PDF, the PDF wins

When modifying `demand_generator.py`:
- start from Task4-style logic, not from the current Task5 implementation
- keep `run_pi_demand_pipeline()` as an orchestrator if useful, but change its internals to return simulator-derived results
- do not use annual Beta or lognormal shortcuts as substitutes for the demand simulator
- do not freeze the old direct DC assignment if the active PI network implies a different service path
- if hub consolidation changes route time or service viability, feed that into the same OTD conversion contract before final demand aggregation

Recommended structural pattern:
1. stochastic demand kernel generates pre-OTD demand at node-compatible geography
2. network modules generate a yearly service matrix from the active hub graph
3. service matrix provides route choice, relay count, consolidation count, and elapsed time
4. OTD conversion uses that service matrix while keeping the prior-task schema / logic family intact
5. realized demand is then aggregated to DC outputs

When modifying downstream modules:
- assume current Task5 annual demand, OTD, cost, and comparison outputs may need recomputation after the demand fix
- do not use old Task5 CSV outputs as regression baselines unless the underlying logic has been validated

## 10) Companion Files

Use these three files together:
- `Task5/CONTEXT.md`: repo context and source-of-truth rules
- `Task5/PLAN.md`: corrected modification plan for the current Task5 framework
- `Task5/ACTIVE_FIXES.md`: open issues, root causes, and fix specifications
