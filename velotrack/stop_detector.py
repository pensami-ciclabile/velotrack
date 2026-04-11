"""Detect and classify stop events from parsed GPX data."""

from dataclasses import dataclass

import pandas as pd

from velotrack.config import (
    COMBINED_STOP_DEDUCT,
    STOP_DISTANCE,
    STOP_TIME_GAP,
    TRAFFIC_LIGHT_RADIUS,
    TRANSIT_STOP_RADIUS,
    TRAFFIC_LIGHTS_CSV,
)
from velotrack.gpx_parser import haversine


@dataclass
class StopEvent:
    lat: float
    lon: float
    duration: float  # seconds
    category: str  # transit_stop, traffic_light, combined, bottleneck
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
    scheduled_stops: pd.DataFrame,
    traffic_lights: pd.DataFrame | None = None,
) -> list[StopEvent]:
    """Classify each stop event by proximity to transit stops and traffic lights.

    ``scheduled_stops`` is the union of tram and rapid-bus stops (from
    ``load_stops``); the category is ``transit_stop`` for both modes.
    """
    if traffic_lights is None:
        traffic_lights = load_traffic_lights()

    for stop in stops:
        # Find nearest scheduled transit stop
        nearest_transit_dist = float("inf")
        nearest_transit_name = None
        nearest_transit_lat = None
        nearest_transit_lon = None
        for _, ts in scheduled_stops.iterrows():
            d = haversine(stop.lat, stop.lon, float(ts["lat"]), float(ts["lon"]))
            if d < nearest_transit_dist:
                nearest_transit_dist = d
                nearest_transit_name = str(ts["stop_name"])
                nearest_transit_lat = float(ts["lat"])
                nearest_transit_lon = float(ts["lon"])

        # Find nearest traffic light
        nearest_tl_dist = float("inf")
        nearest_tl_lat = None
        nearest_tl_lon = None
        if not traffic_lights.empty:
            for _, tl in traffic_lights.iterrows():
                d = haversine(stop.lat, stop.lon, float(tl["lat"]), float(tl["lon"]))
                if d < nearest_tl_dist:
                    nearest_tl_dist = d
                    nearest_tl_lat = float(tl["lat"])
                    nearest_tl_lon = float(tl["lon"])

        near_transit = nearest_transit_dist <= TRANSIT_STOP_RADIUS
        near_tl = nearest_tl_dist <= TRAFFIC_LIGHT_RADIUS

        if near_transit and near_tl:
            stop.category = "combined"
            stop.traffic_light_wait = max(0, stop.duration - COMBINED_STOP_DEDUCT)
            stop.ref_lat = nearest_transit_lat
            stop.ref_lon = nearest_transit_lon
        elif near_transit:
            stop.category = "transit_stop"
            stop.ref_lat = nearest_transit_lat
            stop.ref_lon = nearest_transit_lon
        elif near_tl:
            stop.category = "traffic_light"
            stop.ref_lat = nearest_tl_lat
            stop.ref_lon = nearest_tl_lon
        else:
            stop.category = "bottleneck"

        stop.nearest_stop_name = nearest_transit_name
        stop.nearest_stop_dist = nearest_transit_dist

    return stops
