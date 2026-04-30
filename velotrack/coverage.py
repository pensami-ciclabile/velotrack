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
    stops.csv by name.
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


def _gather_ride_points_for_line(
    rides_by_line: dict[str, dict],
    line_num: str,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Return lat/lon arrays for each recorded ride matching a line number."""
    prefix = f"line{line_num}_"
    rides: list[tuple[np.ndarray, np.ndarray]] = []
    for line_key, data in rides_by_line.items():
        if not (line_key == f"line{line_num}" or line_key.startswith(prefix)):
            continue
        for df in data["ride_dfs"]:
            if df is None or df.empty:
                continue
            rides.append((
                df["lat"].to_numpy(dtype=float),
                df["lon"].to_numpy(dtype=float),
            ))
    return rides


def _gather_points_for_line(rides_by_line: dict[str, dict], line_num: str) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate lat/lon arrays from every recorded ride matching a line number."""
    rides = _gather_ride_points_for_line(rides_by_line, line_num)
    if not rides:
        return np.array([], dtype=float), np.array([], dtype=float)
    lats = [lat for lat, _lon in rides]
    lons = [lon for _lat, lon in rides]
    return np.concatenate(lats), np.concatenate(lons)


def _count_ride_hits(
    lat: float,
    lon: float,
    ride_points: list[tuple[np.ndarray, np.ndarray]],
    radius_m: float,
) -> int:
    """Count rides that pass within radius_m of one stop."""
    hits = 0
    for lats, lons in ride_points:
        if lats.size == 0:
            continue
        dists = _haversine_vec(lat, lon, lats, lons)
        if bool(dists.min() <= radius_m):
            hits += 1
    return hits


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
        ride_points = _gather_ride_points_for_line(rides_by_line, line_num)

        stop_records: list[dict] = []
        covered_count = 0
        missing_names: list[str] = []
        for stop in stops:
            slat = float(stop["lat"])
            slon = float(stop["lon"])
            mapped_count = _count_ride_hits(slat, slon, ride_points, radius_m)
            covered = mapped_count > 0
            stop_records.append({
                "stop_id": stop.get("stop_id", ""),
                "name": stop.get("name", ""),
                "lat": slat,
                "lon": slon,
                "covered": covered,
                "mapped_count": mapped_count,
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


def compute_city_stop_coverage(line_coverage: dict[str, dict]) -> list[dict]:
    """Aggregate coverage for each unique physical stop across all tracked lines."""
    stops: dict[tuple, dict] = {}
    for line_num, cov in line_coverage.items():
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

            entry = stops.setdefault(key, {
                "stop_id": sid,
                "name": stop.get("name", ""),
                "lat": stop["lat"],
                "lon": stop["lon"],
                "mapped_count": 0,
                "served_lines": set(),
                "mapped_lines": set(),
                "missing_lines": set(),
            })
            line = str(line_num)
            entry["served_lines"].add(line)
            entry["mapped_count"] += int(stop.get("mapped_count", 0))
            if stop["covered"]:
                entry["mapped_lines"].add(line)
            else:
                entry["missing_lines"].add(line)

    result: list[dict] = []
    for entry in stops.values():
        served_lines = sorted(entry["served_lines"], key=lambda line: (len(line), line))
        mapped_lines = sorted(entry["mapped_lines"], key=lambda line: (len(line), line))
        missing_lines = sorted(entry["missing_lines"], key=lambda line: (len(line), line))
        mapped_count = int(entry["mapped_count"])
        result.append({
            "stop_id": entry["stop_id"],
            "name": entry["name"],
            "lat": entry["lat"],
            "lon": entry["lon"],
            "covered": mapped_count > 0,
            "mapped_count": mapped_count,
            "served_lines": served_lines,
            "mapped_lines": mapped_lines,
            "missing_lines": missing_lines,
            "served_line_count": len(served_lines),
            "mapped_line_count": len(mapped_lines),
        })

    result.sort(key=lambda s: (not s["covered"], -s["mapped_count"], s["name"]))
    return result
