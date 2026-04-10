from pathlib import Path

# Paths
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RIDES_DIR = DATA_DIR / "rides"
GTFS_DIR = DATA_DIR / "gtfs"
OUTPUT_DIR = PROJECT_ROOT / "outputs"
TRAFFIC_LIGHTS_CSV = DATA_DIR / "traffic_lights.csv"
TRAM_STOPS_CSV = DATA_DIR / "tram_stops.csv"
DAILY_TRIPS_JSON = DATA_DIR / "daily_trips.json"
GTFS_STOPS_JSON = DATA_DIR / "gtfs_stops.json"
LINE_STOPS_JSON = DATA_DIR / "line_stops.json"
OSM_TRACKS_JSON = DATA_DIR / "osm_tracks.json"

# OSM track snapping
SNAP_MAX_DISTANCE = 30.0      # meters — skip points farther than this
SNAP_CONTINUITY_BONUS = 10.0  # meters — preference for contiguous segments

# Site generation
SITE_DIR = PROJECT_ROOT / "site"
MAPS_DIR = SITE_DIR / "maps"
LINES_DIR = SITE_DIR / "lines"
DATA_DIR_SITE = SITE_DIR / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"

# GTFS
GTFS_URL = "https://dati.comune.milano.it/dataset/ae3f3db9-de61-45b7-94e7-9395c0e3ef53/resource/6251f156-4c74-4a0b-904e-01bcb701a686/download/gtfs.zip"

# Stop detection
STOP_TIME_GAP = 5.0  # seconds — gap threshold for a stop
STOP_DISTANCE = 15.0  # meters — max movement during a stop
TRAM_STOP_RADIUS = 30.0  # meters — match radius to GTFS tram stop
TRAFFIC_LIGHT_RADIUS = 25.0  # meters — match radius to traffic light
COMBINED_TRAM_DEDUCT = 12.0  # seconds — estimated boarding time deducted for combined stops

# Velocity outlier removal
MAX_REALISTIC_SPEED = 50.0  # km/h — cap for outlier removal

# Velocity color bins: (max_kmh, color)
VELOCITY_COLORS = [
    (5, "#d73027"),    # red — very slow / crawling
    (10, "#f46d43"),   # orange-red
    (15, "#fdae61"),   # orange
    (20, "#fee08b"),   # yellow
    (25, "#d9ef8b"),   # yellow-green
    (30, "#a6d96a"),   # light green
    (40, "#66bd63"),   # green
    (float("inf"), "#1a9850"),  # dark green — fast
]

# Stop marker colors by category
STOP_COLORS = {
    "tram_stop": "green",
    "traffic_light": "red",
    "combined": "orange",
    "bottleneck": "gray",
}
