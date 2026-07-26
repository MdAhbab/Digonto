# Digonto Database Design

Full schema for the Digonto backend. SQLite 3.45+ in WAL mode, split across three
database files by write pattern. This document is the authority for the schema:
migrations, Pydantic models, and repository classes are all generated from it.

**Read `backend/backend.md` section 1.1 before touching any of this.** The rules
there (single writer, short transactions, no blobs in the database) are what keep
SQLite viable at this scale, and every table below is designed around them.

---

## 0. Why three database files

| File | Write pattern | Contents |
| --- | --- | --- |
| `app.db` | Low volume, transactional, read-heavy | users, profiles, plans, vault metadata, knowledge index, funding, interviews |
| `events.db` | Append-only, high volume, never updated | event log, agent runs, tool calls, notifications |
| `learn.db` | Batch writes, read rarely | replay buffer, adapters, benchmark, evaluation runs |

Splitting them keeps the append-heavy event stream from competing for the single
writer lock on the interactive path. Each file is replicated by Litestream on its
own schedule. `learn.db` can be detached entirely during a training run without
affecting the running site.

Cross-database references (for example `agent_runs.user_id`) are **not** foreign
keys. They are plain integers, validated at the service layer. SQLite cannot
enforce foreign keys across attached databases reliably, so we do not pretend it
can. Every such column is marked "soft reference" below.

## 1. Conventions

- **Primary keys.** `INTEGER PRIMARY KEY` (rowid alias) for internal tables.
  Anything exposed in a URL or shown to a user gets an additional `public_id TEXT
  UNIQUE` holding a ULID, so we never leak row counts or allow enumeration.
- **Timestamps.** `TEXT` in ISO-8601 UTC with a `Z` suffix, for example
  `2026-07-26T09:15:00Z`. Stored as text because SQLite has no native datetime and
  ISO-8601 sorts lexicographically. Column names always end in `_at`.
- **Booleans.** `INTEGER NOT NULL DEFAULT 0` with a `CHECK (col IN (0,1))`.
- **Enumerations.** `TEXT` with an explicit `CHECK (col IN (...))`. Readable in a
  database browser, and the constraint is enforced by the engine rather than by
  convention.
- **JSON.** `TEXT` with `CHECK (json_valid(col))`. Used only where the shape is
  genuinely open (model scores, metrics). Never used to avoid designing a table.
- **Soft delete.** `deleted_at TEXT NULL`. Hard delete is a separate, explicit
  operation that cascades to files and is recorded as an event.
- **Money.** `INTEGER` in minor units (poisha for BDT, cents for USD) plus a
  `currency TEXT`. Never `REAL`. Floating point money is a defect.
- **Bilingual text.** Two columns, `*_en` and `*_bn`. Not a JSON blob, because the
  frontend selects by language and we want indexable, checkable columns. Every
  user-facing generated string has both.

## 2. Pragmas (applied on every connection)

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA temp_store = MEMORY;
PRAGMA mmap_size = 268435456;      -- 256 MB
PRAGMA cache_size = -64000;        -- 64 MB page cache
```

`foreign_keys` is off by default in SQLite and must be set per connection. A
connection factory is the only correct place for this; do not rely on a migration
having run it.

---

## 3. `app.db`

### 3.1 Identity and access

```sql
CREATE TABLE users (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT    NOT NULL UNIQUE,
  email          TEXT    NOT NULL UNIQUE COLLATE NOCASE,
  password_hash  TEXT    NOT NULL,        -- argon2id, never anything else
  display_name   TEXT    NOT NULL DEFAULT '',
  role           TEXT    NOT NULL DEFAULT 'student'
                 CHECK (role IN ('student','moderator','admin')),
  status         TEXT    NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','suspended','banned')),
  status_reason_en TEXT,
  status_reason_bn TEXT,
  suspended_until  TEXT,
  email_verified INTEGER NOT NULL DEFAULT 0 CHECK (email_verified IN (0,1)),
  lang_pref      TEXT    NOT NULL DEFAULT 'bn' CHECK (lang_pref IN ('bn','en')),
  theme_pref     TEXT    NOT NULL DEFAULT 'system' CHECK (theme_pref IN ('light','dark','system')),
  is_demo        INTEGER NOT NULL DEFAULT 0 CHECK (is_demo IN (0,1)),
  failed_logins  INTEGER NOT NULL DEFAULT 0,
  locked_until   TEXT,
  created_at     TEXT    NOT NULL,
  last_seen_at   TEXT,
  deleted_at     TEXT,
  CHECK (status = 'active' OR status_reason_en IS NOT NULL)
);
CREATE INDEX idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX idx_users_role ON users(role) WHERE role != 'student';
CREATE INDEX idx_users_status ON users(status) WHERE status != 'active';

