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

    # Compute deltas
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
