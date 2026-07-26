-- docs/database.md section 4 "events.db". Append-only: nothing here is ever
-- updated. applied_events and dead_letters live alongside `events` (rather
-- than in 002_agents.sql) because they are the idempotency ledger and poison
-- queue for the event stream itself, not agent-specific bookkeeping.

CREATE TABLE IF NOT EXISTS events (
  event_id       TEXT PRIMARY KEY,        -- ULID, sortable by time
  stream         TEXT NOT NULL CHECK (stream IN ('crawl','kb','chat','agent','user','learn')),
  type           TEXT NOT NULL,           -- 'portal.changed'
  actor          TEXT NOT NULL,           -- 'worker:crawl' | 'user:01J8...' | 'system'
  subject_type   TEXT,
  subject_id     TEXT,
  user_id        INTEGER,                 -- soft ref
  payload        TEXT NOT NULL CHECK (json_valid(payload)),
  schema_version INTEGER NOT NULL DEFAULT 1,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_stream_time ON events(stream, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id, created_at DESC);

-- Idempotency ledger. This is what makes "consumers are idempotent" true.
CREATE TABLE IF NOT EXISTS applied_events (
  consumer    TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  applied_at  TEXT NOT NULL,
  PRIMARY KEY (consumer, event_id)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS dead_letters (
  id          INTEGER PRIMARY KEY,
  consumer    TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  attempts    INTEGER NOT NULL,
  last_error  TEXT NOT NULL,
  payload     TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);
