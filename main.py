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

from velotrack.config import MAX_REALISTIC_SPEED, OUTPUT_DIR, RIDES_DIR, TRAFFIC_LIGHTS_CSV
from velotrack.gpx_parser import parse_gpx
from velotrack.gtfs import download_gtfs, load_tram_stops
from velotrack.map_builder import build_map, build_traffic_lights_map
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
            if self.path != "/add":
                self.send_response(404)
                self.end_headers()
                return
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            lat = body["lat"]
            lon = body["lon"]
            name = body.get("name", "")
            notes = body.get("notes", "")
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
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, format, *args):
            pass  # Suppress default request logging

    port = 8000
    server = HTTPServer(("localhost", port), TrafficLightHandler)
    print(f"Serving traffic light map at http://localhost:{port}")
    print(f"Right-click on the map to add new traffic lights.")
    print("Right-click to add, page reloads on submit. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def cmd_analyze(gpx_paths: list[str]):
    if not gpx_paths:
        # Default: all GPX files in rides directory
        gpx_paths = sorted(str(p) for p in RIDES_DIR.glob("*.gpx") if not p.name.startswith("._"))
        if not gpx_paths:
            print(f"No GPX files found. Place .gpx files in {RIDES_DIR}")
            sys.exit(1)

    # Load reference data
    print("Loading tram stops from GTFS...")
    tram_stops = load_tram_stops()
    traffic_lights = load_traffic_lights()

    # Group rides by tram line
    rides_by_line: dict[str, list[tuple[Path, str]]] = defaultdict(list)
    for p in gpx_paths:
        path = Path(p)
        match = re.search(r"line(\d+)_(\w+?)_", path.name)
        line_key = f"line{match.group(1)}_{match.group(2)}" if match else path.stem
        rides_by_line[line_key].append((path, path.name))

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for line_key, ride_files in rides_by_line.items():
        print(f"\nProcessing {line_key} ({len(ride_files)} ride(s))...")
        ride_dfs = []
        all_stops = []
        for ride_path, name in ride_files:
            print(f"  Parsing {name}...")
            df, outlier_count = parse_gpx(ride_path)
            if df.empty:
                print(f"  WARNING: No points in {name}, skipping.")
                continue
            ride_dfs.append(df)
            stops = detect_stops(df)
            stops = classify_stops(stops, tram_stops, traffic_lights)
            all_stops.append(stops)
            if outlier_count > 0:
                print(f"  ⚠ {outlier_count} velocity outliers clamped to {MAX_REALISTIC_SPEED} km/h")
            print(f"  {len(df)} points, {len(stops)} stops detected")

        if not ride_dfs:
            print(f"  No valid rides for {line_key}, skipping.")
            continue

        m = build_map(ride_dfs, all_stops, title=f"Velotrack — {line_key}")
        out_path = OUTPUT_DIR / f"{line_key}.html"
        m.save(str(out_path))
        print(f"  Map saved: {out_path}")

    print("\nDone!")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  uv run main.py download-gtfs          Download Milan GTFS tram stop data")
        print("  uv run main.py template                Create traffic_lights.csv template")
        print("  uv run main.py traffic-lights [--watch]     View traffic lights on a map")
        print("  uv run main.py analyze [files]         Analyze GPX rides and generate maps")
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
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
