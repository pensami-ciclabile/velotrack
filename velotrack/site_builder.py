"""Build the static website from Jinja2 templates and line data."""

import json
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from velotrack.config import (
    DAILY_TRIPS_JSON,
    DATA_DIR_SITE,
    LINES_DIR,
    MAPS_DIR,
    SITE_DIR,
    TEMPLATES_DIR,
)


@dataclass
class LineInfo:
    line_key: str
    display_name: str
    num_rides: int
    stats: dict
    total_distance_km: float


def _destination_name(line_key: str) -> str:
    """Extract destination from line_key, e.g. 'line1_roserio' → 'Roserio'."""
    parts = line_key.split("_", 1)
    if len(parts) > 1:
        words = parts[1].replace("-", " ").split()
        return " ".join(w[0].upper() + w[1:] for w in words)
    return ""


def _display_name(line_key: str) -> str:
    """Convert 'line1_roserio' → 'Line 1 — Roserio'."""
    match = re.search(r"line(\d+)", line_key)
    num = match.group(1) if match else ""
    dest = _destination_name(line_key)
    return f"Line {num} — {dest}".strip(" —")


def _display_name_it(line_key: str) -> str:
    """Convert 'line1_roserio' → 'Linea 1 — Roserio'."""
    match = re.search(r"line(\d+)", line_key)
    num = match.group(1) if match else ""
    dest = _destination_name(line_key)
    return f"Linea {num} — {dest}".strip(" —")


def _group_lines(lines: list[LineInfo]) -> list[dict]:
    """Group lines by line number for the home page.

    Returns list of {"line_number": int, "directions": [LineInfo, ...]}
    sorted by line number.
    """
    groups: dict[int, list[LineInfo]] = {}
    for li in lines:
        match = re.search(r"line(\d+)", li.line_key)
        if match:
            num = int(match.group(1))
            groups.setdefault(num, []).append(li)
        else:
            groups.setdefault(0, []).append(li)

    return [
        {"line_number": num, "directions": dirs}
        for num, dirs in sorted(groups.items())
    ]


def build_site(lines: list[LineInfo]) -> None:
    """Render the full static site into SITE_DIR."""
    # Prepare output dirs
    for d in (SITE_DIR, MAPS_DIR, LINES_DIR, DATA_DIR_SITE):
        d.mkdir(parents=True, exist_ok=True)

    # Copy static assets
    css_dir = SITE_DIR / "css"
    js_dir = SITE_DIR / "js"
    css_dir.mkdir(parents=True, exist_ok=True)
    js_dir.mkdir(parents=True, exist_ok=True)

    static_src = TEMPLATES_DIR / "static"
    shutil.copy2(static_src / "css" / "style.css", css_dir / "style.css")
    shutil.copy2(static_src / "js" / "main.js", js_dir / "main.js")

    # Export lines.json
    lines_data = [asdict(li) for li in lines]
    (DATA_DIR_SITE / "lines.json").write_text(json.dumps(lines_data, indent=2))

    # Group lines by number for home page
    grouped_lines = _group_lines(lines)

    # Compute traffic light hours lost (if trip counts available)
    tl_hours = None
    tl_lines_count = 0
    tl_total_lines = 17
    tl_breakdown = []
    if DAILY_TRIPS_JSON.exists():
        daily_trips = json.loads(DAILY_TRIPS_JSON.read_text())
        # Group directions by line number, averaging tl_wait across directions
        line_tl_wait: dict[str, list[float]] = {}
        line_directions: dict[str, list[str]] = {}
        for li in lines:
            match = re.search(r"line(\d+)", li.line_key)
            if not match:
                continue
            line_num = match.group(1)
            tl_wait = li.stats.get("tl_wait_total", 0)
            if tl_wait > 0:
                line_tl_wait.setdefault(line_num, []).append(tl_wait)
                line_directions.setdefault(line_num, []).append(li.line_key)
        tl_hours = {}
        for day_type in ("weekday", "saturday", "sunday"):
            trip_counts = daily_trips.get(day_type, {})
            total_seconds = 0.0
            matched_lines = set()
            for line_num, waits in line_tl_wait.items():
                if line_num in trip_counts:
                    avg_wait = sum(waits) / len(waits)
                    total_seconds += trip_counts[line_num] * avg_wait
                    matched_lines.add(line_num)
            tl_hours[day_type] = round(total_seconds / 3600, 1)
            if day_type == "weekday":
                tl_lines_count = len(matched_lines)
        # Build per-line breakdown for footnote (weekday)
        weekday_trips = daily_trips.get("weekday", {})
        for line_num in sorted(line_tl_wait, key=int):
            if line_num not in weekday_trips:
                continue
            waits = line_tl_wait[line_num]
            avg_wait = sum(waits) / len(waits)
            trips = weekday_trips[line_num]
            dirs = line_directions[line_num]
            tl_breakdown.append({
                "line": line_num,
                "tl_wait_s": round(avg_wait, 1),
                "directions": len(dirs),
                "trips": trips,
                "hours": round(trips * avg_wait / 3600, 1),
            })

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.globals["destination_name"] = _destination_name
    env.globals["display_name"] = _display_name
    env.globals["display_name_it"] = _display_name_it

    # Render home page
    tmpl = env.get_template("home.html")
    (SITE_DIR / "index.html").write_text(
        tmpl.render(
            grouped_lines=grouped_lines,
            lines=lines,
            root_path=".",
            tl_hours=tl_hours,
            tl_lines_count=tl_lines_count,
            tl_total_lines=tl_total_lines,
            tl_breakdown=tl_breakdown,
        )
    )

    # Render line detail pages
    tmpl = env.get_template("line_detail.html")
    for li in lines:
        (LINES_DIR / f"{li.line_key}.html").write_text(
            tmpl.render(line=li, root_path="..")
        )

    print(f"Site built: {SITE_DIR}")
