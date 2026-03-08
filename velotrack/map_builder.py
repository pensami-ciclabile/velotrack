"""Build an interactive Folium map with velocity heatmap and stop markers."""

import numpy as np
import folium
from folium import Element
import pandas as pd

from velotrack.config import STOP_COLORS, STOP_DISTANCE, STOP_TIME_GAP, VELOCITY_COLORS
from velotrack.gpx_parser import haversine
from velotrack.stop_detector import StopEvent

# Priority for category merging: higher = more specific
_CAT_PRIORITY = {"unknown": 0, "bottleneck": 0, "tram_stop": 1, "traffic_light": 1, "combined": 2}


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

    # --- Speed stats (distance/time based, not mean of instantaneous speeds) ---
    speed_parts = [df[["velocity_kmh", "dt", "dist"]].iloc[1:] for df in ride_dfs if len(df) >= 2]
    if speed_parts:
        all_speeds = pd.concat(speed_parts, ignore_index=True)
    else:
        all_speeds = pd.DataFrame(columns=["velocity_kmh", "dt", "dist"])
    total_dist = all_speeds["dist"].sum()
    total_dt = all_speeds["dt"].sum()
    moving_mask = ~((all_speeds["dt"] > STOP_TIME_GAP) & (all_speeds["dist"] < STOP_DISTANCE))
    moving_dist = all_speeds.loc[moving_mask, "dist"].sum()
    moving_dt = all_speeds.loc[moving_mask, "dt"].sum()

    # Time-weighted percentiles for moving segments
    moving_speeds = all_speeds.loc[moving_mask, ["velocity_kmh", "dt"]].copy()
    if len(moving_speeds):
        moving_speeds = moving_speeds.sort_values("velocity_kmh")
        cum_weight = moving_speeds["dt"].cumsum() / moving_speeds["dt"].sum()
        median_moving = float(moving_speeds.loc[
            cum_weight >= 0.5, "velocity_kmh"
        ].iloc[0])
        p25 = float(moving_speeds.loc[cum_weight >= 0.25, "velocity_kmh"].iloc[0])
        p75 = float(moving_speeds.loc[cum_weight >= 0.75, "velocity_kmh"].iloc[0])
    else:
        median_moving = p25 = p75 = 0

    # Time-weighted median for all segments (including stops)
    all_sorted = all_speeds[["velocity_kmh", "dt"]].sort_values("velocity_kmh")
    if len(all_sorted):
        cum_w = all_sorted["dt"].cumsum() / all_sorted["dt"].sum()
        median_trip = float(all_sorted.loc[cum_w >= 0.5, "velocity_kmh"].iloc[0])
    else:
        median_trip = 0

    # Peak = highest average-across-trips segment speed (typical top speed)
    _x, avg_spd, _ = _speed_space_data(ride_dfs)
    peak = max((s for s in avg_spd if not np.isnan(s)), default=0)
    speed = {
        "avg_moving": (moving_dist / moving_dt * 3.6) if moving_dt > 0 else 0,
        "avg_trip": (total_dist / total_dt * 3.6) if total_dt > 0 else 0,
        "peak": peak if peak else (all_speeds["velocity_kmh"].max() if len(all_speeds) else 0),
        "median_moving": median_moving,
        "median_trip": median_trip,
        "p25": p25,
        "p75": p75,
    }

    # --- Stop time stats (per-category, frequency-weighted) ---
    num_rides = len(ride_dfs)
    cat_counts: dict[str, int] = {}
    cat_total_avg: dict[str, float] = {}
    tl_wait_from_tl = 0.0
    tl_wait_from_combined = 0.0
    tl_wait_from_bottleneck = 0.0
    unweighted_total = 0.0
    for (_lat, _lon), events in merged_stops.items():
        categories = [e.category for e in events]
        category = max(set(categories), key=categories.count)
        avg_dur = sum(e.duration for e in events) / len(events)
        frequency = len(events) / num_rides if num_rides > 0 else 1.0
        weighted_dur = avg_dur * frequency
        cat_counts[category] = cat_counts.get(category, 0) + 1
        cat_total_avg[category] = cat_total_avg.get(category, 0) + weighted_dur
        unweighted_total += avg_dur
        if category == "traffic_light":
            tl_wait_from_tl += weighted_dur
        elif category == "combined":
            avg_tl_wait = sum(e.traffic_light_wait or 0 for e in events) / len(events)
            tl_wait_from_combined += avg_tl_wait * frequency
        elif category == "bottleneck":
            tl_wait_from_bottleneck += weighted_dur

    total_stops = sum(cat_counts.values())
    total_delay = sum(cat_total_avg.values())
    avg_wait = unweighted_total / total_stops if total_stops else 0

    # --- Scenario analysis (per-location min/max/percentiles) ---
    green_wave = 0.0
    red_wave = 0.0
    p25_sum = 0.0
    p75_sum = 0.0
    for (_lat, _lon), events in merged_stops.items():
        durations = [e.duration for e in events]
        frequency = len(events) / num_rides if num_rides > 0 else 1.0
        green_wave += min(durations) * frequency
        red_wave += max(durations) * frequency
        if len(durations) >= 2:
            p25_sum += float(np.percentile(durations, 25)) * frequency
            p75_sum += float(np.percentile(durations, 75)) * frequency
        else:
            p25_sum += durations[0] * frequency
            p75_sum += durations[0] * frequency

    priority_excl = tl_wait_from_tl + tl_wait_from_combined
    priority_incl = priority_excl + tl_wait_from_bottleneck

    # Scenario durations (projected trip times)
    scenario_green_wave = avg_trip_duration - priority_excl
    scenario_red_wave = avg_trip_duration - total_delay + red_wave
    scenario_best_case = avg_trip_duration - priority_incl

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
        "scenario_green_wave": scenario_green_wave,
        "scenario_red_wave": scenario_red_wave,
        "scenario_best_case": scenario_best_case,
        "tl_wait_total": tl_wait_from_tl + tl_wait_from_combined,
        "boarding_total": cat_total_avg.get("tram_stop", 0) + cat_total_avg.get("combined", 0) - tl_wait_from_combined,
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


