"""
hub_network.py — Hub activation, border relay derivation, and lane generation.

Implements PLAN.md §3 (Hub Activation) and §4 (Lane Generation).
Numpy-first for geometry: pandas-in → numpy-compute → pandas-out.
"""

from __future__ import annotations

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
      - BORDER_RELAY_HUB: active if activation_year <= year (set externally)
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
            (nodes["node_type"] == "BORDER_RELAY_HUB")
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
    **extra,
) -> dict:
    hav = float(haversine_km(
        np.array([origin_lat]), np.array([origin_lng]),
        np.array([dest_lat]), np.array([dest_lng]),
    )[0])
    dt = float(drive_time_hr(np.array([hav]))[0])
    dwell = HUB_CONSOL_DWELL_HR if "DC" in dest_id else HUB_RELAY_DWELL_HR
    el = dt + dwell

    cost_per_km = TRUCK_L_EUR_KM if truck_class == "L" else TRUCK_M_EUR_KM
    road_km = hav * DETOUR_FACTOR

    row = {
        "lane_id": f"{origin_id}__{dest_id}",
        "origin_id": origin_id,
        "dest_id": dest_id,
        "lane_type": lane_type,
        "truck_class": truck_class,
        "relay_flag": relay_flag,
        "haversine_km": round(hav, 2),
        "road_km": round(road_km, 2),
        "drive_time_hr": round(dt, 3),
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
    relays  = by_type.get("BORDER_RELAY_HUB", pd.DataFrame())
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
            )
            row_rev = _lane_row(
                dc_b["node_id"], dc_a["node_id"],
                dc_b["lat"], dc_b["lng"],
                dc_a["lat"], dc_a["lng"],
                lane_type="DC_DC",
                truck_class="L",
                relay_flag=rel_flag,
                year=year,
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
            )
            lanes.append(row)

        # Relay-needed lanes (4 < dt <= DC_HUB_RELAY_MAX_HR) — flag only, no new lane
        relay_i, relay_j = np.where(
            (dt_matrix > DC_HUB_DIRECT_MAX_HR) & (dt_matrix <= DC_HUB_RELAY_MAX_HR)
        )
        for i, j in zip(relay_i, relay_j):
            row = _lane_row(
                str(dc_arr[i, 0]), str(hub_arr[j, 0]),
                float(dc_lats[i]), float(dc_lngs[i]),
                float(hub_lats[j]), float(hub_lngs[j]),
                lane_type="DC_HUB_VIA_RELAY",
                truck_class="L",
                relay_flag=True,
                year=year,
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
            road_kms = hav_to_relays * DETOUR_FACTOR
            det_ratio = road_kms / np.maximum(hav_to_relays, 1e-9)
            eligible = np.where(
                (hav_to_relays <= DC_TO_BORDER_RELAY_MAX_KM)
                & (det_ratio <= DETOUR_RATIO_MAX)
            )[0]
            for j in eligible:
                row = _lane_row(
                    dc_row.node_id, str(rel_arr[j, 0]),
                    dc_row.lat, dc_row.lng,
                    float(rel_lats[j]), float(rel_lngs[j]),
                    lane_type="DC_RELAY",
                    truck_class="L",
                    relay_flag=True,
                    year=year,
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
        # Upper triangle only (undirected, both directions added below)
        road_hh = hav_hh * DETOUR_FACTOR
        det_hh = road_hh / np.maximum(hav_hh, 1e-9)

        i_arr, j_arr = np.where(
            (hav_hh <= HUB_CORRIDOR_MAX_KM)
            & (det_hh <= DETOUR_RATIO_MAX)
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
                )
                lanes.append(row)

    if not lanes:
        return pd.DataFrame()

    df = pd.DataFrame(lanes)
    # Compute detour_ratio for all lanes
    df["detour_ratio"] = (df["road_km"] / np.maximum(df["haversine_km"], 1e-9)).round(3)
    return df
