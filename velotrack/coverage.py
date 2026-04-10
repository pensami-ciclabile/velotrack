"""Compute mapping coverage: which canonical GTFS stops have GPS data yet."""

import json

import numpy as np

from velotrack.config import GTFS_DIR, LINE_STOPS_JSON
from velotrack.gtfs import build_line_stops_from_cache, extract_line_stops_with_coords


COVERAGE_RADIUS_M = 50.0


def _haversine_vec(lat: float, lon: float, lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Vectorized haversine: distance in meters from one point to many points."""
    R = 6_371_000.0
    phi1 = np.radians(lat)
    phi2 = np.radians(lats)
    dphi = phi2 - phi1
    dlam = np.radians(lons - lon)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2) ** 2
    return R * 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def load_or_build_line_stops() -> dict[str, list[dict]]:
    """Return per-line stops with coordinates.

    Prefers the cached line_stops.json. If missing but raw GTFS is available,
    extracts from raw. Otherwise falls back to joining gtfs_stops.json with
    tram_stops.csv by name.
    """
    if LINE_STOPS_JSON.exists():
        return json.loads(LINE_STOPS_JSON.read_text())
    if GTFS_DIR.exists():
        extract_line_stops_with_coords()
        if LINE_STOPS_JSON.exists():
            return json.loads(LINE_STOPS_JSON.read_text())
    line_stops = build_line_stops_from_cache()
    if line_stops:
        LINE_STOPS_JSON.parent.mkdir(parents=True, exist_ok=True)
        LINE_STOPS_JSON.write_text(json.dumps(line_stops, ensure_ascii=False, indent=2))
    return line_stops


def _gather_points_for_line(rides_by_line: dict[str, dict], line_num: str) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate lat/lon arrays from every recorded ride matching a line number."""
    prefix = f"line{line_num}_"
    lats: list[np.ndarray] = []
    lons: list[np.ndarray] = []
    for line_key, data in rides_by_line.items():
        if not (line_key == f"line{line_num}" or line_key.startswith(prefix)):
            continue
        for df in data["ride_dfs"]:
            if df is None or df.empty:
                continue
            lats.append(df["lat"].to_numpy(dtype=float))
            lons.append(df["lon"].to_numpy(dtype=float))
    if not lats:
        return np.array([], dtype=float), np.array([], dtype=float)
    return np.concatenate(lats), np.concatenate(lons)


def compute_line_coverage(
    rides_by_line: dict[str, dict],
    line_stops: dict[str, list[dict]],
    radius_m: float = COVERAGE_RADIUS_M,
) -> dict[str, dict]:
    """For each line, mark each canonical stop as covered/missing.

    Returns: {line_num: {total, covered, missing_count, pct, stops: [{name, lat,
        lon, covered}], missing_names: [str]}}
    """
    result: dict[str, dict] = {}
    for line_num, stops in line_stops.items():
        if not stops:
            continue
        plats, plons = _gather_points_for_line(rides_by_line, line_num)

        stop_records: list[dict] = []
        covered_count = 0
        missing_names: list[str] = []
        for stop in stops:
            slat = float(stop["lat"])
            slon = float(stop["lon"])
            covered = False
            if plats.size > 0:
                dists = _haversine_vec(slat, slon, plats, plons)
                covered = bool(dists.min() <= radius_m)
            stop_records.append({
                "stop_id": stop.get("stop_id", ""),
                "name": stop.get("name", ""),
                "lat": slat,
                "lon": slon,
                "covered": covered,
            })
            if covered:
                covered_count += 1
            else:
                missing_names.append(stop.get("name", ""))

        total = len(stop_records)
        pct = round(covered_count / total * 100) if total else 0
        result[line_num] = {
            "total": total,
            "covered": covered_count,
            "missing_count": total - covered_count,
            "pct": pct,
            "stops": stop_records,
            "missing_names": missing_names,
        }
    return result


def compute_city_coverage(line_coverage: dict[str, dict]) -> dict:
    """Aggregate coverage across all lines, deduplicating stops by stop_id.

    A stop served by multiple lines is counted once. If a stop_id is missing
    or empty, fall back to (name, rounded coords) as the dedup key.
    """
    seen: dict[tuple, bool] = {}
    for cov in line_coverage.values():
        for stop in cov["stops"]:
            sid = stop.get("stop_id") or ""
            if sid:
                key: tuple = ("id", sid)
            else:
                key = (
                    "nm",
                    stop.get("name", ""),
                    round(stop["lat"], 5),
                    round(stop["lon"], 5),
                )
            # If covered on any line, keep it covered.
            seen[key] = seen.get(key, False) or stop["covered"]

    total = len(seen)
    covered = sum(1 for v in seen.values() if v)
    pct = round(covered / total * 100) if total else 0
    return {"total": total, "covered": covered, "missing": total - covered, "pct": pct}
