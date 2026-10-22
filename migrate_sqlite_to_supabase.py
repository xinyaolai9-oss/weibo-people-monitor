"""One-time migration of local snapshots to the configured Supabase project."""

import argparse
import os
import sqlite3

from dotenv import load_dotenv
from supabase import create_client

from storage import COLUMNS, required_setting


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sqlite", default="score_snapshots.db")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    load_dotenv()

    connection = sqlite3.connect(args.sqlite)
    try:
        rows = connection.execute(
            f"SELECT {COLUMNS} FROM score_snapshots ORDER BY observed_at"
        ).fetchall()
    finally:
        connection.close()
    records = [dict(zip(COLUMNS.split(","), row)) for row in rows]
    for record in records:
        record["score_approx"] = bool(record["score_approx"])
    print(f"Local snapshots ready for migration: {len(records)}")
    if args.dry_run or not records:
        return

    if os.getenv("STORAGE_BACKEND", "sqlite").lower() != "supabase":
        raise RuntimeError("Set STORAGE_BACKEND=supabase before migration")
    client = create_client(
        required_setting("SUPABASE_URL"),
        required_setting("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
    )
    for start in range(0, len(records), 500):
        client.table("score_snapshots").upsert(
            records[start : start + 500],
            on_conflict="stage,category,candidate_id,observed_at",
        ).execute()
    print(f"Migrated {len(records)} snapshots to Supabase")
