# 🚋 Velotrack

<p align="center">
  <img src="assets/img/teaser.png" alt="Velotrack teaser — interactive tram speed map of Milan" width="700">
</p>

Analyze GPS recordings of tram rides in Milan to produce interactive maps with velocity heatmaps and classified stop events.

Record your tram rides with any GPS tracking app, drop the GPX files into the project, and Velotrack will generate an HTML map showing how fast the tram moved along the route and where it stopped — distinguishing between tram stops, traffic lights, and bottlenecks.

---

> **For Italian speakers 🇮🇹:**
> Questo è parte di un progetto in collaborazione con [Velocipiedi](https://velocipiedi.it), un progetto di divulgazione italiano sulla mobilità e l'urbanistica.
> Qualche mese fa hanno lanciato [TRAMsformaMi](https://velocipiedi.it/tramsformami/), una campagna rivolta al comune di Milano per chiedere il potenziamento dei mezzi pubblici di superficie.
> Velotrack nasce come tool open-source che ho sviluppato per analizzare i dati GPS delle corse in tram a Milano, con l'obiettivo di produrre mappe interattive che mostrano le velocità e i tempi di attesa lungo le linee del tram.
> I dati che nel futuro arriveranno grazie alla community di [Velocipiedi (instagram)](https://www.instagram.com/velocipiedi/) e [PensamiCiclabile (instagram)](https://www.instagram.com/pensamiciclabile/) potranno essere analizzati con Velotrack per identificare i problemi più urgenti e supportare le richieste di miglioramento del servizio.
> L'intero processo è open source, così chiunque può contribuire, esaminare e replicare i risultati, garantendo il massimo livello di trasparenza possibile.

---

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
#    Naming convention: line<N>_<direction>_<description>.gpx
#    Example: line1_west_repubblica_xxsettembre.gpx

# 3. (Optional) Add traffic light locations
uv run main.py template          # creates data/traffic_lights.csv
# Edit the CSV with lat, lon, name, notes

# 4. Generate maps
uv run main.py analyze

# 5. Open the result
open output/line1_west.html
```

You can also analyze specific files:

```bash
uv run main.py analyze data/rides/line1_repubblica_xxsettembre.gpx
```

## Managing data

### Recording GPX rides

To get accurate data, follow these rules when recording a tram ride with your GPS app:

1. **Start tracking before the tram departs**: begin recording as soon as the tram arrives at your stop, while you are still standing outside. This captures the real departure time and avoids cutting off the first segment.
2. **Stay still inside the tram**: do not walk around. Movement inside the vehicle adds GPS noise and creates false speed readings. Try to sit or stand in one spot for the entire ride.
3. **Stop tracking after the tram stops**: wait until the tram has come to a full stop at your destination before ending the recording. This ensures the final stop is captured correctly.
4. **Use a high recording frequency**: set your GPS app to record a point every 1 second if possible. Lower frequencies (e.g. every 5s) may miss short stops.
5. **Keep your phone near a window**: GPS signal is stronger near windows. Avoid keeping the phone deep in a bag or pocket, especially in older trams with metal bodywork.

### GPX file naming

Place `.gpx` files in `data/rides/`. The filename determines which tram line the ride belongs to:

```
line1_west_repubblica_xxsettembre.gpx    → tram line 1
line2_est_duomo_notte.gpx                → tram line 2
line15_north_morning_rush.gpx            → tram line 15
```

The pattern is `line<N>_<direction>_<description>.gpx`. Files that don't match this pattern are processed individually. Multiple rides on the same line are grouped and averaged in the output map.

To remove a ride, delete the GPX file and re-run `uv run main.py analyze`.

### Traffic lights

Edit `data/traffic_lights.csv` to add known traffic light positions:

```csv
lat,lon,name,notes,added_at,added_by
45.4781,9.1897,Corso Buenos Aires / Via Pecchio,often long wait,,2026-03-04T12:54:45.437245+00:00,daniel
```

This is optional — without it, stops near traffic lights will be classified as bottlenecks instead.

To view all traffic lights on an interactive map:

```bash
uv run main.py traffic-lights
open outputs/traffic_lights.html
```

(**recommended**) For an interactive workflow — right-click on the map to add traffic lights directly:

```bash
uv run main.py traffic-lights --watch
```

With `--watch`, a local HTTP server starts at `http://localhost:8000`. The map includes a Google Satellite + Labels layer (toggle in top-right) for easy identification. Right-click anywhere on the map to open a popup form — enter a name (required) and optional notes, then click "Add". The page reloads automatically with the new marker. Each entry is timestamped (`added_at`) and tagged with your local username (`added_by`) in the CSV.

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
