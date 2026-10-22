import os
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from storage import fetch_snapshots, insert_snapshots


class SnapshotIntervalTests(unittest.TestCase):
    def test_exact_start_and_end_bounds(self):
        database = Path.cwd() / f".test-snapshots-{uuid4().hex}.db"
        try:
            environment = {"STORAGE_BACKEND": "sqlite", "SQLITE_PATH": str(database)}
            with patch.dict(os.environ, environment):
                records = []
                for minute, score in ((0, 100), (5, 200), (10, 300)):
                    records.append(
                        {
                            "stage": "final",
                            "category": "剧综人物",
                            "candidate_id": f"candidate-{minute}",
                            "candidate_name": f"人物{minute}",
                            "score": score,
                            "score_approx": False,
                            "rank": None,
                            "observed_at": f"2026-10-23T00:{minute:02d}:00+00:00",
                            "source": "test",
                        }
                    )
                insert_snapshots(records)

                rows = fetch_snapshots(
                    "final",
                    hours=None,
                    start_at=datetime(2026, 10, 23, 0, 5, tzinfo=timezone.utc),
                    end_at=datetime(2026, 10, 23, 0, 10, tzinfo=timezone.utc),
                )
            self.assertEqual([row["score"] for row in rows], [300, 200])
        finally:
            database.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
