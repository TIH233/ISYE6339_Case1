# MISTAKE.md

Last updated: 2026-03-12
Purpose: quick-index file for AI agents and maintainers working on the current Task5 codebase.

Use this file together with:
- `Task5/CONTEXT.md`
- `Task5/PLAN.md`

This file does not replace the plan. It is the indexed map of known wrong parts in the current Task5 implementation.

Current scope note:
- Task5 now runs in PI-only mode.
- Non-PI comparison outputs are intentionally not produced.
- Remaining fallbacks should be treated as route-coverage edge cases, not as a second scenario branch.

---

## 1) Fast Index

| ID | Status | Severity | Area | Main file(s) | Short statement |
|---|---|---|---|---|---|
| `DG-1` | ✅ FIXED | Critical | Demand | `src/demand_generator.py` | Demand generator is not the Task2 / Task4 simulator contract |
| `DG-2` | ✅ FIXED | Critical | Demand | `src/demand_generator.py` | Replacement Monte Carlo math is wrong for `pi_purchase_prob = 1.0` |
| `SIM-1` | ✅ FIXED | Critical | Simulator | `src/demand_generator.py`, `src/pipeline.py` | Simulator is still tied to the old direct `node -> assigned_cand` landscape and does not consume the active PI network |
| `HUB-1` | ✅ FIXED | High | Hub logic | `src/hub_network.py`, `src/pipeline.py` | Hubs are effectively relay-only; consolidation state is not modeled in routing, OTD, or costing |
| `NET-3` | ✅ FIXED | High | Network | `src/hub_network.py` | Dwell logic depends on `dest_id` string contents instead of node role |
| `NET-2` | ✅ FIXED | High | Network | `src/hub_network.py`, `src/reporting.py` | Detour ratio is effectively constant and the detour filter does not really bind |
| `NET-1` | ✅ FIXED | High | Network | `src/hub_network.py`, `src/evaluator.py`, `src/pipeline.py` | Relay routes are represented as pseudo-direct lanes |
| `NET-4` | ✅ SOLVED | High | Network | `src/hub_network.py`, `src/pipeline.py` | Merged relay hubs are dropped before they reach the active graph (solved by HUB-1 new function) |
| `FLOW-1` | ✅ FIXED | High | Flow | `src/flow_model.py`, `src/evaluator.py` | Capacity / interval logic is disconnected from simulated daily demand |
| `COST-1` | ✅ FIXED | Critical | Cost | `src/evaluator.py` | Cost and carbon are based on equal lane splits, not routed demand |
| `REP-1` | ✅ CLOSED BY SCOPE | Medium | Reporting | `src/reporting.py`, `src/pipeline.py` | Non-PI elapsed-time comparison fields are expected but never produced |
| `FIN-1` | ✅ CLOSED BY SCOPE | Medium | Profitability | `src/evaluator.py` | Non-PI cost baseline is arbitrary instead of artifact-backed |
| `DOC-1` | ℹ️ NOTED | Low | Docs | `CONTEXT.md`, `PLAN.md`, `src/preprocess.py` | `data_issue_log.csv` location is inconsistent |
| `DOC-2` | ℹ️ NOTED | Low | Docs | `PLAN.md` | Some artifact lists were stale and misleading |

---

## 2) Detailed Mistakes

### `DG-1` Demand generator is not the Task2 / Task4 simulator contract

Files to inspect:
- `Task5/src/demand_generator.py`
- extracted `Task2/Simulator.ipynb`
- extracted `Task4/DC_Demand_Simulator.ipynb`

What is wrong:
- current Task5 demand code replaced the original simulator mechanics with annual node-level probability math
- it does not preserve calendar, cyber-week, period-share, model-share, and DC-day-model demand generation as the main contract
- downstream annual DC demand is taken from assignment-derived reachable units instead of simulator-derived demand

Why it matters:
- this breaks the user's intended requirement that Task5 demand be the same module family as Task3 / Task4
- downstream flow, capacity, cost, and OTD results become detached from the simulator

Good correction direction:
- port or adapt the Task4 `run_modified_simulator(...)` logic into `Task5/src/demand_generator.py`
- keep PI-specific changes limited to OTD / purchase mapping and PI-specific routing assumptions
- make `annual_by_dc` an aggregation of simulator output

Quick references:
- `Task5/src/demand_generator.py`
- `Task5/CONTEXT.md` section 4
- `Task5/PLAN.md` section 3