-- Refresh tokens. Access tokens are stateless JWTs and are not stored.
CREATE TABLE refresh_tokens (
  id             INTEGER PRIMARY KEY,
  user_id        INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash     TEXT    NOT NULL UNIQUE,
  family_id      TEXT    NOT NULL,        -- rotation family; reuse detection
  issued_at      TEXT    NOT NULL,
  expires_at     TEXT    NOT NULL,
  revoked_at     TEXT,
  replaced_by_id INTEGER REFERENCES refresh_tokens(id),
  user_agent     TEXT,
  ip_hash        TEXT
);
CREATE INDEX idx_refresh_user ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

-- Every moderator action, immutable. A ban with no recorded reason is not
-- moderation, so reason columns are NOT NULL for the actions that need them.
CREATE TABLE moderation_actions (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT    NOT NULL UNIQUE,
  moderator_id INTEGER NOT NULL REFERENCES users(id),
  action       TEXT    NOT NULL CHECK (action IN
               ('suspend','ban','reinstate','change_approve','change_reclassify',
                'change_discard','answer_verify','answer_correct','scholarship_verify',
                'portal_add','portal_pause','adapter_promote','adapter_rollback','note')),
  subject_type TEXT    NOT NULL CHECK (subject_type IN
               ('user','passage_diff','answer','scholarship','portal','adapter','report')),
  subject_id   TEXT    NOT NULL,
  reason_en    TEXT,
  reason_bn    TEXT,
  detail       TEXT CHECK (detail IS NULL OR json_valid(detail)),
  created_at   TEXT    NOT NULL,
  CHECK (action NOT IN ('suspend','ban','reinstate') OR reason_en IS NOT NULL)
);
CREATE INDEX idx_modactions_subject ON moderation_actions(subject_type, subject_id);
CREATE INDEX idx_modactions_mod ON moderation_actions(moderator_id, created_at DESC);

-- Shown to the student in their own account: who looked at what, and when.
CREATE TABLE moderation_views (
  id           INTEGER PRIMARY KEY,
  moderator_id INTEGER NOT NULL REFERENCES users(id),
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scope        TEXT    NOT NULL CHECK (scope IN ('profile','answer','plan','report')),
  subject_id   TEXT,
  viewed_at    TEXT    NOT NULL
);
CREATE INDEX idx_modviews_user ON moderation_views(user_id, viewed_at DESC);

-- Abuse reports, including attempts to make the interview agent coach dishonesty.
CREATE TABLE user_reports (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT    NOT NULL UNIQUE,
  reporter_id    INTEGER REFERENCES users(id) ON DELETE SET NULL,
  subject_type   TEXT    NOT NULL CHECK (subject_type IN ('answer','user','scholarship','content')),
  subject_id     TEXT    NOT NULL,
  category       TEXT    NOT NULL CHECK (category IN
                 ('wrong_information','dishonesty_request','abuse','privacy','other')),
  detail         TEXT,
  status         TEXT    NOT NULL DEFAULT 'open'
                 CHECK (status IN ('open','reviewing','resolved','dismissed')),
  resolved_by    INTEGER REFERENCES users(id),
  resolution     TEXT,
  created_at     TEXT    NOT NULL,
  resolved_at    TEXT
);
CREATE INDEX idx_reports_open ON user_reports(status, created_at) WHERE status IN ('open','reviewing');

