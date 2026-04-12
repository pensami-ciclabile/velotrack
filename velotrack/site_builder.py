"""Build the static website from Jinja2 templates and line data."""

import json
import re
import shutil
from dataclasses import dataclass, asdict, field
from typing import Any

from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from velotrack.config import (
    DAILY_TRIPS_JSON,
    DATA_DIR_SITE,
    GTFS_STOPS_JSON,
    LINES_DIR,
    MAPS_DIR,
    SITE_DIR,
    TEMPLATES_DIR,
)
from velotrack.lines import MODE_LABELS, RAPID_BUS, TRAM, mode_for_line_number


@dataclass
class LineInfo:
    line_key: str
    display_name: str
    num_rides: int
    stats: dict
    total_distance_km: float
    mode: str = field(default=TRAM)

    def __post_init__(self) -> None:
        match = re.search(r"line(\d+)", self.line_key)
        if match:
            self.mode = mode_for_line_number(match.group(1))


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
    """Group lines by mode, then by line number, for the home page.

    Returns a list of one entry per mode, each shaped as::

        {"mode": "tram", "label_it": "Linee tramviarie",
         "label_en": "Tram lines",
         "groups": [{"line_number": 1, "directions": [LineInfo, ...]}, ...]}

    Tram block is always rendered first, rapid-bus second. Within each mode,
    groups are sorted numerically by line number.
    """
    by_mode: dict[str, dict[int, list[LineInfo]]] = {TRAM: {}, RAPID_BUS: {}}
    for li in lines:
        match = re.search(r"line(\d+)", li.line_key)
        num = int(match.group(1)) if match else 0
        by_mode.setdefault(li.mode, {}).setdefault(num, []).append(li)

    out: list[dict] = []
    for mode in (TRAM, RAPID_BUS):
        groups_for_mode = by_mode.get(mode, {})
        if not groups_for_mode:
            continue
        out.append({
            "mode": mode,
            "label_it": MODE_LABELS[mode]["it_plural"],
            "label_en": MODE_LABELS[mode]["en_plural"],
            "chip_it": MODE_LABELS[mode]["it_singular"],
            "chip_en": MODE_LABELS[mode]["en_singular"],
            "groups": [
                {"line_number": num, "directions": dirs}
                for num, dirs in sorted(groups_for_mode.items())
            ],
        })
    return out


def _svg_lollipop_chart(
    data: list[tuple[str, float]],
    color: str = "#5F5E5E",
    highlight_color: str = "#9F4200",
) -> str:
    """Generate a minimal SVG lollipop chart from (label, value) pairs.

    Thin stems with small circles at the top. Sorted by value descending.
    The highest value is highlighted. No Y-axis — shape only.
    """
    if not data:
        return ""
    # Average directions per line number, then sort descending
    merged: dict[str, list[float]] = {}
    for label, val in data:
        merged.setdefault(label, []).append(val)
    items = sorted(
        [(k, sum(v) / len(v)) for k, v in merged.items()],
        key=lambda x: x[1],
        reverse=True,
    )
    max_val = max(v for _, v in items)
    if max_val <= 0:
        return ""

    label_h = 12
    top_pad = 6
    width = 240
    height = 56
    chart_h = height - label_h - top_pad
    n = len(items)
    spacing = width / n
    dot_r = 2.5

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" class="sparkline-chart"'
        f' style="font-family:Inter,system-ui,sans-serif">'
    ]

    label_style = 'font-size="6.5" text-anchor="middle"'
    for i, (label, val) in enumerate(items):
        cx = round(spacing * (i + 0.5), 1)
        h = max(2, val / max_val * (chart_h - dot_r * 2))
        cy = round(top_pad + chart_h - h, 1)
        baseline_y = top_pad + chart_h
        is_top = i == 0
        c = highlight_color if is_top else color
        opacity = "1" if is_top else "0.45"

        # Stem
        parts.append(
            f'<line x1="{cx}" y1="{baseline_y}" x2="{cx}" y2="{cy}"'
            f' stroke="{c}" stroke-width="1.5" opacity="{opacity}"/>'
        )
        # Dot (always solid so stem doesn't show through)
        parts.append(
            f'<circle cx="{cx}" cy="{cy}" r="{dot_r}"'
            f' fill="{c}"/>'
        )
        # Label
        ly = height - 1
        parts.append(
            f'<text x="{cx}" y="{ly}" {label_style}'
            f' fill="{highlight_color if is_top else "#5F5E5E"}"'
            f' font-weight="{700 if is_top else 400}">{label}</text>'
        )

    parts.append("</svg>")
    return "\n".join(parts)