### `DG-2` Replacement Monte Carlo math is wrong for `pi_purchase_prob = 1.0`

Files to inspect:
- `Task5/src/demand_generator.py`

What is wrong:
- the Beta fit used for uncertainty breaks when `pi_purchase_prob` is exactly `1.0`
- clipping the parameters produces a distribution with mean about `0.5`, not `1.0`

Why it matters:
- the simulator summary is mathematically invalid for metro nodes
- even if downstream code stopped using this summary today, keeping wrong math here is dangerous and misleading

Good correction direction:
- delete this replacement Monte Carlo path once the Task4-style simulator port exists
- if any uncertainty summary is still needed, derive it from repeated simulator output rather than a separate Beta shortcut

Quick references:
- `Task5/src/demand_generator.py`
- `Task5/MISTAKE.md` item `DG-1`

### `SIM-1` Simulator is still tied to the old direct assignment landscape

Files to inspect:
- `Task5/src/demand_generator.py`
- `Task5/src/pipeline.py`
- `Task2/assignment_with_otd_prob_reachable.csv`

What is wrong:
- current Task5 demand logic only reads the old Task2 assignment table and adjusts probabilities on top of it
- it does not consume yearly active lanes, chosen paths, or any route/service table derived from the PI network
- therefore the effective `DC -> node` service landscape cannot change when the network design changes

Why it matters:
- this is exactly where PI should differ from the old direct-delivery world
- if inter-hub paths or hub-based service change elapsed time, OTD, or feasible assignment, the simulator currently cannot reflect it

Good correction direction:
- introduce a yearly network-aware service overlay between demand generation and final DC aggregation
- build a service matrix from the active network with fields like assigned DC, chosen path, route elapsed time, relay count, and consolidation count
- apply OTD conversion using that service matrix while preserving the prior-task conversion contract / schema
- default to the same Task2 / Task4 OTD conversion table or function interface unless the case PDF explicitly requires a PI-only overlay
- aggregate simulator output to DC only after the service overlay has been applied

Quick references:
- `Task5/CONTEXT.md` section 4
- `Task5/PLAN.md` section 3
- `Task5/src/demand_generator.py`
- `Task5/src/pipeline.py`

### `HUB-1` Hubs are effectively relay-only; consolidation is not modeled

Files to inspect:
- `Task5/src/hub_network.py`
- `Task5/src/evaluator.py`
- `Task5/src/config.py`

What is wrong:
- current routing logic distinguishes lanes mostly by relay labeling, not by real hub service state
- `HUB_CONSOL_DWELL_HR` and `HUB_CONSOL_COST_EUR` exist in config but are not used as part of an explicit consolidation model
- OTD simulation uses only direct DC-to-hub lanes and relay-style dwell assumptions
- profitability includes hub relay fees but no real consolidation-visit accounting

Why it matters:
- the current network cannot express the user-visible PI effect where hubs consolidate shipments and change service performance
- without explicit consolidation state, route time and route cost are both incomplete

Good correction direction:
- represent relay-only stops and consolidation stops as separate route-service states
- have route-building count `n_relay_hubs` and `n_consol_hubs`
- feed those counts / states into elapsed-time, OTD, and cost logic
- keep demand generation separate from physical shipment consolidation, but let consolidation affect the service matrix that drives demand conversion

Quick references:
- `Task5/PLAN.md` section 4
- `Task5/src/hub_network.py`
- `Task5/src/evaluator.py`

### `NET-1` Relay routes are represented as pseudo-direct lanes

Files to inspect:
- `Task5/src/hub_network.py`
- `Task5/src/pipeline.py`
- `Task5/src/evaluator.py`

What is wrong:
- `DC_HUB_VIA_RELAY` is stored as a single direct lane between a DC and a hub
- OTD evaluation only uses `DC_HUB_DIRECT` lanes
- coverage and elapsed-time logic are therefore not evaluating the same physical routing assumptions

Why it matters:
- the current network can look connected even when the physical relay path is never represented
- OTD results become inconsistent with the network topology being reported

Good correction direction:
- keep lane tables as physical legs only
- add path or route construction for `DC -> relay -> hub` and `DC -> DC -> hub` movements
- evaluate OTD / elapsed metrics on routes, not on a subset of direct legs only

Quick references:
- `Task5/PLAN.md` section 4
- `Task5/src/hub_network.py`
- `Task5/src/evaluator.py`

### `NET-2` Detour ratio is effectively constant

