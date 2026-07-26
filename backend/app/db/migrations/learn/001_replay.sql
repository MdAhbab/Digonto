-- docs/database.md section 5 "learn.db". The CHECK below is the privacy
-- promise enforced by the engine: a sample that was not consented to, or was
-- not scrubbed, cannot physically be stored.

CREATE TABLE IF NOT EXISTS replay_samples (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('refusal','correction','unclear','high_value')),
  question      TEXT NOT NULL,
  answer        TEXT,
  correction    TEXT,
  lang          TEXT NOT NULL,
  kb_version_id INTEGER,
  source_answer_public_id TEXT,           -- soft ref, not a join
  consent       INTEGER NOT NULL CHECK (consent IN (0,1)),
  pii_scrubbed  INTEGER NOT NULL DEFAULT 0 CHECK (pii_scrubbed IN (0,1)),
  scrub_report  TEXT CHECK (scrub_report IS NULL OR json_valid(scrub_report)),
  benchmark_leak INTEGER NOT NULL DEFAULT 0 CHECK (benchmark_leak IN (0,1)),
  exported_in   INTEGER,                  -- adapters.id it was trained into
  created_at    TEXT NOT NULL,
  CHECK (consent = 1 AND pii_scrubbed = 1)
);
CREATE INDEX IF NOT EXISTS idx_replay_unexported ON replay_samples(created_at) WHERE exported_in IS NULL;
