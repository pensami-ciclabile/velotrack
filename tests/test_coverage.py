import unittest

import pandas as pd

from velotrack.coverage import compute_city_stop_coverage, compute_line_coverage


class TestCoverageAggregation(unittest.TestCase):
    def test_city_stop_coverage_counts_ride_hits_across_lines(self):
        rides_by_line = {
            "line1_test": {
                "ride_dfs": [
                    pd.DataFrame({"lat": [45.0], "lon": [9.0]}),
                    pd.DataFrame({"lat": [45.0001], "lon": [9.0001]}),
                ],
            },
            "line2_test": {
                "ride_dfs": [
                    pd.DataFrame({"lat": [46.0], "lon": [10.0]}),
                ],
            },
        }
        line_stops = {
            "1": [{"stop_id": "shared", "name": "Shared stop", "lat": 45.0, "lon": 9.0}],
            "2": [{"stop_id": "shared", "name": "Shared stop", "lat": 45.0, "lon": 9.0}],
        }

        line_coverage = compute_line_coverage(rides_by_line, line_stops, radius_m=50)
        city_stops = compute_city_stop_coverage(line_coverage)

        self.assertEqual(len(city_stops), 1)
        stop = city_stops[0]
        self.assertTrue(stop["covered"])
        self.assertEqual(stop["mapped_count"], 2)
        self.assertEqual(stop["served_lines"], ["1", "2"])
        self.assertEqual(stop["mapped_lines"], ["1"])
        self.assertEqual(stop["missing_lines"], ["2"])


if __name__ == "__main__":
    unittest.main()
