# Task5 Implementation Plan
Last updated: 2026-03-11
Source: full planning conversation with all clarifications resolved.

---

## 1) Node Taxonomy (`nodes_master.csv`)

| node_type | Source | Count | Role | lat/lng source |
|---|---|---|---|---|
| `PORT` | Rotterdam (manually split from metro list) | 1 | Ocean freight entry; no demand | metro sheet row "Rotterdam" |
| `DC` | `Task2/dc_open_plan.csv` | 4 | Storage + consolidation + local peri-urban hub | dc_open_plan |
| `PERI_URBAN_HUB` | `Metro cities_location` sheet (minus Rotterdam) | 272 | PI delivery handoff to last-mile provider; also relay if on corridor | metro sheet |
| `BORDER_RELAY_HUB` | Derived algorithmically (§3 below) | ~25–30 | Transit relay at country-boundary crossings; non-metro handoff | computed midpoints |
| `DEMAND_NONMETRO` | `non_metro_hub` sheet | 28 | Non-metro demand centroid only; NOT a hub | non_metro_hub sheet |

**Key rules:**
- DC cities (Koeln, Lodz, Madrid, Rome) also appear in metro sheet → keep as `DC` only, remove duplicate from `PERI_URBAN_HUB`.
- Rotterdam: create `PORT_NL_rotterdam` (type=PORT) + keep Rotterdam in `PERI_URBAN_HUB` (pop=1.03M, 1M+ bracket).
- `DEMAND_NONMETRO` nodes are demand endpoints only — not transit hubs.
- All `PERI_URBAN_HUB` and `BORDER_RELAY_HUB` are assumed already existing in PI world (PDF p.12).

**Required fields:** `node_id`, `node_type`, `country`, `city`, `lat`, `lng`, `pop_2026` (metro only), `pop_bracket` (1M+/250K-1M/<250K for metro).

**Known data fixes (log to `data_issue_log.csv`):**

| Field | Issue | Fix |
|---|---|---|
| `ing` column | Typo for `lng` in Metro sheet | Alias on read |
| `Countries` column | NaN rows (run-down pattern) | Forward-fill before any groupby |
| Rotterdam | Appears in metro list AND needed as PORT | Split into PORT + PERI_URBAN_HUB |
| DC cities in metro list | Would duplicate as PERI_URBAN_HUB | Keep only as DC type |

---

## 2) PI Demand Generation

**Reuse Task2 stochastic pipeline exactly.** Two PI-specific changes:

**Change 1 — PI OTD conversion (purchase probability)**

| Segment | Non-PI promise | Non-PI prob | PI promise | PI prob |
|---|---|---|---|---|
| Metro 1M+ | 1-day (24hr) | ~95% | 4hr (same-day) | ~100% |
| Metro 250K-1M | 1-day (24hr) | ~85% | 2hr | ~100% |
| Metro <250K | 1-day (24hr) | ~65% | 1hr | ~100% |
| Non-metro ≤250km | 1-day (24hr) | ~99.5% | 8hr | ~99% |
| Non-metro ≤500km | 2-day | ~98% | 16hr | ~99% |
| Non-metro >500km | 3-4 day | ~90% | 32hr | ~99% |

PI collapses OTD from days to hours → purchase probability near 100% for all segments → higher reachable demand than non-PI baseline.

**Change 2 — Sub-DC city-level demand split (same as Task2 logic)**

```
country_demand → metro cities: weight = pop_city / sum(pop_country_metros)
non_metro_demand = country_demand - sum(metro_demand)
non_metro_demand → DEMAND_NONMETRO node for that country
```

**DC assignment:** Use `assignment_with_otd_prob_reachable.csv` yearly weights (unchanged from Task2). Each demand node → assigned DC.

**Output grain:** `sim × date × year × dc_id × model → realized_units` (same as Task4 schema).

---

## 3) Hub Activation Logic (Per Year)

Hubs already exist in PI world. Task is to decide **which to activate into BotWorld's network each year**.

**PERI_URBAN_HUB activation:** Activate all metro cities in countries open per BotWorld roadmap:

| Year | Countries opening | Approx new hubs |
|---|---|---|
| 2027 | BE, DE, LU, NL | ~30 |
| 2028 | DK, EE, FI, LV, LT, NO, PL, SE | +60 |
| 2029 | AT, FR, IE, IT, PT, ES, CH | +80 |
| 2030 | BG, HR, CY, CZ, GR, HU, MT, RO, SK, SI | +100 |

**BORDER_RELAY_HUB derivation (algorithmic):**

```python
for each pair of adjacent open countries (A, B):
    border_hub_lat = (centroid_A_lat + centroid_B_lat) / 2
    border_hub_lng = (centroid_A_lng + centroid_B_lng) / 2
    # Clamp to border zone: check if midpoint is within 100km of both centroids
    if haversine(midpoint, centroid_A) < 300 and haversine(midpoint, centroid_B) < 300:
        add BORDER_RELAY_HUB at midpoint
    # If a PERI_URBAN_HUB exists within 80km of midpoint → merge (reuse city hub)
```

Expected result: ~25–30 border relay hubs by 2030.

