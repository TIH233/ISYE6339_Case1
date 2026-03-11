"""
config.py — All constants for Task 5 PI supply chain network model.
Source: PLAN.md §8 (Appendix B confirmed) + case PDF pp.11-13.
"""

# ---------------------------------------------------------------------------
# PI packaging & handling costs (per unit)
# ---------------------------------------------------------------------------
PI_PACK_COST_EUR        = 2.0     # replaces NON_PI_PACK_COST_EUR = 15
TRANSLOAD_COST_EUR      = 1.5     # per unit per transload center (Sav + Rot = 3.0 total)
HUB_RELAY_COST_EUR      = 0.20    # per unit per relay-only hub visited
HUB_CONSOL_COST_EUR     = 0.40    # per unit per consolidation hub visited

# Hub dwell times (hours)
HUB_RELAY_DWELL_HR      = 1.0
HUB_CONSOL_DWELL_HR     = 2.0

# ---------------------------------------------------------------------------
# Last-mile costs (EUR per unit, from hub to end customer)
# Identical between PI and non-PI scenarios
# ---------------------------------------------------------------------------
LASTMILE_METRO_1M_EUR           = 8
LASTMILE_METRO_250K_EUR         = 10
LASTMILE_METRO_SMALL_EUR        = 12
LASTMILE_NONMETRO_250KM_EUR     = 14
LASTMILE_NONMETRO_500KM_EUR     = 18
LASTMILE_NONMETRO_BEYOND_EUR    = 24

# ---------------------------------------------------------------------------
# DC operating costs
# ---------------------------------------------------------------------------
DC_STORAGE_EUR          = 110       # per pallet-position per year
DC_THROUGHPUT_EUR       = 25        # per max-daily-pallet-throughput per year
DC_INBOUND_PALLET_EUR   = 4
DC_OUTBOUND_PALLET_EUR  = 5
DC_UNIT_PICK_EUR        = 3
DC_FIXED_EUR_YEAR       = 600_000   # per Euro DC per year

# ---------------------------------------------------------------------------
# Transport rates (EUR/km, contracted)
# ---------------------------------------------------------------------------
TRUCK_S_EUR_KM  = 0.45
TRUCK_M_EUR_KM  = 0.75
TRUCK_L_EUR_KM  = 1.15

# Ocean freight (6m container, median)
OCEAN_CONTAINER_USD     = 2500
USD_TO_EUR              = 0.92          # approximate 2026 exchange rate
OCEAN_CONTAINER_EUR     = OCEAN_CONTAINER_USD * USD_TO_EUR

# Rotterdam–Savannah ocean leg distance (km, approximate great-circle)
OCEAN_SAVANNAH_ROTTERDAM_KM = 8_100

# ---------------------------------------------------------------------------
# Carbon emission factors (kg CO2 per km)
# Source: EEA Road Transport Emission Inventory (EU average)
# ---------------------------------------------------------------------------
CO2_TRUCK_L_KG_KM   = 0.62     # heavy goods vehicle (>26t), type L
CO2_TRUCK_M_KG_KM   = 0.41     # medium goods vehicle (12-26t), type M
CO2_TRUCK_S_KG_KM   = 0.20     # light van (<12t), type S
CO2_OCEAN_KG_KM_TEU = 0.021    # ocean freight per TEU-km (IMO/EEA)

# ---------------------------------------------------------------------------
# Product / p-pack dimensions  (Task 5.2)
# BotWorld bot: large consumer robot, ~size of small appliance
# ---------------------------------------------------------------------------
NON_PI_PACK_COST_EUR        = 15.0     # standard box packaging cost/unit
BOT_NONPI_VOL_CM3           = 288_000  # 80 × 60 × 60 cm rigid box
BOT_PI_PACK_VOL_CM3         = 172_800  # 72 × 60 × 40 cm p-pack (40% vol reduction)
PALLET_FOOTPRINT_CM2        = 9_600    # 120 × 80 cm EU standard pallet
PALLET_USEFUL_HEIGHT_CM     = 180      # usable stacking height
NONPI_PALLET_UTIL           = 0.60     # rigid-box fill efficiency
PI_PALLET_UTIL              = 0.85     # p-pack flexible-fill efficiency
UNITS_PER_PALLET_NONPI      = 4        # confirmed: 4 large bots / pallet (non-PI)
UNITS_PER_PALLET_PI         = 6        # computed from vol + packing: ~6 / pallet

