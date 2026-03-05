"""Build the static website from Jinja2 templates and line data."""

import json
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

    # Setup Jinja2
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)

    # Render home page
    tmpl = env.get_template("home.html")
    (SITE_DIR / "index.html").write_text(tmpl.render(lines=lines, root_path="."))

    # Render lines listing
    tmpl = env.get_template("lines.html")
    (LINES_DIR / "index.html").write_text(
        tmpl.render(lines=lines, lines_json=json.dumps(lines_data), root_path="..")
    )

    # Render line detail pages
    tmpl = env.get_template("line_detail.html")
    for li in lines:
        (LINES_DIR / f"{li.line_key}.html").write_text(
            tmpl.render(line=li, root_path="..")
        )

    print(f"Site built: {SITE_DIR}")
