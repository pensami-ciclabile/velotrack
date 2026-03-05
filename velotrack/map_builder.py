"""Build an interactive Folium map with velocity heatmap and stop markers."""

import numpy as np
import folium
from folium import Element
import pandas as pd

from velotrack.config import STOP_COLORS, VELOCITY_COLORS
from velotrack.stop_detector import StopEvent


def build_traffic_lights_map(
    traffic_lights: pd.DataFrame, server_mode: bool = False
) -> folium.Map:
    """Build a Folium map showing all traffic light locations.

    Args:
        traffic_lights: DataFrame with lat, lon, name (and optionally notes) columns.
        server_mode: If True, inject JS for right-click-to-add via POST /add.
    """
    if traffic_lights.empty:
        center_lat, center_lon = 45.464, 9.19
    else:
        center_lat = traffic_lights["lat"].mean()
        center_lon = traffic_lights["lon"].mean()

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron", max_zoom=22)

    # Google Maps satellite (no labels) + CartoDB street-only overlay
    folium.TileLayer(
        tiles="https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}",
        attr="Google",
        name="Google Satellite + Streets",
        overlay=False,
        max_zoom=22,
    ).add_to(m)

    for _, row in traffic_lights.iterrows():
        name = row.get("name", "")
        notes = row.get("notes", "")
        popup_text = f"<b>{name}</b>"
        if notes:
            popup_text += f"<br>{notes}"
        folium.CircleMarker(
            location=[row["lat"], row["lon"]],
            radius=8,
            color="red",
            fill=True,
            fill_color="red",
            fill_opacity=0.7,
            popup=folium.Popup(popup_text, max_width=250),
            tooltip=name,
        ).add_to(m)

    # Street names overlay (no POIs/shops) — useful on top of satellite
    street_labels = folium.TileLayer(
        tiles="https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}@2x.png",
        attr="CartoDB",
        name="Street names",
        overlay=True,
        show=True,
        max_zoom=22,
        min_zoom=15,
        tile_size=1024,
        zoom_offset=-2,
    )
    street_labels.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    if server_mode:
        m.get_root().html.add_child(Element("""
        <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Find the Leaflet map instance
            var map;
            for (var key in window) {
                if (window[key] instanceof L.Map) { map = window[key]; break; }
            }
            if (!map) return;

            // Restore view from URL hash
            var hash = window.location.hash.slice(1);
            if (hash) {
                var parts = hash.split('/');
                if (parts.length === 3) {
                    map.setView([parseFloat(parts[0]), parseFloat(parts[1])], parseInt(parts[2]));
                }
            }

            // Restore tile layer from localStorage
            var savedLayer = localStorage.getItem('tl_layer');
            if (savedLayer) {
                var inputs = document.querySelectorAll('.leaflet-control-layers input[type=radio]');
                inputs.forEach(function(input) {
                    var label = input.nextSibling ? input.nextSibling.textContent.trim() : '';
                    if (label === savedLayer) { input.click(); }
                });
            }

            // Track active layer
            var activeLayer = savedLayer || '';
            map.on('baselayerchange', function(e) { activeLayer = e.name; });

            // Helper to save state before reload
            function saveState() {
                var c = map.getCenter();
                window.location.hash = c.lat.toFixed(6) + '/' + c.lng.toFixed(6) + '/' + map.getZoom();
                if (activeLayer) localStorage.setItem('tl_layer', activeLayer);
            }

            // Right-click to add a traffic light
            map.on('contextmenu', function(e) {
                var lat = e.latlng.lat.toFixed(8);
                var lon = e.latlng.lng.toFixed(8);
                var formHtml = '<div style="font-family:sans-serif;font-size:13px">'
                    + '<b>Add traffic light</b><br>'
                    + '<form id="tl-form" style="margin-top:6px">'
                    + '<input id="tl-name" type="text" placeholder="Name (required)" required '
                    + 'style="width:100%;margin:3px 0;padding:4px;box-sizing:border-box"><br>'
                    + '<input id="tl-notes" type="text" placeholder="Notes (optional)" '
                    + 'style="width:100%;margin:3px 0;padding:4px;box-sizing:border-box"><br>'
                    + '<button type="submit" style="margin-top:4px;padding:4px 12px;cursor:pointer">'
                    + 'Add</button>'
                    + '<span id="tl-status" style="margin-left:8px;color:#888"></span>'
                    + '</form></div>';
                var popup = L.popup({maxWidth: 500, minWidth: 300}).setLatLng(e.latlng).setContent(formHtml).openOn(map);
                setTimeout(function() {
                    var form = document.getElementById('tl-form');
                    if (!form) return;
                    form.addEventListener('submit', function(ev) {
                        ev.preventDefault();
                        var name = document.getElementById('tl-name').value.trim();
                        if (!name) return;
                        var notes = document.getElementById('tl-notes').value.trim();
                        var status = document.getElementById('tl-status');
                        status.textContent = 'Saving...';
                        fetch('/add', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({lat: parseFloat(lat), lon: parseFloat(lon), name: name, notes: notes})
                        }).then(function(r) {
                            if (r.ok) {
                                saveState();
                                window.location.reload();
                            } else {
                                status.textContent = 'Error!';
                            }
                        }).catch(function() { status.textContent = 'Error!'; });
                    });
                }, 50);
            });
        });
        </script>
        """))

    return m


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
    # --- Trip duration ---
    trip_durations = []
    for df in ride_dfs:
        if len(df) >= 2:
            dur = (df["time"].iloc[-1] - df["time"].iloc[0]).total_seconds()
            trip_durations.append(dur)
    avg_trip_duration = sum(trip_durations) / len(trip_durations) if trip_durations else 0

    # --- Speed stats ---
    all_speeds = pd.concat(
        [df["velocity_kmh"] for df in ride_dfs if not df.empty], ignore_index=True
    )
    moving = all_speeds[all_speeds > 0]
    speed = {
        "avg_moving": moving.mean() if len(moving) else 0,
        "avg_trip": all_speeds.mean() if len(all_speeds) else 0,
        "peak": all_speeds.max() if len(all_speeds) else 0,
        "median_moving": moving.median() if len(moving) else 0,
        "median_trip": all_speeds.median() if len(all_speeds) else 0,
        "p25": float(np.percentile(moving, 25)) if len(moving) else 0,
        "p75": float(np.percentile(moving, 75)) if len(moving) else 0,
    }

    # --- Stop time stats (per-category) ---
    cat_counts: dict[str, int] = {}
    cat_total_avg: dict[str, float] = {}
    tl_wait_from_tl = 0.0
    tl_wait_from_combined = 0.0
    tl_wait_from_bottleneck = 0.0
    for (_lat, _lon), events in merged_stops.items():
        categories = [e.category for e in events]
        category = max(set(categories), key=categories.count)
        avg_dur = sum(e.duration for e in events) / len(events)
        cat_counts[category] = cat_counts.get(category, 0) + 1
        cat_total_avg[category] = cat_total_avg.get(category, 0) + avg_dur
        if category == "traffic_light":
            tl_wait_from_tl += avg_dur
        elif category == "combined":
            avg_tl_wait = sum(e.traffic_light_wait or 0 for e in events) / len(events)
            tl_wait_from_combined += avg_tl_wait
        elif category == "bottleneck":
            tl_wait_from_bottleneck += avg_dur

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

    priority_excl = tl_wait_from_tl + tl_wait_from_combined
    priority_incl = priority_excl + tl_wait_from_bottleneck

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
        "avg_trip_duration": avg_trip_duration,
        "priority_savings_excl_bottlenecks": priority_excl,
        "priority_savings_incl_bottlenecks": priority_incl,
    }


