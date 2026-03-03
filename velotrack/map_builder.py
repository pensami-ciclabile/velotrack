"""Build an interactive Folium map with velocity heatmap and stop markers."""

import folium
import pandas as pd

from velotrack.config import STOP_COLORS, VELOCITY_COLORS
from velotrack.stop_detector import StopEvent


def velocity_color(speed_kmh: float) -> str:
    """Map a velocity to a color."""
    for max_speed, color in VELOCITY_COLORS:
        if speed_kmh <= max_speed:
            return color
    return VELOCITY_COLORS[-1][1]


def build_map(
    ride_dfs: list[pd.DataFrame],
    all_stops: list[list[StopEvent]],
    title: str = "Velotrack",
) -> folium.Map:
    """Build a Folium map from one or more rides with velocity-colored segments and stop markers.

    Args:
        ride_dfs: List of parsed GPX DataFrames (one per ride).
        all_stops: List of stop event lists (one per ride, aligned with ride_dfs).
        title: Map title.
    """
    # Center map on first ride's midpoint
    all_lats = [df["lat"].mean() for df in ride_dfs if not df.empty]
    all_lons = [df["lon"].mean() for df in ride_dfs if not df.empty]
    center_lat = sum(all_lats) / len(all_lats) if all_lats else 45.464
    center_lon = sum(all_lons) / len(all_lons) if all_lons else 9.19

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron")

    # Feature groups for layer control
    route_group = folium.FeatureGroup(name="Route (velocity)", show=True)
    stop_groups = {
        cat: folium.FeatureGroup(name=f"Stops: {cat}", show=True)
        for cat in STOP_COLORS
    }

    # Draw velocity-colored route segments for each ride
    for df in ride_dfs:
        if len(df) < 2:
            continue
        for i in range(1, len(df)):
            coords = [
                [df.iloc[i - 1]["lat"], df.iloc[i - 1]["lon"]],
                [df.iloc[i]["lat"], df.iloc[i]["lon"]],
            ]
            speed = df.iloc[i]["velocity_kmh"]
            color = velocity_color(speed)
            folium.PolyLine(
                coords,
                color=color,
                weight=4,
                opacity=0.8,
                popup=f"{speed:.1f} km/h",
            ).add_to(route_group)

    # Add stop markers — aggregate duplicates at same location across rides
    merged_stops: dict[tuple[float, float], list[StopEvent]] = {}
    for stops in all_stops:
        for stop in stops:
            key = (round(stop.lat, 5), round(stop.lon, 5))
            merged_stops.setdefault(key, []).append(stop)

    for (lat, lon), events in merged_stops.items():
        # Use most common category
        categories = [e.category for e in events]
        category = max(set(categories), key=categories.count)
        avg_duration = sum(e.duration for e in events) / len(events)
        count = len(events)

        nearest_name = next((e.nearest_stop_name for e in events if e.nearest_stop_name), "?")
        nearest_dist = min((e.nearest_stop_dist for e in events if e.nearest_stop_dist is not None), default=None)

        popup_parts = [
            f"<b>{category.replace('_', ' ').title()}</b>",
            f"Avg wait: {avg_duration:.0f}s",
            f"Occurrences: {count}",
            f"Nearest stop: {nearest_name}",
        ]
        if nearest_dist is not None:
            popup_parts.append(f"Distance: {nearest_dist:.0f}m")
        if category == "combined":
            avg_tl_wait = sum(e.traffic_light_wait or 0 for e in events) / len(events)
            popup_parts.append(f"Est. traffic light wait: {avg_tl_wait:.0f}s")

        color = STOP_COLORS.get(category, "gray")
        folium.CircleMarker(
            location=[lat, lon],
            radius=7,
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
            popup=folium.Popup("<br>".join(popup_parts), max_width=250),
        ).add_to(stop_groups.get(category, route_group))

    route_group.add_to(m)
    for group in stop_groups.values():
        group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    return m
