"""Download OSM tram track geometry and snap GPS traces to it."""

import json
import math
from collections import defaultdict

import pandas as pd
import requests

from velotrack.config import OSM_TRACKS_JSON, SNAP_CONTINUITY_BONUS, SNAP_MAX_DISTANCE

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Milan bounding box (generous)
MILAN_BBOX = "45.40,9.05,45.54,9.30"

# Equirectangular approximation constants at Milan's latitude (~45.46°)
_COS_LAT = math.cos(math.radians(45.46))
_M_PER_DEG_LAT = 111_320.0
_M_PER_DEG_LON = 111_320.0 * _COS_LAT


def download_osm_tracks() -> None:
    """Download tram track ways and route relations from OSM and cache as JSON."""
    print("Downloading tram track geometry from OpenStreetMap...")

    # Query 1: tram ways with full geometry
    ways_query = f"""
    [out:json][timeout:60];
    way["railway"="tram"]({MILAN_BBOX});
    out body geom;
    """
    resp_ways = requests.post(OVERPASS_URL, data={"data": ways_query}, timeout=90)
    resp_ways.raise_for_status()
    ways_data = resp_ways.json()

    print(f"  {len(ways_data['elements'])} tram track ways downloaded.")

    # Query 2: tram route relations (members + tags, no geom needed)
    rels_query = f"""
    [out:json][timeout:60];
    relation["route"="tram"]({MILAN_BBOX});
    out body;
    """
    resp_rels = requests.post(OVERPASS_URL, data={"data": rels_query}, timeout=90)
    resp_rels.raise_for_status()
    rels_data = resp_rels.json()

    print(f"  {len(rels_data['elements'])} tram route relations downloaded.")

    combined = {
        "ways": ways_data["elements"],
        "relations": rels_data["elements"],
    }

    OSM_TRACKS_JSON.parent.mkdir(parents=True, exist_ok=True)
    OSM_TRACKS_JSON.write_text(json.dumps(combined))
    print(f"  Saved to {OSM_TRACKS_JSON}")


def load_line_tracks(line_number: str) -> list[list[tuple[float, float]]]:
    """Load tram track polylines for a specific line number from cached OSM data.

    Returns list of polylines, each a list of (lat, lon) tuples.
    """
    if not OSM_TRACKS_JSON.exists():
        return []

    data = json.loads(OSM_TRACKS_JSON.read_text())
    ways = data.get("ways", [])
    relations = data.get("relations", [])

    # Find relation(s) matching this line number
    matching_way_ids: set[int] = set()
    for rel in relations:
        ref = rel.get("tags", {}).get("ref", "")
        if ref == line_number:
            for member in rel.get("members", []):
                if member.get("type") == "way" and member.get("role", "") == "":
                    matching_way_ids.add(member["ref"])

    if not matching_way_ids:
        print(f"  Warning: no OSM relation found for line {line_number}, using all tram tracks.")
        matching_way_ids = {w["id"] for w in ways}

    # Build polylines from matching ways
    polylines: list[list[tuple[float, float]]] = []
    for way in ways:
        if way["id"] not in matching_way_ids:
            continue
        geom = way.get("geometry", [])
        if len(geom) < 2:
            continue
        polyline = [(node["lat"], node["lon"]) for node in geom]
        polylines.append(polyline)

    return polylines


def _to_meters(dlat: float, dlon: float) -> tuple[float, float]:
    """Convert lat/lon deltas to approximate meters at Milan's latitude."""
    return dlat * _M_PER_DEG_LAT, dlon * _M_PER_DEG_LON