# Container (TEU = 6m × 2.4m × 2.6m ≈ 37.4 m³ usable)
CONTAINER_VOL_CM3           = 37_400_000
UNITS_PER_TEU_NONPI         = int(CONTAINER_VOL_CM3 * NONPI_PALLET_UTIL / BOT_NONPI_VOL_CM3)
UNITS_PER_TEU_PI            = int(CONTAINER_VOL_CM3 * PI_PALLET_UTIL  / BOT_PI_PACK_VOL_CM3)

# ---------------------------------------------------------------------------
# Revenue reference (from Task2 assignment data)
# ---------------------------------------------------------------------------
REVENUE_PER_UNIT_EUR    = 453.60   # observed: revenue / units = €453.60 across all segments

# ---------------------------------------------------------------------------
# Simulation parameters
# ---------------------------------------------------------------------------
DRIVE_SPEED_SIGMA_FRAC  = 0.10      # speed uncertainty: ±10% (congestion model)
DWELL_UNCERTAINTY_FRAC  = 0.25      # hub dwell uncertainty: ±25%
DEFAULT_N_SIM           = 1_000     # default Monte Carlo sample size
RANDOM_SEED             = 42

# ---------------------------------------------------------------------------
# Route geometry constants
# ---------------------------------------------------------------------------
DETOUR_FACTOR           = 1.2     # road vs straight-line
DRIVE_SPEED_KMH         = 100     # avg truck speed
MAX_SINGLE_DRIVER_HR    = 11      # relay required above this
DETOUR_RATIO_MAX        = 1.35    # max allowed routed_km / direct_km

# DC→PERI_URBAN_HUB lane routing thresholds
DC_HUB_DIRECT_MAX_HR    = 4       # drive_time ≤ 4hr → direct lane
DC_HUB_RELAY_MAX_HR     = 10      # 4–10hr → via border relay; >10hr → via DC-DC

# Border relay hub derivation thresholds
BORDER_RELAY_MAX_DIST_KM    = 300   # max distance from midpoint to each country centroid
BORDER_RELAY_MERGE_KM       = 80    # merge with peri-urban hub if within this distance
DC_TO_BORDER_RELAY_MAX_KM   = 1000  # max DC → border relay lane distance
BORDER_RELAY_TO_HUB_MAX_KM  = 300   # max border relay → peri-urban hub distance
HUB_CORRIDOR_MAX_KM         = 300   # max hub↔hub corridor distance

# ---------------------------------------------------------------------------
# Demand / cyber week
# ---------------------------------------------------------------------------
CYBER_WEEK_ANNUAL_SHARE = 0.15
CYBER_WEEK_DAYS         = 5
UNITS_PER_PALLET        = 4       # TBD from Task 5.2 product dimension analysis

# DC throughput sizing formula
PEAK_DAILY_SHARE = CYBER_WEEK_ANNUAL_SHARE / CYBER_WEEK_DAYS   # = 0.03

# DC-DC stress transfer thresholds
DC_STRESS_TRIGGER       = 1.30    # weekly demand > 1.30× median → stress
DC_SLACK_THRESHOLD      = 0.85    # receiving DC demand < 0.85× its median → has slack
DC_TRANSFER_SHARE       = 0.10    # transfer ≤ 10% of excess
DC_ANNUAL_CAP_SHARE     = 0.10    # cap: ≤ 10% of DC annual throughput

# ---------------------------------------------------------------------------
# Yearly country opening schedule (BotWorld roadmap)
# ---------------------------------------------------------------------------
COUNTRY_OPEN_SCHEDULE: dict[int, list[str]] = {
    2027: ["BE", "DE", "LU", "NL"],
    2028: ["DK", "EE", "FI", "LV", "LT", "NO", "PL", "SE"],
    2029: ["AT", "FR", "IE", "IT", "PT", "ES", "CH"],
    2030: ["BG", "HR", "CY", "CZ", "GR", "HU", "MT", "RO", "SK", "SI"],
}

def get_open_countries(year: int) -> list[str]:
    """Return cumulative list of open countries up to and including `year`."""
    countries: list[str] = []
    for y in sorted(COUNTRY_OPEN_SCHEDULE):
        if y <= year:
            countries.extend(COUNTRY_OPEN_SCHEDULE[y])
    return countries

