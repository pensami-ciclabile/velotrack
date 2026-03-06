"""Download and parse Milan GTFS data to extract tram stop locations."""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from velotrack.config import DAILY_TRIPS_JSON, GTFS_DIR, GTFS_URL, TRAM_STOPS_CSV


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


def extract_daily_trips() -> None:
    """Extract daily trip counts per tram line from GTFS, grouped by day type."""
    import json

    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    tram_routes = routes[routes["route_type"] == 0][["route_id", "route_short_name"]]
    tram_route_ids = set(tram_routes["route_id"])
    # Map route_id -> line number (e.g. "T1" -> "1")
    route_to_line = dict(zip(tram_routes["route_id"], tram_routes["route_short_name"]))

    trips = pd.read_csv(
        GTFS_DIR / "trips.txt", usecols=["route_id", "service_id"], dtype=str
    )
    trips = trips[trips["route_id"].isin(tram_route_ids)].copy()
    trips["line"] = trips["route_id"].map(route_to_line)

    cal = pd.read_csv(GTFS_DIR / "calendar_dates.txt", dtype=str)
    cal = cal[cal["exception_type"] == "1"].copy()
    cal["date"] = pd.to_datetime(cal["date"], format="%Y%m%d")
    cal["dow"] = cal["date"].dt.dayofweek  # 0=Mon, 6=Sun

    # Pick one representative date per day type
    weekday_dates = cal[cal["dow"] < 5]["date"].unique()
    saturday_dates = cal[cal["dow"] == 5]["date"].unique()
    sunday_dates = cal[cal["dow"] == 6]["date"].unique()

    # Use median date for each type (middle of the schedule period)
    def pick_date(dates):
        if len(dates) == 0:
            return None
        s = sorted(dates)
        return s[len(s) // 2]

    result = {"source": "gtfs"}
    for day_type, dates in [
        ("weekday", weekday_dates),
        ("saturday", saturday_dates),
        ("sunday", sunday_dates),
    ]:
        date = pick_date(dates)
        if date is None:
            result[day_type] = {}
            continue
        active_services = set(cal[cal["date"] == date]["service_id"])
        day_trips = trips[trips["service_id"].isin(active_services)]
        counts = day_trips.groupby("line").size().to_dict()
        result[day_type] = {k: int(v) for k, v in counts.items()}
        print(f"  {day_type} ({pd.Timestamp(date).strftime('%Y-%m-%d')}): {sum(counts.values())} tram trips across {len(counts)} lines")

    DAILY_TRIPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    DAILY_TRIPS_JSON.write_text(json.dumps(result, indent=2))
    print(f"Saved: {DAILY_TRIPS_JSON}")


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
