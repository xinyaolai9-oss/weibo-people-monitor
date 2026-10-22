"""Clearly fake scores to exercise the interface before live data access is verified."""
import random
from datetime import datetime, timedelta, timezone
from storage import insert_snapshots

rng = random.Random(20261022)
people = [f"模拟人物 {i:02d}" for i in range(1, 13)]
base = {person: rng.randint(180000, 470000) for person in people}
now = datetime.now(timezone.utc)
rows = []
for tick in range(72, -1, -1):
    current = now - timedelta(minutes=tick * 5)
    for i, name in enumerate(people):
        score = base[name] + (72 - tick) * (150 + 27 * i) + rng.randint(0, 20)
        rows.append({
            "stage": "demo", "category": "剧综人物",
            "candidate_id": f"demo-{i:02d}", "candidate_name": name,
            "score": score, "score_approx": False, "rank": None,
            "observed_at": current.isoformat(), "source": "demo_generated",
        })
insert_snapshots(rows)
print(f"Inserted {len(rows)} explicitly marked demo rows")
