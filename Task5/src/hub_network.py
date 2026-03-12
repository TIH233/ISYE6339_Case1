"""
hub_network.py — Hub activation, border relay derivation, and lane generation.

Implements PLAN.md §3 (Hub Activation) and §4 (Lane Generation).
Numpy-first for geometry: pandas-in → numpy-compute → pandas-out.
"""

from __future__ import annotations

import heapq
import numpy as np
import pandas as pd
from pathlib import Path

from .config import (
    COUNTRY_ADJACENCY,
    COUNTRY_NAME_TO_CODE,
    COUNTRY_OPEN_SCHEDULE,
    DETOUR_FACTOR,
    DRIVE_SPEED_KMH,
    MAX_SINGLE_DRIVER_HR,
    DETOUR_RATIO_MAX,
    DC_HUB_DIRECT_MAX_HR,
    DC_HUB_RELAY_MAX_HR,
    BORDER_RELAY_MAX_DIST_KM,
    BORDER_RELAY_MERGE_KM,
    DC_TO_BORDER_RELAY_MAX_KM,
    BORDER_RELAY_TO_HUB_MAX_KM,
    HUB_CORRIDOR_MAX_KM,
    HUB_RELAY_DWELL_HR,
    HUB_CONSOL_DWELL_HR,
    TRUCK_L_EUR_KM,
    TRUCK_M_EUR_KM,
    get_open_countries,
)

# ---------------------------------------------------------------------------
# Geometry helpers (numpy-vectorized)
# ---------------------------------------------------------------------------

_R_KM = 6371.0  # Earth radius in km


def haversine_km(
    lat1: np.ndarray, lng1: np.ndarray,
    lat2: np.ndarray, lng2: np.ndarray,
) -> np.ndarray:
    """
    Vectorized Haversine distance in km.
    All inputs in decimal degrees; shapes must be broadcastable.
    """
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlng / 2) ** 2
    return 2 * _R_KM * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def drive_time_hr(haversine: np.ndarray) -> np.ndarray:
    """Road drive time in hours from haversine distance."""
    return haversine * DETOUR_FACTOR / DRIVE_SPEED_KMH


def elapsed_hr(hav_km: np.ndarray, dwell_hr: float) -> np.ndarray:
    """Total elapsed time = drive_time + dwell at destination."""
    return drive_time_hr(hav_km) + dwell_hr


def detour_ratio(routed_km: np.ndarray, direct_km: np.ndarray) -> np.ndarray:
    return np.where(direct_km > 0, routed_km / direct_km, np.inf)


# ---------------------------------------------------------------------------
# Hub activation
# ---------------------------------------------------------------------------

