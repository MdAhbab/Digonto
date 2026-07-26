-- docs/database.md section 3.7 "Funding and Khoji".

CREATE TABLE IF NOT EXISTS scholarships (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  name           TEXT NOT NULL,
  provider       TEXT NOT NULL,
  country_code   TEXT REFERENCES countries(code),
  degree_levels  TEXT CHECK (degree_levels IS NULL OR json_valid(degree_levels)),
  fields         TEXT CHECK (fields IS NULL OR json_valid(fields)),
  coverage_type  TEXT CHECK (coverage_type IN ('full','partial','tuition_only','stipend_only','travel')),
  amount         INTEGER,
  currency       TEXT,
  deadline_at    TEXT,
  url            TEXT NOT NULL,
  snapshot_id    INTEGER REFERENCES snapshots(id),
  verified       INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
  active         INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scholarships_country ON scholarships(country_code, active);
CREATE INDEX IF NOT EXISTS idx_scholarships_deadline ON scholarships(deadline_at) WHERE active = 1;

CREATE TABLE IF NOT EXISTS scholarship_criteria (
  id             INTEGER PRIMARY KEY,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  criterion_key  TEXT NOT NULL,           -- 'cgpa_min','nationality','degree_level'
  operator       TEXT NOT NULL CHECK (operator IN ('gte','lte','eq','in','exists')),
  value          TEXT NOT NULL,
  is_hard        INTEGER NOT NULL DEFAULT 1 CHECK (is_hard IN (0,1)),
  weight         REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS funding_matches (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  score          REAL NOT NULL CHECK (score >= 0 AND score <= 1),
  rank           INTEGER NOT NULL,
  eligible       INTEGER NOT NULL CHECK (eligible IN (0,1)),
  kb_version_id  INTEGER REFERENCES kb_versions(id),
  computed_at    TEXT NOT NULL,
  UNIQUE (user_id, scholarship_id)
);
CREATE INDEX IF NOT EXISTS idx_matches_user_rank ON funding_matches(user_id, rank);

-- One row per criterion per match: this is what makes a ranking explainable.
CREATE TABLE IF NOT EXISTS match_reasons (
  id            INTEGER PRIMARY KEY,
  match_id      INTEGER NOT NULL REFERENCES funding_matches(id) ON DELETE CASCADE,
  criterion_key TEXT NOT NULL,
  met           INTEGER NOT NULL CHECK (met IN (0,1)),
  reason_en     TEXT NOT NULL,
  reason_bn     TEXT NOT NULL,
  weight        REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS fx_rates (
  id       INTEGER PRIMARY KEY,
  base     TEXT NOT NULL,
  quote    TEXT NOT NULL,
  rate     REAL NOT NULL,
  source   TEXT NOT NULL,
  as_of    TEXT NOT NULL,
  UNIQUE (base, quote, as_of)
);

CREATE TABLE IF NOT EXISTS solvency_rules (
  id           INTEGER PRIMARY KEY,
  country_code TEXT NOT NULL REFERENCES countries(code),
  visa_type    TEXT NOT NULL,
  amount       INTEGER NOT NULL,
  currency     TEXT NOT NULL,
  hold_days    INTEGER NOT NULL,
  basis_note_en TEXT,
  basis_note_bn TEXT,
  snapshot_id  INTEGER REFERENCES snapshots(id),
  effective_from TEXT NOT NULL,
  UNIQUE (country_code, visa_type, effective_from)
);

CREATE TABLE IF NOT EXISTS budgets (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id      INTEGER REFERENCES student_targets(id) ON DELETE CASCADE,
  tuition_bdt    INTEGER NOT NULL DEFAULT 0,
  living_bdt     INTEGER NOT NULL DEFAULT 0,
  travel_bdt     INTEGER NOT NULL DEFAULT 0,
  visa_fee_bdt   INTEGER NOT NULL DEFAULT 0,
  awards_bdt     INTEGER NOT NULL DEFAULT 0,
  own_funds_bdt  INTEGER NOT NULL DEFAULT 0,
  gap_bdt        INTEGER NOT NULL DEFAULT 0,
  solvency_required_bdt INTEGER,
  fx_rate_used   REAL,
  computed_at    TEXT NOT NULL
);

-- Agent Fee Reality Check
CREATE TABLE IF NOT EXISTS fee_quotes (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  consultancy   TEXT,
  quoted_bdt    INTEGER NOT NULL,
  country_code  TEXT REFERENCES countries(code),
  document_id   INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  fair_bdt      INTEGER,
  created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fee_line_items (
  id          INTEGER PRIMARY KEY,
  quote_id    INTEGER NOT NULL REFERENCES fee_quotes(id) ON DELETE CASCADE,
  label_en    TEXT NOT NULL,
  label_bn    TEXT NOT NULL,
  category    TEXT NOT NULL CHECK (category IN ('free','official_fee','fair_service','unjustified')),
  amount_bdt  INTEGER NOT NULL DEFAULT 0,
  note_en     TEXT,
  note_bn     TEXT,
  snapshot_id INTEGER REFERENCES snapshots(id)
);
