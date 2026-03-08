"""Velotrack CLI — Milan tram GPS ride analysis."""

import csv
import getpass
import io
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from velotrack.config import (
    MAPS_DIR,
    MAX_REALISTIC_SPEED,
    OUTPUT_DIR,
    RIDES_DIR,
    TRAFFIC_LIGHTS_CSV,
)
from velotrack.gpx_parser import parse_gpx
from velotrack.gtfs import download_gtfs, load_tram_stops
from velotrack.location_analytics import (
    aggregate_location_events,
    build_hotspot_slices,
    build_normalized_events,
    serialize_location_aggregates,
)
from velotrack.map_builder import build_map, build_traffic_lights_map, compute_line_stats
from velotrack.stop_detector import classify_stops, detect_stops, load_traffic_lights


def cmd_download_gtfs():
    download_gtfs()
    print("GTFS download complete.")


def cmd_template():
    TRAFFIC_LIGHTS_CSV.parent.mkdir(parents=True, exist_ok=True)
    if TRAFFIC_LIGHTS_CSV.exists():
        print(f"Template already exists: {TRAFFIC_LIGHTS_CSV}")
    else:
        TRAFFIC_LIGHTS_CSV.write_text("lat,lon,name,notes\n")
        print(f"Created template: {TRAFFIC_LIGHTS_CSV}")


def _ensure_csv_columns():
    """Ensure the CSV has added_at and added_by columns in its header."""
    if not TRAFFIC_LIGHTS_CSV.exists():
        return
    with open(TRAFFIC_LIGHTS_CSV) as f:
        first_line = f.readline().strip()
    if "added_at" not in first_line:
        content = TRAFFIC_LIGHTS_CSV.read_text()
        content = content.replace(
            first_line, first_line + ",added_at,added_by", 1
        )
        TRAFFIC_LIGHTS_CSV.write_text(content)


