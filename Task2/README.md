# Task2: BotWorld Europe Demand Simulator

## Overview

This simulator models customer demand for BotWorld's consumer vacuum (CV) products across 15 European countries from 2027-2034. It incorporates market adoption dynamics, seasonal patterns, order-to-delivery (OTD) performance, and product portfolio mix to generate realistic demand scenarios for supply chain planning.

**Key Features:**
- **Deterministic adoption scenarios** (Pessimistic, Most-Probable, Optimistic)
- **Geographic segmentation** (Metro cities vs Non-metro regions)
- **Temporal resolution** (Daily demand with 13 periods + Cyber Week)
- **OTD conversion modeling** (Segment-specific delivery performance impact)
- **Product portfolio decomposition** (24 SKUs with stochastic share allocation)
- **Memory-efficient batch processing** (Handles 100+ simulations with limited RAM)

---

## Recent Updates (Feb 2026)

### Adoption Rate Refactoring ✓

**Previous behavior:** Adoption rates were drawn from a triangular distribution per (simulation, year), introducing randomness across replications.

**Current behavior:** Adoption is now **deterministic within each scenario**:
- Select one scenario: `'pes'` (pessimistic), `'mp'` (most-probable), or `'opt'` (optimistic)
- Adoption rates are fixed by market year within that scenario
- Variability across simulations now comes solely from:
  - Period share randomness (Normal distribution)
  - Model share randomness (Triangular distribution)
  - Not from adoption rate sampling

**Impact:**
- Results are fully reproducible for a given scenario + seed
- Reduced across-simulation variance in annual demand
- Scenario comparison is now meaningful (no adoption noise)

See [ADOPTION_SCENARIO_REFACTOR_REPORT.md](ADOPTION_SCENARIO_REFACTOR_REPORT.md) for technical details.

---

## Project Structure

```
Task2/
├── Simulator.ipynb                              # Main notebook
├── README.md                                     # This file
├── ADOPTION_SCENARIO_REFACTOR_REPORT.md         # Technical refactoring documentation
├── task2 input.xlsx                              # Primary input data
├── nodes.csv                                     # Geographic nodes
├── assignment_by_year_active.csv                 # City-DC assignments
├── assignment_with_otd_prob_reachable.csv        # OTD probability data
├── dc_selected_final.csv                         # Selected distribution centers
└── time_matrix.csv                               # Travel time matrix
```

**Output files** (generated in `../Task3/sim_batches/`):
- `batch_00.csv.gz`, `batch_01.csv.gz`, ..., `batch_19.csv.gz` — Daily demand by (sim, date, model)
- `annual_summary.csv.gz` — Annual aggregates by simulation
- `segment_summary.csv.gz` — Annual aggregates by (simulation, segment)

---

## Quick Start

### 1. Prerequisites
- Python 3.8+
- Jupyter Notebook/Lab
- Required packages: `pandas`, `numpy`, `openpyxl`, `matplotlib`

### 2. Configuration

Open `Simulator.ipynb` and locate **Cell 20** to configure the run:

```python
SIM_OUT_DIR = '../Task3/sim_batches'      # Output directory
N_SIM       = 100                         # Number of Monte Carlo simulations
BATCH_SIZE  = 5                           # Simulations per batch (memory management)
ADOPTION_SCENARIO = 'mp'                  # Adoption scenario: 'pes' | 'mp' | 'opt'
```

**Adoption Scenarios:**
- `'pes'` — Pessimistic adoption trajectory (conservative market growth)
- `'mp'` — Most-probable adoption trajectory (baseline forecast)
- `'opt'` — Optimistic adoption trajectory (aggressive market penetration)

### 3. Run the Simulator

Execute all cells sequentially in `Simulator.ipynb`:
1. **Cells 1-13:** Data loading, parameter configuration, helper functions
2. **Cell 14:** Stochastic helper functions (adoption, model shares, period shares)
3. **Cells 15-16:** Core simulator definition
4. **Cell 20:** Run configuration and execution
5. **Cells 21+:** Results aggregation and validation