def _merge_stops(
    all_stops: list[list[StopEvent]], cluster_radius_m: float = 20.0,
) -> dict[tuple[float, float], list[StopEvent]]:
    """Merge stops: first within each ride (sum durations at same location),
    then across rides (one entry per ride per location).

    Stops with ref_lat/ref_lon (tram_stop, traffic_light, combined) merge by
    exact reference coordinates. Bottlenecks (no ref) merge by spatial
    clustering within cluster_radius_m.

    When merging within a ride, the most specific category wins
    (combined > tram_stop/traffic_light > bottleneck).
    """
    merged: dict[tuple[float, float], list[StopEvent]] = {}

    for stops in all_stops:
        # Phase 1: per-ride merge
        ride_merged: dict[tuple[float, float], StopEvent] = {}
        for stop in stops:
            if stop.ref_lat is not None and stop.ref_lon is not None:
                key = (round(stop.ref_lat, 5), round(stop.ref_lon, 5))
            else:
                # Bottleneck: find nearest existing bottleneck key within radius
                best_key = None
                best_dist = cluster_radius_m
                for k, existing in ride_merged.items():
                    if existing.ref_lat is not None:
                        continue  # skip non-bottleneck keys
                    d = haversine(stop.lat, stop.lon, k[0], k[1])
                    if d < best_dist:
                        best_dist = d
                        best_key = k
                key = best_key if best_key is not None else (round(stop.lat, 5), round(stop.lon, 5))

            if key in ride_merged:
                existing = ride_merged[key]
                existing.duration += stop.duration
                if stop.traffic_light_wait is not None:
                    existing.traffic_light_wait = (existing.traffic_light_wait or 0) + stop.traffic_light_wait
                # Upgrade category if more specific
                if _CAT_PRIORITY.get(stop.category, 0) > _CAT_PRIORITY.get(existing.category, 0):
                    existing.category = stop.category
                    if stop.ref_lat is not None:
                        existing.ref_lat = stop.ref_lat
                        existing.ref_lon = stop.ref_lon
            else:
                ride_merged[key] = StopEvent(
                    lat=stop.lat, lon=stop.lon, duration=stop.duration,
                    category=stop.category, nearest_stop_name=stop.nearest_stop_name,
                    nearest_stop_dist=stop.nearest_stop_dist,
                    traffic_light_wait=stop.traffic_light_wait,
                    ref_lat=stop.ref_lat, ref_lon=stop.ref_lon,
                )

        # Phase 2: cross-ride merge
        for key, stop in ride_merged.items():
            if stop.ref_lat is not None and stop.ref_lon is not None:
                # Non-bottleneck: exact key match
                merged.setdefault(key, []).append(stop)
            else:
                # Bottleneck: spatial clustering across rides
                best_key = None
                best_dist = cluster_radius_m
                for k, events in merged.items():
                    if events[0].ref_lat is not None:
                        continue  # skip non-bottleneck clusters
                    d = haversine(key[0], key[1], k[0], k[1])
                    if d < best_dist:
                        best_dist = d
                        best_key = k
                if best_key is not None:
                    merged[best_key].append(stop)
                else:
                    merged.setdefault(key, []).append(stop)

    return merged