def _remove_traffic_light_from_csv(lat: float, lon: float, tolerance: float = 1e-7) -> bool:
    """Remove first traffic light matching lat/lon within tolerance. Returns True if removed."""
    if not TRAFFIC_LIGHTS_CSV.exists():
        return False

    with open(TRAFFIC_LIGHTS_CSV, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fieldnames = reader.fieldnames

    if not fieldnames:
        return False

    removed = False
    kept_rows: list[dict[str, str]] = []
    for row in rows:
        if removed:
            kept_rows.append(row)
            continue

        try:
            row_lat = float(row.get("lat", ""))
            row_lon = float(row.get("lon", ""))
        except (TypeError, ValueError):
            kept_rows.append(row)
            continue

        if abs(row_lat - lat) <= tolerance and abs(row_lon - lon) <= tolerance:
            removed = True
            continue

        kept_rows.append(row)

    if not removed:
        return False

    with open(TRAFFIC_LIGHTS_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept_rows)

    return True


def cmd_traffic_lights(watch: bool = False):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / "traffic_lights.html"

    def generate():
        tl = load_traffic_lights()
        m = build_traffic_lights_map(tl, server_mode=watch)
        m.save(str(out_path))
        return len(tl)

    if not watch:
        count = generate()
        print(f"Map saved: {out_path} ({count} traffic lights)")
        return

    # Ensure CSV has the new columns
    _ensure_csv_columns()

    class TrafficLightHandler(BaseHTTPRequestHandler):
        def _send_json(self, status_code: int, payload: dict):
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            # Regenerate map on every request
            generate()
            html = out_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            if self.path not in ("/add", "/remove"):
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self._send_json(400, {"ok": False, "error": "invalid_json"})
                return

            if self.path == "/add":
                try:
                    lat = float(body["lat"])
                    lon = float(body["lon"])
                except (KeyError, TypeError, ValueError):
                    self._send_json(400, {"ok": False, "error": "invalid_coordinates"})
                    return
                name = str(body.get("name", "")).strip()
                if not name:
                    self._send_json(400, {"ok": False, "error": "name_required"})
                    return
                notes = str(body.get("notes", "")).strip()
                added_at = datetime.now(timezone.utc).isoformat()
                added_by = getpass.getuser()

                # Append to CSV
                TRAFFIC_LIGHTS_CSV.parent.mkdir(parents=True, exist_ok=True)
                if not TRAFFIC_LIGHTS_CSV.exists():
                    TRAFFIC_LIGHTS_CSV.write_text("lat,lon,name,notes,added_at,added_by\n")
                    _ensure_csv_columns()

                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow([lat, lon, name, notes, added_at, added_by])
                with open(TRAFFIC_LIGHTS_CSV, "a") as f:
                    f.write(buf.getvalue())

                print(f"  Added: {name} ({lat}, {lon})")
                self._send_json(200, {"ok": True})
                return

            try:
                lat = float(body["lat"])
                lon = float(body["lon"])
            except (KeyError, TypeError, ValueError):
                self._send_json(400, {"ok": False, "error": "invalid_coordinates"})
                return

            removed = _remove_traffic_light_from_csv(lat, lon)
            if removed:
                print(f"  Removed: ({lat}, {lon})")
            self._send_json(200, {"ok": True, "removed": removed})

        def log_message(self, format, *args):
            pass  # Suppress default request logging

    port = 8000
    server = HTTPServer(("localhost", port), TrafficLightHandler)
    print(f"Serving traffic light map at http://localhost:{port}")
    print("Right-click to add new traffic lights.")
    print("Click an existing red dot to remove it.")
    print("Map reloads after add/remove. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def _process_rides(gpx_paths: list[str] | None = None):
    """Parse GPX files, detect stops, group by line. Returns (rides_by_line, tram_stops, traffic_lights).

    Each value in rides_by_line is a dict with keys: ride_dfs, all_stops, ride_files.
    """
    if not gpx_paths:
        gpx_paths = sorted(str(p) for p in RIDES_DIR.glob("*.gpx") if not p.name.startswith("._"))
        if not gpx_paths:
            print(f"No GPX files found. Place .gpx files in {RIDES_DIR}")
            sys.exit(1)

    print("Loading tram stops from GTFS...")
    tram_stops = load_tram_stops()
    traffic_lights = load_traffic_lights()

    # Group files by tram line
    files_by_line: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for p in gpx_paths:
        path = Path(p)
        match = re.search(r"line(\d+)_([\w.\-]+?)_", path.name)
        line_key = f"line{match.group(1)}_{match.group(2)}" if match else path.stem
        files_by_line[line_key].append((path, path.name))

    # Parse and detect stops
    rides_by_line: dict[str, dict] = {}
    for line_key, ride_files in files_by_line.items():
        print(f"\nProcessing {line_key} ({len(ride_files)} ride(s))...")
        ride_dfs = []
        all_stops = []
        valid_ride_files: list[tuple[Path, str]] = []
        for ride_path, name in ride_files:
            print(f"  Parsing {name}...")
            df, outlier_count = parse_gpx(ride_path)
            if df.empty:
                print(f"  WARNING: No points in {name}, skipping.")
                continue
            ride_dfs.append(df)
            valid_ride_files.append((ride_path, name))
            stops = detect_stops(df)
            stops = classify_stops(stops, tram_stops, traffic_lights)
            all_stops.append(stops)
            if outlier_count > 0:
                print(f"  ⚠ {outlier_count} velocity outliers clamped to {MAX_REALISTIC_SPEED} km/h")
            print(f"  {len(df)} points, {len(stops)} stops detected")

        if ride_dfs:
            rides_by_line[line_key] = {
                "ride_dfs": ride_dfs,
                "all_stops": all_stops,
                "ride_files": valid_ride_files,
            }
        else:
            print(f"  No valid rides for {line_key}, skipping.")

    return rides_by_line, tram_stops, traffic_lights


def cmd_analyze(gpx_paths: list[str]):
    rides_by_line, tram_stops, traffic_lights = _process_rides(gpx_paths or None)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for line_key, data in rides_by_line.items():
        m = build_map(
            data["ride_dfs"], data["all_stops"], title=f"Velotrack — {line_key}",
            tram_stops=tram_stops, traffic_lights=traffic_lights,
        )
        out_path = OUTPUT_DIR / f"{line_key}.html"
        m.save(str(out_path))
        print(f"  Map saved: {out_path}")

    print("\nDone!")


def cmd_extract_trips():
    from velotrack.gtfs import extract_daily_trips
    extract_daily_trips()


def cmd_build_site():
    from velotrack.site_builder import LineInfo, build_site

    rides_by_line, tram_stops, traffic_lights = _process_rides()

    MAPS_DIR.mkdir(parents=True, exist_ok=True)

    # Build per-line maps and collect stats
    line_infos: list[LineInfo] = []
    for line_key, data in rides_by_line.items():
        ride_dfs = data["ride_dfs"]
        all_stops = data["all_stops"]

        # Save map to site/maps/
        m = build_map(
            ride_dfs, all_stops, title=f"Velotrack — {line_key}",
            tram_stops=tram_stops, traffic_lights=traffic_lights,
        )
        m.save(str(MAPS_DIR / f"{line_key}.html"))
        print(f"  Map saved: {MAPS_DIR / f'{line_key}.html'}")

        # Compute stats
        stats = compute_line_stats(ride_dfs, all_stops)

        # Total distance from all rides
        total_dist_km = sum(
            df["dist"].sum() / 1000 for df in ride_dfs if not df.empty
        )

        # Display name: line1_roserio → Line 1 — Roserio
        match_dn = re.search(r"line(\d+)_(.*)", line_key)
        if match_dn:
            words = match_dn.group(2).replace("-", " ").split()
            dest = " ".join(w[0].upper() + w[1:] for w in words)
            display_name = f"Line {match_dn.group(1)} — {dest}"
        else:
            display_name = line_key

        line_infos.append(LineInfo(
            line_key=line_key,
            display_name=display_name,
            num_rides=len(data["ride_files"]),
            stats=stats,
            total_distance_km=round(total_dist_km, 1),
        ))

    # Build global location analytics (one row per physical hotspot + nested breakdowns)
    normalized_events = build_normalized_events(rides_by_line)
    location_aggregates = aggregate_location_events(normalized_events)
    hotspot_slices = build_hotspot_slices(location_aggregates, limit=25)

    # Build traffic lights map into site/maps/
    tl = load_traffic_lights()
    tl_map = build_traffic_lights_map(tl)
    tl_map.save(str(MAPS_DIR / "traffic_lights.html"))
    print(f"  Traffic lights map saved: {MAPS_DIR / 'traffic_lights.html'}")

    # Render the site
    build_site(
        line_infos,
        location_stats=serialize_location_aggregates(location_aggregates),
        hotspot_slices=hotspot_slices,
    )
    print("\nSite build complete!")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run main.py download-gtfs          Download Milan GTFS tram stop data")
        print("  uv run main.py template                Create traffic_lights.csv template")
        print("  uv run main.py traffic-lights [--watch]     View traffic lights on a map")
        print("  uv run main.py analyze [files]         Analyze GPX rides and generate maps")
        print("  uv run main.py extract-trips           Extract daily trip counts from GTFS")
        print("  uv run main.py build-site              Build static website for GitHub Pages")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "download-gtfs":
        cmd_download_gtfs()
    elif cmd == "template":
        cmd_template()
    elif cmd == "traffic-lights":
        args = sys.argv[2:]
        if "--watch" in args:
            cmd_traffic_lights(watch=True)
        else:
            cmd_traffic_lights()
    elif cmd == "analyze":
        cmd_analyze(sys.argv[2:])
    elif cmd == "extract-trips":
        cmd_extract_trips()
    elif cmd == "build-site":
        cmd_build_site()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
