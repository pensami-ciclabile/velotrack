import unittest
from pathlib import Path

import pandas as pd

from velotrack.location_analytics import (
    LocationAggregate,
    aggregate_location_events,
    build_hotspot_slices,
    build_normalized_events,
    build_ride_context,
    infer_direction_id,
    infer_time_band,
    normalize_stop_events,
    rank_hotspots,
)
from velotrack.stop_detector import StopEvent


class TestLocationAnalytics(unittest.TestCase):
    def _ride_df(self, lon_end: float, ts: str = "2026-03-07T07:00:00+00:00") -> pd.DataFrame:
        t0 = pd.Timestamp(ts)
        t1 = t0 + pd.Timedelta(seconds=20)
        return pd.DataFrame([
            {"lat": 45.0, "lon": 9.0, "time": t0, "dt": None, "dist": 0.0, "velocity_kmh": 0.0},
            {"lat": 45.0, "lon": lon_end, "time": t1, "dt": 20.0, "dist": 100.0, "velocity_kmh": 18.0},
        ])

    def test_direction_and_time_band_are_deterministic(self):
        east_df = self._ride_df(9.01)
        west_df = self._ride_df(8.99)

        self.assertEqual(infer_direction_id(east_df), "E")
        self.assertEqual(infer_direction_id(west_df), "W")
        self.assertEqual(infer_time_band(pd.Timestamp("2026-03-07T07:15:00+00:00")), "am_peak")
        self.assertEqual(infer_time_band(pd.Timestamp("2026-03-07T18:45:00+00:00")), "pm_peak")

    def test_normalization_links_shared_references(self):
        df_a = self._ride_df(9.01)
        df_b = self._ride_df(9.02)

        rides = {
            "line5_ortica": {
                "ride_files": [(Path("a.gpx"), "a.gpx")],
                "ride_dfs": [df_a],
                "all_stops": [[
                    StopEvent(
                        lat=45.1,
                        lon=9.1,
                        duration=30.0,
                        category="traffic_light",
                        ref_lat=45.100001,
                        ref_lon=9.100001,
                    )
                ]],
            },
            "line19_castelli": {
                "ride_files": [(Path("b.gpx"), "b.gpx")],
                "ride_dfs": [df_b],
                "all_stops": [[
                    StopEvent(
                        lat=45.1,
                        lon=9.1,
                        duration=20.0,
                        category="traffic_light",
                        ref_lat=45.100001,
                        ref_lon=9.100001,
                    )
                ]],
            },
        }

        events = build_normalized_events(rides)
        self.assertEqual(len(events), 2)
        self.assertEqual(events[0].location_key, events[1].location_key)

    def test_unknown_bottlenecks_stay_separate_when_coords_differ(self):
        df = self._ride_df(9.01)
        ctx = build_ride_context("line1", Path("x.gpx"), df, 1)
        events = normalize_stop_events(ctx, [
            StopEvent(lat=45.123454, lon=9.456784, duration=12, category="bottleneck"),
            StopEvent(lat=45.123456, lon=9.456786, duration=10, category="bottleneck"),
        ])
        self.assertNotEqual(events[0].location_key, events[1].location_key)

    def test_aggregates_per_location_with_line_direction_labels_and_time_bands(self):
        # Same physical traffic light hit by two lines in the same time band.
        df_a = self._ride_df(9.01, "2026-03-07T07:10:00+00:00")
        df_b = self._ride_df(9.02, "2026-03-07T07:25:00+00:00")
        rides = {
            "line1_roserio": {
                "ride_files": [(Path("a.gpx"), "a.gpx")],
                "ride_dfs": [df_a],
                "all_stops": [[
                    StopEvent(lat=45.1, lon=9.1, duration=30, category="traffic_light", ref_lat=45.10001, ref_lon=9.10001)
                ]],
            },
            "line15_duomo": {
                "ride_files": [(Path("b.gpx"), "b.gpx")],
                "ride_dfs": [df_b],
                "all_stops": [[
                    StopEvent(lat=45.1, lon=9.1, duration=10, category="traffic_light", ref_lat=45.10001, ref_lon=9.10001)
                ]],
            },
        }

        events = build_normalized_events(rides)
        aggregates = aggregate_location_events(events)
        self.assertEqual(len(aggregates), 1)

        agg: LocationAggregate = aggregates[0]
        self.assertEqual(agg.obs_count, 2)
        self.assertEqual(agg.line_count, 2)
        self.assertEqual(agg.line_keys, ["line1_roserio", "line15_duomo"])
        self.assertAlmostEqual(agg.mean_wait_s, 20.0, places=3)
        self.assertAlmostEqual(agg.median_wait_s, 20.0, places=3)

        self.assertIn("am_peak", agg.time_bands)
        self.assertEqual(agg.time_bands["am_peak"]["obs_count"], 2)

        labels = [line.label for line in agg.lines]
        self.assertEqual(labels, ["Line 1 (Roserio)", "Line 15 (Duomo)"])

        # Top-level totals equal sum of time-band totals.
        total_band_obs = sum(b["obs_count"] for b in agg.time_bands.values())
        self.assertEqual(total_band_obs, agg.obs_count)

        slices = build_hotspot_slices(aggregates, limit=5)
        self.assertIn("all", slices)
        self.assertEqual(len(slices["all"]), 1)

    def test_mixed_category_resolution_is_deterministic(self):
        # Equal counts across categories at one location resolves by priority.
        events = [
            # traffic_light
            *normalize_stop_events(
                build_ride_context("line1_roserio", Path("a.gpx"), self._ride_df(9.01), 1),
                [StopEvent(lat=45.1, lon=9.1, duration=12, category="traffic_light", ref_lat=45.101, ref_lon=9.101)],
            ),
            # combined at same location key
            *normalize_stop_events(
                build_ride_context("line2_duomo", Path("b.gpx"), self._ride_df(9.02), 1),
                [StopEvent(lat=45.1, lon=9.1, duration=14, category="combined", ref_lat=45.101, ref_lon=9.101)],
            ),
        ]

        aggregates = aggregate_location_events(events)
        self.assertEqual(len(aggregates), 1)
        self.assertEqual(aggregates[0].category, "traffic_light")

    def test_rank_hotspots_filters_category_and_time_band(self):
        rides = {
            "line1_roserio": {
                "ride_files": [(Path("a.gpx"), "a.gpx"), (Path("a2.gpx"), "a2.gpx")],
                "ride_dfs": [
                    self._ride_df(9.01, "2026-03-07T07:10:00+00:00"),  # am_peak
                    self._ride_df(9.01, "2026-03-07T12:10:00+00:00"),  # midday
                ],
                "all_stops": [
                    [StopEvent(lat=45.1, lon=9.1, duration=30, category="traffic_light", ref_lat=45.10001, ref_lon=9.10001)],
                    [StopEvent(lat=45.1, lon=9.1, duration=10, category="traffic_light", ref_lat=45.10001, ref_lon=9.10001)],
                ],
            },
            "line5_ortica": {
                "ride_files": [(Path("b.gpx"), "b.gpx")],
                "ride_dfs": [self._ride_df(9.02, "2026-03-07T12:20:00+00:00")],  # midday
                "all_stops": [
                    [StopEvent(lat=45.2, lon=9.2, duration=50, category="combined", ref_lat=45.20001, ref_lon=9.20001)],
                ],
            },
        }

        aggregates = aggregate_location_events(build_normalized_events(rides))

        traffic_lights = rank_hotspots(aggregates, category="traffic_light", time_band="all")
        self.assertEqual(len(traffic_lights), 1)
        self.assertEqual(traffic_lights[0]["location_key"], "45.10001,9.10001")

        midday = rank_hotspots(aggregates, category="all", time_band="midday")
        self.assertEqual(len(midday), 2)
        self.assertEqual(midday[0]["location_key"], "45.20001,9.20001")
        self.assertAlmostEqual(midday[0]["rank_mean_wait_s"], 50.0, places=3)
        self.assertEqual(midday[1]["location_key"], "45.10001,9.10001")
        self.assertAlmostEqual(midday[1]["rank_mean_wait_s"], 10.0, places=3)

        pm_peak = rank_hotspots(aggregates, category="all", time_band="pm_peak")
        self.assertEqual(pm_peak, [])


if __name__ == "__main__":
    unittest.main()
