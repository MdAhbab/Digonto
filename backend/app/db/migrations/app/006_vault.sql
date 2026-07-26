-- docs/database.md section 3.6 "Vault and Prohori".
-- document_fields.value_enc has no dedicated nonce column, unlike
-- documents.nonce: see app/security/vault_crypto.py for how the nonce is
-- carried (prepended to the ciphertext blob) when there is no column for it.

CREATE TABLE IF NOT EXISTS documents (
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
CREATE INDEX IF NOT EXISTS idx_docs_user ON documents(user_id, kind) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_docs_expiry ON documents(expires_on) WHERE deleted_at IS NULL;

-- Fields extracted by the Gemma vision pass. Values are encrypted at rest.
CREATE TABLE IF NOT EXISTS document_fields (
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

CREATE TABLE IF NOT EXISTS audits (
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
CREATE INDEX IF NOT EXISTS idx_audits_user ON audits(user_id, started_at DESC);

CREATE TABLE IF NOT EXISTS audit_findings (
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
CREATE INDEX IF NOT EXISTS idx_findings_audit ON audit_findings(audit_id, severity);
