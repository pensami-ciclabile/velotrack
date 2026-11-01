"""Basemap configuration shared by Folium maps and site templates."""

import os
from urllib.parse import quote


def carto_key() -> str:
    return os.environ.get("CARTO_BASEMAP_KEY", "").strip()


def carto_tile_url(style: str) -> str:
    return f"https://basemaps.cartocdn.com/rastertiles/{style}/{{z}}/{{x}}/{{y}}.png?key={quote(carto_key(), safe='')}"


def folium_basemap() -> dict:
    key = carto_key()
    if not key:
        return {"tiles": "OpenStreetMap"}
    return {
        "tiles": carto_tile_url("light_all"),
        "attr": '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/attributions">CARTO</a>',
    }