def _segment_length_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Length of a segment in meters (equirectangular approximation)."""
    dy, dx = _to_meters(lat2 - lat1, lon2 - lon1)
    return math.hypot(dx, dy)


def _project_point_to_segment(
    plat: float, plon: float,
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> tuple[float, float, float, float]:
    """Project point onto line segment. Returns (proj_lat, proj_lon, distance_m, t)."""
    # Convert to local meters
    ax, ay = _to_meters(lat1, lon1)
    bx, by = _to_meters(lat2, lon2)
    px, py = _to_meters(plat, plon)

    abx, aby = bx - ax, by - ay
    apx, apy = px - ax, py - ay

    ab_sq = abx * abx + aby * aby
    if ab_sq < 1e-12:
        # Degenerate segment
        dist = math.hypot(px - ax, py - ay)
        return lat1, lon1, dist, 0.0

    t = max(0.0, min(1.0, (apx * abx + apy * aby) / ab_sq))
    proj_lat = lat1 + t * (lat2 - lat1)
    proj_lon = lon1 + t * (lon2 - lon1)

    proj_mx, proj_my = _to_meters(proj_lat, proj_lon)
    dist = math.hypot(px - proj_mx, py - proj_my)

    return proj_lat, proj_lon, dist, t


def snap_to_tracks(
    df: pd.DataFrame,
    tracks: list[list[tuple[float, float]]],
    max_distance: float = SNAP_MAX_DISTANCE,
) -> pd.DataFrame:
    """Snap GPS points to nearest tram track segments with forward-chain continuity.

    Returns a copy of df with lat/lon updated for snapped points and a 'snapped'
    boolean column. Original dist/velocity_kmh are preserved (they reflect actual
    travel timing better than recomputed distances from snapped positions).
    """
    if not tracks or df.empty:
        df = df.copy()
        df["snapped"] = False
        return df

    # Build segment list: (lat1, lon1, lat2, lon2, polyline_idx, seg_idx)
    segments: list[tuple[float, float, float, float, int, int]] = []
    for poly_idx, polyline in enumerate(tracks):
        for seg_idx in range(len(polyline) - 1):
            lat1, lon1 = polyline[seg_idx]
            lat2, lon2 = polyline[seg_idx + 1]
            segments.append((lat1, lon1, lat2, lon2, poly_idx, seg_idx))

    if not segments:
        df = df.copy()
        df["snapped"] = False
        return df

    # Build adjacency: set of segment indices contiguous with each segment
    contiguous: dict[int, set[int]] = defaultdict(set)

    # Same-polyline adjacency
    idx = 0
    for polyline in tracks:
        n_segs = len(polyline) - 1
        for k in range(n_segs - 1):
            contiguous[idx + k].add(idx + k + 1)
            contiguous[idx + k + 1].add(idx + k)
        idx += n_segs

    # Cross-polyline adjacency via shared endpoints
    endpoint_to_segs: dict[tuple[float, float], list[int]] = defaultdict(list)
    for seg_i, (lat1, lon1, lat2, lon2, _, _) in enumerate(segments):
        endpoint_to_segs[(lat1, lon1)].append(seg_i)
        endpoint_to_segs[(lat2, lon2)].append(seg_i)

    for segs_at_node in endpoint_to_segs.values():
        if len(segs_at_node) > 1:
            for i in range(len(segs_at_node)):
                for j in range(i + 1, len(segs_at_node)):
                    contiguous[segs_at_node[i]].add(segs_at_node[j])
                    contiguous[segs_at_node[j]].add(segs_at_node[i])

    # Build spatial grid index (~100m cells)
    cell_size_lat = 100.0 / _M_PER_DEG_LAT
    cell_size_lon = 100.0 / _M_PER_DEG_LON

    grid: dict[tuple[int, int], list[int]] = defaultdict(list)
    for seg_i, (lat1, lon1, lat2, lon2, _, _) in enumerate(segments):
        min_lat, max_lat = min(lat1, lat2), max(lat1, lat2)
        min_lon, max_lon = min(lon1, lon2), max(lon1, lon2)
        r0 = int(min_lat / cell_size_lat) - 1
        r1 = int(max_lat / cell_size_lat) + 1
        c0 = int(min_lon / cell_size_lon) - 1
        c1 = int(max_lon / cell_size_lon) + 1
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                grid[(r, c)].append(seg_i)

    # Forward-chain snapping
    df = df.copy()
    snapped_flags = [False] * len(df)
    prev_seg: int | None = None

    for i in range(len(df)):
        plat = df.at[i, "lat"]
        plon = df.at[i, "lon"]

        # Find candidate segments from nearby grid cells
        r = int(plat / cell_size_lat)
        c = int(plon / cell_size_lon)
        candidate_indices: set[int] = set()
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                candidate_indices.update(grid.get((r + dr, c + dc), []))

        if not candidate_indices:
            prev_seg = None
            continue

        best_seg: int | None = None
        best_actual_dist = float("inf")
        best_effective_dist = float("inf")
        best_proj_lat = plat
        best_proj_lon = plon

        for seg_i in candidate_indices:
            lat1, lon1, lat2, lon2, _, _ = segments[seg_i]
            proj_lat, proj_lon, actual_dist, _t = _project_point_to_segment(
                plat, plon, lat1, lon1, lat2, lon2,
            )

            effective_dist = actual_dist
            if prev_seg is not None and seg_i in contiguous.get(prev_seg, set()):
                effective_dist -= SNAP_CONTINUITY_BONUS

            if effective_dist < best_effective_dist:
                best_effective_dist = effective_dist
                best_actual_dist = actual_dist
                best_seg = seg_i
                best_proj_lat = proj_lat
                best_proj_lon = proj_lon

        if best_actual_dist <= max_distance and best_seg is not None:
            df.at[i, "lat"] = best_proj_lat
            df.at[i, "lon"] = best_proj_lon
            snapped_flags[i] = True
            prev_seg = best_seg
        else:
            prev_seg = None

    df["snapped"] = snapped_flags
    snap_count = sum(snapped_flags)
    print(f"  Snapped {snap_count}/{len(df)} points ({100*snap_count/len(df):.0f}%)")
    return df
