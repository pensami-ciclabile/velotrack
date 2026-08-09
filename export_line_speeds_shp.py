#!/usr/bin/env python3
"""TEMPORARY one-off exporter: per-line average speed -> ESRI Polyline Shapefile.

Throwaway companion to ``export_traffic_lights_shp.py``. Where that script
exports red-light wait *points*, this one exports, for each tracked line, a
*polyline* broken into short segments, each attributed with the **average speed
across all rides of that line at that position**.

How it works
------------
1. Re-runs the normal Velotrack ride processing (GPX parse -> teleport filter ->
   OSM snapping -> velocity recompute) via ``main._process_rides``, so the speed
   data matches exactly what the site uses. (Requires the project venv, i.e.
   run it with ``uv run``.)
2. For each line it bins every point from every ride into a small square grid
   (default 25 m cells) and computes the mean ``velocity_kmh`` per cell — this
   is the cross-ride "average speed at each position".
3. It draws the route geometry from a reference ride (the one with the greatest
   cumulative distance, which for a transit line usually covers the whole route)
   and emits one 2-vertex polyline feature per segment, tagging each with the
   averaged speed of the grid cell at its midpoint.

Output: a .shp / .shx / .dbf / .prj quartet (WGS84 / EPSG:4326). Style by the
``avg_speed`` field in QGIS (graduated, km/h).

Notes / limitations
-------------------
* All rides of a line are averaged together regardless of travel direction, so a
  cell served in both directions reflects the blended speed. Use --by-direction
  to split features by inferred travel direction instead.
* Geometry comes from a single reference ride; portions only covered by other
  rides won't appear as line geometry (their speeds still feed the averages of
  overlapping cells).

Usage:
    uv run python export_line_speeds_shp.py
    uv run python export_line_speeds_shp.py --output gis/line_speeds --cell-meters 20
    uv run python export_line_speeds_shp.py --line line1_roserio
"""

from __future__ import annotations

import argparse
import datetime as dt
import math
import struct
import sys
from pathlib import Path

# (attr_key, dbf_name<=10 chars, dbf_type, length, decimals)
FIELDS: list[tuple[str, str, str, int, int]] = [
    ("line_key", "line_key", "C", 60, 0),
    ("line_num", "line_num", "C", 8, 0),
    ("direction", "direction", "C", 4, 0),
    ("seg_idx", "seg_idx", "N", 10, 0),
    ("avg_speed", "avg_speed", "N", 10, 2),
    ("ref_speed", "ref_speed", "N", 10, 2),
    ("obs_n", "obs_n", "N", 10, 0),
]


# --------------------------------------------------------------------------- #
# Speed aggregation
# --------------------------------------------------------------------------- #
def _grid_key(lat: float, lon: float, lat0: float, cell_m: float) -> tuple[int, int]:
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * math.cos(math.radians(lat0))
    iy = int(math.floor(lat * m_per_deg_lat / cell_m))
    ix = int(math.floor(lon * m_per_deg_lon / cell_m))
    return ix, iy