**Expected runtime:** ~15-30 minutes for 100 simulations (hardware-dependent)

### 4. Outputs

After execution, outputs are written to `../Task3/sim_batches/`:
- **Batch files:** `batch_{i:02d}.csv.gz` (i = 0 to N_BATCHES-1)
  - Format: `(sim, date, model, sales_units)`
  - Compressed CSV for efficient storage
- **Annual summary:** Aggregated demand/sales/revenue by (sim, year)
- **Segment summary:** Aggregated metrics by (sim, year, segment)

---

## Configuration Parameters

### Market Entry Schedule
Countries are grouped by entry year (defined in **Cell 6**):

| Entry Year | Countries |
|------------|-----------|
| **2027** | Belgium, Germany, Luxembourg, Netherlands |
| **2028** | Denmark, Estonia, Finland, Latvia, Lithuania, Norway, Poland, Sweden |
| **2029** | Croatia, Ireland, Switzerland |

### Temporal Parameters (**Cell 7**)
- **Simulation period:** 2027-2034 (8 years)
- **13 periods per year** + 1 Cyber Week (Period 10, 7 days in November)
- **Day-of-week weights:** Monday-Sunday [0.12, 0.12, 0.23, 0.25, 0.15, 0.10, 0.03]
- **Cyber Week share:** 15% of annual demand
- **Cyber Week discount:** 15% price reduction

### Adoption Rate Functions (**Cells 11-12**)
Three scenario trajectories by market year:
- `adoption_rate_pes(market_year)` — Pessimistic
- `adoption_rate_mp(market_year)` — Most-probable
- `adoption_rate_opt(market_year)` — Optimistic

Example: Germany enters in 2027, so:
- Year 2027 → market_year = 1
- Year 2028 → market_year = 2
- ...

### Stochastic Variability
1. **Period shares:** Normal distribution with CV = 25% around base shares
2. **Model shares:** Triangular distribution with ±20% spread around MP shares
3. **Adoption rates:** NO randomness (fixed by scenario)

### OTD Conversion Model (**Cell 13**)
Segment-specific conversion rates based on delivery days:

| Segment | OTD Range | Conversion Function |
|---------|-----------|---------------------|
| Metro | 2-3 days typical | Piecewise linear (high sensitivity) |
| Non-Metro | 4-5 days typical | Piecewise linear (moderate sensitivity) |

Faster delivery → higher conversion (customers complete purchase vs abandon cart).

---

## Implementation Details

### Demand Generation Pipeline

The simulator follows a 7-step hierarchical decomposition:

```
Annual Adoption (by country-segment)
    ↓
Period Allocation (13 periods + Cyber Week)
    ↓
Daily Allocation (day-of-week weights)
    ↓
Segment Weighting (Metro / Non-Metro)
    ↓
OTD Conversion (aggregate demand → sales)
    ↓
Model Decomposition (24 SKUs)
    ↓
Revenue Calculation (with Cyber Week discount)
```

**Key Design Choice:** OTD conversion is applied at **aggregate level** (before model split) to avoid computational explosion and maintain realistic correlation across SKUs.

### Memory-Efficient Batching

For large simulation runs (N_SIM > 50), the notebook uses batched flushing:
- Accumulate records for `BATCH_SIZE` simulations
- Aggregate to (sim, date, model) level
- Write compressed CSV to disk
- Clear memory and continue
- At the end, return only tiny annual/segment summaries

This enables 100+ simulations on consumer-grade hardware (8-16 GB RAM).

### Random Seed Management

- **Global seed:** Set via `seed=42` parameter in `run_otd_simulator()`
- **Per-simulation seeds:** Derived deterministically from global seed
- **Per-year seeds:** Year-specific + simulation-specific for model shares
- **Result:** Full reproducibility for any given configuration

---

## Validation Checks

