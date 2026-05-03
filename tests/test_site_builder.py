import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import velotrack.site_builder as sb
from velotrack.site_builder import LineInfo


class TestSiteBuilderIntegration(unittest.TestCase):
    def _stats(self) -> dict:
        return {
            "speed": {
                "avg_trip": 12.3,
                "avg_moving": 16.0,
                "peak": 25.0,
                "median_moving": 14.0,
                "median_trip": 10.0,
                "p25": 8.0,
                "p75": 18.0,
            },
            "cat_counts": {"transit_stop": 1},
            "cat_total_avg": {"transit_stop": 20.0, "bottleneck": 0.0},
            "total_stops": 1,
            "total_delay": 20.0,
            "avg_wait": 20.0,
            "green_wave": 0.0,
            "red_wave": 0.0,
            "p25_sum": 0.0,
            "p75_sum": 0.0,
            "avg_trip_duration": 120.0,
            "priority_savings_excl_bottlenecks": 0.0,
            "priority_savings_incl_bottlenecks": 0.0,
            "scenario_green_wave": 120.0,
            "scenario_red_wave": 120.0,
            "scenario_best_case": 120.0,
            "tl_wait_total": 0.0,
            "boarding_total": 20.0,
        }

    def test_build_site_writes_location_stats_and_hotspots_page(self):
        line = LineInfo(
            line_key="line1_test",
            display_name="Line 1 — Test",
            num_rides=1,
            stats=self._stats(),
            total_distance_km=3.2,
        )

        location_stats = [{
            "location_key": "45.10000,9.10000",
            "lat": 45.1,
            "lon": 9.1,
            "category": "traffic_light",
            "obs_count": 2,
            "mean_wait_s": 25.0,
            "median_wait_s": 25.0,
            "p25_s": 20.0,
            "p75_s": 30.0,
            "min_s": 20.0,
            "max_s": 30.0,
            "time_bands": {
                "am_peak": {"obs_count": 2, "mean_wait_s": 25.0},
            },
            "line_keys": ["line1_test"],
            "line_count": 1,
            "lines": [{
                "line_key": "line1_test",
                "line_number": "1",
                "direction_name": "Test",
                "label": "Line 1 (Test)",
                "obs_count": 2,
                "mean_wait_s": 25.0,
                "time_bands": {"am_peak": {"obs_count": 2, "mean_wait_s": 25.0}},
            }],
        }]
        hotspot_slices = {"all": location_stats}

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            site_dir = tmp / "site"
            maps_dir = site_dir / "maps"
            lines_dir = site_dir / "lines"
            data_dir = site_dir / "data"

            with patch.object(sb, "SITE_DIR", site_dir), \
                 patch.object(sb, "MAPS_DIR", maps_dir), \
                 patch.object(sb, "LINES_DIR", lines_dir), \
                 patch.object(sb, "DATA_DIR_SITE", data_dir), \
                 patch.object(sb, "DAILY_TRIPS_JSON", tmp / "daily_trips.json"), \
                 patch.object(sb, "GTFS_STOPS_JSON", tmp / "gtfs_stops.json"), \
                 patch.object(sb, "TEMPLATES_DIR", Path(__file__).resolve().parents[1] / "templates"), \
                 patch.object(sb, "_latest_git_update_dates", return_value={"it": "3 Maggio 2026", "en": "3 May 2026"}):
                sb.build_site([line], location_stats=location_stats, hotspot_slices=hotspot_slices)

            self.assertTrue((site_dir / "index.html").exists())
            self.assertTrue((site_dir / "hotspots.html").exists())
            self.assertTrue((data_dir / "location_stats.json").exists())
            home_html = (site_dir / "index.html").read_text()
            self.assertIn("Ultimo aggiornamento: 3 Maggio 2026", home_html)
            self.assertIn("Last updated: 3 May 2026", home_html)
            html = (site_dir / "hotspots.html").read_text()
            self.assertIn("id=\"hotspots-map\"", html)
            self.assertIn("id=\"hotspots-list\"", html)
            self.assertIn("id=\"hotspot-category\"", html)
            self.assertIn("id=\"hotspot-timeband\"", html)
            self.assertNotIn("id=\"hotspot-direction\"", html)

            parsed = json.loads((data_dir / "location_stats.json").read_text())
            self.assertEqual(len(parsed), 1)
            self.assertEqual(parsed[0]["category"], "traffic_light")


if __name__ == "__main__":
    unittest.main()
