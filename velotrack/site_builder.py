"""Build the static website from Jinja2 templates and line data."""

import json
import re
import shutil
from dataclasses import dataclass, asdict
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from velotrack.config import (
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


def _display_name(line_key: str) -> str:
    """Convert 'line1_west' → 'Line 1 West'."""
    parts = line_key.replace("line", "Line ").split("_")
    return " ".join(p.capitalize() if p[0].islower() else p for p in parts)


def _direction_name(line_key: str) -> str:
    """Extract direction from line_key, e.g. 'line1_west' → 'West'."""
    parts = line_key.split("_", 1)
    if len(parts) > 1:
        return parts[1].capitalize()
    return ""


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

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    env.globals["direction_name"] = _direction_name

    # Render home page
    tmpl = env.get_template("home.html")
    (SITE_DIR / "index.html").write_text(
        tmpl.render(grouped_lines=grouped_lines, lines=lines, root_path=".")
    )

    # Render line detail pages
    tmpl = env.get_template("line_detail.html")
    for li in lines:
        (LINES_DIR / f"{li.line_key}.html").write_text(
            tmpl.render(line=li, root_path="..")
        )

    print(f"Site built: {SITE_DIR}")