def _svg_paired_lollipop_chart(
    data: list[tuple[str, float, float]],
    color_a: str = "#5F5E5E",
    color_b: str = "#9F4200",
) -> str:
    """Generate a minimal SVG with paired lollipops (current vs potential).

    Two dots per line, connected by a thin stem from current to potential.
    Sorted by potential descending. No Y-axis.
    """
    if not data:
        return ""
    merged: dict[str, tuple[list[float], list[float]]] = {}
    for label, a, b in data:
        entry = merged.setdefault(label, ([], []))
        entry[0].append(a)
        entry[1].append(b)
    items = sorted(
        [
            (k, sum(va) / len(va), sum(vb) / len(vb))
            for k, (va, vb) in merged.items()
        ],
        key=lambda x: x[2],
        reverse=True,
    )
    max_val = max(max(a, b) for _, a, b in items)
    if max_val <= 0:
        return ""

    label_h = 12
    top_pad = 6
    width = 240
    height = 56
    chart_h = height - label_h - top_pad
    n = len(items)
    spacing = width / n
    dot_r = 2.5

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}"'
        f' viewBox="0 0 {width} {height}" class="sparkline-chart"'
        f' style="font-family:Inter,system-ui,sans-serif">'
    ]

    label_style = 'fill="#5F5E5E" font-size="6.5" text-anchor="middle"'
    for i, (label, val_a, val_b) in enumerate(items):
        cx = round(spacing * (i + 0.5), 1)
        h_a = max(2, val_a / max_val * (chart_h - dot_r * 2))
        h_b = max(2, val_b / max_val * (chart_h - dot_r * 2))
        cy_a = round(top_pad + chart_h - h_a, 1)
        cy_b = round(top_pad + chart_h - h_b, 1)
        baseline_y = top_pad + chart_h

        # Stem from baseline to lower dot (current)
        parts.append(
            f'<line x1="{cx}" y1="{baseline_y}" x2="{cx}" y2="{cy_a}"'
            f' stroke="{color_a}" stroke-width="1" opacity="0.3"/>'
        )
        # Stem from current to potential
        parts.append(
            f'<line x1="{cx}" y1="{cy_a}" x2="{cx}" y2="{cy_b}"'
            f' stroke="{color_b}" stroke-width="1.5" opacity="0.7"/>'
        )
        # Current dot (smaller, muted)
        parts.append(
            f'<circle cx="{cx}" cy="{cy_a}" r="2"'
            f' fill="{color_a}" opacity="0.5"/>'
        )
        # Potential dot (larger, highlighted)
        parts.append(
            f'<circle cx="{cx}" cy="{cy_b}" r="{dot_r}"'
            f' fill="{color_b}" opacity="0.9"/>'
        )
        # Label
        ly = height - 1
        parts.append(f'<text x="{cx}" y="{ly}" {label_style}>{label}</text>')

    parts.append("</svg>")

    parts.append("</svg>")
    parts.append("</svg>")
    return "\n".join(parts)