Files to inspect:
- `Task5/src/hub_network.py`
- `Task5/output/network_kpis_by_year.csv`

What is wrong:
- `road_km` is computed as `haversine_km * DETOUR_FACTOR`
- detour checks and KPI calculations compare that same road estimate against haversine again
- this makes detour ratio nearly fixed at `1.2` across the network

Why it matters:
- the plan says detour should be a real screening constraint
- the current code turns detour into a tautology instead of a network-quality measure

Good correction direction:
- compute detour on full routes: `routed_path_km / direct_od_km`
- use actual path assembly or corridor-specific route distance logic
- allow detour checks to reject candidates

Quick references:
- `Task5/src/hub_network.py`
- `Task5/PLAN.md` section 4

### `NET-3` Dwell logic depends on id-string matching

Files to inspect:
- `Task5/src/hub_network.py`
- `Task5/output/subtask_5_4_joint_shipment_trace.csv`

What is wrong:
- dwell type is currently inferred from whether `dest_id` contains the substring `DC`
- actual DC ids are `CAND_*`, so many DC destinations receive relay dwell instead of consolidation dwell

Why it matters:
- elapsed-time outputs are wrong even when the lane geometry is otherwise correct
- OTD / comparison metrics inherit the wrong time accounting

Good correction direction:
- determine dwell by destination node type or lane role
- keep a node lookup available when lanes are built or when route time is evaluated

Quick references:
- `Task5/src/hub_network.py`
- `Task5/MISTAKE.md` item `NET-1`

### `NET-4` Merged relay hubs are dropped from the active graph

Files to inspect:
- `Task5/src/hub_network.py`
- `Task5/src/pipeline.py`

What is wrong:
- relay derivation can reuse an existing peri-urban hub id when merging
- pipeline later filters out relay rows whose `node_id` already exists in the base node table
- the intended dual-role relay hub therefore disappears as a relay object

Why it matters:
- the planned “reuse existing city hub as relay” rule never actually survives to routing
- relay readiness and dual-role metrics become structurally unreliable

Good correction direction:
- model merged relay capability as role augmentation or metadata, not as a duplicate row with the same `node_id`
- preserve dual-role hubs in a way that path-building logic can consume

Quick references:
- `Task5/src/hub_network.py`
- `Task5/src/pipeline.py`

### `FLOW-1` Capacity / interval logic is disconnected from simulated daily demand

Files to inspect:
- `Task5/src/flow_model.py`
- `Task5/src/evaluator.py`

What is wrong:
- capacity intervals and cyber-week stress use synthetic annual / peak distributions
- they do not consume Task4-style daily DC demand or corrected PI daily DC demand

Why it matters:
- Task5 effectively has a second demand engine inside flow / sizing logic
- capacity numbers are not traceable back to the simulator output contract

Good correction direction:
- derive DC daily arrays from corrected demand simulation
- run cyber-week stress and interval summaries from those arrays or from sim-level aggregates

Quick references:
- `Task5/PLAN.md` section 5
- `Task5/src/flow_model.py`

### `COST-1` Cost and carbon are based on equal lane splits, not routed demand

Files to inspect:
- `Task5/src/evaluator.py`
- `Task5/output/subtask_5_9_cost_carbon_summary.csv`

What is wrong:
- the current model spreads each DC's annual demand evenly across every outbound lane
- cost and carbon are then computed as if each of those lane allocations is real traffic

Why it matters:
- cost becomes a function of lane count rather than actual OD demand and route usage
- carbon and transport cost cannot support credible decision-making

Good correction direction:
- define path allocation rules from demand origins / assigned DCs to served hubs or demand nodes
- compute lane flows from route usage, then compute cost and carbon from those flows

Quick references:
- `Task5/PLAN.md` section 6
- `Task5/src/evaluator.py`

### `REP-1` Reporting expects fields that upstream code never produces

Files to inspect:
- `Task5/src/reporting.py`
- `Task5/src/pipeline.py`
- `Task5/output/network_vs_nonpi_comparison.csv`
- `Task5/output/activation_decisions_log.csv`

What is wrong:
- reporting expects elapsed-comparison and time-saving fields that are never produced upstream
- exported comparison files therefore contain blanks or placeholder behavior

Why it matters:
- the output bundle claims a comparison that the pipeline does not actually compute
- this is especially dangerous for AI agents that assume the file exists, therefore the metric exists