def _ride_direction(df) -> str:
    """Crude 8-bin compass direction from a ride's first/last point."""
    if len(df) < 2:
        return "UNK"
    dy = float(df["lat"].iloc[-1]) - float(df["lat"].iloc[0])
    dx = float(df["lon"].iloc[-1]) - float(df["lon"].iloc[0])
    if abs(dx) < 1e-9 and abs(dy) < 1e-9:
        return "UNK"
    bearing = (math.degrees(math.atan2(dy, dx)) + 360.0) % 360.0
    bins = ["E", "NE", "N", "NW", "W", "SW", "S", "SE"]
    return bins[int(((bearing + 22.5) % 360.0) // 45.0)]


def build_grid(ride_dfs, lat0: float, cell_m: float) -> dict[tuple[int, int], tuple[float, int]]:
    """Return {cell: (mean_speed, count)} across all given rides."""
    sums: dict[tuple[int, int], float] = {}
    counts: dict[tuple[int, int], int] = {}
    for df in ride_dfs:
        for lat, lon, spd in zip(df["lat"].values, df["lon"].values, df["velocity_kmh"].values):
            if spd != spd:  # NaN guard
                continue
            key = _grid_key(float(lat), float(lon), lat0, cell_m)
            sums[key] = sums.get(key, 0.0) + float(spd)
            counts[key] = counts.get(key, 0) + 1
    return {k: (sums[k] / counts[k], counts[k]) for k in counts}


def _pick_reference(ride_dfs):
    """Reference ride = the one with the greatest cumulative distance."""
    best, best_dist = None, -1.0
    for df in ride_dfs:
        if len(df) < 2:
            continue
        d = float(df["dist"].sum())
        if d > best_dist:
            best, best_dist = df, d
    return best


def build_line_segments(line_key, ride_dfs, cell_m, by_direction):
    """Yield segment features (vertices + attrs) for one line."""
    if by_direction:
        groups: dict[str, list] = {}
        for df in ride_dfs:
            groups.setdefault(_ride_direction(df), []).append(df)
    else:
        groups = {"": ride_dfs}

    line_num = line_key[4:].split("_", 1)[0] if line_key.startswith("line") else ""

    for direction, dfs in groups.items():
        usable = [df for df in dfs if len(df) >= 2]
        if not usable:
            continue
        all_lats = [float(v) for df in usable for v in df["lat"].values]
        lat0 = sum(all_lats) / len(all_lats)
        grid = build_grid(usable, lat0, cell_m)
        ref = _pick_reference(usable)
        if ref is None:
            continue

        lats = ref["lat"].values
        lons = ref["lon"].values
        dists = ref["dist"].values
        speeds = ref["velocity_kmh"].values

        for i in range(1, len(ref)):
            # dist==0 marks a teleport-gap boundary: don't bridge it.
            if float(dists[i]) == 0.0:
                continue
            x1, y1 = float(lons[i - 1]), float(lats[i - 1])
            x2, y2 = float(lons[i]), float(lats[i])
            mid_lat = (y1 + y2) / 2.0
            mid_lon = (x1 + x2) / 2.0
            cell = _grid_key(mid_lat, mid_lon, lat0, cell_m)
            mean_spd, obs_n = grid.get(cell, (float(speeds[i]), 0))
            yield {
                "vertices": [(x1, y1), (x2, y2)],
                "attrs": {
                    "line_key": line_key,
                    "line_num": line_num,
                    "direction": direction or "ALL",
                    "seg_idx": i,
                    "avg_speed": round(mean_spd, 2),
                    "ref_speed": round(float(speeds[i]), 2),
                    "obs_n": obs_n,
                },
            }


# --------------------------------------------------------------------------- #
# Shapefile writers (stdlib only)
# --------------------------------------------------------------------------- #
def _fmt_field(value, ftype: str, length: int, decimals: int) -> bytes:
    if ftype == "N":
        if value is None or value == "":
            text = ""
        elif decimals > 0:
            text = f"{float(value):.{decimals}f}"
        else:
            text = f"{int(round(float(value)))}"
        text = text[:length].rjust(length)
    else:
        text = "" if value is None else str(value)
        text = text[:length].ljust(length)
    return text.encode("ascii", "replace")


def write_dbf(path: Path, features: list[dict]) -> None:
    record_length = 1 + sum(f[3] for f in FIELDS)
    header_length = 32 + 32 * len(FIELDS) + 1
    today = dt.date.today()

    buf = bytearray()
    buf += struct.pack("<B", 0x03)
    buf += struct.pack("<3B", today.year % 100, today.month, today.day)
    buf += struct.pack("<I", len(features))
    buf += struct.pack("<H", header_length)
    buf += struct.pack("<H", record_length)
    buf += b"\x00" * 20

    for _key, name, ftype, length, decimals in FIELDS:
        buf += name.encode("ascii")[:11].ljust(11, b"\x00")
        buf += ftype.encode("ascii")
        buf += b"\x00" * 4
        buf += struct.pack("<B", length)
        buf += struct.pack("<B", decimals)
        buf += b"\x00" * 14
    buf += b"\x0D"

    for feat in features:
        buf += b"\x20"
        attrs = feat["attrs"]
        for key, _name, ftype, length, decimals in FIELDS:
            buf += _fmt_field(attrs.get(key), ftype, length, decimals)
    buf += b"\x1A"

    path.write_bytes(buf)


def write_shp_shx(shp_path: Path, shx_path: Path, features: list[dict]) -> None:
    all_x = [x for f in features for x, _ in f["vertices"]] or [0.0]
    all_y = [y for f in features for _, y in f["vertices"]] or [0.0]
    xmin, xmax, ymin, ymax = min(all_x), max(all_x), min(all_y), max(all_y)

    POLYLINE = 3

    def header(file_length_words: int) -> bytes:
        h = bytearray(100)
        struct.pack_into(">i", h, 0, 9994)
        struct.pack_into(">i", h, 24, file_length_words)
        struct.pack_into("<i", h, 28, 1000)
        struct.pack_into("<i", h, 32, POLYLINE)
        struct.pack_into("<4d", h, 36, xmin, ymin, xmax, ymax)
        return bytes(h)

    shp = bytearray(b"\x00" * 100)
    shx = bytearray(b"\x00" * 100)
    offset_words = 50

    for i, feat in enumerate(features, start=1):
        verts = feat["vertices"]
        xs = [x for x, _ in verts]
        ys = [y for _, y in verts]
        n = len(verts)

        content = bytearray()
        content += struct.pack("<i", POLYLINE)
        content += struct.pack("<4d", min(xs), min(ys), max(xs), max(ys))
        content += struct.pack("<i", 1)            # numParts
        content += struct.pack("<i", n)            # numPoints
        content += struct.pack("<i", 0)            # part 0 start index
        for x, y in verts:
            content += struct.pack("<2d", x, y)

        content_words = len(content) // 2
        shp += struct.pack(">ii", i, content_words)
        shp += content
        shx += struct.pack(">ii", offset_words, content_words)
        offset_words += 4 + content_words

    shp[:100] = header(len(shp) // 2)
    shx[:100] = header(50 + len(features) * 4)

    shp_path.write_bytes(shp)
    shx_path.write_bytes(shx)


PRJ_WGS84 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="gis/line_speeds",
                        help="output basename (without extension)")
    parser.add_argument("--cell-meters", type=float, default=25.0,
                        help="grid cell size in meters for speed averaging")
    parser.add_argument("--line", default=None,
                        help="only export this line_key (e.g. line1_roserio)")
    parser.add_argument("--by-direction", action="store_true",
                        help="split features by inferred travel direction")
    args = parser.parse_args(argv)

    # Imported lazily so --help works without the project venv.
    from main import _process_rides

    rides_by_line, _scheduled_stops, _traffic_lights = _process_rides()

    features: list[dict] = []
    for line_key, data in rides_by_line.items():
        if args.line and line_key != args.line:
            continue
        ride_dfs = [df for df in data["ride_dfs"] if not df.empty]
        if not ride_dfs:
            continue
        features.extend(
            build_line_segments(line_key, ride_dfs, args.cell_meters, args.by_direction)
        )

    if not features:
        print("ERROR: no segments produced. Are there GPX rides in data/rides/?",
              file=sys.stderr)
        return 1

    base = Path(args.output)
    base.parent.mkdir(parents=True, exist_ok=True)
    write_shp_shx(base.with_suffix(".shp"), base.with_suffix(".shx"), features)
    write_dbf(base.with_suffix(".dbf"), features)
    base.with_suffix(".prj").write_text(PRJ_WGS84, encoding="utf-8")

    n_lines = len({f["attrs"]["line_key"] for f in features})
    print(f"Wrote {len(features)} segments across {n_lines} line(s) to "
          f"{base}.shp (+ .shx/.dbf/.prj), EPSG:4326")
    print(f"Cell size: {args.cell_meters} m · style by 'avg_speed' (km/h) in QGIS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
