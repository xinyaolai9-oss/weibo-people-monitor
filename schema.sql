-- Execute in Supabase SQL Editor; this table contains PUBLIC rankings only.
CREATE TABLE IF NOT EXISTS score_snapshots (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  stage TEXT NOT NULL,
  category TEXT NOT NULL CHECK (category = '剧综人物'),
  candidate_id TEXT NOT NULL,
  candidate_name TEXT NOT NULL,
  score BIGINT NOT NULL CHECK (score >= 0),
  score_approx BOOLEAN NOT NULL DEFAULT FALSE,
  rank INTEGER,
  observed_at TIMESTAMPTZ NOT NULL,
  source TEXT NOT NULL DEFAULT 'public_page',
  UNIQUE(stage, category, candidate_id, observed_at)
);
CREATE INDEX IF NOT EXISTS score_snapshots_stage_time_idx
ON score_snapshots(stage, observed_at DESC);
CREATE INDEX IF NOT EXISTS score_snapshots_candidate_time_idx
ON score_snapshots(stage, candidate_id, observed_at DESC);
ALTER TABLE score_snapshots ENABLE ROW LEVEL SECURITY;
-- Publish ONLY the scoreboard snapshots, never cookie/session or account information.
REVOKE ALL ON TABLE score_snapshots FROM anon, authenticated;
GRANT SELECT ON TABLE score_snapshots TO anon;
GRANT ALL ON TABLE score_snapshots TO service_role;
GRANT USAGE, SELECT ON SEQUENCE score_snapshots_id_seq TO service_role;
DROP POLICY IF EXISTS "Public can read scores" ON score_snapshots;
CREATE POLICY "Public can read scores" ON score_snapshots
FOR SELECT TO anon USING (true);
-- No INSERT policy for anon. Backend writer must use a secret service-role key.
