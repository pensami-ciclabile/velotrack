"""Detect and classify stop events from parsed GPX data."""

from dataclasses import dataclass

import pandas as pd

from velotrack.config import (
    COMBINED_TRAM_DEDUCT,
    STOP_DISTANCE,
    STOP_TIME_GAP,
    TRAFFIC_LIGHT_RADIUS,
    TRAM_STOP_RADIUS,
    TRAFFIC_LIGHTS_CSV,
)
from velotrack.gpx_parser import haversine


@dataclass
class StopEvent:
    lat: float
    lon: float
    duration: float  # seconds
    category: str  # tram_stop, traffic_light, combined, bottleneck
    nearest_stop_name: str | None = None
    nearest_stop_dist: float | None = None
    traffic_light_wait: float | None = None
    ref_lat: float | None = None  # matched reference location lat
    ref_lon: float | None = None  # matched reference location lon


def detect_stops(df: pd.DataFrame) -> list[StopEvent]:
    """Find stops: rows where dt > threshold and distance < threshold.

    The GPS app drops points when stationary, so a stop is simply a time gap
    with minimal position change.
    """
    stops = []
    for i in range(1, len(df)):
        dt = df.loc[i, "dt"]
        dist = df.loc[i, "dist"]
        if dt > STOP_TIME_GAP and dist < STOP_DISTANCE:
            stops.append(StopEvent(
                lat=df.loc[i, "lat"],
                lon=df.loc[i, "lon"],
                duration=dt,
                category="unknown",
            ))
    return stops


def load_traffic_lights() -> pd.DataFrame:
    """Load traffic lights from CSV. Returns empty DataFrame if file missing/empty."""
    if not TRAFFIC_LIGHTS_CSV.exists():
        return pd.DataFrame(columns=["lat", "lon", "name"])
    try:
        tl = pd.read_csv(TRAFFIC_LIGHTS_CSV)
        if tl.empty:
            return pd.DataFrame(columns=["lat", "lon", "name"])
        tl["lat"] = pd.to_numeric(tl["lat"], errors="coerce")
        tl["lon"] = pd.to_numeric(tl["lon"], errors="coerce")
        tl = tl.dropna(subset=["lat", "lon"])
        return tl
    except Exception:
        return pd.DataFrame(columns=["lat", "lon", "name"])


def classify_stops(
    stops: list[StopEvent],
    tram_stops: pd.DataFrame,
    traffic_lights: pd.DataFrame | None = None,
) -> list[StopEvent]:
    """Classify each stop event based on proximity to tram stops and traffic lights."""
    if traffic_lights is None:
        traffic_lights = load_traffic_lights()

    for stop in stops:
        # Find nearest tram stop
        nearest_tram_dist = float("inf")
        nearest_tram_name = None
        nearest_tram_lat = None
        nearest_tram_lon = None
        for _, ts in tram_stops.iterrows():
            d = haversine(stop.lat, stop.lon, ts["lat"], ts["lon"])
            if d < nearest_tram_dist:
                nearest_tram_dist = d
                nearest_tram_name = ts["stop_name"]
                nearest_tram_lat = ts["lat"]
                nearest_tram_lon = ts["lon"]

        # Find nearest traffic light
        nearest_tl_dist = float("inf")
        nearest_tl_lat = None
        nearest_tl_lon = None
        if not traffic_lights.empty:
            for _, tl in traffic_lights.iterrows():
                d = haversine(stop.lat, stop.lon, tl["lat"], tl["lon"])
                if d < nearest_tl_dist:
                    nearest_tl_dist = d
                    nearest_tl_lat = tl["lat"]
                    nearest_tl_lon = tl["lon"]

        near_tram = nearest_tram_dist <= TRAM_STOP_RADIUS
        near_tl = nearest_tl_dist <= TRAFFIC_LIGHT_RADIUS

        if near_tram and near_tl:
            stop.category = "combined"
            stop.traffic_light_wait = max(0, stop.duration - COMBINED_TRAM_DEDUCT)
            stop.ref_lat = nearest_tram_lat
            stop.ref_lon = nearest_tram_lon
        elif near_tram:
            stop.category = "tram_stop"
            stop.ref_lat = nearest_tram_lat
            stop.ref_lon = nearest_tram_lon
        elif near_tl:
            stop.category = "traffic_light"
            stop.ref_lat = nearest_tl_lat
            stop.ref_lon = nearest_tl_lon
        else:
            stop.category = "bottleneck"

        stop.nearest_stop_name = nearest_tram_name
        stop.nearest_stop_dist = nearest_tram_dist

    return stops
