# DC Demand Simulator — Technical Pipeline & Output Reference

## 1. Pipeline Overview

The simulator converts raw population and adoption-rate inputs into a DC-level daily demand table through five sequential stages.

```
[Pop_inputs.xlsx]          [assignment_with_otd_prob_reachable.csv]
     │                                       │
     ▼                                       ▼
[Stage 1] Modified OTD Simulator    [City Proportions Lookup]
     │     (100 sims × 8 years)             │
     │     → (sim, date, year,              │
     │         country, segment,            │
     │         model, sales_units)          │
     │                                       │
     └───────────────────┬───────────────────┘
                         ▼
               [Stage 2] City-Level Disaggregation
                    → (sim, date, year,
                        node_id, euro_dc_id,
                        model, city_demand)
                         │
                         ▼
               [Stage 3] DC-Level Aggregation
                    → (sim, date, year,
                        euro_dc_id, model,
                        realized_units)
                         │
                         ▼
               [dc_daily_demand.csv.gz]
```

---

## 2. Input Data Sources

| Source File | Sheet / Content | Key Fields Used |
|---|---|---|
| `Task4/Pop_inputs.xlsx` | **Metro** — 273 cities | `Country`, `City`, `Pop_{year}` (2027–2034) |
| `Task4/Pop_inputs.xlsx` | **NonMetro** — 29 countries | `Country`, `NonMetroPop_{year}` (2027–2034) |
| `Task4/Pop_inputs.xlsx` | **Model** — 24 products | `Model`, `Price_EUR`, `Share_MP` |
| `Task2/assignment_with_otd_prob_reachable.csv` | City-to-DC assignments | `node_id`, `node_type`, `year`, `assigned_cand`, `units`, `otd_days_promise` |

---

## 3. Stage 1 — Modified OTD Simulator

### 3.1 Calendar Construction

For each simulation year, a daily calendar is built with:

- **Day-of-week (DOW) weights** used for intra-period demand allocation:

  | Weekday | Weight |
  |---|---|
  | Monday | 0.10 |
  | Tuesday | 0.12 |
  | Wednesday | 0.13 |
  | Thursday | 0.14 |
  | Friday | 0.18 |
  | Saturday | 0.19 |
  | Sunday | 0.14 |

- **Cyber Week** — identified as the ISO week containing Black Friday (4th Thursday of November). All 7 days of that week are flagged `is_cyber_week = True`.

- **Periods** — 365 days split into 13 periods of 28 days each; overflow days assigned to period 13.

### 3.2 Annual Segment Demand

For each `(country, segment)` pair, annual demand is computed as:

```
annual_demand(country, segment, year) =
    Σ_city [ city_population(year) × adoption_rate(market_year, scenario) ]
```

where:

- `market_year = simulation_year − entry_year[country] + 1`
- Countries not yet entered (market_year < 1) contribute zero demand.
- **Adoption rates by scenario (most probable `mp`):**

  | Market Year | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
  |---|---|---|---|---|---|---|---|---|
  | Rate | 0.002 | 0.003 | 0.005 | 0.008 | 0.012 | 0.018 | 0.025 | 0.032 |

### 3.3 Period Share Simulation

13 period shares are drawn per simulation using a **triangular distribution**:

```
raw_draw ~ Triangular(left=0.5, mode=1.0, right=1.5),  shape=(n_sim, 13)
period_shares = raw_draw / row_sum                       # normalize to sum=1
```

Shares vary across simulations, capturing seasonal uncertainty.

### 3.4 Cyber Week vs Regular Demand Split

```
cyber_total   = total_annual × 0.18   (18% of annual demand)
regular_total = total_annual × 0.82
```

During Cyber Week, a **15% price discount** is applied to revenue (not to units).

### 3.5 Daily Demand Allocation

**Regular days** (non-Cyber Week):

```
period_units(p) = regular_total × period_shares[p]

DOW_weights_normalized = DOW_weights[day] / Σ(DOW_weights in period p)

day_demand = period_units(p) × DOW_weights_normalized[day]
```

**Cyber Week days**:

```
CW_weights_normalized = DOW_weights[day] / Σ(DOW_weights in CW)

CW_day_demand = cyber_total × CW_weights_normalized[day]
```

### 3.6 OTD Conversion Rate

Daily segment demand is multiplied by a conversion rate that depends on delivery speed:

| OTD Bucket | OTD Days | Metro | Non-Metro |
|---|---|---|---|
| 0 | ≤ 1 day | 1.00 | 1.00 |
| 1 | 1–2 days | 0.95 | 0.98 |
| 2 | 2–3 days | 0.85 | 0.93 |
| 3 | > 3 days | 0.70 | 0.85 |

OTD days used per segment:
- **Metro**: population-weighted average OTD across all cities in `(country, year)`
- **Non-Metro**: country-level OTD from `nonmetro_otd[country_code][year]`

```
daily_sales(day, country, segment) =
    day_demand × segment_weight(country, segment) × conversion_rate(segment, otd_days)
```

### 3.7 Product Model Decomposition

24 model shares are sampled per `(sim, year)` using triangular variation around the base `Share_MP`:

```
draw ~ Triangular(left=0.8, mode=1.0, right=1.2),  shape=(24,)
model_shares = (Share_MP × draw) / Σ(Share_MP × draw)   # re-normalize

sales_units(model) = daily_sales(day, country, segment) × model_shares[model]
```

### 3.8 Batch Output (Intermediate)

After every 10 simulations, a batch is flushed and saved to `dc_output/batch_NN.csv.gz`.

**Batch file schema (segment-level)**:

| Column | Type | Description |
|---|---|---|
| `sim` | int | Simulation index (0-based) |
| `date` | datetime | Calendar date |
| `year` | int | Simulation year |
| `country` | str | ISO 2-letter country code (e.g., `DE`) |
| `segment` | str | `Metro` or `Non-Metro` |
| `model` | str | Product model code (e.g., `FC_01`) |
| `sales_units` | float | Converted daily sales units |

---

## 4. Stage 2 — City-Level Disaggregation

Segment demand is split to individual cities using population proportions derived from the Task2 assignment file.

### 4.1 City Proportion Calculation

```
proportion(city, year, country, segment) =
    units_assigned(city, year) /
    Σ_c units_assigned(c, year)   for all cities c in (country, segment)
```

Proportions are guaranteed to sum to 1.0 within each `(year, country, segment)` group.

### 4.2 Disaggregation Formula

```
city_demand(sim, date, year, city) =
    sales_units(sim, date, year, country, segment, model) × proportion(city, year, country, segment)
```

The merge key is `[year, country, segment]`. Every segment record expands into ~6–10 city records (the number of cities in that country-segment).

**Expansion factor**: ~13× (from segment-level to city-level).

---

## 5. Stage 3 — DC-Level Aggregation

Cities are mapped to DCs via the `assigned_cand` column in the assignment file. City-level demand is summed per `(sim, date, year, euro_dc_id, model)`:

```
realized_units(sim, date, year, DC, model) =
    Σ_city [ city_demand(sim, date, year, city, model) ]
    for all cities assigned to DC
```

**Reduction factor**: ~40× (from city-level back down to DC-level).

Demand is fully conserved at each stage — total units are identical from segment → city → DC.

---

## 6. DC Output Schema

**File**: `Task4/dc_output/dc_daily_demand.csv.gz`

### 6.1 Column Definitions

| Column | Type | Values | Description |
|---|---|---|---|
| `sim` | int | 0 – 99 | Monte Carlo simulation index (0-based; 100 total) |
| `date` | datetime64 | 2027-01-01 – 2034-12-31 | Calendar date of demand |
| `year` | int | 2027, 2028, …, 2034 | Year (redundant with date; retained for fast groupby) |
| `euro_dc_id` | str | `CAND_DE_koeln`, `CAND_FR_paris`, `CAND_IT_milan`, `CAND_PL_warsaw` | Assigned DC identifier (4 DCs total) |
| `model` | str | 24 codes across 6 categories | Product model code (see §6.3) |
| `realized_units` | float | > 0 | Daily realized sales units after OTD conversion |

### 6.2 DC Identifiers

| `euro_dc_id` | Location | Countries Served |
|---|---|---|
| `CAND_DE_koeln` | Cologne, Germany | BE, DE, LU, NL, DK, EE, FI, LT, LV, SE, AT, … |
| `CAND_FR_paris` | Paris, France | FR, ES, PT, … |
| `CAND_IT_milan` | Milan, Italy | IT, … |
| `CAND_PL_warsaw` | Warsaw, Poland | PL, CZ, BG, GR, HR, HU, RO, SI, SK, … |

> DC-to-country assignments are determined by the Task2 network optimization and stored in `assignment_with_otd_prob_reachable.csv`.

### 6.3 Model Codes (24 Products)

Products span 6 categories, 4 models each:

| Category | Codes | Price Range (EUR) |
|---|---|---|
| Floor Care | `FC_01` – `FC_04` | 360 – 720 |
| Kitchen Help | `KH_01` – `KH_04` | 360 – 720 |
| Safety & Security | `SS_01` – `SS_04` | 360 – 720 |
| Wall & Window | `WW_01` – `WW_04` | 360 – 720 |
| Leisure | `LE_01` – `LE_04` | 360 – 720 |
| Exterior Care | `EC_01` – `EC_04` | 360 – 720 |

> Exact codes match the `Model` column in `Pop_inputs.xlsx` → `Model` sheet.

### 6.4 Record Count & Scale

| Dimension | Value |
|---|---|
| Simulations | 100 |
| Years | 8 (2027–2034) |
| Days per year | 365 or 366 |
| DCs | 4 |
| Models | 24 |
| Estimated total records | ~100 × 2,922 days × 4 DCs × 24 models ≈ 28 M |

Not all `(date, DC, model)` combinations have records — only those with demand > 0 (countries not yet entered contribute nothing until their entry year).

### 6.5 Key Statistical Properties

- `realized_units` is a **continuous float** (not rounded to integers), representing stochastic realized demand.
- Values near 0 exist for low-population non-metro segments in early market-entry years.
- Cyber Week days (7 per year) show elevated demand (~18% of annual total compressed into one week).
- Demand grows year-over-year as more countries enter and adoption rates increase.

---

## 7. Demand Conservation Invariant

At every aggregation step the following identity holds:

```
Σ sales_units(segment-level)
  = Σ city_demand(city-level)
  = Σ realized_units(DC-level)
```

This is verified automatically during execution; any deviation from 100% triggers an assertion error.

---

## 8. Key Parameters Summary

| Parameter | Value | Location in Code |
|---|---|---|
| `N_SIM` | 100 | `CONFIGURATION` block |
| `SEED` | 42 | `CONFIGURATION` block |
| `YEARS` | 2027–2034 | `CONFIGURATION` block |
| `ADOPTION_SCENARIO` | `'mp'` (most probable) | `CONFIGURATION` block |
| `BATCH_SIZE` | 10 sims per batch file | `CONFIGURATION` block |
| `CYBER_WEEK_SHARE` | 0.18 | `CONSTANTS` block |
| `CYBER_PRICE_DISCOUNT` | 0.15 | `CONSTANTS` block |
| Triangular period shares | Tri(0.5, 1.0, 1.5) | `simulate_period_shares()` |
| Triangular model shares | Tri(0.8, 1.0, 1.2) | `triangular_model_shares()` |
