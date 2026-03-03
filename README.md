# Velotrack

Analyze GPS recordings of tram rides in Milan to produce interactive maps with velocity heatmaps and classified stop events.

Record your tram rides with any GPS tracking app, drop the GPX files into the project, and Velotrack will generate an HTML map showing how fast the tram moved along the route and where it stopped — distinguishing between tram stops, traffic lights, and bottlenecks.

## How it works

The GPS tracking app stops recording points when you're not moving, creating time gaps in the data. Velotrack exploits this: a **stop** is any gap longer than 5 seconds where the tram moved less than 15 meters. Each stop is then classified by proximity to known tram stops (from Milan's official GTFS data) and user-provided traffic light locations.

**Stop categories:**
- **Tram stop** — within 30m of a GTFS tram stop
- **Traffic light** — within 25m of a known traffic light
- **Combined** — near both a tram stop and a traffic light
- **Bottleneck** — none of the above (congestion, intersections, etc.)

**Velocity outlier removal:** GPS jitter can produce unrealistic speed spikes. Velocities above the configured max (default 50 km/h) are clamped before computing statistics or rendering the heatmap.

When multiple rides share the same tram line, wait times and velocities are averaged.

**Line statistics panel:** Each generated map includes a summary panel (bottom-left corner) with:
- **Speed stats** — average, peak, median, P25/P75 (computed from moving segments only)
- **Stop breakdown** — count and total wait time per category (tram stops, traffic lights, combined, bottlenecks)
- **Scenario analysis** — green wave (sum of min wait at each location), red wave (sum of max), and P25/P75 totals

## Quick start

```bash
# 1. Download Milan tram stop data (one-time)
uv run main.py download-gtfs

# 2. Place your GPX files in data/rides/
#    Naming convention: line<N>_<description>.gpx
#    Example: line1_repubblica_xxsettembre.gpx

# 3. (Optional) Add traffic light locations
uv run main.py template          # creates data/traffic_lights.csv
# Edit the CSV with lat, lon, name, notes

# 4. Generate maps
uv run main.py analyze

# 5. Open the result
open data/output/line1.html
```

You can also analyze specific files:

```bash
uv run main.py analyze data/rides/line1_repubblica_xxsettembre.gpx
```

## Managing data

### GPX rides

Place `.gpx` files in `data/rides/`. The filename determines which tram line the ride belongs to:

```
line1_repubblica_xxsettembre.gpx   → tram line 1
line2_duomo_notte.gpx              → tram line 2
line15_morning_rush.gpx            → tram line 15
```

The pattern is `line<N>_<description>.gpx`. Files that don't match this pattern are processed individually. Multiple rides on the same line are grouped and averaged in the output map.

To remove a ride, delete the GPX file and re-run `uv run main.py analyze`.

### Traffic lights

Edit `data/traffic_lights.csv` to add known traffic light positions:

```csv
lat,lon,name,notes
45.4781,9.1897,Corso Buenos Aires / Via Pecchio,often long wait
```

This is optional — without it, stops near traffic lights will be classified as bottlenecks instead.

### GTFS data

Tram stop locations are downloaded from [Milan's open data portal](https://dati.comune.milano.it/dataset/ds929-orari-del-trasporto-pubblico-locale-nel-comune-di-milano-in-formato-gtfs). Re-run `uv run main.py download-gtfs` to update them. The data is stored in `data/gtfs/` (gitignored).

## Project structure

```
velotrack/
  main.py                  # CLI entry point
  velotrack/
    config.py              # thresholds, paths, colors
    gpx_parser.py          # GPX → DataFrame with velocity
    stop_detector.py       # detect + classify stops
    gtfs.py                # download/parse GTFS tram stops
    map_builder.py         # folium map generation
  data/
    rides/                 # your GPX files go here
    traffic_lights.csv     # user-provided traffic light locations
    gtfs/                  # auto-downloaded, gitignored
    output/                # generated HTML maps, gitignored
```
