-- docs/database.md section 3.8 "Interview room and Shonchari".

CREATE TABLE IF NOT EXISTS interview_bank (
  id           INTEGER PRIMARY KEY,
  country_code TEXT REFERENCES countries(code),
  visa_type    TEXT,
  text_en      TEXT NOT NULL,
  text_bn      TEXT NOT NULL,
  probes       TEXT NOT NULL,             -- what the officer is really testing
  difficulty   TEXT NOT NULL CHECK (difficulty IN ('opening','standard','pressure')),
  category     TEXT NOT NULL CHECK (category IN ('intent','finance','academic','ties','post_study')),
  snapshot_id  INTEGER REFERENCES snapshots(id)
);

CREATE TABLE IF NOT EXISTS interview_sessions (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id    INTEGER REFERENCES student_targets(id) ON DELETE SET NULL,
  country_code TEXT REFERENCES countries(code),
  visa_type    TEXT,
  mode         TEXT NOT NULL DEFAULT 'text' CHECK (mode IN ('text','voice')),
  status       TEXT NOT NULL CHECK (status IN ('active','complete','abandoned')),
  started_at   TEXT NOT NULL,
  ended_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON interview_sessions(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS interview_turns (
  id            INTEGER PRIMARY KEY,
  session_id    INTEGER NOT NULL REFERENCES interview_sessions(id) ON DELETE CASCADE,
  ordinal       INTEGER NOT NULL,
  bank_id       INTEGER REFERENCES interview_bank(id),
  question_text TEXT NOT NULL,
  answer_text   TEXT,
  audio_path    TEXT,
  relevance     REAL,
  consistency   REAL,
  credibility   REAL,
  contradicts   TEXT CHECK (contradicts IS NULL OR json_valid(contradicts)),
  feedback_en   TEXT,
  feedback_bn   TEXT,
  answered_at   TEXT,
  UNIQUE (session_id, ordinal)
);

CREATE TABLE IF NOT EXISTS interview_reports (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  session_id   INTEGER NOT NULL UNIQUE REFERENCES interview_sessions(id) ON DELETE CASCADE,
  overall      REAL NOT NULL,
  summary_en   TEXT NOT NULL,
  summary_bn   TEXT NOT NULL,
  strengths    TEXT CHECK (json_valid(strengths)),
  weaknesses   TEXT CHECK (json_valid(weaknesses)),
  created_at   TEXT NOT NULL
);