Good correction direction:
- either produce the required comparison fields upstream, or remove the claim until they exist
- prefer real PI vs non-PI elapsed comparisons based on routes and baseline travel fields

Quick references:
- `Task5/src/reporting.py`
- `Task5/PLAN.md` section 6

### `FIN-1` Non-PI cost baseline is arbitrary

Files to inspect:
- `Task5/src/evaluator.py`
- `Task2/assignment_with_otd_prob_reachable.csv`
- `Task4` demand artifacts

What is wrong:
- profitability uses guessed non-PI multipliers instead of artifact-backed non-PI cost logic
- this makes margin-uplift outputs weak and hard to defend

Why it matters:
- profitability is a summary conclusion metric; weak baseline logic contaminates the final story

Good correction direction:
- use actual baseline artifacts where possible
- if approximations remain necessary, label them explicitly and keep them separate from measured metrics

Quick references:
- `Task5/src/evaluator.py`
- `Task5/PLAN.md` section 6

### `DOC-1` `data_issue_log.csv` location was inconsistent

Files to inspect:
- `Task5/CONTEXT.md`
- `Task5/PLAN.md`
- `Task5/src/preprocess.py`

What was wrong:
- docs and code did not agree on whether `data_issue_log.csv` belongs in `data/` or `output/`

Correction policy now:
- treat it as a run output
- if code is touched later, standardize on `Task5/output/data_issue_log.csv`

### `DOC-2` Some artifact lists were stale

Files to inspect:
- `Task5/PLAN.md`

What was wrong:
- some listed artifacts did not match what the current code actually produces
- “generated, not committed” notes also did not match the repo state

Correction policy now:
- treat docs as modification guidance, not as proof that current outputs are valid
- keep artifact lists synchronized when source files change

---

## 3) Priority Order For AI Work

### ✅ Completed (in order)
1. ✅ `DG-1` - Demand generator contract (2026-03-11 AM)
2. ✅ `DG-2` - Beta Monte Carlo math (2026-03-11 AM)
3. ✅ `SIM-1` - Service overlay layer (2026-03-11 AM)
4. ✅ `HUB-1` - Hub consolidation integration (2026-03-11 PM)
5. ✅ `NET-3` - Dwell logic fix (2026-03-11 PM)
6. ✅ `NET-2` - Detour ratio fix (2026-03-11 PM)

### ❌ Remaining (priority order)
7. `NET-1` - Relay routes as pseudo-direct lanes (**HIGH**)
8. `FLOW-1` - Capacity disconnected from daily demand (**HIGH**)
9. `COST-1` - Cost based on equal splits (**CRITICAL**)
10. `REP-1` - Missing comparison fields (Medium)
11. `FIN-1` - Arbitrary non-PI baseline (Medium)

Note: `NET-4` solved by HUB-1 new function (no additional work needed)

Reason for remaining order:
- `NET-1` unlocks proper route-based OTD evaluation
- `FLOW-1` and `COST-1` depend on having routes and daily demand (now available)
- `COST-1` is critical for business decision-making
- `REP-1` and `FIN-1` are reporting polish after core fixes

---

## 4) Short Rule Set

Do:
- preserve simulator grain
- preserve the prior-task OTD conversion contract / schema
- aggregate annual metrics from simulator output
- let the active network update service assignment and elapsed time before OTD conversion
- evaluate elapsed time and detour on actual routes
- represent consolidation explicitly if it affects route service
- tie cost to routed flow
- use Task2 / Task4 artifacts as baseline references

Do not:
- invent a substitute demand engine inside downstream modules
- freeze the old Task2 direct assignment as the PI service landscape
- trust existing Task5 CSV outputs without checking the producing logic
- assume a field exists just because a report file exists

---

## 5) Companion Reminder

Use:
- `Task5/CONTEXT.md` for source-of-truth rules
- `Task5/PLAN.md` for the corrected modification sequence
- `Task5/MISTAKE.md` for quick indexing and inspection priority

---

## 6) 2nd Edition Implementation Notes (2026-03-11 AM)

### Fixes Applied

#### DG-1: ✅ FIXED
**Demand generator now follows Task2/Task4 simulator contract**
- Ported calendar builder, adoption rates, period shares, model shares, OTD conversion
- Output grain: (sim, date, year, euro_dc_id, model, realized_units)
- All stochastic operations use numpy (pandas only for I/O)
- See: `demand_generator.py` lines 1-493

