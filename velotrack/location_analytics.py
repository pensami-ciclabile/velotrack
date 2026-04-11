"""Cross-line location analytics built from normalized stop events."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import re

import numpy as np
import pandas as pd

from velotrack.stop_detector import StopEvent

MILAN_TZ = ZoneInfo("Europe/Rome")

# Deterministic category tie-breaker (higher wins).
CATEGORY_PRIORITY = {
    "traffic_light": 4,
    "combined": 3,
    "transit_stop": 2,
    "bottleneck": 1,
    "unknown": 0,
}

TIME_BAND_ORDER = {
    "am_peak": 0,
    "midday": 1,
    "pm_peak": 2,
    "evening": 3,
    "night": 4,
    "unknown": 5,
}


@dataclass
class NormalizedStopEvent:
    """Canonical event format used for global location analytics."""

    ride_id: str
    line_key: str
    direction_id: str
    time_band: str
    location_key: str
    location_type: str
    location_lat: float
    location_lon: float
    duration_s: float
    tl_component_s: float
    is_combined: bool


@dataclass
class LineContribution:
    """Per-line contribution metrics for one physical hotspot."""

    line_key: str
    line_number: str
    direction_name: str
    label: str
    obs_count: int
    mean_wait_s: float
    time_bands: dict[str, dict[str, float | int]]


@dataclass
class LocationAggregate:
    """One aggregate row per physical hotspot with nested breakdowns."""

    location_key: str
    lat: float
    lon: float
    category: str
    obs_count: int
    mean_wait_s: float
    median_wait_s: float
    p25_s: float
    p75_s: float
    min_s: float
    max_s: float
    line_keys: list[str]
    line_count: int
    lines: list[LineContribution]
    time_bands: dict[str, dict[str, float | int]]


@dataclass
class RideContext:
    """Per-ride metadata used to normalize stop events."""

    ride_id: str
    line_key: str
    direction_id: str
    time_band: str


def _location_key_for_stop(stop: StopEvent) -> tuple[str, float, float]:
    """Return stable location key + coordinates for a stop event."""
    if stop.ref_lat is not None and stop.ref_lon is not None:
        lat = round(float(stop.ref_lat), 5)
        lon = round(float(stop.ref_lon), 5)
    else:
        lat = round(float(stop.lat), 5)
        lon = round(float(stop.lon), 5)
    return f"{lat:.5f},{lon:.5f}", lat, lon


def _direction_from_bearing(bearing: float) -> str:
    """Map a bearing in degrees to one of 8 deterministic direction bins."""
    if bearing < 0:
        bearing += 360
    bins = [
        (22.5, "E"),
        (67.5, "NE"),
        (112.5, "N"),
        (157.5, "NW"),
        (202.5, "W"),
        (247.5, "SW"),
        (292.5, "S"),
        (337.5, "SE"),
        (360.1, "E"),
    ]
    for edge, label in bins:
        if bearing < edge:
            return label
    return "E"


def infer_direction_id(df: pd.DataFrame) -> str:
    """Infer deterministic ride direction from start/end coordinates."""
    if len(df) < 2:
        return "UNK"

    lat1 = float(df["lat"].iloc[0])
    lon1 = float(df["lon"].iloc[0])
    lat2 = float(df["lat"].iloc[-1])
    lon2 = float(df["lon"].iloc[-1])

    dx = lon2 - lon1
    dy = lat2 - lat1
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return "UNK"

    # 0 deg at East, counter-clockwise.
    bearing = np.degrees(np.arctan2(dy, dx))
    return _direction_from_bearing(float(bearing))


def infer_time_band(ts: datetime | pd.Timestamp | None) -> str:
    """Map timestamp to fixed time-of-day bands in Europe/Rome timezone."""
    if ts is None:
        return "unknown"

    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()

    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=MILAN_TZ)
    else:
        ts = ts.astimezone(MILAN_TZ)

    h = ts.hour
    if 6 <= h <= 9:
        return "am_peak"
    if 10 <= h <= 15:
        return "midday"
    if 16 <= h <= 19:
        return "pm_peak"
    if 20 <= h <= 23:
        return "evening"
    return "night"


def build_ride_context(
    line_key: str,
    ride_path: Path,
    ride_df: pd.DataFrame,
    ride_idx: int,
) -> RideContext:
    """Build deterministic ride metadata shared by all events of one ride."""
    direction_id = infer_direction_id(ride_df)
    start_time = ride_df["time"].iloc[0] if len(ride_df) else None
    time_band = infer_time_band(start_time)
    ride_id = f"{line_key}:{ride_path.stem}:{ride_idx}"
    return RideContext(
        ride_id=ride_id,
        line_key=line_key,
        direction_id=direction_id,
        time_band=time_band,
    )


def normalize_stop_events(
    ride_ctx: RideContext,
    stops: list[StopEvent],
) -> list[NormalizedStopEvent]:
    """Normalize stop events for a single ride."""
    normalized: list[NormalizedStopEvent] = []
    for stop in stops:
        location_key, lat, lon = _location_key_for_stop(stop)
        if stop.category == "traffic_light":
            tl_component = float(stop.duration)
        elif stop.category == "combined":
            tl_component = float(stop.traffic_light_wait or 0.0)
        else:
            tl_component = 0.0

        normalized.append(NormalizedStopEvent(
            ride_id=ride_ctx.ride_id,
            line_key=ride_ctx.line_key,
            direction_id=ride_ctx.direction_id,
            time_band=ride_ctx.time_band,
            location_key=location_key,
            location_type=stop.category,
            location_lat=lat,
            location_lon=lon,
            duration_s=float(stop.duration),
            tl_component_s=tl_component,
            is_combined=(stop.category == "combined"),
        ))
    return normalized


def build_normalized_events(rides_by_line: dict[str, dict]) -> list[NormalizedStopEvent]:
    """Build one normalized event stream across all rides/lines."""
    events: list[NormalizedStopEvent] = []

    for line_key, data in rides_by_line.items():
        ride_files = data.get("ride_files", [])
        ride_dfs = data.get("ride_dfs", [])
        all_stops = data.get("all_stops", [])

        for idx, ((ride_path, _name), df, stops) in enumerate(zip(ride_files, ride_dfs, all_stops), start=1):
            ctx = build_ride_context(line_key, Path(ride_path), df, idx)
            events.extend(normalize_stop_events(ctx, stops))

    return events


def _dominant_category(events: list[NormalizedStopEvent]) -> str:
    counter = Counter(e.location_type for e in events)
    return max(counter.keys(), key=lambda cat: (counter[cat], CATEGORY_PRIORITY.get(cat, 0), cat))


def _line_descriptor(line_key: str) -> tuple[str, str]:
    match = re.search(r"line(\d+)", line_key)
    line_number = match.group(1) if match else line_key

    parts = line_key.split("_", 1)
    if len(parts) > 1:
        words = parts[1].replace("-", " ").split()
        destination = " ".join(w[:1].upper() + w[1:] for w in words)
    else:
        destination = ""

    return line_number, destination


def _stats_dict(durations: np.ndarray) -> dict[str, float | int]:
    return {
        "obs_count": int(len(durations)),
        "mean_wait_s": float(np.mean(durations)),
        "median_wait_s": float(np.median(durations)),
        "p25_s": float(np.percentile(durations, 25)),
        "p75_s": float(np.percentile(durations, 75)),
        "min_s": float(np.min(durations)),
        "max_s": float(np.max(durations)),
    }


def _sort_band_keys(keys: set[str] | list[str]) -> list[str]:
    return sorted(set(keys), key=lambda b: (TIME_BAND_ORDER.get(b, 99), b))


def _line_sort_key(line: LineContribution) -> tuple[int, str, str]:
    try:
        num = int(line.line_number)
    except (TypeError, ValueError):
        num = 9999
    return (num, line.direction_name, line.line_key)


def aggregate_location_events(events: list[NormalizedStopEvent]) -> list[LocationAggregate]:
    """Aggregate normalized events into one row per physical location."""
    grouped: dict[str, list[NormalizedStopEvent]] = defaultdict(list)
    for event in events:
        grouped[event.location_key].append(event)

    out: list[LocationAggregate] = []
    for location_key, bucket in grouped.items():
        durations = np.array([e.duration_s for e in bucket], dtype=float)
        category = _dominant_category(bucket)

        # Time-band breakdown for this hotspot.
        by_band: dict[str, list[NormalizedStopEvent]] = defaultdict(list)
        for event in bucket:
            by_band[event.time_band].append(event)

        band_stats: dict[str, dict[str, float | int]] = {}
        for band in _sort_band_keys(list(by_band.keys())):
            band_durations = np.array([e.duration_s for e in by_band[band]], dtype=float)
            band_stats[band] = _stats_dict(band_durations)

        # Line contribution breakdown.
        by_line: dict[str, list[NormalizedStopEvent]] = defaultdict(list)
        for event in bucket:
            by_line[event.line_key].append(event)

        line_rows: list[LineContribution] = []
        for line_key, line_bucket in by_line.items():
            line_durations = np.array([e.duration_s for e in line_bucket], dtype=float)
            line_number, direction_name = _line_descriptor(line_key)
            label = f"Line {line_number}"
            if direction_name:
                label = f"{label} ({direction_name})"

            line_by_band: dict[str, list[NormalizedStopEvent]] = defaultdict(list)
            for event in line_bucket:
                line_by_band[event.time_band].append(event)

            line_band_stats: dict[str, dict[str, float | int]] = {}
            for band in _sort_band_keys(list(line_by_band.keys())):
                band_durations = np.array([e.duration_s for e in line_by_band[band]], dtype=float)
                line_band_stats[band] = {
                    "obs_count": int(len(band_durations)),
                    "mean_wait_s": float(np.mean(band_durations)),
                }

            line_rows.append(LineContribution(
                line_key=line_key,
                line_number=line_number,
                direction_name=direction_name,
                label=label,
                obs_count=int(len(line_bucket)),
                mean_wait_s=float(np.mean(line_durations)),
                time_bands=line_band_stats,
            ))

        line_rows.sort(key=_line_sort_key)
        line_keys = [lr.line_key for lr in line_rows]
        overall = _stats_dict(durations)

        out.append(LocationAggregate(
            location_key=location_key,
            lat=bucket[0].location_lat,
            lon=bucket[0].location_lon,
            category=category,
            obs_count=overall["obs_count"],
            mean_wait_s=overall["mean_wait_s"],
            median_wait_s=overall["median_wait_s"],
            p25_s=overall["p25_s"],
            p75_s=overall["p75_s"],
            min_s=overall["min_s"],
            max_s=overall["max_s"],
            line_keys=line_keys,
            line_count=len(line_rows),
            lines=line_rows,
            time_bands=band_stats,
        ))

    out.sort(key=lambda a: (-a.mean_wait_s, -a.obs_count, a.location_key))
    return out


def build_hotspot_slices(
    aggregates: list[LocationAggregate],
    limit: int = 20,
) -> dict[str, list[dict]]:
    """Build ranked hotspot slices from aggregate data."""
    slices: dict[str, list[dict]] = {
        "all": rank_hotspots(aggregates, category="all", time_band="all", limit=limit),
    }

    for category in ["traffic_light", "combined", "bottleneck", "transit_stop"]:
        slices[category] = rank_hotspots(
            aggregates, category=category, time_band="all", limit=limit,
        )

    return slices


def rank_hotspots(
    aggregates: list[LocationAggregate],
    category: str = "all",
    time_band: str = "all",
    limit: int | None = None,
) -> list[dict]:
    """Filter + rank hotspots by category and optional time band."""
    ranked_rows: list[dict] = []
    for agg in aggregates:
        if category != "all" and agg.category != category:
            continue

        if time_band == "all":
            rank_obs = agg.obs_count
            rank_mean = agg.mean_wait_s
        else:
            band_stats = agg.time_bands.get(time_band)
            if not band_stats:
                continue
            rank_obs = int(band_stats.get("obs_count", 0))
            rank_mean = float(band_stats.get("mean_wait_s", 0.0))
            if rank_obs <= 0:
                continue

        row = asdict(agg)
        row["rank_obs_count"] = rank_obs
        row["rank_mean_wait_s"] = rank_mean
        ranked_rows.append(row)

    ranked_rows.sort(
        key=lambda r: (-r["rank_mean_wait_s"], -r["rank_obs_count"], r["location_key"]),
    )
    if limit is not None:
        return ranked_rows[:limit]
    return ranked_rows


def serialize_location_aggregates(aggregates: list[LocationAggregate]) -> list[dict]:
    """Convert aggregate objects to JSON-serializable list of dictionaries."""
    return [asdict(a) for a in aggregates]