def _jsonify_stats(obj):
    """Convert numpy/pandas types to plain Python for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _jsonify_stats(v) for k, v in obj.items()}
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating, np.float64)):
        return float(obj)
    if isinstance(obj, (np.ndarray,)):
        return [_jsonify_stats(x) for x in obj]
    return obj


def compute_line_stats(
    ride_dfs: list[pd.DataFrame],
    all_stops: list[list[StopEvent]],
) -> dict:
    """Compute JSON-serializable stats for a tram line.

    Reuses the same merge-stops + _compute_stats logic from build_map.
    """
    merged_stops: dict[tuple[float, float], list[StopEvent]] = {}
    for stops in all_stops:
        for stop in stops:
            key = (round(stop.lat, 5), round(stop.lon, 5))
            merged_stops.setdefault(key, []).append(stop)

    stats = _compute_stats(ride_dfs, merged_stops)
    return _jsonify_stats(stats)


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
        box-shadow: 0 2px 8px rgba(0,0,0,0.18);
        border: 1px solid #ddd; pointer-events: auto; white-space: nowrap;
    ">
        <div style="font-weight:bold;text-align:center;margin-bottom:6px;
                     border-bottom:1px solid #ccc;padding-bottom:4px;">
            Line Statistics
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
            <span>Avg moving: <b>{s['avg_moving']:.1f}</b> km/h</span>
            <span>Avg trip: <b>{s['avg_trip']:.1f}</b> km/h</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
            <span>Median moving: <b>{s['median_moving']:.1f}</b> km/h</span>
            <span>Median trip: <b>{s['median_trip']:.1f}</b> km/h</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
            <span>Peak: <b>{s['peak']:.1f}</b> km/h</span>
            <span style="color:#888">P25: {s['p25']:.1f} · P75: {s['p75']:.1f}</span>
        </div>
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
        <div style="border-top:1px solid #eee;margin:6px 0 4px"></div>
        <div style="font-weight:bold;margin-bottom:2px;">Traffic light priority:</div>
        <div style="display:flex;justify-content:space-between">
            <span style="color:#888">Excl. bottlenecks:</span>
            <span>-{stats['priority_savings_excl_bottlenecks']:.0f}s ({stats['priority_savings_excl_bottlenecks'] / stats['avg_trip_duration'] * 100 if stats['avg_trip_duration'] else 0:.1f}% faster)</span>
        </div>
        <div style="display:flex;justify-content:space-between">
            <span style="color:#888">Incl. bottlenecks:</span>
            <span>-{stats['priority_savings_incl_bottlenecks']:.0f}s ({stats['priority_savings_incl_bottlenecks'] / stats['avg_trip_duration'] * 100 if stats['avg_trip_duration'] else 0:.1f}% faster)</span>
        </div>
    </div>
    """