#### DG-2: ✅ FIXED
**Broken Beta Monte Carlo math removed**
- Deleted `simulate_pi_demand()` function
- Uncertainty captured by running n_sim simulations
- No Beta approximation that breaks at p=1.0

#### SIM-1: ✅ FIXED
**Service overlay layer added**
- Two-layer architecture implemented:
  * Layer 1: Stochastic kernel (network-agnostic pre-OTD demand)
  * Layer 2: Service overlay (network-aware routing + OTD conversion)
- Service landscape can change yearly
- See: `demand_generator.py` lines 218-321, 404-492

#### HUB-1: ⚠️ PARTIAL FIX
**Hub capabilities and driving-distance relay placement added**
- Relay hubs now placed based on 11-hour driving constraint
- Hub capability tagging: is_consol_capable, is_relay_capable
- Route builder counts relay vs consolidation stops separately
- See: `hub_network.py` lines 502-780
- **Remaining**: Full route enumeration, pipeline integration

### Approach Used

**Approach A (Capability-Based)**:
- DC: consolidation + relay capable
- PERI_URBAN_HUB: consolidation + relay capable
- RELAY_HUB: relay-only (no consolidation)
- Placement: driving-distance algorithm (not border-midpoint)

### Integration Status (2nd Edition)

Completed modules:
- ✅ `demand_generator.py` - rewritten with 2-layer architecture
- ✅ `hub_network.py` - new functions added (not yet integrated)

Pending modules:
- ⏳ `pipeline.py` - needs update to pass routes to demand generator
- ⏳ `evaluator.py` - will consume dc_daily_sim output
- ⏳ `flow_model.py` - will consume dc_daily_sim output

---

## 7) 3rd Edition Implementation Notes (2026-03-11 PM)

### Fixes Applied

#### HUB-1: ✅ FULLY FIXED
**Pipeline integration completed**
- `pipeline.py` now uses `derive_relay_hubs_by_driving_distance()` instead of old border-midpoint logic
- Routes built via `build_routes()` after lane generation
- Routes passed to demand generator for network-aware service overlay
- Routes stored in pipeline results for downstream use
- See: `pipeline.py` lines 26-29, 138-169, 265
- Verified: Sanity check shows routes successfully built (49 routes for 2027)

#### NET-3: ✅ FIXED
**Dwell logic now uses node type, not string matching**
- `_lane_row()` function updated to accept `dest_node_type` parameter
- Dwell determination logic:
  * DC, PERI_URBAN_HUB → HUB_CONSOL_DWELL_HR (2 hrs)
  * RELAY_HUB, BORDER_RELAY_HUB → HUB_RELAY_DWELL_HR (0.5 hrs)
  * PORT → HUB_CONSOL_DWELL_HR (2 hrs)
  * Other → 0 (no dwell)
- All 7 call sites updated to pass correct node types
- See: `hub_network.py` lines 247-264, 322, 347, 357, 390, 407, 442, 473, 509
- Verified: Dwell times correctly assigned by node type

#### NET-2: ✅ FIXED
**Detour ratio tautology eliminated**
- `road_km` no longer multiplied by `DETOUR_FACTOR` in `_lane_row()`
- Tautological detour checks removed from lane generation
- Detour ratio now genuinely computed at route level: `actual_route_km / direct_km`
- Reporting updated to get detour from routes instead of lanes
- See: `hub_network.py` lines 270-272, 428-430, 490-495, 520-522
- See: `reporting.py` lines 80-86
- Verified: Direct routes show detour=1.0 (genuinely direct, not tautological)

### Integration Status (3rd Edition)

Fully integrated modules:
- ✅ `pipeline.py` - routes built and passed to demand generator
- ✅ `hub_network.py` - dwell logic fixed, detour tautology removed
- ✅ `reporting.py` - updated to use routes for detour ratio

Verified outputs:
- ✅ Routes table with service_mode, n_relay_stops, n_consol_stops, detour_ratio
- ✅ Dwell times vary by destination node type
- ✅ `dc_daily_sim` with 18,250 rows ready for downstream use

### Sanity Check Results (Year 2027)

Pipeline execution: **PASSED** ✅
- Active nodes: 77 (71 hubs, 4 non-metro, 1 port, 1 DC)
- Lanes: 2,644 | Routes: 49 (all DIRECT)
- Demand: 196,294 PI units | Daily sim: 18,250 rows
- Coverage: 100% | Relay readiness: 98.1%

See `Task5/FIX_SUMMARY.md` for detailed implementation notes and validation results.
