"""
preprocess.py — Build nodes_master.csv and data_issue_log.csv.

Node taxonomy (PLAN.md §1):
  PORT          : 1   Rotterdam (split from metro sheet)
  DC            : 4   from dc_open_plan.csv
  PERI_URBAN_HUB: 272 metro sheet minus DC cities; Rotterdam kept as hub too
  RELAY_HUB     : derived algorithmically in hub_network.py
  DEMAND_NONMETRO : 28/29  non_metro_hub sheet

This module handles data fixes and writes the base node table.
Relay hubs are added later by hub_network.py.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from .config import COUNTRY_NAME_TO_CODE, COUNTRY_CODE_TO_NAME, COUNTRY_OPEN_SCHEDULE
from .data_loader import load_metro_sheet, load_nonmetro_sheet, load_dc_open_plan

OUTPUT_DIR = Path(__file__).resolve().parent.parent / "data"

# DC cities that appear in metro list — keep only as DC type
_DC_CITY_SLUGS = {"koeln", "lodz", "madrid", "rome"}


def _city_slug(city: str) -> str:
    """Normalise city name to lowercase slug for matching."""
    return (
        city.lower()
        .strip()
        .replace(" ", "_")
        .replace("-", "_")
        .replace("(", "")
        .replace(")", "")
        .replace(",", "")
        .replace("'", "")
    )


def _pop_bracket(pop: float) -> str:
    if pop >= 1_000_000:
        return "1M+"
    elif pop >= 250_000:
        return "250K-1M"
    else:
        return "<250K"


def _country_open_year(country_code: str) -> int | None:
    """Return the year when a country first opens in the BotWorld roadmap."""
    for year, codes in COUNTRY_OPEN_SCHEDULE.items():
        if country_code in codes:
            return year
    return None


def build_nodes_master() -> tuple[pd.DataFrame, list[dict]]:
    """
    Build nodes_master DataFrame and return (df, issue_log_records).

    Output columns:
      node_id, node_type, country, city, lat, lng,
      pop_2026, pop_bracket, first_open_year
    """
    issues: list[dict] = []
    metro = load_metro_sheet()
    nonmetro = load_nonmetro_sheet()
    dc_plan = load_dc_open_plan()

    # ---- Log known data fixes ----
    issues.append({
        "source": "Metro cities_location", "field": "ing",
        "issue": "Typo for lng column header",
        "fix": "Renamed to 'lng' on read in data_loader.py",
        "impact": "Longitude coordinates correctly parsed for all 273 metro cities",
    })
    issues.append({
        "source": "Metro cities_location", "field": "Countries",
        "issue": "NaN rows (run-down / merged-cell pattern)",
        "fix": "Forward-fill applied on read in data_loader.py",
        "impact": "Country assignment correct for all 273 metro cities",
    })
    issues.append({
        "source": "Metro cities_location", "field": "Czech Republic",
        "issue": "Metro sheet uses 'Czech Republic'; config uses 'Czechia' / ISO code CZ",
        "fix": "Added alias 'Czech Republic' → 'CZ' in COUNTRY_NAME_TO_CODE",
        "impact": "CZ metro cities correctly tagged; no orphan nodes",
    })

    nodes: list[dict] = []

    # ------------------------------------------------------------------
    # 1) PORT node — Rotterdam
    # ------------------------------------------------------------------
    rot_mask = metro["Metropolitan cities"].str.lower().str.strip() == "rotterdam"
    rot_row = metro[rot_mask].iloc[0]
    nodes.append({
        "node_id": "PORT_NL_rotterdam",
        "node_type": "PORT",
        "country": "NL",
        "city": "Rotterdam",
        "lat": rot_row["lat"],
        "lng": rot_row["lng"],
        "pop_2026": np.nan,
        "pop_bracket": np.nan,
        "first_open_year": 2027,   # port always open from network launch
    })
    issues.append({
        "source": "Metro cities_location", "field": "Rotterdam",
        "issue": "Rotterdam appears in metro list AND is needed as the ocean PORT entry node",
        "fix": "Split: PORT_NL_rotterdam (type=PORT) + METRO_NL_rotterdam (type=PERI_URBAN_HUB)",
        "impact": "Two nodes for Rotterdam; port has no demand, hub has pop=1.03M",
    })

    # ------------------------------------------------------------------
    # 2) DC nodes
    # ------------------------------------------------------------------
    dc_city_slugs = set(dc_plan["city"].str.lower().str.strip())
    for _, row in dc_plan.iterrows():
        nodes.append({
            "node_id": row["cand_id"],
            "node_type": "DC",
            "country": row["cca2"],
            "city": row["city"],
            "lat": row["lat"],
            "lng": row["lng"],
            "pop_2026": np.nan,
            "pop_bracket": np.nan,
            "first_open_year": int(row["first_open_year"]),
        })
    issues.append({
        "source": "Metro cities_location", "field": "DC cities",
        "issue": "Koeln, Lodz, Madrid, Rome appear in metro list but also are DC locations",
        "fix": "These cities kept only as type=DC; excluded from PERI_URBAN_HUB creation",
        "impact": "No duplicate node_ids; DC nodes serve hub role implicitly",
    })

    # ------------------------------------------------------------------
    # 3) PERI_URBAN_HUB nodes (metro sheet, skip DC cities)
    # ------------------------------------------------------------------
    for _, row in metro.iterrows():
        city_lower = _city_slug(row["Metropolitan cities"])
        # Skip cities that are DC locations
        if city_lower in dc_city_slugs:
            continue
        country_name = row["Countries"]
        code = COUNTRY_NAME_TO_CODE.get(country_name)
        if code is None:
            # Fallback: first 2 chars uppercased (logs warning implicitly)
            code = country_name[:2].upper()
            issues.append({
                "source": "Metro cities_location", "field": "Countries",
                "issue": f"Unmapped country name '{country_name}'",
                "fix": f"Used fallback code '{code}'",
                "impact": "May affect country-year schedule lookup for this city",
            })

        node_id = f"METRO_{code}_{city_lower}"
        open_year = _country_open_year(code)

        nodes.append({
            "node_id": node_id,
            "node_type": "PERI_URBAN_HUB",
            "country": code,
            "city": row["Metropolitan cities"],
            "lat": float(row["lat"]),
            "lng": float(row["lng"]),
            "pop_2026": float(row["Pop_2026"]),
            "pop_bracket": _pop_bracket(float(row["Pop_2026"])),
            "first_open_year": open_year,
        })

    # ------------------------------------------------------------------
    # 4) DEMAND_NONMETRO nodes (one per country, demand centroid only)
    # ------------------------------------------------------------------
    for _, row in nonmetro.iterrows():
        country_name = row["country"]
        code = COUNTRY_NAME_TO_CODE.get(country_name)
        if code is None:
            code = country_name[:2].upper()
        open_year = _country_open_year(code)
        nodes.append({
            "node_id": f"NONMETRO_{code}",
            "node_type": "DEMAND_NONMETRO",
            "country": code,
            "city": f"{country_name} (non-metro centroid)",
            "lat": float(row["lat"]),
            "lng": float(row["lng"]),
            "pop_2026": np.nan,
            "pop_bracket": np.nan,
            "first_open_year": open_year,
        })

    df = pd.DataFrame(nodes)
    return df, issues


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_preprocess(output_dir: Path = OUTPUT_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Build nodes_master and data_issue_log; write both to output_dir.
    Returns (nodes_master_df, issue_log_df).
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    nodes, issues = build_nodes_master()
    nodes.to_csv(output_dir / "nodes_master.csv", index=False)

    issue_df = pd.DataFrame(issues)
    issue_df.to_csv(output_dir / "data_issue_log.csv", index=False)

    print(f"nodes_master: {len(nodes)} rows saved to {output_dir / 'nodes_master.csv'}")
    print(f"  {nodes['node_type'].value_counts().to_dict()}")
    print(f"data_issue_log: {len(issues)} entries")

    return nodes, issue_df
