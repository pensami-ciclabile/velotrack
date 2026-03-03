"""Download and parse Milan GTFS data to extract tram stop locations."""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from velotrack.config import GTFS_DIR, GTFS_URL


def download_gtfs() -> Path:
    """Download and extract the Milan GTFS zip to GTFS_DIR."""
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GTFS from {GTFS_URL} ...")
    resp = requests.get(GTFS_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(GTFS_DIR)
    print(f"Extracted to {GTFS_DIR}")
    return GTFS_DIR


def load_tram_stops() -> pd.DataFrame:
    """Load tram stops from GTFS data.

    Filter chain: routes (type=0) → trips → stop_times → stops.
    Returns DataFrame with columns: stop_id, stop_name, lat, lon.
    """
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    tram_routes = routes[routes["route_type"] == 0]
    tram_route_ids = set(tram_routes["route_id"])

    trips = pd.read_csv(GTFS_DIR / "trips.txt", usecols=["route_id", "trip_id"], dtype=str)
    tram_trip_ids = set(trips[trips["route_id"].isin(tram_route_ids)]["trip_id"])

    stop_times = pd.read_csv(GTFS_DIR / "stop_times.txt", usecols=["trip_id", "stop_id"], dtype=str)
    tram_stop_ids = set(stop_times[stop_times["trip_id"].isin(tram_trip_ids)]["stop_id"])

    stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})
    tram_stops = stops[stops["stop_id"].isin(tram_stop_ids)][
        ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    ].drop_duplicates(subset="stop_id").reset_index(drop=True)

    tram_stops = tram_stops.rename(columns={"stop_lat": "lat", "stop_lon": "lon"})
    print(f"Loaded {len(tram_stops)} tram stops")
    return tram_stops
