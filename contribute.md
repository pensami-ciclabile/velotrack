# Contribute to Velotrack

This guide explains architecture, analytics contracts, and test expectations for safe changes.

## 1) Architecture at a glance

`build-site` runs two parallel analytics layers:

1. **Line analytics (line-scoped)**
- Source: rides grouped by `line<N>_<destination>_...`.
- Module: `/Volumes/T7/velotrack/velotrack/map_builder.py`.
- Output: line KPIs + line maps used by home cards and `/site/lines/*.html`.
- Rule: line KPIs are computed from that line's rides only.

2. **Infrastructure analytics (cross-line, location-scoped)**
- Source: normalized stop events from all rides.
- Module: `/Volumes/T7/velotrack/velotrack/location_analytics.py`.
- Output: `/Volumes/T7/velotrack/site/data/location_stats.json` + `/Volumes/T7/velotrack/site/hotspots.html`.
- Rule: one aggregate row per physical hotspot (`location_key`), with nested breakdowns by `time_band` and by line contributions.

## 2) Pipeline and module responsibilities

### Ingestion and stop classification
- `/Volumes/T7/velotrack/main.py::_process_rides()`
  - Parses GPX with `parse_gpx()`.
  - Detects stops with `detect_stops()`.
  - Classifies stops with `classify_stops()`.
  - Returns `rides_by_line` with aligned arrays: `ride_files`, `ride_dfs`, `all_stops`.

- `/Volumes/T7/velotrack/velotrack/gpx_parser.py`
  - GPX -> DataFrame (`lat`, `lon`, `time`, `dt`, `dist`, `velocity_kmh`).
  - Clamps unrealistic speed spikes.

- `/Volumes/T7/velotrack/velotrack/stop_detector.py`
  - Categories: `tram_stop`, `traffic_light`, `combined`, `bottleneck`.

### Line analytics
- `/Volumes/T7/velotrack/velotrack/map_builder.py`
  - `compute_line_stats()` computes per-line KPIs and scenario totals.
  - `build_map()` renders per-line Folium maps.

### Infrastructure analytics
- `/Volumes/T7/velotrack/velotrack/location_analytics.py`
  - `NormalizedStopEvent`: canonical event row.
  - `build_normalized_events(rides_by_line)`: builds one global stream.
  - `aggregate_location_events(events)`: groups by physical `location_key`.
  - `build_hotspot_slices(...)`: home page preview slices.
  - `rank_hotspots(...)`: backend helper for category/time-band ranking semantics.

Key normalization fields:
- `ride_id`, `line_key`, `direction_id`, `time_band`
- `location_key`, `location_type`, `location_lat`, `location_lon`
- `duration_s`, `tl_component_s`, `is_combined`

Location key rule:
- Prefer canonical `ref_lat/ref_lon` when present.
- Fallback to rounded observed coordinates for unknown bottlenecks.

### Site generation
- `/Volumes/T7/velotrack/velotrack/site_builder.py`
  - Exports `/site/data/lines.json` and `/site/data/location_stats.json`.
  - Renders `/site/index.html`, `/site/lines/*.html`, `/site/hotspots.html`.

- Templates/frontend:
  - `/Volumes/T7/velotrack/templates/home.html`: line cards + hotspot preview table.
  - `/Volumes/T7/velotrack/templates/hotspots.html`: map-first hotspots page.
  - `/Volumes/T7/velotrack/templates/static/js/main.js`: filtering, ranking, map sync, popup rendering.
  - `/Volumes/T7/velotrack/templates/static/css/style.css`: hotspots map/list layout styles.

## 3) Data contracts

### `/Volumes/T7/velotrack/site/data/location_stats.json`

One row per physical hotspot with stable top-level keys:
- `location_key`, `lat`, `lon`, `category`
- `obs_count`, `mean_wait_s`, `median_wait_s`, `p25_s`, `p75_s`, `min_s`, `max_s`
- `line_keys`, `line_count`
- `time_bands`: object keyed by band (`am_peak`, `midday`, `pm_peak`, `evening`, `night`, `unknown`)
- `lines`: array of line contributions:
  - `line_key`, `line_number`, `direction_name`, `label`
  - `obs_count`, `mean_wait_s`
  - `time_bands` (per-line per-band `obs_count` + `mean_wait_s`)

Category resolution when mixed categories hit one location:
- dominant count wins; ties use deterministic priority: `traffic_light > combined > tram_stop > bottleneck > unknown`.

## 4) Hotspots UX behavior (expected)

Hotspots page (`/site/hotspots.html`):
- Filters: `category` + `time_band` only.
- Map: always shows all currently filtered hotspots.
- Ranking: top 20 filtered hotspots.
- Selector: radio list; selecting an item pans/zooms/highlights marker and opens popup.
- Popup: overall metrics + per-time-band stats + line contributions (`Line N (Destination)`).

Ranking semantics:
- `time_band=all`: rank by overall `mean_wait_s`, then `obs_count`.
- specific band: rank by that band's `mean_wait_s`, then band `obs_count`.
- rows with zero observations in selected band are excluded.

## 5) Testing strategy

Test framework: `unittest`.

Run all tests:

```bash
uv run python -m unittest discover -s tests -v
```

### Current test coverage
- `/Volumes/T7/velotrack/tests/test_location_analytics.py`
  - shared-location normalization across lines
  - unknown bottleneck separation
  - deterministic direction/time-band inference
  - per-location aggregate shape (lines + time bands)
  - deterministic mixed-category resolution
  - ranking/filter behavior by category and time band

- `/Volumes/T7/velotrack/tests/test_map_builder.py`
  - degenerate ride regression safety

- `/Volumes/T7/velotrack/tests/test_site_builder.py`
  - site generation writes `location_stats.json`
  - hotspots page includes map/list/filter containers and no direction filter

### Manual acceptance checklist
1. Build site: `uv run main.py build-site`.
2. Open `/Volumes/T7/velotrack/site/hotspots.html`.
3. Verify:
- category/time-band filters update both map and ranking.
- ranking radios focus/open corresponding marker popup.
- popup shows overall + per-band + per-line data.
4. Confirm line pages/cards remain unchanged.

## 6) Extension guidelines

1. Keep line and infrastructure analytics separated.
- Do not mix cross-line pooled values into line KPI totals unless explicitly changing product semantics.

2. Prefer additive schema changes.
- Add fields instead of renaming/removing existing keys used by frontend.

3. Preserve deterministic behavior.
- Stable keying, stable category tie-breaks, stable sorting.

4. Document and test any new stratification.
- If adding weekday/weekend/weather/etc., update normalization, aggregation, UI filters, and tests together.

5. Treat infrastructure metrics as observational.
- Current model is observed-stop analytics, not pass-through exposure inference.
