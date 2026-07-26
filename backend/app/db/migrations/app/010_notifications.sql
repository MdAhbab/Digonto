-- docs/database.md section 3.10 "Notifications".

CREATE TABLE IF NOT EXISTS notifications (
  id          INTEGER PRIMARY KEY,
  public_id   TEXT NOT NULL UNIQUE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind        TEXT NOT NULL CHECK (kind IN
              ('portal_change','deadline','audit_finding','funding_match','adapter_note','system')),
  severity    TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('critical','warning','info')),
  title_en    TEXT NOT NULL,
  title_bn    TEXT NOT NULL,
  body_en     TEXT NOT NULL,
  body_bn     TEXT NOT NULL,
  link_path   TEXT,
  snapshot_id INTEGER REFERENCES snapshots(id),
  read_at     TEXT,
  emailed_at  TEXT,
  created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notif_user_unread ON notifications(user_id, created_at DESC) WHERE read_at IS NULL;
