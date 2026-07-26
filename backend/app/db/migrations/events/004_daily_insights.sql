-- One row per day of aggregate usage counts, for answering "is this working".
--
-- Nothing here identifies a person, and that is a design constraint rather than a
-- side effect. Two rules produce it, and both are enforced in
-- app/workers/insights.py where the rows are written:
--
--   1. Counts only. No row in this table refers to a user, a question, a document,
--      or a target. There is no user_id column to populate, so a later change
--      cannot quietly start filling one in.
--   2. A small-group floor. Any breakdown bucket, such as "students targeting
--      Sweden", is suppressed below MIN_BUCKET_SIZE rather than published, because
--      a count of one in a narrow bucket is a description of one person. Suppressed
--      buckets are reported as a single "below the reporting floor" total so the
--      column still sums correctly and the suppression is visible.
--
-- This lives in events.db rather than app.db because it is derived operational
-- data: it can be recomputed from the source tables, it is not read on any request
-- path, and losing it would cost a chart rather than a student's record.
CREATE TABLE IF NOT EXISTS daily_insights (
  day              TEXT PRIMARY KEY,    -- 'YYYY-MM-DD', UTC

  -- Reach.
  accounts_total       INTEGER NOT NULL DEFAULT 0,
  accounts_new         INTEGER NOT NULL DEFAULT 0,
  accounts_active      INTEGER NOT NULL DEFAULT 0,  -- last_seen_at within the day
  accounts_pending_deletion INTEGER NOT NULL DEFAULT 0,
  accounts_purged      INTEGER NOT NULL DEFAULT 0,

  -- Whether the answering path is doing its job.
  questions_asked      INTEGER NOT NULL DEFAULT 0,
  answers_grounded     INTEGER NOT NULL DEFAULT 0,
  answers_refused      INTEGER NOT NULL DEFAULT 0,
  answers_cached       INTEGER NOT NULL DEFAULT 0,

  -- Whether the recurrent loop is doing its job.
  portals_enabled      INTEGER NOT NULL DEFAULT 0,
  portals_unreachable  INTEGER NOT NULL DEFAULT 0,
  snapshots_new        INTEGER NOT NULL DEFAULT 0,
  changes_classified   INTEGER NOT NULL DEFAULT 0,
  alerts_sent          INTEGER NOT NULL DEFAULT 0,

  -- Whether students are getting value out of the agents.
  documents_checked    INTEGER NOT NULL DEFAULT 0,
  funding_plans        INTEGER NOT NULL DEFAULT 0,
  interviews_scored    INTEGER NOT NULL DEFAULT 0,
  feedback_received    INTEGER NOT NULL DEFAULT 0,

  -- JSON object of {bucket: count} for destination interest, already floored.
  -- A JSON column rather than a second table because it is written once a night,
  -- read as a whole, and never joined.
  destinations_json    TEXT NOT NULL DEFAULT '{}',

  generated_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_daily_insights_day ON daily_insights(day DESC);
