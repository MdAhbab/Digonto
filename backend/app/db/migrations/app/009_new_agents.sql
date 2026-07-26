-- docs/database.md section 3.9 "New agent tables": Bicharok, Lekhok, Dalil.

CREATE TABLE IF NOT EXISTS rejection_cases (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  document_id  INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  country_code TEXT REFERENCES countries(code),
  visa_type    TEXT,
  refused_on   TEXT,
  summary_en   TEXT,
  summary_bn   TEXT,
  reapply_ready_at TEXT,
  created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS rejection_grounds (
  id            INTEGER PRIMARY KEY,
  case_id       INTEGER NOT NULL REFERENCES rejection_cases(id) ON DELETE CASCADE,
  code          TEXT,                     -- e.g. UKVI paragraph, US 214(b)
  quoted_text   TEXT NOT NULL,
  meaning_en    TEXT NOT NULL,
  meaning_bn    TEXT NOT NULL,
  remedy_en     TEXT NOT NULL,
  remedy_bn     TEXT NOT NULL,
  remediable    TEXT NOT NULL CHECK (remediable IN ('yes','partly','no')),
  snapshot_id   INTEGER REFERENCES snapshots(id),
  linked_step_key TEXT
);

-- Lekhok: checks a statement of purpose against the student's own documents.
CREATE TABLE IF NOT EXISTS statements (
  id         INTEGER PRIMARY KEY,
  public_id  TEXT NOT NULL UNIQUE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id  INTEGER REFERENCES student_targets(id) ON DELETE SET NULL,
  kind       TEXT NOT NULL CHECK (kind IN ('sop','motivation','cover','study_plan')),
  body       TEXT NOT NULL,
  version    INTEGER NOT NULL DEFAULT 1,
  word_count INTEGER NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS statement_findings (
  id           INTEGER PRIMARY KEY,
  statement_id INTEGER NOT NULL REFERENCES statements(id) ON DELETE CASCADE,
  severity     TEXT NOT NULL CHECK (severity IN ('critical','warning','info')),
  kind         TEXT NOT NULL CHECK (kind IN ('contradiction','unsupported','vague','cliche','missing')),
  excerpt      TEXT NOT NULL,
  detail_en    TEXT NOT NULL,
  detail_bn    TEXT NOT NULL,
  conflicts_document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  suggestion_en TEXT,
  suggestion_bn TEXT
);

-- Dalil: audits a consultancy contract for predatory clauses.
CREATE TABLE IF NOT EXISTS contracts (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  consultancy  TEXT,
  risk_overall TEXT CHECK (risk_overall IN ('low','medium','high')),
  analysed_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS contract_clauses (
  id           INTEGER PRIMARY KEY,
  contract_id  INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
  quoted_text  TEXT NOT NULL,
  category     TEXT NOT NULL CHECK (category IN
               ('fee','refund','document_retention','exclusivity','liability','guarantee','other')),
  risk         TEXT NOT NULL CHECK (risk IN ('low','medium','high')),
  why_en       TEXT NOT NULL,
  why_bn       TEXT NOT NULL,
  fair_alternative_en TEXT,
  fair_alternative_bn TEXT
);