def _speed_space_data(
    ride_dfs: list[pd.DataFrame], bin_width_m: float = 25.0
) -> tuple[list[float], list[float], list[list[tuple[float, float]]]]:
    """Compute binned speed-vs-distance data across rides.

    Returns:
        x_km: bin center positions in km
        avg_speed: average speed per bin across all rides
        ride_traces: per-ride list of (distance_km, speed) points
    """
    ride_traces: list[list[tuple[float, float]]] = []
    bin_sums: dict[int, float] = {}
    bin_counts: dict[int, int] = {}

    for df in ride_dfs:
        if len(df) < 2:
            continue
        cum_dist = df["dist"].cumsum().values  # meters
        speeds = df["velocity_kmh"].values
        trace = [(cum_dist[i] / 1000, float(speeds[i])) for i in range(len(df))]
        ride_traces.append(trace)

        for i in range(len(df)):
            b = int(cum_dist[i] // bin_width_m)
            bin_sums[b] = bin_sums.get(b, 0.0) + speeds[i]
            bin_counts[b] = bin_counts.get(b, 0) + 1

    if not bin_counts:
        return [], [], ride_traces

    max_bin = max(bin_counts.keys())
    x_km = []
    avg_speed = []
    for b in range(max_bin + 1):
        x_km.append((b * bin_width_m + bin_width_m / 2) / 1000)
        if b in bin_counts:
            avg_speed.append(bin_sums[b] / bin_counts[b])
        else:
            avg_speed.append(float("nan"))

    return x_km, avg_speed, ride_traces


def _speed_space_chart_html(
    x_km: list[float],
    avg_speed: list[float],
    ride_traces: list[list[tuple[float, float]]],
) -> str:
    """Build HTML/JS for a Chart.js speed-space diagram."""
    import json

    avg_data = json.dumps(
        [{"x": round(x, 4), "y": round(y, 1)} for x, y in zip(x_km, avg_speed) if y == y]
    )

    ride_datasets = ""
    for idx, trace in enumerate(ride_traces):
        points = json.dumps(
            [{"x": round(d, 4), "y": round(s, 1)} for d, s in trace]
        )
        ride_datasets += f"""{{
            label: 'Ride {idx + 1}',
            data: {points},
            borderColor: 'rgba(100,149,237,0.25)',
            borderWidth: 1,
            pointRadius: 0,
            fill: false,
            tension: 0.3,
            showLine: true,
        }},"""

    return f"""
    <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
    <div id="ssd-toggle" style="
        position:fixed; bottom:30px; right:10px; z-index:9999;
        background:rgba(255,255,255,0.92); border-radius:8px;
        padding:6px 12px; font-family:'Menlo','Consolas',monospace;
        font-size:11px; color:#222; cursor:pointer;
        box-shadow:0 2px 8px rgba(0,0,0,0.18); border:1px solid #ddd;
        pointer-events:auto;
    " onclick="document.getElementById('ssd-panel').style.display =
        document.getElementById('ssd-panel').style.display === 'none' ? 'block' : 'none'">
        Speed-Space Diagram
    </div>
    <div id="ssd-panel" style="
        display:none; position:fixed; bottom:60px; right:10px; z-index:9998;
        background:rgba(255,255,255,0.96); border-radius:8px;
        padding:12px; font-family:'Menlo','Consolas',monospace;
        box-shadow:0 2px 8px rgba(0,0,0,0.18); border:1px solid #ddd;
        pointer-events:auto; width:520px; height:320px;
    ">
        <canvas id="ssd-canvas"></canvas>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded', function() {{
        const ctx = document.getElementById('ssd-canvas').getContext('2d');
        new Chart(ctx, {{
            type: 'scatter',
            data: {{
                datasets: [
                    {ride_datasets}
                    {{
                        label: 'Average',
                        data: {avg_data},
                        borderColor: 'rgba(220,60,60,0.9)',
                        borderWidth: 2.5,
                        pointRadius: 0,
                        fill: false,
                        tension: 0.3,
                        showLine: true,
                    }}
                ]
            }},
            options: {{
                responsive: true,
                maintainAspectRatio: false,
                animation: false,
                plugins: {{
                    legend: {{ display: false }},
                    tooltip: {{
                        mode: 'nearest',
                        intersect: false,
                        callbacks: {{
                            label: function(ctx) {{
                                return ctx.dataset.label + ': ' +
                                    ctx.parsed.y.toFixed(1) + ' km/h @ ' +
                                    ctx.parsed.x.toFixed(2) + ' km';
                            }}
                        }}
                    }}
                }},
                scales: {{
                    x: {{
                        type: 'linear',
                        title: {{ display: true, text: 'Distance (km)' }},
                        ticks: {{ maxTicksLimit: 12 }}
                    }},
                    y: {{
                        title: {{ display: true, text: 'Speed (km/h)' }},
                        beginAtZero: true
                    }}
                }}
            }}
        }});
    }});
    </script>
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

    # Speed-space diagram
    x_km, avg_speed, ride_traces = _speed_space_data(ride_dfs)
    if x_km:
        chart_html = _speed_space_chart_html(x_km, avg_speed, ride_traces)
        m.get_root().html.add_child(Element(chart_html))

    return m