def activate_hubs(nodes: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Return subset of nodes active in `year`.
    Rules:
      - PORT: always active (first_open_year = 2027)
      - DC: active if first_open_year <= year
      - PERI_URBAN_HUB: active if node's country is in open countries for year
      - DEMAND_NONMETRO: active if country is open
      - RELAY_HUB / BORDER_RELAY_HUB: active if first_open_year <= year
    """
    open_countries = set(get_open_countries(year))

    mask = (
        ((nodes["node_type"] == "PORT") & (nodes["first_open_year"] <= year))
        | ((nodes["node_type"] == "DC") & (nodes["first_open_year"] <= year))
        | (
            nodes["node_type"].isin(["PERI_URBAN_HUB", "DEMAND_NONMETRO"])
            & nodes["country"].isin(open_countries)
        )
        | (
            nodes["node_type"].isin(["RELAY_HUB", "BORDER_RELAY_HUB"])
            & (nodes["first_open_year"] <= year)
        )
    )
    return nodes[mask].copy()


# ---------------------------------------------------------------------------
# Border relay hub derivation (PLAN.md §3)
# ---------------------------------------------------------------------------

def _country_centroids(nonmetro_df: pd.DataFrame) -> pd.DataFrame:
    """
    Return country centroid table from the non_metro_hub sheet.
    Adds ISO2 country code column.
    """
    df = nonmetro_df.copy()
    df["country_code"] = df["country"].map(COUNTRY_NAME_TO_CODE)
    return df[["country_code", "lat", "lng"]].dropna(subset=["country_code"])


def derive_border_relay_hubs(
    open_countries: list[str],
    nonmetro_df: pd.DataFrame,
    peri_urban_nodes: pd.DataFrame,
    base_year: int,
) -> pd.DataFrame:
    """
    Derive BORDER_RELAY_HUB nodes for all adjacent country pairs that are
    both open in `open_countries`.

    Algorithm (PLAN.md §3):
      1. For each adjacent open-country pair (A, B):
         midpoint_lat = (centroid_A_lat + centroid_B_lat) / 2
         midpoint_lng = (centroid_A_lng + centroid_B_lng) / 2
      2. Keep midpoint if haversine(midpoint, centroid_A) < BORDER_RELAY_MAX_DIST_KM
                        AND haversine(midpoint, centroid_B) < BORDER_RELAY_MAX_DIST_KM
      3. If a PERI_URBAN_HUB exists within BORDER_RELAY_MERGE_KM → use that city
         as the relay hub (merge/reuse).

    Returns DataFrame with columns:
      node_id, node_type, country, city, lat, lng, pop_2026, pop_bracket,
      first_open_year, derived_from_pair
    """
    centroids = _country_centroids(nonmetro_df)
    cent_by_code = centroids.set_index("country_code")[["lat", "lng"]].to_dict("index")

    open_set = set(open_countries)
    relay_nodes: list[dict] = []
    seen_pairs: set[frozenset] = set()

    # Peri-urban hub arrays for merge check
    hub_mask = peri_urban_nodes["node_type"] == "PERI_URBAN_HUB"
    hubs = peri_urban_nodes[hub_mask][["node_id", "city", "country", "lat", "lng"]].copy()
    hub_lat = hubs["lat"].values
    hub_lng = hubs["lng"].values

    for a, b in COUNTRY_ADJACENCY:
        if a not in open_set or b not in open_set:
            continue
        pair_key = frozenset((a, b))
        if pair_key in seen_pairs:
            continue
        seen_pairs.add(pair_key)

        if a not in cent_by_code or b not in cent_by_code:
            continue

        c_a = cent_by_code[a]
        c_b = cent_by_code[b]

        mid_lat = (c_a["lat"] + c_b["lat"]) / 2.0
        mid_lng = (c_a["lng"] + c_b["lng"]) / 2.0

        # Distance checks
        d_a = haversine_km(
            np.array([mid_lat]), np.array([mid_lng]),
            np.array([c_a["lat"]]), np.array([c_a["lng"]]),
        )[0]
        d_b = haversine_km(
            np.array([mid_lat]), np.array([mid_lng]),
            np.array([c_b["lat"]]), np.array([c_b["lng"]]),
        )[0]

        if d_a >= BORDER_RELAY_MAX_DIST_KM or d_b >= BORDER_RELAY_MAX_DIST_KM:
            continue   # midpoint too far from one centroid

        # Check if any PERI_URBAN_HUB is close enough to merge
        if len(hubs) > 0:
            dists_to_hubs = haversine_km(
                np.full(len(hub_lat), mid_lat), np.full(len(hub_lng), mid_lng),
                hub_lat, hub_lng,
            )
            nearest_idx = int(np.argmin(dists_to_hubs))
            nearest_dist = dists_to_hubs[nearest_idx]

            if nearest_dist <= BORDER_RELAY_MERGE_KM:
                # Reuse existing peri-urban hub as relay
                hub_row = hubs.iloc[nearest_idx]
                relay_nodes.append({
                    "node_id": hub_row["node_id"],   # reuse existing id
                    "node_type": "BORDER_RELAY_HUB",  # will be DUAL_ROLE in practice
                    "country": f"{a}-{b}",
                    "city": hub_row["city"],
                    "lat": hub_row["lat"],
                    "lng": hub_row["lng"],
                    "pop_2026": np.nan,
                    "pop_bracket": np.nan,
                    "first_open_year": base_year,
                    "derived_from_pair": f"{a}-{b}",
                    "merged_with_hub": hub_row["node_id"],
                })
                continue

        # Create new midpoint relay hub
        node_id = f"RELAY_{a}_{b}"
        relay_nodes.append({
            "node_id": node_id,
            "node_type": "BORDER_RELAY_HUB",
            "country": f"{a}-{b}",
            "city": f"Border relay {a}-{b}",
            "lat": mid_lat,
            "lng": mid_lng,
            "pop_2026": np.nan,
            "pop_bracket": np.nan,
            "first_open_year": base_year,
            "derived_from_pair": f"{a}-{b}",
            "merged_with_hub": np.nan,
        })

    if not relay_nodes:
        return pd.DataFrame(columns=[
            "node_id", "node_type", "country", "city", "lat", "lng",
            "pop_2026", "pop_bracket", "first_open_year",
            "derived_from_pair", "merged_with_hub",
        ])
    return pd.DataFrame(relay_nodes)


# ---------------------------------------------------------------------------
# Lane generation (PLAN.md §4)
# ---------------------------------------------------------------------------

def _lane_row(
    origin_id: str, dest_id: str,
    origin_lat: float, origin_lng: float,
    dest_lat: float, dest_lng: float,
    lane_type: str,
    truck_class: str,
    relay_flag: bool,
    year: int,
    dest_node_type: str = None,  # NET-3 fix: use node type for dwell logic
    **extra,
) -> dict:
    hav = float(haversine_km(
        np.array([origin_lat]), np.array([origin_lng]),
        np.array([dest_lat]), np.array([dest_lng]),
    )[0])
    dt = float(drive_time_hr(np.array([hav]))[0])

    # NET-3 fix: Determine dwell by destination node type, not string matching
    if dest_node_type in ["DC", "PERI_URBAN_HUB"]:
        dwell = HUB_CONSOL_DWELL_HR  # Consolidation-capable hubs
    elif dest_node_type in ["RELAY_HUB", "BORDER_RELAY_HUB"]:
        dwell = HUB_RELAY_DWELL_HR   # Relay-only hubs
    elif dest_node_type == "PORT":
        dwell = HUB_CONSOL_DWELL_HR  # Ports act like consolidation hubs
    else:
        dwell = 0  # No dwell for demand nodes or unknown types

    el = dt + dwell

    cost_per_km = TRUCK_L_EUR_KM if truck_class == "L" else TRUCK_M_EUR_KM

    # NET-2 fix: Store haversine as road_km; detour is applied in time calc only
    # This allows real detour ratio computation at route level
    road_km = hav  # NOT multiplied by DETOUR_FACTOR

    row = {
        "lane_id": f"{origin_id}__{dest_id}",
        "origin_id": origin_id,
        "dest_id": dest_id,
        "lane_type": lane_type,
        "truck_class": truck_class,
        "relay_flag": relay_flag,
        "haversine_km": round(hav, 2),
        "road_km": round(road_km, 2),  # NET-2 fix: no detour factor here
        "drive_time_hr": round(dt, 3),  # Detour already in drive_time_hr
        "elapsed_hr": round(el, 3),
        "cost_per_km": cost_per_km,
        "activation_year": year,
    }
    row.update(extra)
    return row


def generate_lanes(active_nodes: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    Generate all lane candidates for the given year's active node set.

    Returns DataFrame with columns:
      lane_id, origin_id, dest_id, lane_type, truck_class, relay_flag,
      haversine_km, road_km, drive_time_hr, elapsed_hr, cost_per_km,
      activation_year, detour_ratio (where applicable)
    """
    lanes: list[dict] = []

    # Index by type for fast lookup
    by_type = {t: g for t, g in active_nodes.groupby("node_type")}

    ports   = by_type.get("PORT", pd.DataFrame())
    dcs     = by_type.get("DC", pd.DataFrame())
    hubs    = by_type.get("PERI_URBAN_HUB", pd.DataFrame())
    relay_frames = [
        frame for frame in [
            by_type.get("BORDER_RELAY_HUB", pd.DataFrame()),
            by_type.get("RELAY_HUB", pd.DataFrame()),
        ] if not frame.empty
    ]
    relays = pd.concat(relay_frames, ignore_index=True) if relay_frames else pd.DataFrame()
    # DEMAND_NONMETRO are demand sinks only — no outgoing lanes generated here

    # ------------------------------------------------------------------
    # 1) PORT → DC
    # ------------------------------------------------------------------
    for _, port in ports.iterrows():
        for _, dc in dcs.iterrows():
            row = _lane_row(
                port["node_id"], dc["node_id"],
                port["lat"], port["lng"],
                dc["lat"], dc["lng"],
                lane_type="PORT_DC",
                truck_class="L",
                relay_flag=False,
                year=year,
                dest_node_type="DC",  # NET-3 fix
            )
            lanes.append(row)

    # ------------------------------------------------------------------
    # 2) DC ↔ DC
    # ------------------------------------------------------------------
    dc_list = dcs.to_dict("records")
    for i, dc_a in enumerate(dc_list):
        for dc_b in dc_list[i + 1:]:
            hav = float(haversine_km(
                np.array([dc_a["lat"]]), np.array([dc_a["lng"]]),
                np.array([dc_b["lat"]]), np.array([dc_b["lng"]]),
            )[0])
            dt = float(drive_time_hr(np.array([hav]))[0])
            rel_flag = dt > MAX_SINGLE_DRIVER_HR

            row_fwd = _lane_row(
                dc_a["node_id"], dc_b["node_id"],
                dc_a["lat"], dc_a["lng"],
                dc_b["lat"], dc_b["lng"],
                lane_type="DC_DC",
                truck_class="L",
                relay_flag=rel_flag,
                year=year,
                dest_node_type="DC",  # NET-3 fix
            )
            row_rev = _lane_row(
                dc_b["node_id"], dc_a["node_id"],
                dc_b["lat"], dc_b["lng"],
                dc_a["lat"], dc_a["lng"],
                lane_type="DC_DC",
                truck_class="L",
                relay_flag=rel_flag,
                year=year,
                dest_node_type="DC",  # NET-3 fix
            )
            lanes += [row_fwd, row_rev]

    # ------------------------------------------------------------------
    # 3) DC → PERI_URBAN_HUB  (direct if drive_time ≤ DC_HUB_DIRECT_MAX_HR)
    # ------------------------------------------------------------------
    if len(dcs) > 0 and len(hubs) > 0:
        dc_arr = dcs[["node_id", "lat", "lng"]].values
        hub_arr = hubs[["node_id", "lat", "lng"]].values

        dc_lats = dc_arr[:, 1].astype(float)
        dc_lngs = dc_arr[:, 2].astype(float)
        hub_lats = hub_arr[:, 1].astype(float)
        hub_lngs = hub_arr[:, 2].astype(float)

        # Broadcast: (n_dc, n_hub)
        hav_matrix = haversine_km(
            dc_lats[:, None], dc_lngs[:, None],
            hub_lats[None, :], hub_lngs[None, :],
        )
        dt_matrix = drive_time_hr(hav_matrix)

        direct_i, direct_j = np.where(dt_matrix <= DC_HUB_DIRECT_MAX_HR)
        for i, j in zip(direct_i, direct_j):
            row = _lane_row(
                str(dc_arr[i, 0]), str(hub_arr[j, 0]),
                float(dc_lats[i]), float(dc_lngs[i]),
                float(hub_lats[j]), float(hub_lngs[j]),
                lane_type="DC_HUB_DIRECT",
                truck_class="M",
                relay_flag=False,
                year=year,
                dest_node_type="PERI_URBAN_HUB",  # NET-3 fix
            )
            lanes.append(row)

    # ------------------------------------------------------------------
    # 4) DC → BORDER_RELAY  (within DC_TO_BORDER_RELAY_MAX_KM, detour ≤ 1.35)
    # ------------------------------------------------------------------
    if len(dcs) > 0 and len(relays) > 0:
        rel_arr = relays[["node_id", "lat", "lng"]].values
        rel_lats = rel_arr[:, 1].astype(float)
        rel_lngs = rel_arr[:, 2].astype(float)

        for i_dc, dc_row in enumerate(dcs.itertuples()):
            hav_to_relays = haversine_km(
                np.full(len(rel_lats), dc_row.lat),
                np.full(len(rel_lngs), dc_row.lng),
                rel_lats, rel_lngs,
            )
            # NET-2 fix: Removed tautological detour check
            # Detour is evaluated on full routes, not individual legs
            eligible = np.where(hav_to_relays <= DC_TO_BORDER_RELAY_MAX_KM)[0]
            for j in eligible:
                # NET-3 fix: Look up relay node type
                relay_node_type = relays.iloc[j].get("node_type", "RELAY_HUB")
                row = _lane_row(
                    dc_row.node_id, str(rel_arr[j, 0]),
                    dc_row.lat, dc_row.lng,
                    float(rel_lats[j]), float(rel_lngs[j]),
                    lane_type="DC_RELAY",
                    truck_class="L",
                    relay_flag=True,
                    year=year,
                    dest_node_type=relay_node_type,  # NET-3 fix
                )
                lanes.append(row)

    # ------------------------------------------------------------------
    # 5) BORDER_RELAY → PERI_URBAN_HUB  (within BORDER_RELAY_TO_HUB_MAX_KM)
    # ------------------------------------------------------------------
    if len(relays) > 0 and len(hubs) > 0:
        rel_arr = relays[["node_id", "lat", "lng"]].values
        rel_lats = rel_arr[:, 1].astype(float)
        rel_lngs = rel_arr[:, 2].astype(float)

        hub_arr = hubs[["node_id", "lat", "lng"]].values
        hub_lats = hub_arr[:, 1].astype(float)
        hub_lngs = hub_arr[:, 2].astype(float)

        # (n_relay, n_hub)
        hav_rh = haversine_km(
            rel_lats[:, None], rel_lngs[:, None],
            hub_lats[None, :], hub_lngs[None, :],
        )
        r_i, h_j = np.where(hav_rh <= BORDER_RELAY_TO_HUB_MAX_KM)
        for i, j in zip(r_i, h_j):
            row = _lane_row(
                str(rel_arr[i, 0]), str(hub_arr[j, 0]),
                float(rel_lats[i]), float(rel_lngs[i]),
                float(hub_lats[j]), float(hub_lngs[j]),
                lane_type="RELAY_HUB",
                truck_class="M",
                relay_flag=False,
                year=year,
                dest_node_type="PERI_URBAN_HUB",  # NET-3 fix
            )
            lanes.append(row)

    # ------------------------------------------------------------------
    # 6) HUB ↔ HUB corridor  (≤ HUB_CORRIDOR_MAX_KM, detour ≤ 1.35)
    # ------------------------------------------------------------------
    if len(hubs) >= 2:
        hub_arr = hubs[["node_id", "lat", "lng"]].values
        hub_lats = hub_arr[:, 1].astype(float)
        hub_lngs = hub_arr[:, 2].astype(float)
        n = len(hub_arr)

        hav_hh = haversine_km(
            hub_lats[:, None], hub_lngs[:, None],
            hub_lats[None, :], hub_lngs[None, :],
        )
        # NET-2 fix: Removed tautological detour check
        # Upper triangle only (undirected, both directions added below)
        i_arr, j_arr = np.where(
            (hav_hh <= HUB_CORRIDOR_MAX_KM)
            & np.triu(np.ones((n, n), dtype=bool), k=1)
        )
        for i, j in zip(i_arr, j_arr):
            for origin_idx, dest_idx in [(i, j), (j, i)]:
                row = _lane_row(
                    str(hub_arr[origin_idx, 0]), str(hub_arr[dest_idx, 0]),
                    float(hub_lats[origin_idx]), float(hub_lngs[origin_idx]),
                    float(hub_lats[dest_idx]), float(hub_lngs[dest_idx]),
                    lane_type="HUB_CORRIDOR",
                    truck_class="M",
                    relay_flag=True,
                    year=year,
                    dest_node_type="PERI_URBAN_HUB",  # NET-3 fix
                )
                lanes.append(row)

    if not lanes:
        return pd.DataFrame()

    df = pd.DataFrame(lanes)
    # NET-2 fix: Removed tautological detour_ratio calculation
    # Detour ratio is now computed at route level in build_routes()
    return df

# ===========================================================================
# NEW FUNCTIONS: Approach A - Capability-based hub consolidation (HUB-1 fix)
# ===========================================================================

# ---------------------------------------------------------------------------
# Driving-distance-based relay hub placement (replaces border-midpoint logic)
# ---------------------------------------------------------------------------

def derive_relay_hubs_by_driving_distance(
    active_nodes: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """
    Place relay hubs based on actual driving time constraints (HUB-1 fix).
    
    Algorithm:
      1. For each DC → destination pair:
         IF drive_time > MAX_SINGLE_DRIVER_HR (11 hr):
            → Place relay hub at mid-journey point (~5.5 hr from each end)
      2. Cluster nearby relay candidates (within BORDER_RELAY_MERGE_KM)
      3. Merge with existing peri-urban hubs if within merge distance
    
    Returns DataFrame with columns:
      node_id, node_type, lat, lng, first_open_year, serves_route, is_merged, merged_with
    """
    dcs = active_nodes[active_nodes["node_type"] == "DC"].copy()
    destinations = active_nodes[active_nodes["node_type"].isin(
        ["PERI_URBAN_HUB", "DEMAND_NONMETRO"]
    )].copy()
    peri_urban_hubs = active_nodes[active_nodes["node_type"] == "PERI_URBAN_HUB"].copy()
    
    if dcs.empty or destinations.empty:
        return pd.DataFrame()
    
    relay_candidates = []
    
    # Find all DC→dest pairs that exceed single-driver limit
    for _, dc in dcs.iterrows():
        for _, dest in destinations.iterrows():
            dist_km = float(haversine_km(
                np.array([dc["lat"]]), np.array([dc["lng"]]),
                np.array([dest["lat"]]), np.array([dest["lng"]]),
            )[0])
            
            drive_hr = dist_km * DETOUR_FACTOR / DRIVE_SPEED_KMH
            
            if drive_hr > MAX_SINGLE_DRIVER_HR:  # 11 hours
                # Place relay at mid-journey
                relay_lat = (dc["lat"] + dest["lat"]) / 2
                relay_lng = (dc["lng"] + dest["lng"]) / 2
                
                relay_candidates.append({
                    "lat": relay_lat,
                    "lng": relay_lng,
                    "serves_route": f"{dc['node_id']}__{dest['node_id']}",
                    "drive_hr_segment": drive_hr / 2,
                })
    
    if not relay_candidates:
        return pd.DataFrame()
    
    # Cluster nearby candidates (avoid hub proliferation)
    relay_hubs = []
    used_candidates = set()
    
    for i, candidate in enumerate(relay_candidates):
        if i in used_candidates:
            continue
        
        # Find all candidates within clustering distance
        cluster = [candidate]
        for j, other in enumerate(relay_candidates):
            if j <= i or j in used_candidates:
                continue
            
            dist_km = float(haversine_km(
                np.array([candidate["lat"]]), np.array([candidate["lng"]]),
                np.array([other["lat"]]), np.array([other["lng"]]),
            )[0])
            
            if dist_km <= BORDER_RELAY_MERGE_KM:
                cluster.append(other)
                used_candidates.add(j)
        
        # Compute cluster centroid
        cluster_lat = np.mean([c["lat"] for c in cluster])
        cluster_lng = np.mean([c["lng"] for c in cluster])
        
        # Check if we can reuse existing peri-urban hub
        if not peri_urban_hubs.empty:
            dists_to_hubs = haversine_km(
                np.full(len(peri_urban_hubs), cluster_lat),
                np.full(len(peri_urban_hubs), cluster_lng),
                peri_urban_hubs["lat"].values,
                peri_urban_hubs["lng"].values,
            )
            
            nearest_idx = int(np.argmin(dists_to_hubs))
            nearest_dist = dists_to_hubs[nearest_idx]
            
            if nearest_dist <= BORDER_RELAY_MERGE_KM:
                # Reuse existing hub (dual-role)
                nearest_hub = peri_urban_hubs.iloc[nearest_idx]
                relay_hubs.append({
                    "node_id": f"RELAY_{year}_{len(relay_hubs)}",  # New ID for relay role
                    "node_type": "RELAY_HUB",
                    "lat": nearest_hub["lat"],
                    "lng": nearest_hub["lng"],
                    "first_open_year": year,
                    "serves_route": "; ".join([c["serves_route"] for c in cluster]),
                    "is_merged": True,
                    "merged_with": nearest_hub["node_id"],
                })
                continue
        
        # Create new standalone relay hub
        relay_hubs.append({
            "node_id": f"RELAY_{year}_{len(relay_hubs)}",
            "node_type": "RELAY_HUB",
            "lat": cluster_lat,
            "lng": cluster_lng,
            "first_open_year": year,
            "serves_route": "; ".join([c["serves_route"] for c in cluster]),
            "is_merged": False,
            "merged_with": None,
        })
    
    return pd.DataFrame(relay_hubs) if relay_hubs else pd.DataFrame()


# ---------------------------------------------------------------------------
# Hub capability tagging (HUB-1 fix)
# ---------------------------------------------------------------------------

def tag_hub_capabilities(hubs: pd.DataFrame, demand_volume: dict = None) -> pd.DataFrame:
    """
    Tag hubs with service capabilities (HUB-1 fix).
    
    Rules:
    - DC: Always can consolidate and relay
    - PERI_URBAN_HUB: Can consolidate (assumed metro hubs serve consolidation)
    - RELAY_HUB: Relay-only (no consolidation)
    
    Input:
      - hubs: DataFrame with node_id, node_type
      - demand_volume: optional {node_id: annual_units} to refine consolidation capability
    
    Returns: hubs DataFrame with added columns is_consol_capable, is_relay_capable
    """
    hubs = hubs.copy()
    
    # Initialize capability flags
    hubs["is_consol_capable"] = False
    hubs["is_relay_capable"] = False
    
    # Tag by node type
    hubs.loc[hubs["node_type"] == "DC", "is_consol_capable"] = True
    hubs.loc[hubs["node_type"] == "DC", "is_relay_capable"] = True
    
    hubs.loc[hubs["node_type"] == "PERI_URBAN_HUB", "is_consol_capable"] = True
    hubs.loc[hubs["node_type"] == "PERI_URBAN_HUB", "is_relay_capable"] = True
    
    hubs.loc[hubs["node_type"] == "RELAY_HUB", "is_consol_capable"] = False
    hubs.loc[hubs["node_type"] == "RELAY_HUB", "is_relay_capable"] = True
    hubs.loc[hubs["node_type"] == "BORDER_RELAY_HUB", "is_consol_capable"] = False
    hubs.loc[hubs["node_type"] == "BORDER_RELAY_HUB", "is_relay_capable"] = True
    
    # Optional: refine based on demand volume threshold
    if demand_volume:
        for node_id, volume in demand_volume.items():
            if volume < 50_000:  # Low-volume hubs: relay-only
                hubs.loc[hubs["node_id"] == node_id, "is_consol_capable"] = False
    
    return hubs


# ---------------------------------------------------------------------------
# Route builder for multi-leg paths (NET-1 fix)
# ---------------------------------------------------------------------------

def build_routes(
    nodes: pd.DataFrame,
    lanes: pd.DataFrame,
    year: int,
) -> pd.DataFrame:
    """
    Build route table from physical lane legs (NET-1 fix).

    Routes are shortest-elapsed-time DC -> PERI_URBAN_HUB paths over the active
    lane graph. Pseudo-direct relay markers are excluded; only physical legs are
    allowed in a route path.
    """
    if lanes.empty:
        return pd.DataFrame()

    node_lookup = nodes.set_index("node_id").to_dict("index")
    dc_ids = nodes.loc[nodes["node_type"] == "DC", "node_id"].tolist()
    dest_hubs = nodes.loc[nodes["node_type"] == "PERI_URBAN_HUB", "node_id"].tolist()
    if not dc_ids or not dest_hubs:
        return pd.DataFrame()

    usable_lanes = lanes[~lanes["lane_type"].isin(["PORT_DC", "DC_HUB_VIA_RELAY"])].copy()
    if usable_lanes.empty:
        return pd.DataFrame()

    hub_nodes = nodes[nodes["node_type"].isin(["DC", "PERI_URBAN_HUB", "RELAY_HUB", "BORDER_RELAY_HUB"])].copy()
    hub_nodes = tag_hub_capabilities(hub_nodes)
    hub_caps = hub_nodes.set_index("node_id")[["is_consol_capable", "is_relay_capable"]].to_dict("index")

    adjacency: dict[str, list] = {}
    lane_lookup: dict[str, object] = {}
    for lane in usable_lanes.itertuples(index=False):
        adjacency.setdefault(lane.origin_id, []).append(lane)
        lane_lookup[str(lane.lane_id)] = lane

    def classify_service_mode(path_lanes: list) -> str:
        lane_types = [lane.lane_type for lane in path_lanes]
        if lane_types == ["DC_HUB_DIRECT"]:
            return "DIRECT"
        if any(lane_type == "DC_DC" for lane_type in lane_types):
            return "VIA_DC_TRANSFER"
        if any(lane_type in {"DC_RELAY", "RELAY_HUB"} for lane_type in lane_types):
            return "VIA_RELAY"
        if any(lane_type == "HUB_CORRIDOR" for lane_type in lane_types):
            return "VIA_HUB_CORRIDOR"
        return "MULTI_STOP"

    routes: list[dict] = []

    for origin_dc in dc_ids:
        dist: dict[str, float] = {origin_dc: 0.0}
        prev: dict[str, tuple[str, object]] = {}
        heap: list[tuple[float, str]] = [(0.0, origin_dc)]

        while heap:
            elapsed_val, node_id = heapq.heappop(heap)
            if elapsed_val > dist.get(node_id, float("inf")):
                continue
            for lane in adjacency.get(node_id, []):
                next_elapsed = elapsed_val + float(lane.elapsed_hr)
                if next_elapsed < dist.get(lane.dest_id, float("inf")):
                    dist[lane.dest_id] = next_elapsed
                    prev[lane.dest_id] = (node_id, lane)
                    heapq.heappush(heap, (next_elapsed, lane.dest_id))

        for dest_hub in dest_hubs:
            if dest_hub not in dist:
                continue

            path_lanes: list = []
            path_nodes = [dest_hub]
            cursor = dest_hub
            while cursor in prev:
                parent, lane = prev[cursor]
                path_lanes.append(lane)
                path_nodes.append(parent)
                cursor = parent
            path_lanes.reverse()
            path_nodes.reverse()
            if not path_lanes:
                continue

            total_distance = float(sum(float(lane.road_km) for lane in path_lanes))
            total_drive = float(sum(float(lane.drive_time_hr) for lane in path_lanes))
            total_elapsed = float(sum(float(lane.elapsed_hr) for lane in path_lanes))
            total_hub_dwell = max(total_elapsed - total_drive, 0.0)

            n_relay = 0
            n_consol = 0
            for stop_id in path_nodes[1:]:
                cap = hub_caps.get(stop_id, {})
                if cap.get("is_relay_capable") and not cap.get("is_consol_capable"):
                    n_relay += 1
                elif cap.get("is_consol_capable"):
                    n_consol += 1

            origin_node = node_lookup[origin_dc]
            dest_node = node_lookup[dest_hub]
            direct_distance = float(haversine_km(
                np.array([origin_node["lat"]]), np.array([origin_node["lng"]]),
                np.array([dest_node["lat"]]), np.array([dest_node["lng"]]),
            )[0])
            detour = total_distance / max(direct_distance, 1e-9)
            if detour > DETOUR_RATIO_MAX:
                continue

            routes.append({
                "route_id": f"{origin_dc}__{dest_hub}__{classify_service_mode(path_lanes)}",
                "origin_dc": origin_dc,
                "dest_hub": dest_hub,
                "service_mode": classify_service_mode(path_lanes),
                "n_relay_stops": n_relay,
                "n_consol_stops": n_consol,
                "total_distance_km": round(total_distance, 3),
                "total_drive_hr": round(total_drive, 3),
                "total_hub_dwell_hr": round(total_hub_dwell, 3),
                "total_elapsed_hr": round(total_elapsed, 3),
                "detour_ratio": round(detour, 3),
                "path_lane_ids": "|".join(str(lane.lane_id) for lane in path_lanes),
                "path_node_ids": "|".join(str(node_id) for node_id in path_nodes),
                "year": year,
            })

    if not routes:
        return pd.DataFrame()
    return (
        pd.DataFrame(routes)
        .sort_values(["origin_dc", "dest_hub", "total_elapsed_hr", "detour_ratio"])
        .drop_duplicates(["origin_dc", "dest_hub"], keep="first")
        .reset_index(drop=True)
    )
