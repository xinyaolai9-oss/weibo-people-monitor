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


def _as_utc_iso(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Snapshot query datetimes must include a timezone")
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def fetch_snapshots(
    stage="final",
    hours=24,
    limit=35000,
    *,
    start_at=None,
    end_at=None,
):
    """Read snapshots within an exact UTC-aware interval.

    ``hours`` remains for backward compatibility. Passing ``start_at`` takes
    precedence; passing ``hours=None`` and no bounds returns the newest rows.
    """

    since = _as_utc_iso(start_at)
    until = _as_utc_iso(end_at)
    if since is None and hours is not None:
        since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    if backend() == "sqlite":
        conn = sqlite_conn()
        try:
            clauses = ["stage=?", "category='剧综人物'"]
            params = [stage]
            if since is not None:
                clauses.append("observed_at>=?")
                params.append(since)
            if until is not None:
                clauses.append("observed_at<=?")
                params.append(until)
            params.append(limit)
            cur = conn.execute(
                f"SELECT {COLUMNS} FROM score_snapshots WHERE {' AND '.join(clauses)} "
                "ORDER BY observed_at DESC LIMIT ?",
                params,
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
            query = (client.table("score_snapshots")
                     .select(COLUMNS)
                     .eq("stage", stage)
                     .eq("category", "剧综人物"))
            if since is not None:
                query = query.gte("observed_at", since)
            if until is not None:
                query = query.lte("observed_at", until)
            rows = (query.order("observed_at", desc=True)
                    .range(start, min(start + batch - 1, limit - 1)).execute().data)
            out.extend(rows)
            if len(rows) < batch:
                break
        return out
    else:
        raise ValueError("Unknown storage backend")