-- Explicit, revocable consent. Checked at write time by the replay buffer.
CREATE TABLE consents (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT    NOT NULL CHECK (kind IN ('improve_model','usage_analytics','email_alerts')),
  granted    INTEGER NOT NULL CHECK (granted IN (0,1)),
  changed_at TEXT    NOT NULL,
  UNIQUE (user_id, kind)
);
```

**Reuse detection matters.** If a refresh token that was already replaced is
presented again, the whole `family_id` is revoked. That is the standard defence
against a stolen refresh token, and it costs one index.

### 3.2 Student profile and targets

```sql
CREATE TABLE profiles (
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

CREATE TABLE countries (
  code         TEXT PRIMARY KEY,          -- lowercased ISO-3166-1 alpha-2, e.g. 'uk' not 'gb'; see migration 011
  name_en      TEXT NOT NULL,
  name_bn      TEXT NOT NULL,
  visa_types   TEXT NOT NULL CHECK (json_valid(visa_types)),
  active       INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  sort_order   INTEGER NOT NULL DEFAULT 100
);

CREATE TABLE institutions (
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
CREATE INDEX idx_institutions_country ON institutions(country_code);

CREATE TABLE programmes (
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
CREATE INDEX idx_programmes_inst ON programmes(institution_id);
CREATE INDEX idx_programmes_deadline ON programmes(deadline_at);

-- A student's shortlist. Drives Porter, the planner, and Khoji.
-- public_id was added by migration 012 (below): this table was originally
-- built without one, unlike every sibling table, and every read through
-- app/repositories/target_repo.py already selected and inserted public_id
-- before there was a column for it to live in.
CREATE TABLE student_targets (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT UNIQUE,             -- added by migration 012; see section 6
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  programme_id INTEGER NOT NULL REFERENCES programmes(id) ON DELETE CASCADE,
  visa_type    TEXT,
  rank         INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'considering'
               CHECK (status IN ('considering','applying','submitted','offer','rejected','accepted','withdrawn')),
  created_at   TEXT NOT NULL,
  UNIQUE (user_id, programme_id)
);
CREATE INDEX idx_targets_user ON student_targets(user_id);
```

### 3.3 Portals, snapshots, and the Truth Ledger

This is the evidence layer. Every factual claim anywhere in the product resolves
to a row in `snapshots`.

```sql
CREATE TABLE portals (
  id             INTEGER PRIMARY KEY,
  public_id      TEXT NOT NULL UNIQUE,
  url            TEXT NOT NULL UNIQUE,
  kind           TEXT NOT NULL CHECK (kind IN ('embassy','university','scholarship','government','bank')),
  country_code   TEXT REFERENCES countries(code),
  label          TEXT NOT NULL,           -- shown in the UI, e.g. 'ukvi.gov.uk'
  parser_key     TEXT NOT NULL DEFAULT 'generic',
  crawl_cron     TEXT NOT NULL DEFAULT '0 */6 * * *',
  enabled        INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0,1)),
  last_fetch_at  TEXT,
  last_status    TEXT CHECK (last_status IN ('ok','unchanged','unreachable','parse_failed')),
  consecutive_failures INTEGER NOT NULL DEFAULT 0,
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_portals_enabled ON portals(enabled, last_fetch_at);

-- One row per successful fetch whose content hash differed from the previous one.
-- public_id is the snapshot ID the user sees, e.g. 'SNAP-01J8XQ...'.
CREATE TABLE snapshots (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  portal_id     INTEGER NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
  content_hash  TEXT NOT NULL,            -- sha256 of normalised text
  storage_path  TEXT NOT NULL,            -- raw HTML on the encrypted volume
  http_status   INTEGER,
  byte_size     INTEGER,
  fetched_at    TEXT NOT NULL,
  retired_at    TEXT,                     -- set at 90 days; row kept, file may go
  UNIQUE (portal_id, content_hash)
);
CREATE INDEX idx_snapshots_portal_time ON snapshots(portal_id, fetched_at DESC);

-- Passage-level content. The unit of diffing, embedding, and citation.
CREATE TABLE passages (
  id           INTEGER PRIMARY KEY,
  snapshot_id  INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  ordinal      INTEGER NOT NULL,
  section_path TEXT,                      -- 'Requirements > Financial evidence'
  text         TEXT NOT NULL,
  text_hash    TEXT NOT NULL,
  lang         TEXT NOT NULL DEFAULT 'en',
  char_count   INTEGER NOT NULL,
  UNIQUE (snapshot_id, ordinal)
);
CREATE INDEX idx_passages_hash ON passages(text_hash);

-- What actually changed between two snapshots of the same portal.
CREATE TABLE passage_diffs (
  id             INTEGER PRIMARY KEY,
  portal_id      INTEGER NOT NULL REFERENCES portals(id) ON DELETE CASCADE,
  from_snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  to_snapshot_id   INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
  change_type    TEXT NOT NULL CHECK (change_type IN ('added','removed','modified')),
  old_passage_id INTEGER REFERENCES passages(id) ON DELETE SET NULL,
  new_passage_id INTEGER REFERENCES passages(id) ON DELETE SET NULL,
  similarity     REAL,
  -- Filled by Porter's Gemma classification pass:
  category       TEXT CHECK (category IN ('deadline','fee','document_requirement','policy','cosmetic')),
  category_confidence REAL,
  classified_at  TEXT,
  needs_review   INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0,1)),
  created_at     TEXT NOT NULL
);
CREATE INDEX idx_diffs_portal ON passage_diffs(portal_id, created_at DESC);
CREATE INDEX idx_diffs_review ON passage_diffs(needs_review) WHERE needs_review = 1;

-- Versioned knowledge store. One live version at a time, via alias flip.
CREATE TABLE kb_versions (
  id                 INTEGER PRIMARY KEY,
  version_no         INTEGER NOT NULL UNIQUE,
  qdrant_collection  TEXT NOT NULL UNIQUE,
  status             TEXT NOT NULL CHECK (status IN ('building','live','retired')),
  chunk_count        INTEGER NOT NULL DEFAULT 0,
  built_at           TEXT NOT NULL,
  published_at       TEXT,
  retired_at         TEXT
);
CREATE UNIQUE INDEX idx_kb_one_live ON kb_versions(status) WHERE status = 'live';