**Hub dual-role rule:** Any `PERI_URBAN_HUB` on a DC-hub lane corridor automatically serves as a relay stop if it reduces the next-leg drive time.

---

## 4) Lane Generation

**Route time formula (all lane types):**
```
drive_time_hr = haversine_km(A, B) * DETOUR_FACTOR / DRIVE_SPEED_KMH
             = haversine_km(A, B) * 1.2 / 100
elapsed_hr   = drive_time_hr + hub_dwell_hr  (at destination)
```

**Lane types and rules:**

| Lane type | Candidates | Filter | Truck | Relay flag |
|---|---|---|---|---|
| PORT→DC | Rotterdam → each open DC | always included | L (€1.15/km) | False |
| DC↔DC | All 6 pairs of 4 DCs | always included | L (€1.15/km) | True if drive_time > 11hr |
| DC→PERI_URBAN_HUB | DC → hubs in open-country territory | drive_time ≤ 4hr: direct; 4–10hr: via border relay; >10hr: via DC-DC | M or L | True if > 4hr |
| DC→BORDER_RELAY | DC → all border relay hubs within 1000km | detour_ratio ≤ 1.35 | L | True |
| BORDER_RELAY→PERI_URBAN | each border relay → peri-urban hubs within 300km | always included | M | False |
| HUB↔HUB corridor | adjacent peri-urban hubs ≤ 300km apart on same corridor | detour_ratio ≤ 1.35 | M | True |

**DC-DC approximate drive times:**

| Pair | ~km | Drive_hr | Relay stops |
|---|---|---|---|
| Koeln↔Lodz | 900 | 10.8 | 0 |
| Koeln↔Rome | 1100 | 13.2 | 1 |
| Koeln↔Madrid | 1900 | 22.8 | 2 |
| Lodz↔Rome | 1500 | 18.0 | 1 |
| Lodz↔Madrid | 2700 | 32.4 | 3 |
| Rome↔Madrid | 1700 | 20.4 | 2 |

Relay stops = border relay hubs used as driver-swap points → maintains daily frequency on all lanes regardless of total distance.

**Detour constraint:** `detour_ratio = routed_km / direct_km ≤ 1.35`. Reject lanes exceeding this.

---

## 5) DC-DC Flow Model

**Two regimes — critical distinction:**

### Normal periods (non-cyber-week)
Need-based weekly rebalancing:
```
for each DC, rolling 7-day window:
    if weekly_demand > 1.30 × median_weekly_demand:          # stress trigger
        excess = weekly_demand - median_weekly_demand
        find nearest_DC where weekly_demand < 0.85 × its_median  # has slack
        transfer = min(excess × 0.10, 0.10 × nearest_DC.median_weekly)
        route via existing DC-DC relay lane
        cost: lane transport cost + €0.20/unit per relay hub stop
```

Cap: transfers never exceed 10% of any DC's annual throughput. No cascading.

### Cyber week (hard override — no DC-DC transfers)
```
is_cyber_week = date in Black_Friday .. Cyber_Monday + 2 days  # ~7 calendar days
if is_cyber_week:
    DC_DC_transfer = 0  # ALL DCs at peak simultaneously; no DC has slack
    each DC handles its own demand independently
    demand > throughput_capacity → lost_sales (Appendix B §9)
```

**Rationale:** Cyber week = 15% of annual demand in ~5 working days. All DCs stressed simultaneously. DC-DC mechanism would create circular stress with no resolution.

### DC throughput capacity sizing (cyber week drives the constraint)
```
CYBER_WEEK_SHARE   = 0.15
CYBER_WEEK_DAYS    = 5
peak_daily_units   = annual_demand_DC × 0.15 / 5     # = 3% of annual per day
peak_daily_pallets = peak_daily_units / UNITS_PER_PALLET
throughput_cap     = peak_daily_pallets × 2           # inbound + outbound
throughput_cost    = throughput_cap × 25              # €25/pallet-throughput/year
```

---

## 6) Yearly Network Roadmap

| Year | DCs open | Approx peri-urban hubs | Border relay hubs | DC-DC lanes active |
|---|---|---|---|---|
| 2027 | Koeln | ~30 (BE/NL/DE/LU) | ~5 | None |
| 2028 | +Lodz | +60 (Nordics/Baltic/PL) | +10 | Koeln↔Lodz |
| 2029 | +Madrid | +80 (ES/PT/FR/IT/AT/IE/CH) | +10 | +Madrid↔Koeln, Madrid↔Lodz |
| 2030 | +Rome | +100 (Balkans/EE/SE Europe) | +8 | Full 6-lane mesh |
| 2031–34 | All 4 | All 272 | ~28–30 | Full mesh + optimized |

**Activation log per year:** `(node_id, activation_year, coverage_gain_pct, drive_time_reduction_hr, detour_ratio)`

---

## 7) KPI Definitions (Task 5.1 Proof)

PDF states: *"do not size hubs nor estimate flows"* — KPIs are topology + time only.