# ---------------------------------------------------------------------------
# Country code ↔ name mapping
# Handles aliases (Czech Republic / Czechia both → CZ)
# ---------------------------------------------------------------------------
COUNTRY_CODE_TO_NAME: dict[str, str] = {
    "AT": "Austria",
    "BE": "Belgium",
    "BG": "Bulgaria",
    "CH": "Switzerland",
    "CY": "Cyprus",
    "CZ": "Czechia",
    "DE": "Germany",
    "DK": "Denmark",
    "EE": "Estonia",
    "ES": "Spain",
    "FI": "Finland",
    "FR": "France",
    "GR": "Greece",
    "HR": "Croatia",
    "HU": "Hungary",
    "IE": "Ireland",
    "IT": "Italy",
    "LT": "Lithuania",
    "LU": "Luxembourg",
    "LV": "Latvia",
    "MT": "Malta",
    "NL": "Netherlands",
    "NO": "Norway",
    "PL": "Poland",
    "PT": "Portugal",
    "RO": "Romania",
    "SE": "Sweden",
    "SI": "Slovenia",
    "SK": "Slovakia",
}

# Alias map: country names that appear in source data but differ from canonical
COUNTRY_NAME_ALIASES: dict[str, str] = {
    "Czech Republic": "CZ",   # metro sheet uses this name
    "Czechia": "CZ",
}

# Invert for name → code (apply aliases first)
COUNTRY_NAME_TO_CODE: dict[str, str] = {v: k for k, v in COUNTRY_CODE_TO_NAME.items()}
COUNTRY_NAME_TO_CODE.update(COUNTRY_NAME_ALIASES)

# ---------------------------------------------------------------------------
# European country adjacency (undirected; used for border relay derivation)
# Only pairs that share a meaningful land corridor are included.
# ---------------------------------------------------------------------------
COUNTRY_ADJACENCY: list[tuple[str, str]] = [
    # Benelux + Germany core
    ("BE", "DE"), ("BE", "FR"), ("BE", "LU"), ("BE", "NL"),
    ("DE", "LU"), ("DE", "NL"), ("DE", "FR"), ("DE", "AT"),
    ("DE", "CH"), ("DE", "CZ"), ("DE", "PL"), ("DE", "DK"),
    # France neighbours
    ("FR", "LU"), ("FR", "CH"), ("FR", "IT"), ("FR", "ES"),
    # DACH + Alpine
    ("AT", "CH"), ("AT", "IT"), ("AT", "SI"), ("AT", "HU"),
    ("AT", "CZ"), ("AT", "SK"),
    ("CH", "IT"),
    # Iberia
    ("PT", "ES"),
    # Italy + Balkans
    ("IT", "SI"),
    ("SI", "HR"), ("SI", "HU"),
    ("HR", "HU"),
    # Central-Eastern Europe
    ("HU", "SK"), ("HU", "RO"),
    ("SK", "CZ"), ("SK", "PL"),
    ("CZ", "PL"),
    ("PL", "LT"), ("PL", "LV"),  # Baltic corridor
    # Balkans / Southeast
    ("RO", "BG"), ("RO", "HU"),
    ("BG", "GR"),
    ("HR", "BG"),   # via corridor
    # Nordics / Baltic
    ("NO", "SE"), ("SE", "FI"), ("SE", "DK"),
    ("DK", "DE"),
    ("LT", "LV"), ("LT", "EE"),
    ("LV", "EE"),
    # Note: CY, MT, IE are islands — no land-border relay hubs
]

# ---------------------------------------------------------------------------
# PI OTD conversion rates (for demand_generator.py reference)
# ---------------------------------------------------------------------------
PI_OTD_BY_SEGMENT: dict[str, dict] = {
    "metro_1m+":        {"promise_hr": 4,  "purchase_prob": 1.00},
    "metro_250k-1m":    {"promise_hr": 2,  "purchase_prob": 1.00},
    "metro_<250k":      {"promise_hr": 1,  "purchase_prob": 1.00},
    "nonmetro_<=250km": {"promise_hr": 8,  "purchase_prob": 0.99},
    "nonmetro_<=500km": {"promise_hr": 16, "purchase_prob": 0.99},
    "nonmetro_>500km":  {"promise_hr": 32, "purchase_prob": 0.99},
}
