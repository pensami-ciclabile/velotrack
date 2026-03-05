"""Download and parse Milan GTFS data to extract tram stop locations."""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from velotrack.config import GTFS_DIR, GTFS_URL, TRAM_STOPS_CSV


def _extract_tram_stops_from_gtfs() -> pd.DataFrame:
    """Extract tram stops from raw GTFS data in GTFS_DIR.

    Filter chain: routes (type=0) -> trips -> stop_times -> stops.
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
    return tram_stops


def download_gtfs() -> Path:
    """Download and extract the Milan GTFS zip, then export tram_stops.csv cache."""
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GTFS from {GTFS_URL} ...")
    resp = requests.get(GTFS_URL, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(GTFS_DIR)
    print(f"Extracted to {GTFS_DIR}")

    tram_stops = _extract_tram_stops_from_gtfs()
    TRAM_STOPS_CSV.parent.mkdir(parents=True, exist_ok=True)
    tram_stops.to_csv(TRAM_STOPS_CSV, index=False)
    print(f"Exported {len(tram_stops)} tram stops to {TRAM_STOPS_CSV}")

    return GTFS_DIR


def load_tram_stops() -> pd.DataFrame:
    """Load tram stops from the cached data/tram_stops.csv file.

    Returns DataFrame with columns: stop_id, stop_name, lat, lon.
    """
    if not TRAM_STOPS_CSV.exists():
        print(
            f"Error: {TRAM_STOPS_CSV} not found.\n"
            "Run 'uv run main.py download-gtfs' to generate it, "
            "or provide your own CSV with columns: stop_id, stop_name, lat, lon."
        )
        return pd.DataFrame(columns=["stop_id", "stop_name", "lat", "lon"])

    tram_stops = pd.read_csv(TRAM_STOPS_CSV, dtype={"stop_id": str})
    print(f"Loaded {len(tram_stops)} tram stops from {TRAM_STOPS_CSV}")
    return tram_stops
