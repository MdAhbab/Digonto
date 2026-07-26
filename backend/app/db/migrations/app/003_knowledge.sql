-- docs/database.md section 3.3 "Portals, snapshots, and the Truth Ledger".
-- Every factual claim anywhere in the product resolves to a row in snapshots.

CREATE TABLE IF NOT EXISTS portals (
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
CREATE INDEX IF NOT EXISTS idx_portals_enabled ON portals(enabled, last_fetch_at);

-- One row per successful fetch whose content hash differed from the previous one.
-- public_id is the snapshot ID the user sees, e.g. 'SNAP-01J8XQ...'.
CREATE TABLE IF NOT EXISTS snapshots (
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
CREATE INDEX IF NOT EXISTS idx_snapshots_portal_time ON snapshots(portal_id, fetched_at DESC);

-- Passage-level content. The unit of diffing, embedding, and citation.
CREATE TABLE IF NOT EXISTS passages (
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
CREATE INDEX IF NOT EXISTS idx_passages_hash ON passages(text_hash);

-- What actually changed between two snapshots of the same portal.
CREATE TABLE IF NOT EXISTS passage_diffs (
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
CREATE INDEX IF NOT EXISTS idx_diffs_portal ON passage_diffs(portal_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_diffs_review ON passage_diffs(needs_review) WHERE needs_review = 1;

-- Versioned knowledge store. One live version at a time, via alias flip.
CREATE TABLE IF NOT EXISTS kb_versions (
  id                 INTEGER PRIMARY KEY,
  version_no         INTEGER NOT NULL UNIQUE,
  qdrant_collection  TEXT NOT NULL UNIQUE,
  status             TEXT NOT NULL CHECK (status IN ('building','live','retired')),
  chunk_count        INTEGER NOT NULL DEFAULT 0,
  built_at           TEXT NOT NULL,
  published_at       TEXT,
  retired_at         TEXT
);
-- Partial unique index: makes "two live knowledge versions at once" impossible
-- at the database level rather than by careful coding.
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_one_live ON kb_versions(status) WHERE status = 'live';

CREATE TABLE IF NOT EXISTS kb_chunks (
  id             INTEGER PRIMARY KEY,
  kb_version_id  INTEGER NOT NULL REFERENCES kb_versions(id) ON DELETE CASCADE,
  passage_id     INTEGER NOT NULL REFERENCES passages(id) ON DELETE CASCADE,
  qdrant_point_id TEXT NOT NULL,
  embedded_at    TEXT NOT NULL,
  UNIQUE (kb_version_id, passage_id)
);