CREATE TABLE kb_chunks (
  id             INTEGER PRIMARY KEY,
  kb_version_id  INTEGER NOT NULL REFERENCES kb_versions(id) ON DELETE CASCADE,
  passage_id     INTEGER NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
  qdrant_point_id TEXT NOT NULL,
  embedded_at    TEXT NOT NULL,
  UNIQUE (kb_version_id, passage_id)
);
```

`idx_kb_one_live` is a partial unique index, and it is doing real work: it makes
"two live knowledge versions at once" impossible at the database level rather than
by careful coding. An alias flip becomes one transaction that retires the old row
and promotes the new one.

### 3.4 Questions, answers, citations

Shapes here map directly onto the frontend `QA` and `Citation` interfaces.

```sql
CREATE TABLE conversations (
  id         INTEGER PRIMARY KEY,
  public_id  TEXT NOT NULL UNIQUE,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  title      TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE INDEX idx_conv_user ON conversations(user_id, updated_at DESC);

CREATE TABLE questions (
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

CREATE TABLE answers (
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
  CHECK ( (is_refusal = 1 AND refusal_reason IS NOT NULL)
       OR (is_refusal = 0 AND (answer_bn IS NOT NULL OR answer_en IS NOT NULL)) )
);
CREATE INDEX idx_answers_created ON answers(created_at DESC);

-- The Citation interface: {id, portal, captured, quoted}
CREATE TABLE answer_citations (
  id          INTEGER PRIMARY KEY,
  answer_id   INTEGER NOT NULL REFERENCES answers(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,           -- the n in the ‖n‖ marker
  snapshot_id INTEGER NOT NULL REFERENCES snapshots(id),
  passage_id  INTEGER REFERENCES passages(id),
  quoted_span TEXT NOT NULL,
  UNIQUE (answer_id, ordinal)
);

CREATE TABLE answer_feedback (
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
```

The `CHECK` on `answers` is the refusal contract expressed in the schema. A row
that is not a refusal must carry text; a refusal must carry a reason. The database
rejects a half-formed answer even if a bug in the service layer tries to write
one. This is the single most important constraint in the file.

### 3.5 Plans (the Visa Timeline Reactor)

Maps onto the frontend `Step` and `ChangeEntry` interfaces.

```sql
CREATE TABLE plans (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id     INTEGER REFERENCES student_targets(id) ON DELETE SET NULL,
  intake_label  TEXT,
  generated_at  TEXT NOT NULL,
  updated_at    TEXT NOT NULL,
  UNIQUE (user_id, target_id)
);

CREATE TABLE plan_steps (
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
CREATE INDEX idx_steps_plan ON plan_steps(plan_id, order_idx);

-- Every re-plan writes an explainable entry. This is the "what changed" drawer.
CREATE TABLE plan_changes (
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
CREATE INDEX idx_changes_plan ON plan_changes(plan_id, created_at DESC);
```

`step_key` is deliberately stable while `month_label` and `due_at` are not. That
is what makes re-planning safe: the reactor moves dates and rewrites descriptions,
but a step keeps its identity, so the frontend's `layout` animation can move the
row instead of destroying and recreating it.

### 3.6 Vault and Prohori

```sql
CREATE TABLE documents (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN
                ('passport','transcript','certificate','bank_statement','solvency_letter',
                 'english_test','sop','recommendation','offer_letter','visa_refusal',
                 'consultancy_contract','photo','other')),
  original_name TEXT NOT NULL,
  storage_path  TEXT NOT NULL,            -- encrypted file on the volume
  mime_type     TEXT NOT NULL,
  byte_size     INTEGER NOT NULL,
  sha256        TEXT NOT NULL,
  wrapped_dek   BLOB NOT NULL,            -- per-file key, wrapped by the user key
  nonce         BLOB NOT NULL,
  page_count    INTEGER,
  issued_on     TEXT,
  expires_on    TEXT,
  status        TEXT NOT NULL DEFAULT 'uploaded'
                CHECK (status IN ('uploaded','scanning','extracted','failed','quarantined')),
  uploaded_at   TEXT NOT NULL,
  deleted_at    TEXT
);
CREATE INDEX idx_docs_user ON documents(user_id, kind) WHERE deleted_at IS NULL;
CREATE INDEX idx_docs_expiry ON documents(expires_on) WHERE deleted_at IS NULL;

-- Fields extracted by the Gemma vision pass. Values are encrypted at rest.
CREATE TABLE document_fields (
  id          INTEGER PRIMARY KEY,
  document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  field_key   TEXT NOT NULL,              -- 'surname','passport_no','balance','issue_date'
  value_enc   BLOB NOT NULL,
  value_hash  TEXT NOT NULL,              -- for cross-document comparison without decrypting
  confidence  REAL,
  page_no     INTEGER,
  bbox        TEXT CHECK (bbox IS NULL OR json_valid(bbox)),
  extracted_at TEXT NOT NULL,
  UNIQUE (document_id, field_key)
);

CREATE TABLE audits (
  id          INTEGER PRIMARY KEY,
  public_id   TEXT NOT NULL UNIQUE,
  user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  target_id   INTEGER REFERENCES student_targets(id) ON DELETE SET NULL,
  agent       TEXT NOT NULL DEFAULT 'prohori',
  status      TEXT NOT NULL CHECK (status IN ('queued','running','complete','failed')),
  started_at  TEXT NOT NULL,
  finished_at TEXT,
  error       TEXT
);
CREATE INDEX idx_audits_user ON audits(user_id, started_at DESC);

CREATE TABLE audit_findings (
  id          INTEGER PRIMARY KEY,
  public_id   TEXT NOT NULL UNIQUE,
  audit_id    INTEGER NOT NULL REFERENCES audits(id) ON DELETE CASCADE,
  document_id INTEGER REFERENCES documents(id) ON DELETE SET NULL,
  code        TEXT NOT NULL,              -- 'MISSING','EXPIRING','NAME_MISMATCH','AMOUNT_SHORT'
  severity    TEXT NOT NULL CHECK (severity IN ('critical','warning','info')),
  title_en    TEXT NOT NULL,
  title_bn    TEXT NOT NULL,
  detail_en   TEXT NOT NULL,
  detail_bn   TEXT NOT NULL,
  evidence    TEXT CHECK (evidence IS NULL OR json_valid(evidence)),
  action_en   TEXT,
  action_bn   TEXT,
  snapshot_id INTEGER REFERENCES snapshots(id),
  resolved_at TEXT
);
CREATE INDEX idx_findings_audit ON audit_findings(audit_id, severity);
```

`value_hash` deserves a note. Prohori needs to know whether the surname on the
passport matches the surname on the transcript. Comparing hashes of normalised
values answers that without decrypting either field, so the comparison can run in
a worker that never holds the user's key.

### 3.7 Funding and Khoji

```sql
CREATE TABLE scholarships (
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
CREATE INDEX idx_scholarships_country ON scholarships(country_code, active);
CREATE INDEX idx_scholarships_deadline ON scholarships(deadline_at) WHERE active = 1;

CREATE TABLE scholarship_criteria (
  id             INTEGER PRIMARY KEY,
  scholarship_id INTEGER NOT NULL REFERENCES scholarships(id) ON DELETE CASCADE,
  criterion_key  TEXT NOT NULL,           -- 'cgpa_min','nationality','degree_level'
  operator       TEXT NOT NULL CHECK (operator IN ('gte','lte','eq','in','exists')),
  value          TEXT NOT NULL,
  is_hard        INTEGER NOT NULL DEFAULT 1 CHECK (is_hard IN (0,1)),
  weight         REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE funding_matches (
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
CREATE INDEX idx_matches_user_rank ON funding_matches(user_id, rank);

-- One row per criterion per match: this is what makes a ranking explainable.
CREATE TABLE match_reasons (
  id            INTEGER PRIMARY KEY,
  match_id      INTEGER NOT NULL REFERENCES funding_matches(id) ON DELETE CASCADE,
  criterion_key TEXT NOT NULL,
  met           INTEGER NOT NULL CHECK (met IN (0,1)),
  reason_en     TEXT NOT NULL,
  reason_bn     TEXT NOT NULL,
  weight        REAL NOT NULL DEFAULT 1.0
);

CREATE TABLE fx_rates (
  id       INTEGER PRIMARY KEY,
  base     TEXT NOT NULL,
  quote    TEXT NOT NULL,
  rate     REAL NOT NULL,
  source   TEXT NOT NULL,
  as_of    TEXT NOT NULL,
  UNIQUE (base, quote, as_of)
);

CREATE TABLE solvency_rules (
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

CREATE TABLE budgets (
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
CREATE TABLE fee_quotes (
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

CREATE TABLE fee_line_items (
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
```

### 3.8 Interview room and Shonchari

```sql
CREATE TABLE interview_bank (
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

CREATE TABLE interview_sessions (
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
CREATE INDEX idx_sessions_user ON interview_sessions(user_id, started_at DESC);

CREATE TABLE interview_turns (
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

CREATE TABLE interview_reports (
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
```

### 3.9 New agent tables

Three agents added beyond the original four. Rationale and workflows are in
`agents.md`; the storage is here.

```sql
-- Bicharok: reads an actual refusal letter and maps each ground to a remedy.
CREATE TABLE rejection_cases (
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

CREATE TABLE rejection_grounds (
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
CREATE TABLE statements (
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

CREATE TABLE statement_findings (
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
CREATE TABLE contracts (
  id           INTEGER PRIMARY KEY,
  public_id    TEXT NOT NULL UNIQUE,
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  document_id  INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  consultancy  TEXT,
  risk_overall TEXT CHECK (risk_overall IN ('low','medium','high')),
  analysed_at  TEXT NOT NULL
);

CREATE TABLE contract_clauses (
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
```

### 3.10 Notifications

```sql
CREATE TABLE notifications (
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
CREATE INDEX idx_notif_user_unread ON notifications(user_id, created_at DESC) WHERE read_at IS NULL;
```

---

## 4. `events.db`

Append-only. Nothing in this file is ever updated, which is why it can take the
highest write volume without contending with the interactive path.

```sql
CREATE TABLE events (
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
CREATE INDEX idx_events_stream_time ON events(stream, created_at DESC);
CREATE INDEX idx_events_type ON events(type, created_at DESC);
CREATE INDEX idx_events_user ON events(user_id, created_at DESC);

-- Idempotency ledger. This is what makes "consumers are idempotent" true.
CREATE TABLE applied_events (
  consumer    TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  applied_at  TEXT NOT NULL,
  PRIMARY KEY (consumer, event_id)
) WITHOUT ROWID;

CREATE TABLE dead_letters (
  id          INTEGER PRIMARY KEY,
  consumer    TEXT NOT NULL,
  event_id    TEXT NOT NULL,
  attempts    INTEGER NOT NULL,
  last_error  TEXT NOT NULL,
  payload     TEXT NOT NULL,
  created_at  TEXT NOT NULL,
  resolved_at TEXT
);

-- Schema for an audited, multi-step tool-calling runtime (one row per agent
-- invocation, steps_used capped by max_steps). Not populated yet: the seven
-- agents each make one schema-constrained model call today, called directly
-- by the owning service or worker, not dispatched through a tracked run.
-- docs/api_contract.md section 16 has the detail.
CREATE TABLE agent_runs (
  id            INTEGER PRIMARY KEY,
  public_id     TEXT NOT NULL UNIQUE,
  agent         TEXT NOT NULL CHECK (agent IN
                ('porter','prohori','khoji','shonchari','bicharok','lekhok','dalil')),
  user_id       INTEGER,
  trigger_event_id TEXT,
  status        TEXT NOT NULL CHECK (status IN ('queued','running','complete','failed','refused')),
  steps_used    INTEGER NOT NULL DEFAULT 0,
  max_steps     INTEGER NOT NULL DEFAULT 8,
  model_tag     TEXT,
  thinking      INTEGER NOT NULL DEFAULT 0 CHECK (thinking IN (0,1)),
  input_tokens  INTEGER,
  output_tokens INTEGER,
  latency_ms    INTEGER,
  error         TEXT,
  started_at    TEXT NOT NULL,
  finished_at   TEXT
);
CREATE INDEX idx_runs_agent ON agent_runs(agent, started_at DESC);
CREATE INDEX idx_runs_user ON agent_runs(user_id, started_at DESC);

-- Schema for a per-tool-call audit trail. Not populated yet, for the same
-- reason as agent_runs above: no code path writes a row here.
CREATE TABLE agent_tool_calls (
  id          INTEGER PRIMARY KEY,
  run_id      INTEGER NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
  ordinal     INTEGER NOT NULL,
  tool_name   TEXT NOT NULL,
  args_hash   TEXT NOT NULL,
  args_redacted TEXT CHECK (args_redacted IS NULL OR json_valid(args_redacted)),
  result_hash TEXT,
  ok          INTEGER NOT NULL DEFAULT 1 CHECK (ok IN (0,1)),
  error       TEXT,
  latency_ms  INTEGER,
  called_at   TEXT NOT NULL,
  UNIQUE (run_id, ordinal)
);

-- Request-level metrics, for the production latency numbers the paper will
-- report. Schema only today: request handling records these in Prometheus
-- (GET /metrics, in-memory) but nothing yet inserts a row here, so
-- GET /mod/health's latency percentiles read null until that is wired up.
CREATE TABLE request_metrics (
  id            INTEGER PRIMARY KEY,
  route         TEXT NOT NULL,
  method        TEXT NOT NULL,
  status        INTEGER NOT NULL,
  latency_ms    INTEGER NOT NULL,
  cache_hit     INTEGER NOT NULL DEFAULT 0 CHECK (cache_hit IN (0,1)),
  kb_version_id INTEGER,
  created_at    TEXT NOT NULL
);
CREATE INDEX idx_metrics_route_time ON request_metrics(route, created_at DESC);
```

Storing tool-call arguments as a hash plus a redacted copy is deliberate. We need
the audit trail to prove what an agent did, but a full argument dump would put
document contents into the append-only log, which contradicts the data
minimisation commitment. Hash for proof, redacted copy for debugging.

---

## 5. `learn.db`

```sql
CREATE TABLE replay_samples (
  id            INTEGER PRIMARY KEY,
  kind          TEXT NOT NULL CHECK (kind IN ('refusal','correction','unclear','high_value')),
  question      TEXT NOT NULL,
  answer        TEXT,
  correction    TEXT,
  lang          TEXT NOT NULL,
  kb_version_id INTEGER,
  source_answer_public_id TEXT,           -- soft ref, not a join
  consent       INTEGER NOT NULL CHECK (consent IN (0,1)),
  pii_scrubbed  INTEGER NOT NULL DEFAULT 0 CHECK (pii_scrubbed IN (0,1)),
  scrub_report  TEXT CHECK (scrub_report IS NULL OR json_valid(scrub_report)),
  benchmark_leak INTEGER NOT NULL DEFAULT 0 CHECK (benchmark_leak IN (0,1)),
  exported_in   INTEGER,                  -- adapters.id it was trained into
  created_at    TEXT NOT NULL,
  CHECK (consent = 1 AND pii_scrubbed = 1)
);
CREATE INDEX idx_replay_unexported ON replay_samples(created_at) WHERE exported_in IS NULL;

CREATE TABLE adapters (
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

CREATE TABLE benchmark_questions (
  id           INTEGER PRIMARY KEY,
  country_code TEXT NOT NULL,
  family       TEXT NOT NULL CHECK (family IN ('documents','financial','deadlines','process')),
  question_bn  TEXT NOT NULL,
  question_en  TEXT NOT NULL,
  gold_answer  TEXT NOT NULL,
  gold_snapshot_id INTEGER,
  question_hash TEXT NOT NULL UNIQUE,     -- used for the leakage audit
  frozen_at    TEXT NOT NULL
);

CREATE TABLE benchmark_runs (
  id          INTEGER PRIMARY KEY,
  adapter_id  INTEGER REFERENCES adapters(id) ON DELETE CASCADE,
  model_tag   TEXT NOT NULL,
  groundedness REAL,
  refusal_correctness REAL,
  bangla_clarity REAL,
  latency_p50_ms INTEGER,
  latency_p95_ms INTEGER,
  question_count INTEGER NOT NULL,
  raw_results TEXT CHECK (json_valid(raw_results)),
  run_at      TEXT NOT NULL
);
```

The `CHECK (consent = 1 AND pii_scrubbed = 1)` on `replay_samples` is worth more
than any policy document. A sample that was not consented, or was not scrubbed,
cannot physically be stored. The privacy promise is enforced by the engine.

`benchmark_leak` and `question_hash` implement the leakage audit from
`backend/backend.md` section 3.3. Before an export, every candidate sample is
hashed and matched against frozen benchmark questions; matches are flagged and
excluded.

---

## 6. Migrations

Plain numbered SQL files, applied in order, tracked in a table. No ORM migration
framework: the schema is small enough that generated migrations would add more
risk than they remove.

```
backend/app/db/migrations/
  app/001_identity.sql  002_profile.sql  003_knowledge.sql  004_qa.sql
      005_plans.sql     006_vault.sql    007_funding.sql    008_interview.sql
      009_new_agents.sql 010_notifications.sql  011_seed_countries.sql
      012_student_targets_public_id.sql   013_document_extraction.sql
      014_country_geography.sql           015_portal_registry.sql
      016_portal_discovery.sql            017_portal_registry_corrections.sql
  events/001_events.sql 002_agents.sql   003_metrics.sql
  learn/001_replay.sql  002_adapters.sql 003_benchmark.sql
```

**015 to 017 are the watched-portal registry**, and they are worth reading
together because they change what kind of data `portals` holds.

`015_portal_registry.sql` seeds 31 official sources — embassies, immigration
ministries, scholarship bodies, Bangladesh Bank, UGC, IELTS and TOEFL — across the
eight destination countries, plus six with a NULL `country_code` that apply to
every destination (an outward-remittance rule or an IELTS band is not
country-specific). This is a migration and not seed data on purpose: `portals` was
previously populated only by `app/db/seed_demo.py`, which does not run when
`APP_ENV=production`, so a production deployment watched zero portals and every
stage of the recurrent loop downstream of the crawler had no input at all.

`016_portal_discovery.sql` adds `discovered_from_portal_id` and `discovered_at`, so
the registry can grow itself. The crawler follows a bounded set of same-site links
from each registry root and registers each as its own portal row rather than
folding it into the parent — necessary because `snapshots` carries no URL column,
so a snapshot's URL *is* its portal's URL, and folding a child's snapshot under the
parent would point every citation to it at the wrong page. `discovered_at IS NULL`
is the test for "curated root, may be expanded", which caps crawl depth at one
level without needing a counter and also correctly excludes portals found by
search, which have no parent row.

`017_portal_registry_corrections.sql` records what checking all 31 URLs against
the live web found: 25 returned 200, one had moved (deleted, since the reachable
parent plus link expansion covers it), three sit behind a WAF that returns 403 to
any non-browser client while their robots.txt permits crawling (disabled, with a
reachable alternative retained for each affected country), and two were unreachable
from the development network but left enabled, because inferring a dead source from
one vantage point would be wrong and `consecutive_failures` already exists to
surface it properly.

The net after 015 to 017 is **30 rows, 27 of them enabled**, which is the number to
quote wherever the count matters. 31 is what 015 inserts, not what a deployment
watches.

`018_portal_validators.sql` adds `etag` and `last_modified`, so a re-crawl can send
`If-None-Match` and `If-Modified-Since` and let the host answer `304 Not Modified`.
The cheap path was previously only cheap on our side: the crawler downloaded the
whole body every cycle, hashed it, compared, and usually discarded it. Measured
against the live registry, gov.uk answers 304 and saves 148 kB per cycle and
studyinnl.org saves 42 kB, while study-in-germany.de returns an ETag and then ignores
the conditional request, so revalidation is best-effort by design and the full-body
path stays correct. A validator is stored on `portals` rather than `snapshots`
because it describes the current state of a URL, not a historical capture of one, and
it is only overwritten when the host actually sends a replacement: writing NULL for a
header the host merely omitted would permanently disable conditional requests against
any host that sends one inconsistently.

The migration also gives `last_status = 'unchanged'` a meaning for the first time.
That value was already permitted by the CHECK constraint in 003, already listed in
`PortalStatus` in both `app/models/ledger.py` and `frontend/src/app/lib/api.ts`, and
never written: the crawler recorded `'ok'` whether the hash matched or not. It now
means "the host answered 304 and we never saw a body", which is a different
operational fact from "we downloaded the page", and the difference is what tells a
reviewer whether a long-stable portal is honestly stable or is serving a stale ETag
behind a page that has changed. Because the value already existed end to end, no
type, model, or frontend change was needed. The allowed set is now enforced in
`app/repositories/portal_repo.py` next to the code that writes it, alongside an
allowlist of the columns `patch` may write: identity and provenance columns are
excluded, because changing a portal's URL under an existing snapshot would repoint
every citation that resolves through it, which is the one guarantee the Truth Ledger
cannot give up.

Migration 012 is the one addition after the original eleven: it adds the
`student_targets.public_id` column described in section 3.2, found by running
the target endpoints end to end and hitting "no such column: st.public_id"
on every read, since `app/repositories/target_repo.py` had always selected
and inserted a `public_id` that had no column to live in. No backfill
statement is needed, because schema migrations run before any request (including
the demo-account seed) can insert a `student_targets` row, so the table is
always empty at the point this migration runs.

```sql
CREATE TABLE schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  checksum   TEXT NOT NULL
);
```

The checksum is the sha256 of the file. If an applied migration file changes on
disk, startup fails loudly rather than running a different schema than the one
recorded. Rules: migrations are append-only and never edited after being applied
anywhere; every migration is wrapped in a transaction; each file is idempotent
where SQLite allows it (`IF NOT EXISTS`).

## 7. Retention and deletion

All four rows below run nightly (`app/workers/retention.py`, scheduled at
03:17 UTC by `app/workers/main.py`), not on separate schedules. There is no
`otp_codes` table: this system has no OTP step (section 3.1's own note, and
`docs/api_contract.md` section 3), so that row from the original design is
removed here rather than left describing a table that does not exist.

| Data | Retention | Mechanism |
| --- | --- | --- |
| Snapshots and passages | 90 days for files, rows kept indefinitely | nightly job sets `retired_at`, deletes the file, keeps the row so old citations still resolve to a verifiable record |
| Refresh tokens | 30 days past expiry | nightly purge |
| Events | 180 days | nightly job archives to a compressed file in batches, then deletes the archived rows |
| Request metrics | 90 days | nightly purge, once rows exist; nothing in this codebase currently inserts into `request_metrics`, so this table is empty in practice today (`docs/api_contract.md` section 16) |
| Vault documents | until the user deletes | hard delete cascades to the file and shreds the wrapped key |
| Replay samples | until the user deletes their account | full account deletion (`AuthService.delete_account`) removes a user's replay samples. Withdrawing the `improve_model` consent alone does not: no repository exposes that as a standalone operation yet (`docs/api_contract.md` section 16 has the detail) |

**Hard delete of a user** runs in one transaction per database, in this order:
delete vault files from the volume, delete `app.db` rows (cascades handle the
rest), null out `user_id` on `events.db` rows rather than deleting them (the audit
trail must survive, without identifying anyone), delete `learn.db` replay samples
traceable to that user, then write a final `user.deleted` event. The whole
operation is recorded, and the user gets an emailed confirmation.

## 8. Indexing rationale

Every index above exists for one named query. There are no speculative indexes,
because each one costs write throughput on a single-writer database.

| Index | Query it serves |
| --- | --- |
| `idx_portals_enabled` | the crawler picking the next portal due |
| `idx_snapshots_portal_time` | Truth Ledger page, latest snapshot per portal |
| `idx_diffs_review` | the human review queue for low-confidence classifications |
| `idx_kb_one_live` | correctness, not speed: one live version only |
| `idx_docs_expiry` | Prohori finding documents expiring before travel |
| `idx_matches_user_rank` | the Funding Studio broadsheet, ordered |
| `idx_notif_user_unread` | the unread badge, on every page load |
| `idx_replay_unexported` | the learning worker's export query |

## 9. What is deliberately not in SQLite

- **Vector embeddings.** Qdrant, keyed by `kb_chunks.qdrant_point_id`.
- **The semantic cache.** Redis plus a Qdrant `cache` collection. It is derived
  state and must be reconstructible by deleting it.
- **Event delivery.** Redis Streams. `events.db` is the durable archive and the
  idempotency ledger, not the bus.
- **Files.** The encrypted volume. The database stores paths and hashes.
- **Sessions.** Access tokens are stateless JWTs; only refresh tokens are stored.
