-- docs/database.md section 5: the frozen benchmark and its evaluation runs.
-- question_hash and benchmark_leak (in 001_replay.sql) implement the leakage
-- audit from backend/backend.md section 3.3.

CREATE TABLE IF NOT EXISTS benchmark_questions (
  id           INTEGER PRIMARY KEY,
  country_code TEXT NOT NULL,
  family       TEXT NOT NULL CHECK (family IN ('documents','financial','deadlines','process')),
  question_bn  TEXT NOT NULL,
  question_en  TEXT NOT NULL,
  gold_answer  TEXT NOT NULL,
  gold_snapshot_id INTEGER,
  question_hash TEXT NOT NULL UNIQUE,     -- used for the leakage audit
  frozen_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS benchmark_runs (
  id          INTEGER PRIMARY KEY,
  adapter_id  INTEGER REFERENCES adapters(id) ON DELETE CASCADE,
  model_tag   TEXT NOT NULL,
  groundedness REAL,
  refusal_correctness REAL,
  bangla_clarity REAL,
  latency_p50_ms INTEGER,
  latency_p95_ms INTEGER,
  question_count INTEGER NOT NULL,
  raw_results TEXT CHECK (json_valid(raw_results)),
  run_at      TEXT NOT NULL
);