def _majority_category(events: list[StopEvent]) -> str:
    """Return the most common category among a list of stop events."""
    categories = [e.category for e in events]
    return max(set(categories), key=categories.count)


def _filter_bottlenecks(
    merged_stops: dict[tuple[float, float], list[StopEvent]], num_rides: int,
) -> dict[tuple[float, float], list[StopEvent]]:
    """Remove bottleneck locations where fewer than 50% of rides stop."""
    if num_rides <= 0:
        return merged_stops
    threshold = num_rides * 0.5
    return {
        key: events for key, events in merged_stops.items()
        if not (_majority_category(events) == "bottleneck" and len(events) < threshold)
    }


def compute_line_stats(
    ride_dfs: list[pd.DataFrame],
    all_stops: list[list[StopEvent]],
) -> dict:
    """Compute JSON-serializable stats for a tram line.

    Reuses the same merge-stops + _compute_stats logic from build_map.
    """
    merged_stops = _merge_stops(all_stops)
    merged_stops = _filter_bottlenecks(merged_stops, len(all_stops))
    stats = _compute_stats(ride_dfs, merged_stops)
    return _jsonify_stats(stats)


def _fmt_duration(seconds: float) -> str:
    """Format seconds as m:ss."""
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d}"


def _fmt_delta(seconds: float) -> str:
    """Format a delta in seconds as ±m:ss."""
    sign = "+" if seconds >= 0 else "-"
    m, s = divmod(int(round(abs(seconds))), 60)
    return f"{sign}{m}:{s:02d}"


def _fmt_pct(scenario: float, baseline: float) -> str:
    """Format relative change as percentage string."""
    if not baseline:
        return ""
    pct = (scenario - baseline) / baseline * 100
    return f"{pct:+.1f}%"


