"""SQLite for local demo, Supabase for production. Never publish service-role credentials."""
import os
import sqlite3
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

CREATE_SQL = """
CREATE TABLE IF NOT EXISTS score_snapshots (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  stage TEXT NOT NULL,
  category TEXT NOT NULL,
  candidate_id TEXT NOT NULL,
  candidate_name TEXT NOT NULL,
  score INTEGER NOT NULL,
  score_approx INTEGER NOT NULL DEFAULT 0,
  rank INTEGER,
  observed_at TEXT NOT NULL,
  source TEXT NOT NULL,
  UNIQUE(stage,category,candidate_id,observed_at)
)"""
COLUMNS = "stage,category,candidate_id,candidate_name,score,score_approx,rank,observed_at,source"


def backend():
    return os.getenv("STORAGE_BACKEND", "sqlite").lower()


def required_setting(*names):
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    raise RuntimeError("Missing setting: " + " or ".join(names))


def sqlite_conn():
    conn = sqlite3.connect(os.getenv("SQLITE_PATH", "score_snapshots.db"))
    conn.execute(CREATE_SQL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_stage_time ON score_snapshots(stage, observed_at DESC)")
    return conn


def insert_snapshots(records):
    if not records:
        raise ValueError("Refusing to write an empty snapshot")
    if backend() == "sqlite":
        conn = sqlite_conn()
        try:
            params = [tuple(int(r[k]) if k == "score_approx" else r.get(k) for k in COLUMNS.split(",")) for r in records]
            conn.executemany(f"INSERT OR IGNORE INTO score_snapshots ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)", params)
            conn.commit()
        finally:
            conn.close()
    elif backend() == "supabase":
        from supabase import create_client
        client = create_client(
            required_setting("SUPABASE_URL"),
            required_setting("SUPABASE_SECRET_KEY", "SUPABASE_SERVICE_ROLE_KEY"),
        )
        client.table("score_snapshots").upsert(records, on_conflict="stage,category,candidate_id,observed_at").execute()
    else:
        raise ValueError("Unknown storage backend")


def fetch_snapshots(stage="final", hours=24, limit=35000):
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    if backend() == "sqlite":
        conn = sqlite_conn()
        try:
            cur = conn.execute(
                f"SELECT {COLUMNS} FROM score_snapshots WHERE stage=? AND category='剧综人物' AND observed_at>=? ORDER BY observed_at DESC LIMIT ?",
                (stage, since, limit),
            )
            return [dict(zip(COLUMNS.split(","), row)) for row in cur.fetchall()]
        finally:
            conn.close()
    elif backend() == "supabase":
        from supabase import create_client
        url = required_setting("SUPABASE_URL")
        # Web process only needs a publishable/anon key. Never use a secret or
        # service-role key in Streamlit Community Cloud.
        key = required_setting("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY")
        client = create_client(url, key)
        out = []
        batch = 1000
        for start in range(0, limit, batch):
            rows = (client.table("score_snapshots")
                    .select(COLUMNS)
                    .eq("stage", stage)
                    .eq("category", "剧综人物")
                    .gte("observed_at", since)
                    .order("observed_at", desc=True)
                    .range(start, min(start + batch - 1, limit - 1)).execute().data)
            out.extend(rows)
            if len(rows) < batch:
                break
        return out
    else:
        raise ValueError("Unknown storage backend")