The notebook includes several validation cells:
1. **Country coverage:** All entry map countries have OTD data
2. **City-DC assignments:** All metro cities have valid DC assignments
3. **Annual demand ordering:** `demand(opt) >= demand(mp) >= demand(pes)` at each year
4. **Conversion rate sanity:** Metro conversion > Non-Metro for same OTD
5. **Revenue totals:** Match expected order of magnitude (~€100M-€1B range)

---

## Input Data Files

### `task2 input.xlsx`
- **Countries sheet:** Overall population, growth rates
- **Metro Cities sheet:** City-level 2026 populations
- **24 Models sheet:** SKU codes, prices, market share (MP scenario)

### `assignment_by_year_active.csv`
City-to-DC assignments by year (determines which DCs serve each metro city).

### `assignment_with_otd_prob_reachable.csv`
OTD probability distributions by city-DC pair (used for conversion rate modeling).

### `nodes.csv`
Geographic nodes (cities + DCs) with coordinates and metadata.

### `time_matrix.csv`
Travel time matrix between all nodes (used for OTD calculation).

---

## Troubleshooting

### Issue: `ValueError: adoption_scenario must be one of {'pes','mp','opt'}`
**Solution:** Check Cell 20 — `ADOPTION_SCENARIO` must be exactly `'pes'`, `'mp'`, or `'opt'` (case-insensitive).

### Issue: Out-of-memory errors
**Solutions:**
1. Reduce `N_SIM` (try 50 instead of 100)
2. Decrease `BATCH_SIZE` (try 3 or 2)
3. Close other memory-intensive applications

### Issue: Batch files not written
**Solution:** Check that `SIM_OUT_DIR` path exists or can be created. The simulator creates directories automatically but requires write permissions.

### Issue: Results vary across runs with same seed
**Possible causes:**
1. `adoption_scenario` was changed between runs
2. Input data files were modified
3. Notebook cells were executed out of order

**Solution:** Restart kernel and run all cells sequentially from top to bottom.

---

## Scenario Comparison Workflow

To compare all three adoption scenarios:

1. **Run 'mp' scenario:**
   ```python
   ADOPTION_SCENARIO = 'mp'
   ```
   Execute Cell 20 → outputs to `../Task3/sim_batches/`

2. **Rename output folder:**
   ```bash
   mv ../Task3/sim_batches ../Task3/sim_batches_mp
   ```

3. **Run 'pes' scenario:**
   ```python
   ADOPTION_SCENARIO = 'pes'
   ```
   Execute Cell 20 → outputs to `../Task3/sim_batches/`

4. **Rename output folder:**
   ```bash
   mv ../Task3/sim_batches ../Task3/sim_batches_pes
   ```

5. **Run 'opt' scenario:**
   ```python
   ADOPTION_SCENARIO = 'opt'
   ```
   Execute Cell 20 → outputs to `../Task3/sim_batches/`

6. **Rename output folder:**
   ```bash
   mv ../Task3/sim_batches ../Task3/sim_batches_opt
   ```

7. **Compare results:** Load all three `annual_summary.csv.gz` files and visualize demand trajectories.

---

## Contact & Support

For questions about:
- **Adoption scenario logic:** See [ADOPTION_SCENARIO_REFACTOR_REPORT.md](ADOPTION_SCENARIO_REFACTOR_REPORT.md)
- **OTD conversion modeling:** Review Cell 13 and OTD validation cells
- **Data sources:** Refer to `task2 input.xlsx` metadata tabs
- **Task3 integration:** See Task3 production feasibility simulator

---

## Change Log

| Date | Version | Changes |
|------|---------|---------|
| Feb 26, 2026 | 2.0 | Refactored adoption mechanism to deterministic scenario-based approach |
| Feb 25, 2026 | 1.5 | Added memory-efficient batch processing for 100+ simulations |
| Feb 22, 2026 | 1.0 | Initial simulator implementation with stochastic adoption |

---

**License:** Internal use for ISYE 6339 course project
**Last updated:** February 26, 2026
