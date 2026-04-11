"""Central definition of which transit lines Velotrack tracks.

Velotrack follows two classes of ATM surface lines:

* **Tram** — every GTFS route with ``route_type == 0``.
* **Rapid bus** ("Linee di forza") — ATM's orbital high-capacity corridors
  that behave like BRTs: lines 90, 91, 92, 93. Technically a mix of diesel
  bus (``route_type == 3``) and trolleybus (``route_type == 11``).

This module is the single source of truth for that classification so the
rest of the pipeline (GTFS extraction, OSM snapping, site builder) can
branch on a well-defined ``mode`` string rather than scattering magic
numbers around.
"""

# GTFS ``route_type`` codes we care about. Anything not listed is untracked.
_TRAM_ROUTE_TYPE = 0
_BUS_ROUTE_TYPES = frozenset({3, 11})  # 3 = bus, 11 = trolleybus

# ATM "linee di forza" — orbital rapid-bus corridors similar to BRTs.
# 90 and 91 are trolleybus, 92 and 93 are diesel bus.
RAPID_BUS_LINES: frozenset[str] = frozenset({"90", "91", "92", "93"})

# Mode strings used throughout the codebase.
TRAM = "tram"
RAPID_BUS = "rapid_bus"

# Human-readable labels for each mode, keyed by language.
MODE_LABELS: dict[str, dict[str, str]] = {
    TRAM: {
        "it_plural": "Linee tramviarie",
        "en_plural": "Tram lines",
        "it_singular": "Tram",
        "en_singular": "Tram",
    },
    RAPID_BUS: {
        "it_plural": "Linee di forza",
        "en_plural": "Rapid bus lines",
        "it_singular": "Linea di forza",
        "en_singular": "Rapid bus",
    },
}


def mode_for_route(route_short_name: str, route_type: int) -> str | None:
    """Return ``"tram"``, ``"rapid_bus"`` or ``None`` for a GTFS route row.

    ``None`` means the route is not part of Velotrack's tracked scope and
    should be dropped from every extractor.
    """
    if route_type == _TRAM_ROUTE_TYPE:
        return TRAM
    name = str(route_short_name).strip()
    if name in RAPID_BUS_LINES and route_type in _BUS_ROUTE_TYPES:
        return RAPID_BUS
    return None


def mode_for_line_number(line_number: str) -> str:
    """Classify a line by its number alone.

    Used where we no longer have the raw GTFS row — e.g. when looking at a
    ride filename ``line90_*`` or an already-cached ``line_stops.json`` key.
    Assumes the line is one Velotrack tracks; untracked numbers fall back to
    ``tram`` (the historical default) because every code path that calls
    this is already operating on tracked-line data.
    """
    return RAPID_BUS if str(line_number).strip() in RAPID_BUS_LINES else TRAM


def sort_key(line_number: str) -> tuple[int, int]:
    """Sort key that groups tram lines before rapid-bus lines, then numeric.

    Use with ``sorted(..., key=lambda x: sort_key(x.line_num))`` to render
    tram lines first, followed by "linee di forza", each block ordered
    numerically.
    """
    n = str(line_number).strip()
    try:
        num = int(n)
    except ValueError:
        num = 9999
    mode_rank = 1 if n in RAPID_BUS_LINES else 0
    return (mode_rank, num)
