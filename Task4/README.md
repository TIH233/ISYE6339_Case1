# Task 4: DC-Level Daily Demand Simulator

## Overview

This notebook generates DC-level daily realized demand from the modified OTD simulator, using population-based disaggregation to map segment-level demand to individual DCs.

## What This Does

**Pipeline:**
1. **Modified Simulation**: Runs OTD simulator saving `(country, segment)` information
2. **City Disaggregation**: Uses population proportions to split segment demand to city-level
3. **DC Mapping**: Maps cities to DCs using Task2 assignment file
4. **DC Aggregation**: Aggregates city demand to final DC-level output

**Output:** `dc_daily_demand.csv.gz` with schema:
```
(sim, date, year, euro_dc_id, model, realized_units)
```

## Configuration

- **Simulations**: 100
- **Years**: 2027-2034
- **Adoption Scenario**: 'mp' (most probable)
- **Batch Size**: 10 sims per batch

## How to Run

1. Open `DC_Demand_Simulator.ipynb` in Jupyter
2. Run all cells sequentially (Cell → Run All)
3. The notebook will:
   - Load data from Task1 and Task2
   - Run 100 simulations
   - Process and save results
   - Display validation and summary statistics

**Expected runtime**: ~30-60 minutes for 100 simulations

## Output Files

All outputs saved to `Task4/dc_output/`:

- `batch_*.csv.gz` - Intermediate segment-level simulation batches
- `dc_daily_demand.csv.gz` - **Final DC-level demand output**

## File Size Estimates

- Batch files: ~50-100 MB total (compressed)
- Final output: ~500-800 MB (compressed)

## Key Sections

1. **Setup & Configuration** - Import libraries and set parameters
2. **Core Functions** - Calendar, adoption rates, model shares, OTD conversion
3. **Data Loading** - Load population, models, DC assignments
4. **Modified Simulator** - Run simulation with geographic info preserved
5. **Disaggregation** - Split segment demand to cities using population weights
6. **DC Aggregation** - Combine city demand by assigned DC
7. **Validation** - Sanity checks and statistics
8. **Summary** - Final output verification

## Data Dependencies

**From Task1:**
- `BotWorld_inputs.xlsx` (Metro, NonMetro, Model sheets)

**From Task2:**
- `assignment_with_otd_prob_reachable.csv` (City-DC assignments with OTD)

## Validation Checks

The notebook performs automatic validation:
- ✓ Simulation count (100)
- ✓ Year coverage (2027-2034)
- ✓ Model count (24)
- ✓ Demand conservation (segment → city → DC)
- ✓ No null values
- ✓ Date range consistency

## Mathematical Approach

**Why population-based disaggregation works:**

The simulator aggregates city demand to segment level:
```
segment_demand = Σ(city_pop × adoption_rate) for all cities in segment
```

Since `adoption_rate` is uniform within `(country, year)`, we can reverse this:
```
city_demand = segment_demand × (city_pop / segment_pop)
```

This exactly recovers the original city-level distribution.

## Next Steps

After successful run:
1. Load `dc_daily_demand.csv.gz` for analysis
2. Use for:
   - DC capacity planning
   - Inventory optimization
   - Transportation planning
   - Network design validation

## Troubleshooting

**Memory issues:**
- Reduce `N_SIM` from 100 to 50
- Decrease `BATCH_SIZE` from 10 to 5

**Missing data errors:**
- Verify Task1/BotWorld_inputs.xlsx exists
- Verify Task2/assignment_with_otd_prob_reachable.csv exists

**Runtime too long:**
- Run on a subset of years first (e.g., [2027, 2028])
- Reduce simulations for testing

## Contact

For questions or issues, refer to the main case documentation or contact the project team.
