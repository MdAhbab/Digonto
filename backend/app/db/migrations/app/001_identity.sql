-- docs/database.md section 3.1 "Identity and access".
-- Users, refresh tokens (rotation-family reuse detection), moderation actions
-- and views, abuse reports, and consent. No otp_codes table: auth is plain
-- email + password per docs/api_contract.md section 3.

CREATE TABLE IF NOT EXISTS users (
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
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role) WHERE role != 'student';
CREATE INDEX IF NOT EXISTS idx_users_status ON users(status) WHERE status != 'active';

-- Refresh tokens. Access tokens are stateless JWTs and are not stored.
CREATE TABLE IF NOT EXISTS refresh_tokens (
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
CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id) WHERE revoked_at IS NULL;

-- Every moderator action, immutable. A ban with no recorded reason is not
-- moderation, so reason columns are NOT NULL for the actions that need them.
CREATE TABLE IF NOT EXISTS moderation_actions (
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
CREATE INDEX IF NOT EXISTS idx_modactions_subject ON moderation_actions(subject_type, subject_id);
CREATE INDEX IF NOT EXISTS idx_modactions_mod ON moderation_actions(moderator_id, created_at DESC);

-- Shown to the student in their own account: who looked at what, and when.
CREATE TABLE IF NOT EXISTS moderation_views (
  id           INTEGER PRIMARY KEY,
  moderator_id INTEGER NOT NULL REFERENCES users(id),
  user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  scope        TEXT    NOT NULL CHECK (scope IN ('profile','answer','plan','report')),
  subject_id   TEXT,
  viewed_at    TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_modviews_user ON moderation_views(user_id, viewed_at DESC);

-- Abuse reports, including attempts to make the interview agent coach dishonesty.
CREATE TABLE IF NOT EXISTS user_reports (
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
CREATE INDEX IF NOT EXISTS idx_reports_open ON user_reports(status, created_at) WHERE status IN ('open','reviewing');

-- Explicit, revocable consent. Checked at write time by the replay buffer.
CREATE TABLE IF NOT EXISTS consents (
  id         INTEGER PRIMARY KEY,
  user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind       TEXT    NOT NULL CHECK (kind IN ('improve_model','usage_analytics','email_alerts')),
  granted    INTEGER NOT NULL CHECK (granted IN (0,1)),
  changed_at TEXT    NOT NULL,
  UNIQUE (user_id, kind)
);
