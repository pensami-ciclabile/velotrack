#!/usr/bin/env python3
"""TEMPORARY one-off exporter: traffic-light wait-time hotspots -> ESRI Shapefile.

This is a throwaway utility (no project dependencies, stdlib only) to get the
per-location red-light wait statistics into a point shapefile you can drop into
QGIS next to a separate priority/reserved-lanes layer.

Input : site/data/location_stats.json  (produced by `uv run main.py build-site`)
Output: a .shp / .shx / .dbf / .prj quartet (WGS84 / EPSG:4326).

By default only the light-related categories are exported (traffic_light,
combined), since those are the locations whose `mean_wait_s` represents
red-light waiting time. Use --categories all to export everything.

Usage:
    python3 export_traffic_lights_shp.py
    python3 export_traffic_lights_shp.py --input site/data/location_stats.json \
        --output gis/traffic_lights --categories traffic_light combined
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import struct
import sys
from pathlib import Path

# (json_key, dbf_name<=10 chars, dbf_type, length, decimals)
# Shapefile/DBF field names are capped at 10 characters.
FIELDS: list[tuple[str, str, str, int, int]] = [
    ("location_key", "loc_key", "C", 80, 0),
    ("category", "category", "C", 16, 0),
    ("lat", "lat", "N", 19, 9),
    ("lon", "lon", "N", 19, 9),
    ("obs_count", "obs_n", "N", 10, 0),
    ("mean_wait_s", "mean_wait", "N", 12, 3),
    ("median_wait_s", "med_wait", "N", 12, 3),
    ("p25_s", "p25", "N", 12, 3),
    ("p75_s", "p75", "N", 12, 3),
    ("min_s", "min_wait", "N", 12, 3),
    ("max_s", "max_wait", "N", 12, 3),
    ("line_count", "line_n", "N", 10, 0),
    ("__lines__", "lines", "C", 200, 0),  # synthesized: comma-joined line_keys
]


def load_records(path: Path, categories: set[str] | None) -> list[dict]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    rows = raw if isinstance(raw, list) else raw.get("hotspots") or raw.get("locations") or []
    out: list[dict] = []
    for row in rows:
        if "lat" not in row or "lon" not in row:
            continue
        if categories and row.get("category") not in categories:
            continue
        rec = dict(row)
        rec["__lines__"] = ",".join(str(k) for k in row.get("line_keys", []))
        out.append(rec)
    return out


def _fmt_field(value, ftype: str, length: int, decimals: int) -> bytes:
    if ftype == "N":
        if value is None or value == "":
            text = ""
        elif decimals > 0:
            text = f"{float(value):.{decimals}f}"
        else:
            text = f"{int(round(float(value)))}"
        text = text[:length].rjust(length)
    else:  # 'C'
        text = "" if value is None else str(value)
        text = text[:length].ljust(length)
    return text.encode("ascii", "replace")


def write_dbf(path: Path, records: list[dict]) -> None:
    record_length = 1 + sum(f[3] for f in FIELDS)
    header_length = 32 + 32 * len(FIELDS) + 1
    today = dt.date.today()

    buf = bytearray()
    buf += struct.pack("<B", 0x03)
    buf += struct.pack("<3B", today.year % 100, today.month, today.day)
    buf += struct.pack("<I", len(records))
    buf += struct.pack("<H", header_length)
    buf += struct.pack("<H", record_length)
    buf += b"\x00" * 20  # reserved

    for _json_key, name, ftype, length, decimals in FIELDS:
        buf += name.encode("ascii")[:11].ljust(11, b"\x00")
        buf += ftype.encode("ascii")
        buf += b"\x00" * 4  # field data address
        buf += struct.pack("<B", length)
        buf += struct.pack("<B", decimals)
        buf += b"\x00" * 14
    buf += b"\x0D"  # header terminator

    for rec in records:
        buf += b"\x20"  # not-deleted flag
        for json_key, _name, ftype, length, decimals in FIELDS:
            buf += _fmt_field(rec.get(json_key), ftype, length, decimals)
    buf += b"\x1A"  # EOF marker

    path.write_bytes(buf)


def write_shp_shx(shp_path: Path, shx_path: Path, records: list[dict]) -> None:
    lons = [float(r["lon"]) for r in records] or [0.0]
    lats = [float(r["lat"]) for r in records] or [0.0]
    xmin, xmax, ymin, ymax = min(lons), max(lons), min(lats), max(lats)

    def header(file_length_words: int) -> bytes:
        h = bytearray(100)
        struct.pack_into(">i", h, 0, 9994)            # file code
        struct.pack_into(">i", h, 24, file_length_words)
        struct.pack_into("<i", h, 28, 1000)           # version
        struct.pack_into("<i", h, 32, 1)              # shape type: point
        struct.pack_into("<4d", h, 36, xmin, ymin, xmax, ymax)
        # Z and M ranges left at 0
        return bytes(h)

    POINT_CONTENT_WORDS = 10  # (4 + 8 + 8) bytes = 20 bytes = 10 16-bit words

    shp = bytearray(b"\x00" * 100)
    shx = bytearray(b"\x00" * 100)
    offset_words = 50  # SHP records start right after the 100-byte (50-word) header

    for i, rec in enumerate(records, start=1):
        x, y = float(rec["lon"]), float(rec["lat"])
        shp += struct.pack(">ii", i, POINT_CONTENT_WORDS)  # record header
        shp += struct.pack("<i", 1)                        # shape type point
        shp += struct.pack("<dd", x, y)
        shx += struct.pack(">ii", offset_words, POINT_CONTENT_WORDS)
        offset_words += 4 + POINT_CONTENT_WORDS            # 4-word record header + content

    shp[:100] = header(len(shp) // 2)
    shx[:100] = header(50 + len(records) * 4)

    shp_path.write_bytes(shp)
    shx_path.write_bytes(shx)


PRJ_WGS84 = (
    'GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",'
    'SPHEROID["WGS_1984",6378137.0,298.257223563]],'
    'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]'
)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", default="site/data/location_stats.json",
                        help="path to location_stats.json")
    parser.add_argument("--output", default="gis/traffic_lights",
                        help="output basename (without extension)")
    parser.add_argument("--categories", nargs="+",
                        default=["traffic_light", "combined"],
                        help="categories to keep, or 'all'")
    args = parser.parse_args(argv)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: {in_path} not found.\n"
              f"Generate it first with:  uv run main.py build-site", file=sys.stderr)
        return 1

    categories = None if "all" in args.categories else set(args.categories)
    records = load_records(in_path, categories)
    if not records:
        print("ERROR: no matching records found.", file=sys.stderr)
        return 1

    base = Path(args.output)
    base.parent.mkdir(parents=True, exist_ok=True)
    write_shp_shx(base.with_suffix(".shp"), base.with_suffix(".shx"), records)
    write_dbf(base.with_suffix(".dbf"), records)
    base.with_suffix(".prj").write_text(PRJ_WGS84, encoding="utf-8")

    print(f"Wrote {len(records)} points to {base}.shp (+ .shx/.dbf/.prj), EPSG:4326")
    print(f"Categories: {sorted(categories) if categories else 'all'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