| KPI | Formula | Target |
|---|---|---|
| Coverage % | feasible_OD_pairs / total_OD_pairs | ≥ 95% per year |
| Elapsed time | drive_time + hub_dwell vs non-PI `travel_elapsed_hr` | Reduction demonstrated |
| Detour ratio | routed_km / direct_km | ≤ 1.35 |
| Relay readiness | lanes with relay_flag=True / total lanes | ≥ 80% |
| DC-DC connectivity | DC pairs with relay path via border hubs | 100% by 2028 |

---

## 8) config.py Constants (Appendix B — All Confirmed)

```python
# PI packaging (replaces non-PI)
PI_PACK_COST_EUR        = 2.0     # per unit; replaces NON_PI_PACK_COST_EUR=15
TRANSLOAD_COST_EUR      = 1.5     # per unit per transload center (Sav+Rot = 3.0 total)
HUB_RELAY_COST_EUR      = 0.20    # per unit per relay-only hub visited
HUB_CONSOL_COST_EUR     = 0.40    # per unit per consolidation hub visited
HUB_RELAY_DWELL_HR      = 1.0
HUB_CONSOL_DWELL_HR     = 2.0

# Last-mile from hub (identical PI and non-PI)
LASTMILE_METRO_1M_EUR       = 8
LASTMILE_METRO_250K_EUR     = 10
LASTMILE_METRO_SMALL_EUR    = 12
LASTMILE_NONMETRO_250KM_EUR = 14
LASTMILE_NONMETRO_500KM_EUR = 18
LASTMILE_NONMETRO_BEYOND_EUR= 24

# DC operating
DC_STORAGE_EUR              = 110   # per pallet-position per year
DC_THROUGHPUT_EUR           = 25    # per max-daily-pallet-throughput per year
DC_INBOUND_PALLET_EUR       = 4
DC_OUTBOUND_PALLET_EUR      = 5
DC_UNIT_PICK_EUR            = 3
DC_FIXED_EUR_YEAR           = 600_000   # per Euro DC per year

# Transport — Europe (per km, contracted)
TRUCK_S_EUR_KM  = 0.45
TRUCK_M_EUR_KM  = 0.75
TRUCK_L_EUR_KM  = 1.15

# Ocean (6m container, median)
OCEAN_CONTAINER_USD = 2500

# Route geometry
DETOUR_FACTOR        = 1.2
DRIVE_SPEED_KMH      = 100
MAX_SINGLE_DRIVER_HR = 11      # relay required above this
DETOUR_RATIO_MAX     = 1.35

# Cyber week
CYBER_WEEK_ANNUAL_SHARE = 0.15
CYBER_WEEK_DAYS         = 5

# Demand split
UNITS_PER_PALLET = 4    # TBD from product dimension analysis (Task 5.2)
```

---

## 9) Module Structure

```
Task5/
  src/
    config.py           all constants (§8 above)
    data_loader.py      read Task2-Task4 artifacts + Excel sheets; apply data fixes
    preprocess.py       build nodes_master; Rotterdam split; column fixes; write data_issue_log.csv
    demand_generator.py Task2 stochastic pipeline reused; PI OTD conversion rates applied
    hub_network.py      peri-urban hub activation by country-year;
                        border relay hub derivation;
                        lane generation (all 5 types in §4)
    flow_model.py       DC-DC stress transfer (non-cyber-week only);
                        cyber week capacity sizing;
                        is_cyber_week() helper
    evaluator.py        KPI computation (coverage, elapsed time, detour, relay readiness)
    reporting.py        roadmap tables; activation log; map exports
    pipeline.py         year-by-year orchestrator: 2027→2034 loop calling all modules
  notebooks/
    task5_runner.ipynb  lightweight orchestrator calling pipeline.py; display outputs
  data/                 (generated, not committed)
    nodes_master.csv
    border_relay_hubs.csv
    lane_candidates.parquet
    od_yearly_base.parquet
  output/               (generated, not committed)
    network_roadmap_{2027..2034}.csv
    activation_decisions_log.csv
    network_kpis_by_year.csv
    network_vs_nonpi_comparison.csv
    dc_capacity_sizing.csv
    data_issue_log.csv
```

---

## 10) Subtask Coverage Map

| PDF Task 5.x | Covered by | Key module |
|---|---|---|
| 5.1 Network design + roadmap | hub_network.py + pipeline.py | hub_network, evaluator |
| 5.2 p-pack space saving | config.py dimensions + notebook cell | config, reporting |
| 5.3 Transport time reduction | evaluator.py vs non-PI baseline | evaluator |
| 5.4 Joint shipment example | reporting.py illustrative trace | reporting |
| 5.5 OTD + reachable demand | demand_generator.py PI scenario | demand_generator |
| 5.6 Autonomy targets | flow_model.py + evaluator.py | flow_model |
| 5.7 PI simulator adaptation | demand_generator.py + flow_model.py | all |
| 5.9 Shipment/truck/distance/cost | evaluator.py + reporting.py | evaluator |
| 5.10 DC sizing + costing | flow_model.py (capacity) + config.py | flow_model |
| 5.11 Transload load + cost | reporting.py | reporting |
| 5.12 Overall profitability | reporting.py using all cost modules | reporting |
