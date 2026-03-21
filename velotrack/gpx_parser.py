"""Parse GPX files into a pandas DataFrame with velocity data."""

import math
from pathlib import Path

import gpxpy
import pandas as pd

from velotrack.config import MAX_REALISTIC_SPEED


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance in meters between two GPS coordinates."""
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def filter_teleports(
    df: pd.DataFrame,
    window: int = 10,
    ratio_threshold: float = 5.0,
    min_cum_dist: float = 100.0,
) -> tuple[pd.DataFrame, int]:
    """Remove GPS teleport artifacts where points bounce back and forth.

    Detects windows where cumulative distance is much larger than net displacement,
    indicating the GPS receiver lost lock and positions are jumping erratically.

    Returns (filtered_df, removed_count).
    """
    if len(df) < window or "dist" not in df.columns:
        return df, 0

    n = len(df)
    bad = set()

    for i in range(n - window):
        j = i + window
        cum_dist = df.iloc[i + 1 : j + 1]["dist"].sum()
        if cum_dist < min_cum_dist:
            continue
        net_disp = haversine(
            df.iloc[i]["lat"], df.iloc[i]["lon"],
            df.iloc[j]["lat"], df.iloc[j]["lon"],
        )
        if net_disp < 1.0:
            # Near-zero displacement with significant cumulative distance = teleporting
            for k in range(i + 1, j):
                bad.add(k)
        elif cum_dist / net_disp > ratio_threshold:
            for k in range(i + 1, j):
                bad.add(k)

    if not bad:
        return df, 0

    removed = len(bad)

    # Find gap boundaries: indices just after each contiguous block of removed points
    bad_sorted = sorted(bad)
    gap_after: set[int] = set()
    prev_bad = None
    for b in bad_sorted:
        if prev_bad is None or b != prev_bad + 1:
            # Start of a new bad block — the point before it is a gap boundary
            pass
        prev_bad = b
    # The first good point after each bad block needs dist=0
    # to avoid a velocity spike across the gap
    for b in bad_sorted:
        next_idx = b + 1
        if next_idx < len(df) and next_idx not in bad:
            gap_after.add(next_idx)

    df = df.drop(index=df.index[list(bad)]).reset_index(drop=True)

    # Mark gap boundaries in the filtered df: set dist/velocity to 0
    # so no line is drawn and velocity doesn't spike across the gap
    # Map old indices to new indices after drop
    old_to_new = {}
    new_idx = 0
    for old_idx in range(len(df) + removed):
        if old_idx not in bad:
            old_to_new[old_idx] = new_idx
            new_idx += 1

    for old_idx in gap_after:
        if old_idx in old_to_new:
            new_i = old_to_new[old_idx]
            df.at[new_i, "dist"] = 0.0
            df.at[new_i, "velocity_kmh"] = 0.0

    return df, removed


def parse_gpx(path: Path) -> tuple[pd.DataFrame, int]:
    """Parse a GPX file into a DataFrame with columns:
    lat, lon, ele, time, dt, dist, velocity_kmh
    """
    with open(path) as f:
        gpx = gpxpy.parse(f)

    points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for pt in segment.points:
                points.append({
                    "lat": pt.latitude,
                    "lon": pt.longitude,
                    "ele": pt.elevation,
                    "time": pt.time,
                })

    df = pd.DataFrame(points)
    if df.empty:
        return df, 0

    df = df.sort_values("time").reset_index(drop=True)
    df, outlier_count = recalculate_distances(df)
    return df, outlier_count


def recalculate_distances(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """(Re)compute dt, dist, and velocity_kmh from lat/lon/time columns.

    Returns (df, outlier_count). Useful after snapping coordinates.
    """
    df["dt"] = df["time"].diff().dt.total_seconds()
    df["dist"] = 0.0
    for i in range(1, len(df)):
        df.loc[i, "dist"] = haversine(
            df.loc[i - 1, "lat"], df.loc[i - 1, "lon"],
            df.loc[i, "lat"], df.loc[i, "lon"],
        )

    df["velocity_kmh"] = 0.0
    mask = df["dt"] > 0
    df.loc[mask, "velocity_kmh"] = (df.loc[mask, "dist"] / df.loc[mask, "dt"]) * 3.6

    outlier_count = int((df["velocity_kmh"] > MAX_REALISTIC_SPEED).sum())
    df.loc[df["velocity_kmh"] > MAX_REALISTIC_SPEED, "velocity_kmh"] = MAX_REALISTIC_SPEED

    return df, outlier_count
