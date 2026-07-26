-- docs/database.md section 3.5 "Plans (the Visa Timeline Reactor)".
-- Maps onto the frontend Step and ChangeEntry interfaces. step_key is
-- deliberately stable across re-plans while month_label/due_at are not.

CREATE TABLE IF NOT EXISTS plans (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id     INTEGER REFERENCES student_targets(id) ON DELETE SET NULL,
  intake_label  TEXT,
  generated_at  TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  UNIQUE (user_id, target_id)
);

CREATE TABLE IF NOT EXISTS plan_steps (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  plan_id      INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  step_key     TEXT NOT NULL,             -- stable: 'ielts', 'solvency', 'visa'
  order_idx    INTEGER NOT NULL,
  month_label  TEXT NOT NULL,             -- 'Sep 2026', rendered directly
  due_at       TEXT,
  title_en     TEXT NOT NULL,
  title_bn     TEXT NOT NULL,
  desc_en      TEXT NOT NULL,
  desc_bn      TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('done','active','upcoming','blocked')),
  depends_on   TEXT CHECK (depends_on IS NULL OR json_valid(depends_on)),
  lead_days    INTEGER NOT NULL DEFAULT 0,
  source_snapshot_id INTEGER REFERENCES snapshots(id),
  completed_at TEXT,
  UNIQUE (plan_id, step_key)
);
CREATE INDEX IF NOT EXISTS idx_steps_plan ON plan_steps(plan_id, order_idx);

-- Every re-plan writes an explainable entry. This is the "what changed" drawer.
CREATE TABLE IF NOT EXISTS plan_changes (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  plan_id        INTEGER NOT NULL REFERENCES plans(id) ON DELETE CASCADE,
  step_id        INTEGER REFERENCES plan_steps(id) ON DELETE SET NULL,
  trigger        TEXT NOT NULL CHECK (trigger IN ('portal_change','profile_update','document_change','manual','schedule')),
  text_en        TEXT NOT NULL,
  text_bn        TEXT NOT NULL,
  source_label   TEXT NOT NULL,           -- 'ukvi.gov.uk · SNAP-01J8...'
  snapshot_id    INTEGER REFERENCES snapshots(id),
  event_id       TEXT,                    -- soft ref to events.db
  seen_at        TEXT,
  created_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_changes_plan ON plan_changes(plan_id, created_at DESC);
