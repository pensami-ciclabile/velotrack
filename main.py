"""Velotrack CLI — Milan tram GPS ride analysis."""

import re
import sys
from collections import defaultdict
from pathlib import Path

from velotrack.config import MAX_REALISTIC_SPEED, OUTPUT_DIR, RIDES_DIR, TRAFFIC_LIGHTS_CSV
from velotrack.gpx_parser import parse_gpx
from velotrack.gtfs import download_gtfs, load_tram_stops
from velotrack.map_builder import build_map
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
        match = re.search(r"line(\d+)_", path.name)
        line_key = f"line{match.group(1)}" if match else path.stem
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
        print("  uv run main.py download-gtfs    Download Milan GTFS tram stop data")
        print("  uv run main.py template          Create traffic_lights.csv template")
        print("  uv run main.py analyze [files]   Analyze GPX rides and generate maps")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "download-gtfs":
        cmd_download_gtfs()
    elif cmd == "template":
        cmd_template()
    elif cmd == "analyze":
        cmd_analyze(sys.argv[2:])
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
