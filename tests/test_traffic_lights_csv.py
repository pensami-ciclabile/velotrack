import csv
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


class TestTrafficLightsCsv(unittest.TestCase):
    def test_remove_traffic_light_removes_first_matching_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "traffic_lights.csv"
            csv_path.write_text(
                "lat,lon,name,notes,added_at,added_by\n"
                "45.0000000,9.0000000,A,,,user\n"
                "45.0000000,9.0000000,B,,,user\n"
                "46.0000000,10.0000000,C,,,user\n"
            )

            with patch.object(main, "TRAFFIC_LIGHTS_CSV", csv_path):
                removed = main._remove_traffic_light_from_csv(45.0, 9.0)

            self.assertTrue(removed)
            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["name"], "B")
            self.assertEqual(rows[1]["name"], "C")

    def test_remove_traffic_light_uses_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "traffic_lights.csv"
            csv_path.write_text(
                "lat,lon,name,notes\n"
                "45.12345670,9.12345670,A,\n"
            )

            with patch.object(main, "TRAFFIC_LIGHTS_CSV", csv_path):
                removed = main._remove_traffic_light_from_csv(45.12345675, 9.12345675)

            self.assertTrue(removed)
            with open(csv_path, newline="") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])

    def test_remove_traffic_light_returns_false_when_not_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "traffic_lights.csv"
            csv_path.write_text(
                "lat,lon,name,notes\n"
                "45.0,9.0,A,\n"
            )

            with patch.object(main, "TRAFFIC_LIGHTS_CSV", csv_path):
                removed = main._remove_traffic_light_from_csv(45.1, 9.1)

            self.assertFalse(removed)


if __name__ == "__main__":
    unittest.main()
