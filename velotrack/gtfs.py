"""Download and parse Milan GTFS data for the lines Velotrack tracks.

The on-disk caches this module produces cover both tram lines and the
"linee di forza" rapid-bus corridors (90, 91, 92, 93). See
``velotrack.lines`` for the classification used throughout.
"""

import io
import json
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
    STOPS_CSV,
)
from velotrack.lines import mode_for_route


def _tracked_routes(routes: pd.DataFrame) -> pd.DataFrame:
    """Return the subset of GTFS routes Velotrack tracks, annotated with mode.

    Input must have at least ``route_short_name`` and ``route_type`` columns.
    The returned frame carries an extra ``mode`` column (`"tram"` or
    `"rapid_bus"`).
    """
    modes = [
        mode_for_route(str(name), int(rtype))
        for name, rtype in zip(routes["route_short_name"], routes["route_type"])
    ]
    out = routes.copy()
    out["mode"] = modes
    tracked: pd.DataFrame = out[out["mode"].notna()]  # type: ignore[assignment]
    return tracked.reset_index(drop=True)


def _extract_stops_from_gtfs() -> pd.DataFrame:
    """Extract the union of tracked stops from raw GTFS data in GTFS_DIR.

    Returns DataFrame with columns: stop_id, stop_name, lat, lon, mode.
    A stop shared by tram + rapid-bus lines is listed once, with the
    highest-priority mode (``tram`` wins, matching historical behaviour).
    """
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    routes["route_type"] = routes["route_type"].astype(int)
    tracked = _tracked_routes(routes)
    route_mode = dict(zip(tracked["route_id"], tracked["mode"]))

    trips = pd.read_csv(GTFS_DIR / "trips.txt", usecols=["route_id", "trip_id"], dtype=str)
    trips = trips[trips["route_id"].isin(route_mode)].copy()
    trip_mode = dict(zip(trips["trip_id"], trips["route_id"].map(route_mode)))

    stop_times = pd.read_csv(GTFS_DIR / "stop_times.txt", usecols=["trip_id", "stop_id"], dtype=str)
    stop_times = stop_times[stop_times["trip_id"].isin(trip_mode)].copy()
    stop_times["mode"] = stop_times["trip_id"].map(trip_mode)

    # For each stop, keep the strongest mode (tram > rapid_bus).
    _mode_rank = {"tram": 0, "rapid_bus": 1}
    stop_to_mode: dict[str, str] = {}
    for sid, mode in zip(stop_times["stop_id"], stop_times["mode"]):
        prev = stop_to_mode.get(sid)
        if prev is None or _mode_rank[mode] < _mode_rank[prev]:
            stop_to_mode[sid] = mode

    stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})
    out = stops[stops["stop_id"].isin(stop_to_mode)][
        ["stop_id", "stop_name", "stop_lat", "stop_lon"]
    ].drop_duplicates(subset="stop_id").reset_index(drop=True)
    out = out.rename(columns={"stop_lat": "lat", "stop_lon": "lon"})
    out["mode"] = out["stop_id"].map(stop_to_mode)
    return out


def download_gtfs() -> Path:
    """Download and extract Milan GTFS, then refresh every local cache."""
    GTFS_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Downloading GTFS from {GTFS_URL} ...")
    # dati.comune.milano.it blocks the default python-requests user agent with
    # a 403, so pass a browser-like UA explicitly.
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    }
    resp = requests.get(GTFS_URL, headers=headers, timeout=120)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        zf.extractall(GTFS_DIR)
    print(f"Extracted to {GTFS_DIR}")

    stops_df = _extract_stops_from_gtfs()
    STOPS_CSV.parent.mkdir(parents=True, exist_ok=True)
    stops_df.to_csv(STOPS_CSV, index=False)
    n_tram = int((stops_df["mode"] == "tram").sum())
    n_bus = int((stops_df["mode"] == "rapid_bus").sum())
    print(
        f"Exported {len(stops_df)} stops to {STOPS_CSV} "
        f"({n_tram} tram · {n_bus} rapid-bus)"
    )

    extract_gtfs_stops()
    extract_line_stops_with_coords()
    extract_daily_trips()

    return GTFS_DIR


def _longest_trip(trip_ids: pd.Series, stop_times: pd.DataFrame) -> str | None:
    """Return the ID of the trip (from ``trip_ids``) that has the most stops."""
    counts = stop_times[stop_times["trip_id"].isin(trip_ids)].groupby("trip_id").size()
    if counts.empty:
        return None
    return counts.idxmax()


def extract_gtfs_stops() -> None:
    """Export stop name sequences per tracked line to ``gtfs_stops.json``.

    For each line we pick the longest trip in direction 0 (or direction 1 if
    0 is missing) — the one that visits the most stops — and record its
    stop-name sequence. Shape: ``{"1": ["foo", "bar", ...], "90": [...]}``.
    """
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    routes["route_type"] = routes["route_type"].astype(int)
    tracked = _tracked_routes(routes)

    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str)
    stop_times = pd.read_csv(
        GTFS_DIR / "stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence"],
        dtype=str,
    )
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    all_stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})

    stops_by_line: dict[str, list[str]] = {}
    for _, route in tracked.iterrows():
        route_num = str(route["route_short_name"])
        rt = trips[trips["route_id"] == route["route_id"]]
        for dir_id in ("0", "1"):
            dt = rt[rt["direction_id"] == dir_id]
            if dt.empty:
                continue
            best_trip = _longest_trip(dt["trip_id"], stop_times)
            if best_trip is None:
                continue
            st = stop_times[stop_times["trip_id"] == best_trip].sort_values("stop_sequence")
            stop_names = st.merge(
                all_stops[["stop_id", "stop_name"]], on="stop_id"
            )["stop_name"].tolist()
            stops_by_line[route_num] = stop_names
            break

    GTFS_STOPS_JSON.write_text(json.dumps(stops_by_line, ensure_ascii=False, indent=2))
    print(f"Exported stop sequences for {len(stops_by_line)} lines to {GTFS_STOPS_JSON}")


