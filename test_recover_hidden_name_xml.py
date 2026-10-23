import unittest
from pathlib import Path

from scripts.recover_hidden_name_xml import map_observations, timestamp_from_filename


class HiddenNameRecoveryTests(unittest.TestCase):
    def test_pm_filename_to_utc_timestamp(self):
        timestamp = timestamp_from_filename(
            Path("window_live_5_30.xml"), "2026-10-23", 12
        )
        self.assertEqual(timestamp, "2026-10-23T09:30:00+00:00")

    def test_shared_signature_maps_by_score_order(self):
        observations = [
            {"position": 1, "score": 120, "score_approx": True, "signature": "same"},
            {"position": 2, "score": 220, "score_approx": True, "signature": "same"},
        ]
        candidates = [
            {
                "candidate_name": "较低分人物",
                "candidate_id": "low",
                "signature": "same",
                "score_at_enrollment": 150,
            },
            {
                "candidate_name": "较高分人物",
                "candidate_id": "high",
                "signature": "same",
                "score_at_enrollment": 250,
            },
        ]
        mapped = map_observations(observations, candidates, Path("sample.xml"))
        by_name = {item["candidate_name"]: item["score"] for item in mapped}
        self.assertEqual(by_name, {"较低分人物": 120, "较高分人物": 220})


if __name__ == "__main__":
    unittest.main()
