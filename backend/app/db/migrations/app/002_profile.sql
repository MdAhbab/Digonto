-- docs/database.md section 3.2 "Student profile and targets".
-- countries.code values are lowercase (uk, us, ca, ...) rather than strict
-- uppercase ISO-3166-1 alpha-2: see 011_seed_countries.sql for why.

CREATE TABLE IF NOT EXISTS profiles (
  user_id          INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  display_name     TEXT,
  home_district    TEXT,                  -- for pilot cohort analysis, optional
  degree_level     TEXT CHECK (degree_level IN ('bachelor','master','phd','diploma')),
  field_of_study   TEXT,
  cgpa             REAL CHECK (cgpa IS NULL OR (cgpa >= 0 AND cgpa <= 5)),
  cgpa_scale       REAL CHECK (cgpa_scale IN (4.0, 5.0)),
  graduation_year  INTEGER,
  english_test     TEXT CHECK (english_test IN ('ielts','toefl','duolingo','pte','none')),
  english_overall  REAL,
  english_sub      TEXT CHECK (english_sub IS NULL OR json_valid(english_sub)),
  budget_bdt       INTEGER,               -- minor units
  intake_target    TEXT,                  -- 'Fall 2027'
  study_gap_years  INTEGER NOT NULL DEFAULT 0,
  updated_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS countries (
  code         TEXT PRIMARY KEY,          -- ISO-3166-1 alpha-2 (lowercased)
  name_en      TEXT NOT NULL,
  name_bn      TEXT NOT NULL,
  visa_types   TEXT NOT NULL CHECK (json_valid(visa_types)),
  active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  sort_order   INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE IF NOT EXISTS institutions (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  country_code  TEXT NOT NULL REFERENCES countries(code),
  name          TEXT NOT NULL,
  city          TEXT,
  website       TEXT,
  portal_id     INTEGER,                  -- soft ref to portals.id
  verified      INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1)),
  is_partner    INTEGER NOT NULL DEFAULT 0 CHECK (is_partner IN (0,1)),
  created_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_institutions_country ON institutions(country_code);

CREATE TABLE IF NOT EXISTS programmes (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  institution_id INTEGER NOT NULL REFERENCES institutions(id) ON DELETE CASCADE,
  name           TEXT NOT NULL,
  degree_level   TEXT NOT NULL CHECK (degree_level IN ('bachelor','master','phd','diploma')),
  field_of_study TEXT,
  duration_months INTEGER,
  tuition_amount INTEGER,                 -- minor units
  tuition_currency TEXT,
  intake_months  TEXT CHECK (intake_months IS NULL OR json_valid(intake_months)),
  min_cgpa       REAL,
  min_english    REAL,
  deadline_at    TEXT,
  source_snapshot_id INTEGER,             -- soft ref: every fact is citable
  updated_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_programmes_inst ON programmes(institution_id);
CREATE INDEX IF NOT EXISTS idx_programmes_deadline ON programmes(deadline_at);

-- A student's shortlist. Drives Porter, the planner, and Khoji.
CREATE TABLE IF NOT EXISTS student_targets (
  id           INTEGER PRIMARY KEY,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  programme_id INTEGER NOT NULL REFERENCES programmes(id) ON DELETE CASCADE,
  visa_type    TEXT,
  rank         INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'considering'
               CHECK (status IN ('considering','applying','submitted','offer','rejected','accepted','withdrawn')),
  created_at   TEXT NOT NULL,
  UNIQUE (user_id, programme_id)
);
CREATE INDEX IF NOT EXISTS idx_targets_user ON student_targets(user_id);