def extract_line_stops_with_coords() -> None:
    """Export per-line stop sequences with coordinates to ``line_stops.json``.

    Same "longest trip per route" logic as :func:`extract_gtfs_stops` but
    records stop coordinates too. Shape:
    ``{"1": [{"stop_id": "...", "name": "...", "lat": ..., "lon": ...}, ...]}``
    """
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    routes["route_type"] = routes["route_type"].astype(int)
    tracked = _tracked_routes(routes)

    trips = pd.read_csv(GTFS_DIR / "trips.txt", dtype=str)
    stop_times = pd.read_csv(
        GTFS_DIR / "stop_times.txt",
        usecols=["trip_id", "stop_id", "stop_sequence"],
        dtype=str,
    )
    stop_times["stop_sequence"] = stop_times["stop_sequence"].astype(int)
    all_stops = pd.read_csv(GTFS_DIR / "stops.txt", dtype={"stop_id": str})

    line_stops: dict[str, list[dict]] = {}
    for _, route in tracked.iterrows():
        route_num = str(route["route_short_name"])
        rt = trips[trips["route_id"] == route["route_id"]]
        if rt.empty:
            continue
        best_trip = _longest_trip(rt["trip_id"], stop_times)
        if best_trip is None:
            continue
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
    """Rebuild the per-line stops mapping from ``gtfs_stops.json`` + ``stops.csv``.

    Used when raw GTFS_DIR is not available. Names match case-insensitively
    (both lowercased). For duplicate names (multiple platforms/directions),
    pick the row whose coords are closest to the previously chosen stop —
    a greedy walk along the line.
    """
    from velotrack.gpx_parser import haversine

    if not GTFS_STOPS_JSON.exists() or not STOPS_CSV.exists():
        return {}

    raw = json.loads(GTFS_STOPS_JSON.read_text())
    stops_df = pd.read_csv(STOPS_CSV, dtype={"stop_id": str})
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
    """Extract daily trip counts per tracked line, grouped by day type."""
    routes = pd.read_csv(GTFS_DIR / "routes.txt", dtype={"route_id": str})
    routes["route_type"] = routes["route_type"].astype(int)
    tracked = _tracked_routes(routes)[["route_id", "route_short_name"]]
    tracked_ids = set(tracked["route_id"])
    route_to_line = dict(zip(tracked["route_id"], tracked["route_short_name"]))

    trips = pd.read_csv(
        GTFS_DIR / "trips.txt", usecols=["route_id", "service_id"], dtype=str
    )
    trips = trips[trips["route_id"].isin(tracked_ids)].copy()
    trips["line"] = trips["route_id"].map(route_to_line)

    cal = pd.read_csv(GTFS_DIR / "calendar_dates.txt", dtype=str)
    cal = cal[cal["exception_type"] == "1"].copy()
    cal["date"] = pd.to_datetime(cal["date"], format="%Y%m%d")
    cal["dow"] = cal["date"].dt.dayofweek  # 0=Mon, 6=Sun

    weekday_dates = cal[cal["dow"] < 5]["date"].unique()
    saturday_dates = cal[cal["dow"] == 5]["date"].unique()
    sunday_dates = cal[cal["dow"] == 6]["date"].unique()

    def pick_date(dates):
        if len(dates) == 0:
            return None
        s = sorted(dates)
        return s[len(s) // 2]

    result: dict = {"source": "gtfs"}
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
        print(
            f"  {day_type} ({pd.Timestamp(date).strftime('%Y-%m-%d')}): "
            f"{sum(counts.values())} trips across {len(counts)} lines"
        )

    DAILY_TRIPS_JSON.parent.mkdir(parents=True, exist_ok=True)
    DAILY_TRIPS_JSON.write_text(json.dumps(result, indent=2))
    print(f"Saved: {DAILY_TRIPS_JSON}")


def load_stops() -> pd.DataFrame:
    """Load the cached scheduled-stop table used for stop classification.

    Returns DataFrame with columns: stop_id, stop_name, lat, lon, mode.
    Older cache files without a ``mode`` column are loaded as tram-only
    so upgrades still work before ``download-gtfs`` is re-run.
    """
    if not STOPS_CSV.exists():
        print(
            f"Error: {STOPS_CSV} not found.\n"
            "Run 'uv run main.py download-gtfs' to generate it, "
            "or provide your own CSV with columns: stop_id, stop_name, lat, lon, mode."
        )
        return pd.DataFrame(columns=["stop_id", "stop_name", "lat", "lon", "mode"])

    stops = pd.read_csv(STOPS_CSV, dtype={"stop_id": str})
    if "mode" not in stops.columns:
        stops["mode"] = "tram"
    print(f"Loaded {len(stops)} scheduled stops from {STOPS_CSV}")
    return stops
