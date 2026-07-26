-- docs/database.md section 3.4 "Questions, answers, citations".
-- Shapes map directly onto the frontend QA and Citation interfaces.

CREATE TABLE IF NOT EXISTS conversations (
  id         INTEGER PRIMARY KEY,
  public_id  TEXT NOT NULL UNIQUE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS questions (
  id              INTEGER PRIMARY KEY,
  public_id       TEXT NOT NULL UNIQUE,
  conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  text_raw        TEXT NOT NULL,
  text_normalised TEXT NOT NULL,          -- Banglish transliterated
  lang_detected   TEXT NOT NULL CHECK (lang_detected IN ('bn','en','banglish','mixed')),
  country_filter  TEXT REFERENCES countries(code),
  created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS answers (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  question_id    INTEGER NOT NULL UNIQUE REFERENCES questions(id) ON DELETE CASCADE,
  answer_bn      TEXT,
  answer_en      TEXT,
  confidence     REAL CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
  is_refusal     INTEGER NOT NULL DEFAULT 0 CHECK (is_refusal IN (0,1)),
  refusal_reason TEXT,
  kb_version_id  INTEGER REFERENCES kb_versions(id),
  model_tag      TEXT NOT NULL,           -- 'gemma4:e2b+adapter-2026-07'
  served_by      TEXT NOT NULL DEFAULT 'local' CHECK (served_by IN ('local','cache','degraded')),
  cache_hit      INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0,1)),
  latency_ms     INTEGER,
  first_token_ms INTEGER,
  created_at     TEXT NOT NULL,
  -- The refusal contract, enforced by the engine: a non-refusal must carry
  -- text, a refusal must carry a reason. See docs/database.md section 3.4.
  CHECK ( (is_refusal = 1 AND refusal_reason IS NOT NULL)
       OR (is_refusal = 0 AND (answer_bn IS NOT NULL OR answer_en IS NOT NULL)) )
);
CREATE INDEX IF NOT EXISTS idx_answers_created ON answers(created_at DESC);

-- The Citation interface: {id, portal, captured, quoted}
CREATE TABLE IF NOT EXISTS answer_citations (
  id          INTEGER PRIMARY KEY,
  answer_id   INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,           -- the n in the ||n|| marker
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  passage_id  INTEGER REFERENCES passages(id),
  quoted_span TEXT NOT NULL,
  UNIQUE (answer_id, ordinal)
);

CREATE TABLE IF NOT EXISTS answer_feedback (
  id                INTEGER PRIMARY KEY,
  answer_id         INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  user_id           INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  rating            TEXT NOT NULL CHECK (rating IN ('up','down','unclear')),
  correction_text   TEXT,
  reviewer_verified INTEGER NOT NULL DEFAULT 0 CHECK (reviewer_verified IN (0,1)),
  reviewer_note     TEXT,
  created_at        TEXT NOT NULL,
  UNIQUE (answer_id, user_id)
);
