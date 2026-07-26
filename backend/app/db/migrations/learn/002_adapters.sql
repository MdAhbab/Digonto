-- docs/database.md section 5: QLoRA adapter lifecycle.

CREATE TABLE IF NOT EXISTS adapters (
  id            INTEGER PRIMARY KEY,
  tag           TEXT NOT NULL UNIQUE,     -- 'digonto-2026-08a'
  base_model    TEXT NOT NULL,
  rank          INTEGER NOT NULL,
  sample_count  INTEGER NOT NULL,
  rehearsal_ratio REAL NOT NULL,
  status        TEXT NOT NULL CHECK (status IN ('training','candidate','promoted','rolled_back','failed')),
  trained_at    TEXT NOT NULL,
  promoted_at   TEXT,
  rolled_back_at TEXT,
  notes         TEXT
);