def build_site(
    lines: list[LineInfo],
    location_stats: list[dict[str, Any]] | None = None,
    hotspot_slices: dict[str, list[dict[str, Any]]] | None = None,
    rides_by_line: dict[str, dict] | None = None,
    debug_rides: list[dict[str, Any]] | None = None,
    debug_lines: list[dict[str, Any]] | None = None,
) -> None:
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
    location_stats = location_stats or []
    hotspot_slices = hotspot_slices or {}
    (DATA_DIR_SITE / "location_stats.json").write_text(
        json.dumps(location_stats, indent=2)
    )

    # Group lines by number for home page
    grouped_lines = _group_lines(lines)

    # Compute traffic light hours lost (if trip counts available).
    # tl_total_lines is derived from the GTFS-stop cache so the denominator
    # in the "X of Y lines" footnote naturally tracks tram + rapid-bus scope.
    tl_hours = None
    tl_lines_count = 0
    tl_total_lines = 0
    if GTFS_STOPS_JSON.exists():
        try:
            tl_total_lines = len(json.loads(GTFS_STOPS_JSON.read_text()))
        except (OSError, ValueError):
            tl_total_lines = 0
    tl_breakdown = []
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
    if DAILY_TRIPS_JSON.exists():
        daily_trips = json.loads(DAILY_TRIPS_JSON.read_text())
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

    # Compute extra rides that could be run with saved TL time
    tl_extra_rides = None
    if DAILY_TRIPS_JSON.exists() and line_tl_wait:
        line_duration: dict[str, list[float]] = {}
        for li in lines:
            match = re.search(r"line(\d+)", li.line_key)
            if not match:
                continue
            line_num = match.group(1)
            dur = li.stats.get("avg_trip_duration", 0)
            if dur > 0:
                line_duration.setdefault(line_num, []).append(dur)

        tl_extra_rides = {}
        for day_type in ("weekday", "saturday", "sunday"):
            trip_counts = daily_trips.get(day_type, {})
            total_extra = 0.0
            for line_num, waits in line_tl_wait.items():
                if line_num in trip_counts and line_num in line_duration:
                    avg_wait = sum(waits) / len(waits)
                    avg_dur = sum(line_duration[line_num]) / len(line_duration[line_num])
                    total_extra += (trip_counts[line_num] * avg_wait) / avg_dur
            tl_extra_rides[day_type] = round(total_extra)

    # Compute aggregate network stats for expandable section
    extra_stats = {}
    per_line_speed: list[tuple[str, float]] = []
    per_line_tl_pct: list[tuple[str, float]] = []
    per_line_tl_stops: list[tuple[str, float]] = []
    per_line_stops_with_dur: list[tuple[float, float]] = []  # (stops, dur_sec)
    per_line_comparison: list[tuple[str, float, float]] = []
    for li in lines:
        s = li.stats
        match = re.search(r"line(\d+)", li.line_key)
        label = match.group(1) if match else li.line_key
        avg_spd = s.get("speed", {}).get("avg_trip", 0)
        dur = s.get("avg_trip_duration", 0)
        tl_wait = s.get("tl_wait_total", 0)
        cat = s.get("cat_counts", {})
        priority = s.get("priority_savings_incl_bottlenecks", 0)
        if avg_spd > 0:
            per_line_speed.append((label, avg_spd))
        if dur > 0 and tl_wait > 0:
            per_line_tl_pct.append((label, tl_wait / dur * 100))
        tl_stops = cat.get("traffic_light", 0) + cat.get("combined", 0)
        if tl_stops > 0:
            per_line_tl_stops.append((label, float(tl_stops)))
            if dur > 0:
                per_line_stops_with_dur.append((float(tl_stops), dur))
        if dur > 0 and priority > 0 and li.total_distance_km > 0:
            potential_spd = li.total_distance_km / ((dur - priority) / 3600)
            per_line_comparison.append((label, avg_spd, potential_spd))

    # Aggregate values + charts
    if per_line_speed:
        vals = [v for _, v in per_line_speed]
        extra_stats["avg_network_speed"] = round(sum(vals) / len(vals), 1)
        extra_stats["speed_chart"] = Markup(_svg_lollipop_chart(
            per_line_speed, color="#5F5E5E", highlight_color="#9F4200",
        ))
    if per_line_tl_pct:
        vals = [v for _, v in per_line_tl_pct]
        extra_stats["tl_time_pct"] = round(sum(vals) / len(vals))
        extra_stats["tl_pct_chart"] = Markup(_svg_lollipop_chart(
            per_line_tl_pct, color="#5F5E5E", highlight_color="#c44030",
        ))
    if per_line_tl_stops:
        vals = [v for _, v in per_line_tl_stops]
        extra_stats["tl_stops_per_trip"] = round(sum(vals) / len(vals), 1)
        if per_line_stops_with_dur:
            avg_stops = sum(s for s, _ in per_line_stops_with_dur) / len(per_line_stops_with_dur)
            avg_dur = sum(d for _, d in per_line_stops_with_dur) / len(per_line_stops_with_dur)
            if avg_stops > 0:
                extra_stats["tl_seconds_per_stop"] = round(avg_dur / avg_stops)
    if per_line_comparison:
        avg_potential = sum(v for _, _, v in per_line_comparison) / len(
            per_line_comparison
        )
        avg_current = sum(v for _, v, _ in per_line_comparison) / len(
            per_line_comparison
        )
        extra_stats["potential_speed"] = round(avg_potential, 1)
        extra_stats["current_speed"] = round(avg_current, 1)
        pct_faster = round((avg_potential / avg_current - 1) * 100)
        extra_stats["speed_gain_pct"] = pct_faster
        extra_stats["comparison_chart"] = Markup(_svg_paired_lollipop_chart(
            per_line_comparison, color_a="#5F5E5E", color_b="#9F4200",
        ))
    # Insight for hours-lost card: equivalent driver shifts (8h shift)
    if tl_hours:
        extra_stats["hours_shifts"] = round(tl_hours.get("weekday", 0) / 8)

    # Annual cost: hours_lost_per_day * 365 * €35/h driver cost
    if tl_hours:
        annual_hours = tl_hours.get("weekday", 0) * 365
        extra_stats["annual_hours_lost"] = f"{round(annual_hours / 1000) * 1000:,}".replace(",", ".")
        extra_stats["annual_cost_m"] = round(annual_hours * 35 / 1_000_000, 1)
        extra_stats["fte_drivers"] = round(annual_hours / 1760)

    # Time actually moving: avg_trip_speed / avg_moving_speed
    per_line_moving: list[tuple[float, float]] = []
    for li in lines:
        s = li.stats
        trip_spd = s.get("speed", {}).get("avg_trip", 0)
        moving_spd = s.get("speed", {}).get("avg_moving", 0)
        if trip_spd > 0 and moving_spd > 0:
            per_line_moving.append((trip_spd, moving_spd))
    if per_line_moving:
        avg_ratio = sum(t / m for t, m in per_line_moving) / len(per_line_moving)
        moving_pct = round(avg_ratio * 100)
        extra_stats["moving_pct"] = moving_pct
        extra_stats["stopped_pct"] = 100 - moving_pct
        extra_stats["stopped_minutes"] = round(20 * (1 - avg_ratio))

    # Lines slower than a runner (10 km/h = 6:00/km pace)
    total_dirs = len(lines)
    slower_count = sum(
        1 for li in lines
        if li.stats.get("speed", {}).get("avg_trip", 99) < 10
    )
    extra_stats["lines_slower_than_runner"] = slower_count
    extra_stats["total_directions"] = total_dirs

    # Load GTFS stop sequences from cache file
    gtfs_stops_by_line: dict[int, list[str]] = {}
    if GTFS_STOPS_JSON.exists():
        raw = json.loads(GTFS_STOPS_JSON.read_text())
        gtfs_stops_by_line = {int(k): v for k, v in raw.items()}

    commute_lines = []
    for route_num in [1,2,3,4,5,7,9,10,12,14,15,16,19,24,27,31,33,90,91,92,93]:
        num_str = str(route_num)
        waits = line_tl_wait.get(num_str, [])
        commute_lines.append({
            "line": route_num,
            "mode": mode_for_line_number(num_str),
            "tl_wait": round(sum(waits)/len(waits), 1) if waits else None,
            "stops": gtfs_stops_by_line.get(route_num, []),
        })
    commute_lines_json = Markup(json.dumps(commute_lines, ensure_ascii=False))

    # Compute coverage once — reused by home (for the veil) and status pages.
    line_coverage: dict[str, dict] | None = None
    city_coverage: dict | None = None
    if rides_by_line is not None:
        from velotrack.coverage import (
            compute_city_coverage,
            compute_line_coverage,
            load_or_build_line_stops,
        )

        line_stops = load_or_build_line_stops()
        if line_stops:
            line_coverage = compute_line_coverage(rides_by_line, line_stops)
            city_coverage = compute_city_coverage(line_coverage)

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
            tl_extra_rides=tl_extra_rides,
            commute_lines_json=commute_lines_json,
            hotspot_slices_json=Markup(json.dumps(hotspot_slices, ensure_ascii=False)),
            extra_stats=extra_stats,
            city_coverage=city_coverage,
        )
    )

    # Render line detail pages
    tmpl = env.get_template("line_detail.html")
    for li in lines:
        (LINES_DIR / f"{li.line_key}.html").write_text(
            tmpl.render(line=li, root_path="..")
        )

    # Render network hotspots page
    tmpl = env.get_template("hotspots.html")
    (SITE_DIR / "hotspots.html").write_text(
        tmpl.render(
            root_path=".",
            location_stats_json=Markup(json.dumps(location_stats, ensure_ascii=False)),
        )
    )

    # Render methodology page
    tmpl = env.get_template("methodology.html")
    (SITE_DIR / "methodology.html").write_text(
        tmpl.render(root_path=".")
    )

    # Render mapping status page
    if line_coverage is not None and city_coverage is not None:
        # Build per-line cards: sort ascending by pct, then by line number
        cards: list[dict[str, Any]] = []
        for line_num, cov in line_coverage.items():
            try:
                sort_num = int(line_num)
            except (TypeError, ValueError):
                sort_num = 9999
            cards.append({
                "line_num": line_num,
                "sort_num": sort_num,
                "mode": mode_for_line_number(str(line_num)),
                "total": cov["total"],
                "covered": cov["covered"],
                "missing_count": cov["missing_count"],
                "pct": cov["pct"],
                "missing_names": cov["missing_names"],
            })
        cards.sort(key=lambda c: (c["pct"], c["sort_num"]))

        # Split into tram vs rapid-bus sections for the two-section layout
        card_sections: list[dict[str, Any]] = []
        for mode in (TRAM, RAPID_BUS):
            mode_cards = [c for c in cards if c["mode"] == mode]
            if not mode_cards:
                continue
            card_sections.append({
                "mode": mode,
                "label_it": MODE_LABELS[mode]["it_plural"],
                "label_en": MODE_LABELS[mode]["en_plural"],
                "chip_it": MODE_LABELS[mode]["it_singular"],
                "chip_en": MODE_LABELS[mode]["en_singular"],
                "cards": mode_cards,
            })

        # Compact JSON for client-side map rendering — only the data the
        # browser needs (stop coords + covered flag), keyed by line number.
        map_data = {
            ln: [
                {
                    "n": s["name"],
                    "y": round(s["lat"], 6),
                    "x": round(s["lon"], 6),
                    "c": 1 if s["covered"] else 0,
                }
                for s in cov["stops"]
            ]
            for ln, cov in line_coverage.items()
        }

        tmpl = env.get_template("status.html")
        (SITE_DIR / "status.html").write_text(
            tmpl.render(
                root_path=".",
                city_coverage=city_coverage,
                cards=cards,
                card_sections=card_sections,
                coverage_json=Markup(json.dumps(map_data, ensure_ascii=False)),
            )
        )
        print(
            f"Coverage: {city_coverage['pct']}% of city stops mapped "
            f"({city_coverage['covered']}/{city_coverage['total']})"
        )

    # Render hidden /debug/ section (not linked from any navbar)
    debug_dir = SITE_DIR / "debug"
    debug_dir.mkdir(parents=True, exist_ok=True)

    tmpl = env.get_template("debug/index.html")
    (debug_dir / "index.html").write_text(tmpl.render(root_path=".."))

    tmpl = env.get_template("debug/inspect.html")
    (debug_dir / "inspect.html").write_text(
        tmpl.render(
            root_path="..",
            debug_rides_json=Markup(
                json.dumps(debug_rides or [], ensure_ascii=False)
            ),
            num_rides=len(debug_rides or []),
        )
    )

    tmpl = env.get_template("debug/lines.html")

    def _line_sort_key(d: dict[str, Any]) -> tuple[int, str]:
        match = re.search(r"line(\d+)", d["line_key"])
        num = int(match.group(1)) if match is not None else 9999
        return (num, d["line_key"])

    # Sort line entries by line number (so line1, line2, … line90 order).
    sorted_debug_lines = sorted(debug_lines or [], key=_line_sort_key)
    (debug_dir / "lines.html").write_text(
        tmpl.render(
            root_path="..",
            debug_lines_json=Markup(
                json.dumps(sorted_debug_lines, ensure_ascii=False)
            ),
            num_lines=len(sorted_debug_lines),
        )
    )

    print(f"Site built: {SITE_DIR}")
