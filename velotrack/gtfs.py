"""Download and parse Milan GTFS data to extract tram stop locations."""

import io
import zipfile
from pathlib import Path

import pandas as pd
import requests

from velotrack.config import (
    DAILY_TRIPS_JSON,
    GTFS_DIR,
    GTFS_STOPS_JSON,
    GTFS_URL,
    LINE_STOPS_JSON,
    TRAM_STOPS_CSV,
)


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

    extract_gtfs_stops()
    extract_line_stops_with_coords()
    extract_daily_trips()

    return GTFS_DIR


def extract_gtfs_stops() -> None:
    """Extract tram stop sequences per line from GTFS and save to gtfs_stops.json cache."""
    import json

    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str)
    stop_times = pd.read_csv(
        GTFS_DIR / "stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence"],
        dtype=str,
    )
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    all_stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})

    tram_routes = routes[routes["route_type"] == 0]
    stops_by_line: dict[str, list[str]] = {}
    for _, route in tram_routes.iterrows():
        route_num = route["route_short_name"]
        rt = trips[trips["route_id"] == route["route_id"]]
        for dir_id in ["0", "1"]:
            dt = rt[rt["direction_id"] == dir_id]
            if dt.empty:
                continue
            trip_stop_counts = stop_times[stop_times["trip_id"].isin(dt["trip_id"])].groupby("trip_id").size()
            best_trip = trip_stop_counts.idxmax()
            st = stop_times[stop_times["trip_id"] == best_trip].sort_values("stop_sequence")
            stop_names = st.merge(
                all_stops[["stop_id", "stop_name"]], on="stop_id"
            )["stop_name"].tolist()
            stops_by_line[str(route_num)] = stop_names
            break

    GTFS_STOPS_JSON.write_text(json.dumps(stops_by_line, ensure_ascii=False, indent=2))
    print(f"Exported stop sequences for {len(stops_by_line)} lines to {GTFS_STOPS_JSON}")


def extract_line_stops_with_coords() -> None:
    """Extract per-line stop sequences with coordinates from raw GTFS.

    Same "longest trip per route" logic as extract_gtfs_stops, but also pulls
    stop_id, stop_lat, stop_lon. Output: data/line_stops.json shape:
        {"1": [{"stop_id": "...", "name": "...", "lat": ..., "lon": ...}, ...]}
    """
    import json

    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str)
    stop_times = pd.read_csv(
        GTFS_DIR / "stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence"],
        dtype=str,
    )
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    all_stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})

    tram_routes = routes[routes["route_type"] == 0]
    line_stops: dict[str, list[dict]] = {}
    for _, route in tram_routes.iterrows():
        route_num = str(route["route_short_name"])
        rt = trips[trips["route_id"] == route["route_id"]]
        # Pick the longest trip across both directions (= most stops covered)
        if rt.empty:
            continue
        trip_stop_counts = stop_times[stop_times["trip_id"].isin(rt["trip_id"])].groupby("trip_id").size()
        if trip_stop_counts.empty:
            continue
        best_trip = trip_stop_counts.idxmax()
        st = stop_times[stop_times["trip_id"] == best_trip].sort_values("stop_sequence")
        merged = st.merge(
            all_stops[["stop_id", "stop_name", "stop_lat", "stop_lon"]],
            on="stop_id",
        )
        line_stops[route_num] = [
            {
                "stop_id": str(row["stop_id"]),
                "name": str(row["stop_name"]),
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
            }
            for _, row in merged.iterrows()
        ]

    LINE_STOPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    LINE_STOPS_JSON.write_text(json.dumps(line_stops, ensure_ascii=False, indent=2))
    print(f"Exported per-line stop coordinates for {len(line_stops)} lines to {LINE_STOPS_JSON}")


def build_line_stops_from_cache() -> dict[str, list[dict]]:
    """Build line_stops mapping by joining gtfs_stops.json (names) with
    tram_stops.csv (coords). Used when raw GTFS_DIR is not available.

    Names match in case (both lowercased). For duplicate names (multiple
    platforms/directions), pick the row whose coords are closest to the
    previously chosen stop in the line sequence — a greedy walk along the line.
    """
    import json
    from velotrack.gpx_parser import haversine

    if not GTFS_STOPS_JSON.exists() or not TRAM_STOPS_CSV.exists():
        return {}

    raw = json.loads(GTFS_STOPS_JSON.read_text())
    stops_df = pd.read_csv(TRAM_STOPS_CSV, dtype={"stop_id": str})
    # Index rows by name → list of (stop_id, lat, lon)
    by_name: dict[str, list[tuple[str, float, float]]] = {}
    for _, row in stops_df.iterrows():
        name = str(row["stop_name"]).strip().lower()
        try:
            lat = float(row["lat"])
            lon = float(row["lon"])
        except (TypeError, ValueError):
            continue
        by_name.setdefault(name, []).append((str(row["stop_id"]), lat, lon))

    line_stops: dict[str, list[dict]] = {}
    for line_num, names in raw.items():
        sequence: list[dict] = []
        prev_lat: float | None = None
        prev_lon: float | None = None
        for name in names:
            key = str(name).strip().lower()
            candidates = by_name.get(key, [])
            if not candidates:
                continue
            if len(candidates) == 1 or prev_lat is None:
                sid, lat, lon = candidates[0]
            else:
                sid, lat, lon = min(
                    candidates,
                    key=lambda c: haversine(prev_lat, prev_lon, c[1], c[2]),  # type: ignore[arg-type]
                )
            sequence.append({"stop_id": sid, "name": key, "lat": lat, "lon": lon})
            prev_lat, prev_lon = lat, lon
        if sequence:
            line_stops[str(line_num)] = sequence

    return line_stops


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
