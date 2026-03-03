"""Build an interactive Folium map with velocity heatmap and stop markers."""

import numpy as np
import folium
from folium import Element
import pandas as pd

from velotrack.config import STOP_COLORS, VELOCITY_COLORS
from velotrack.stop_detector import StopEvent


def velocity_color(speed_kmh: float) -> str:
    """Map a velocity to a color."""
    for max_speed, color in VELOCITY_COLORS:
        if speed_kmh <= max_speed:
            return color
    return VELOCITY_COLORS[-1][1]


def _compute_stats(
    ride_dfs: list[pd.DataFrame],
    merged_stops: dict[tuple[float, float], list[StopEvent]],
) -> dict:
    """Compute aggregate statistics from ride data and merged stops."""
    # --- Speed stats ---
    all_speeds = pd.concat(
        [df["velocity_kmh"] for df in ride_dfs if not df.empty], ignore_index=True
    )
    moving = all_speeds[all_speeds > 0]
    speed = {
        "avg": moving.mean() if len(moving) else 0,
        "peak": all_speeds.max() if len(all_speeds) else 0,
        "median": moving.median() if len(moving) else 0,
        "p25": float(np.percentile(moving, 25)) if len(moving) else 0,
        "p75": float(np.percentile(moving, 75)) if len(moving) else 0,
    }

    # --- Stop time stats (per-category) ---
    cat_counts: dict[str, int] = {}
    cat_total_avg: dict[str, float] = {}
    for (_lat, _lon), events in merged_stops.items():
        categories = [e.category for e in events]
        category = max(set(categories), key=categories.count)
        avg_dur = sum(e.duration for e in events) / len(events)
        cat_counts[category] = cat_counts.get(category, 0) + 1
        cat_total_avg[category] = cat_total_avg.get(category, 0) + avg_dur

    total_stops = sum(cat_counts.values())
    total_delay = sum(cat_total_avg.values())
    avg_wait = total_delay / total_stops if total_stops else 0

    # --- Scenario analysis (per-location min/max/percentiles) ---
    green_wave = 0.0
    red_wave = 0.0
    p25_sum = 0.0
    p75_sum = 0.0
    for events in merged_stops.values():
        durations = [e.duration for e in events]
        green_wave += min(durations)
        red_wave += max(durations)
        if len(durations) >= 2:
            p25_sum += float(np.percentile(durations, 25))
            p75_sum += float(np.percentile(durations, 75))
        else:
            p25_sum += durations[0]
            p75_sum += durations[0]

    return {
        "speed": speed,
        "cat_counts": cat_counts,
        "cat_total_avg": cat_total_avg,
        "total_stops": total_stops,
        "total_delay": total_delay,
        "avg_wait": avg_wait,
        "green_wave": green_wave,
        "red_wave": red_wave,
        "p25_sum": p25_sum,
        "p75_sum": p75_sum,
    }


def _stats_html(stats: dict) -> str:
    """Build the HTML/CSS for the statistics panel."""
    s = stats["speed"]
    cat_order = ["tram_stop", "traffic_light", "combined", "bottleneck"]
    cat_labels = {
        "tram_stop": "Tram stops",
        "traffic_light": "Traffic lights",
        "combined": "Combined",
        "bottleneck": "Bottlenecks",
    }

    cat_rows = ""
    for cat in cat_order:
        count = stats["cat_counts"].get(cat, 0)
        if count == 0:
            continue
        total = stats["cat_total_avg"][cat]
        avg = total / count
        label = cat_labels[cat]
        cat_rows += (
            f'<div style="display:flex;justify-content:space-between">'
            f'<span style="color:#888">{label}:</span>'
            f'<span>{count} &times; avg {avg:.0f}s = {total:.0f}s</span></div>\n'
        )

    return f"""
    <div id="stats-panel" style="
        position: fixed; bottom: 30px; left: 10px; z-index: 9999;
        background: rgba(255,255,255,0.92); border-radius: 8px;
        padding: 12px 16px; font-family: 'Menlo','Consolas',monospace;
        font-size: 11px; line-height: 1.6; color: #222;
        box-shadow: 0 2px 8px rgba(0,0,0,0.18); max-width: 320px;
        border: 1px solid #ddd; pointer-events: auto;
    ">
        <div style="font-weight:bold;text-align:center;margin-bottom:6px;
                     border-bottom:1px solid #ccc;padding-bottom:4px;">
            Line Statistics
        </div>
        <div style="display:flex;justify-content:space-between">
            <span>Avg speed: <b>{s['avg']:.1f}</b> km/h</span>
            <span>Peak: <b>{s['peak']:.1f}</b> km/h</span>
        </div>
        <div>Median: {s['median']:.1f} km/h
            (P25: {s['p25']:.1f} · P75: {s['p75']:.1f})</div>
        <div style="border-top:1px solid #eee;margin:6px 0 4px"></div>
        <div style="display:flex;justify-content:space-between">
            <span>Stops: <b>{stats['total_stops']}</b> total</span>
            <span>Total delay: <b>{stats['total_delay']:.0f}s</b></span>
        </div>
        {cat_rows}
        <div style="color:#888;font-size:10px">
            Avg wait per stop: {stats['avg_wait']:.0f}s</div>
        <div style="border-top:1px solid #eee;margin:6px 0 4px"></div>
        <div style="font-weight:bold;margin-bottom:2px;">Scenarios (total delay):</div>
        <div style="display:flex;justify-content:space-between">
            <span style="color:#2a2">Green wave: {stats['green_wave']:.0f}s</span>
            <span style="color:#888">P25: {stats['p25_sum']:.0f}s</span>
        </div>
        <div style="display:flex;justify-content:space-between">
            <span style="color:#c33">Red wave: {stats['red_wave']:.0f}s</span>
            <span style="color:#888">P75: {stats['p75_sum']:.0f}s</span>
        </div>
    </div>
    """


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

    # Compute and inject statistics panel
    stats = _compute_stats(ride_dfs, merged_stops)
    panel_html = _stats_html(stats)
    m.get_root().html.add_child(Element(panel_html))

    return m
