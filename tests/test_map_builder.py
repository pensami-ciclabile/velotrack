import unittest

import pandas as pd

from velotrack.map_builder import compute_line_stats


class TestMapBuilderEdgeCases(unittest.TestCase):
    def test_compute_line_stats_with_degenerate_ride_does_not_crash(self):
        df = pd.DataFrame([
            {
                "lat": 45.0,
                "lon": 9.0,
                "ele": 0.0,
                "time": pd.Timestamp("2026-01-01T00:00:00+00:00"),
                "dt": None,
                "dist": 0.0,
                "velocity_kmh": 0.0,
            }
        ])

        stats = compute_line_stats([df], [[]])
        self.assertEqual(stats["speed"]["avg_trip"], 0)
        self.assertEqual(stats["speed"]["avg_moving"], 0)
        self.assertEqual(stats["avg_trip_duration"], 0)
        self.assertEqual(stats["total_delay"], 0)


if __name__ == "__main__":
    unittest.main()