def _scenario_row(color: str, label: str, value: float, baseline: float) -> str:
    """Build one scenario row with absolute time, delta, and percentage."""
    delta = _fmt_delta(value - baseline)
    pct = _fmt_pct(value, baseline)
    return (
        f'<div style="display:flex;justify-content:space-between">'
        f'<span style="color:{color}">{label}:</span>'
        f'<span style="color:{color}"><b>{_fmt_duration(value)}</b>'
        f' ({delta}, {pct})</span>'
        f'</div>'
    )


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
    <style>
    @media (max-width: 639px) {{
        #stats-panel {{
            left: 5px !important; right: 5px !important;
            max-height: 60vh; overflow-y: auto;
            white-space: normal !important; font-size: 10px !important;
        }}
        #stats-toggle {{ left: 5px !important; }}
        #ssd-panel {{
            left: 5px !important; right: 5px !important;
            width: auto !important; height: 250px !important;
        }}
        #ssd-toggle {{ right: 5px !important; }}
        #layer-panel {{
            top: 5px !important; right: 5px !important;
            font-size: 10px !important; padding: 8px 10px !important;
        }}
    }}
    </style>
    <div id="stats-toggle" style="
        position:fixed; bottom:10px; left:10px; z-index:10000;
        background:rgba(253,249,219,0.95); border-radius:8px;
        padding:6px 12px; font-family:'Menlo','Consolas',monospace;
        font-size:11px; color:#222; cursor:pointer;
        box-shadow:0 2px 8px rgba(0,0,0,0.18); border:1px solid #ddd;
        pointer-events:auto;
    " onclick="document.getElementById('stats-panel').style.display =
        document.getElementById('stats-panel').style.display === 'none' ? 'block' : 'none'">
        Line Statistics
    </div>
    <div id="stats-panel" style="
        position: fixed; bottom: 40px; left: 10px; z-index: 9999;
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
        <div style="font-weight:bold;margin-bottom:2px;">Trip duration scenarios:</div>
        <div style="display:flex;justify-content:space-between">
            <span>Current:</span>
            <span><b>{_fmt_duration(stats['avg_trip_duration'])}</b></span>
        </div>
        {_scenario_row('#2a2', 'Green wave (TL priority)', stats['scenario_green_wave'], stats['avg_trip_duration'])}
        {_scenario_row('#c33', 'Red wave (worst case)', stats['scenario_red_wave'], stats['avg_trip_duration'])}
        {_scenario_row('#07a', 'Best case (no TL + no bottlenecks)', stats['scenario_best_case'], stats['avg_trip_duration'])}
    </div>
    """


def _layer_control_html(layer_js_names: dict[str, str]) -> str:
    """Build a custom layer-control legend styled like the stats panel.

    Args:
        layer_js_names: mapping of logical name → Folium JS variable name,
            e.g. {"route_velocity": "feature_group_abc123", "stops_tram_stop": "feature_group_def456"}
    """
    import json

    vel_colors = ["#d73027", "#f46d43", "#fdae61", "#fee08b", "#d9ef8b", "#a6d96a", "#1a9850"]
    gradient = ", ".join(vel_colors)
    js_map = json.dumps(layer_js_names)

    return """
    <div id="layer-panel" style="
        position:fixed; top:10px; right:10px; z-index:9999;
        background:rgba(255,255,255,0.92); border-radius:8px;
        padding:10px 14px; font-family:'Menlo','Consolas',monospace;
        font-size:11px; line-height:1.8; color:#222;
        box-shadow:0 2px 8px rgba(0,0,0,0.18); border:1px solid #ddd;
        pointer-events:auto;
    ">
        <div style="font-weight:bold;margin-bottom:4px;">Layers</div>

        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" checked data-layer="route_velocity" style="margin:0">
            <span style="display:inline-block;width:20px;height:4px;border-radius:2px;
                         background:linear-gradient(to right, """ + gradient + """)"></span>
            Route
        </label>

        <div style="font-weight:600;margin:6px 0 2px;color:#888;font-size:10px;
                     text-transform:uppercase;letter-spacing:0.5px">Stops</div>

        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" checked data-layer="stops_tram_stop" style="margin:0">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                         background:green;opacity:0.8"></span>
            Tram stops
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" checked data-layer="stops_traffic_light" style="margin:0">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                         background:red;opacity:0.8"></span>
            Traffic lights
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" checked data-layer="stops_combined" style="margin:0">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                         background:orange;opacity:0.8"></span>
            Combined
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer">
            <input type="checkbox" checked data-layer="stops_bottleneck" style="margin:0">
            <span style="display:inline-block;width:10px;height:10px;border-radius:50%;
                         background:gray;opacity:0.8"></span>
            Bottlenecks
        </label>
    </div>
    <script>
    document.addEventListener('DOMContentLoaded', function() {
        var nameToVar = """ + js_map + """;
        // Find the Leaflet map
        var map;
        for (var key in window) {
            if (window[key] instanceof L.Map) { map = window[key]; break; }
        }
        if (!map) return;

        document.querySelectorAll('#layer-panel input[data-layer]').forEach(function(cb) {
            cb.addEventListener('change', function() {
                var jsVar = nameToVar[cb.getAttribute('data-layer')];
                if (!jsVar) return;
                var layer = window[jsVar];
                if (!layer) return;
                if (cb.checked) { map.addLayer(layer); }
                else { map.removeLayer(layer); }
            });
        });
    });
    </script>
    """


def _speed_space_data(
    ride_dfs: list[pd.DataFrame], bin_width_m: float = 50.0
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


def _average_route(ride_dfs: list[pd.DataFrame], step_m: float = 10.0) -> pd.DataFrame:
    """Compute an averaged route line from multiple rides.

    Resamples each ride at fixed distance intervals and averages lat/lon/speed
    across rides at each distance bin. Uses max ride length so the full route
    is shown even when rides differ in length.

    Returns DataFrame with columns: cum_dist, lat, lon, velocity_kmh,
        n_rides, median_kmh, p25_kmh, p75_kmh
    """
    resampled = []
    for df in ride_dfs:
        if len(df) < 2:
            continue
        cum_dist = df["dist"].cumsum().values
        max_dist = cum_dist[-1]
        if max_dist < step_m:
            continue
        steps = np.arange(0, max_dist, step_m)
        lat_interp = np.interp(steps, cum_dist, df["lat"].values)
        lon_interp = np.interp(steps, cum_dist, df["lon"].values)
        vel_interp = np.interp(steps, cum_dist, df["velocity_kmh"].values)
        resampled.append({
            "steps": steps,
            "lat": lat_interp,
            "lon": lon_interp,
            "vel": vel_interp,
            "n_steps": len(steps),
        })

    if not resampled:
        return pd.DataFrame(columns=[
            "cum_dist", "lat", "lon", "velocity_kmh",
            "n_rides", "median_kmh", "p25_kmh", "p75_kmh",
        ])

    max_len = max(r["n_steps"] for r in resampled)
    steps = next(r["steps"] for r in resampled if r["n_steps"] == max_len)

    avg_lat = np.full(max_len, np.nan)
    avg_lon = np.full(max_len, np.nan)
    avg_vel = np.full(max_len, np.nan)
    median_vel = np.full(max_len, np.nan)
    p25_vel = np.full(max_len, np.nan)
    p75_vel = np.full(max_len, np.nan)
    n_rides = np.zeros(max_len, dtype=int)

    for i in range(max_len):
        lats = [r["lat"][i] for r in resampled if i < r["n_steps"]]
        lons = [r["lon"][i] for r in resampled if i < r["n_steps"]]
        vels = [r["vel"][i] for r in resampled if i < r["n_steps"]]
        n = len(lats)
        n_rides[i] = n
        avg_lat[i] = np.mean(lats)
        avg_lon[i] = np.mean(lons)
        avg_vel[i] = np.mean(vels)
        median_vel[i] = np.median(vels)
        if n >= 2:
            p25_vel[i] = np.percentile(vels, 25)
            p75_vel[i] = np.percentile(vels, 75)
        else:
            p25_vel[i] = vels[0]
            p75_vel[i] = vels[0]

    return pd.DataFrame({
        "cum_dist": steps,
        "lat": avg_lat,
        "lon": avg_lon,
        "velocity_kmh": avg_vel,
        "n_rides": n_rides,
        "median_kmh": median_vel,
        "p25_kmh": p25_vel,
        "p75_kmh": p75_vel,
    })


def build_map(
    ride_dfs: list[pd.DataFrame],
    all_stops: list[list[StopEvent]],
    title: str = "Velotrack",
    tram_stops: pd.DataFrame | None = None,
    traffic_lights: pd.DataFrame | None = None,
) -> folium.Map:
    """Build a Folium map from one or more rides with velocity-colored segments and stop markers.

    Args:
        ride_dfs: List of parsed GPX DataFrames (one per ride).
        all_stops: List of stop event lists (one per ride, aligned with ride_dfs).
        title: Map title.
        tram_stops: GTFS tram stop locations (for fixed stop marker positions).
        traffic_lights: Traffic light locations (for fixed stop marker positions).
    """
    num_rides = len(ride_dfs)

    # Center map on first ride's midpoint
    all_lats = [df["lat"].mean() for df in ride_dfs if not df.empty]
    all_lons = [df["lon"].mean() for df in ride_dfs if not df.empty]
    center_lat = sum(all_lats) / len(all_lats) if all_lats else 45.464
    center_lon = sum(all_lons) / len(all_lons) if all_lons else 9.19

    m = folium.Map(location=[center_lat, center_lon], zoom_start=14, tiles="cartodbpositron")

    # Feature groups for layer control
    route_group = folium.FeatureGroup(name="route_velocity", show=True)
    stop_groups = {
        cat: folium.FeatureGroup(name=f"stops_{cat}", show=True)
        for cat in STOP_COLORS
    }

    # Draw a single averaged velocity-colored route line
    avg_route = _average_route(ride_dfs)
    if len(avg_route) >= 2:
        for i in range(1, len(avg_route)):
            row = avg_route.iloc[i]
            coords = [
                [avg_route.iloc[i - 1]["lat"], avg_route.iloc[i - 1]["lon"]],
                [row["lat"], row["lon"]],
            ]
            speed = row["velocity_kmh"]
            n = int(row["n_rides"])
            median = row["median_kmh"]
            p25 = row["p25_kmh"]
            p75 = row["p75_kmh"]
            color = velocity_color(speed)
            popup_text = (
                f"<b>{speed:.1f} km/h</b> (avg)"
                f"<br>Median: {median:.1f} km/h"
                f"<br>P25–P75: {p25:.1f}–{p75:.1f} km/h"
                f"<br>Rides: {n}/{num_rides}"
            )
            folium.PolyLine(
                coords,
                color=color,
                weight=4,
                opacity=0.8,
                popup=folium.Popup(popup_text, max_width=200),
            ).add_to(route_group)

    # Merge stops: within each ride first (sum durations), then across rides
    # Filter bottlenecks below 50% threshold — used for both map and stats
    merged_stops = _filter_bottlenecks(_merge_stops(all_stops), num_rides)

    for (lat, lon), events in merged_stops.items():
        category = _majority_category(events)
        avg_duration = sum(e.duration for e in events) / len(events)
        count = len(events)

        nearest_name = next((e.nearest_stop_name for e in events if e.nearest_stop_name), "?")

        popup_parts = [
            f"<b>{category.replace('_', ' ').title()}</b>",
        ]
        if category in ("tram_stop", "combined"):
            popup_parts.append(f"Stop: {nearest_name}")
        elif category == "bottleneck":
            nearest_dist = min((e.nearest_stop_dist for e in events if e.nearest_stop_dist is not None), default=None)
            popup_parts.append(f"Nearest stop: {nearest_name}")
            if nearest_dist is not None:
                popup_parts.append(f"Distance: {nearest_dist:.0f}m")
        popup_parts.extend([
            f"Avg wait: {avg_duration:.0f}s",
            f"Occurrences: {count}/{num_rides} rides",
        ])
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

    # Custom layer control panel (replaces default LayerControl)
    layer_js_names = {"route_velocity": route_group.get_name()}
    for cat, group in stop_groups.items():
        layer_js_names[f"stops_{cat}"] = group.get_name()
    m.get_root().html.add_child(Element(_layer_control_html(layer_js_names)))

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
