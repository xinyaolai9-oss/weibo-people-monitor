import unittest

from dashboard_data import prepare_records


class DashboardDataTests(unittest.TestCase):
    def test_mixed_iso8601_fractional_seconds(self):
        frame = prepare_records(
            [
                {
                    "observed_at": "2026-10-23T12:00:00+00:00",
                    "score": "1000",
                    "score_approx": True,
                },
                {
                    "observed_at": "2026-10-23T12:17:24.204940+00:00",
                    "score": "2000",
                    "score_approx": True,
                },
            ]
        )

        self.assertEqual(len(frame), 2)
        self.assertEqual(str(frame["observed_at"].dt.tz), "UTC")
        self.assertEqual(frame["score"].tolist(), [1000, 2000])


if __name__ == "__main__":
    unittest.main()
