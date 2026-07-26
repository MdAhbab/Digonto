-- Rewrites `deleted_accounts` (023) to hold the email address and display name in plain
-- text instead of a keyed digest of the address.
--
-- 023 stored an HMAC-SHA256 of the address and dropped the name. That answered "have we
-- seen this address" and nothing else. The operator's requirement is broader: a support
-- or abuse question of the form "who held this account" has to be answerable after the
-- account is gone, and a digest cannot be read back. Keeping the name serves the same
-- need. A digest also cannot be corrected: a mistyped address recorded as a hash is a
-- permanent, unexaminable signup block with no way to see what it blocks.
--
-- The trade this makes is real and is the reason the columns are annotated rather than
-- just declared. This table is now a readable list of the name and address of every
-- person who deleted their account, which makes it the single most attractive object in
-- this database to anybody who obtains the file, and the row cannot be removed by the
-- person it describes. Two consequences follow and are enforced elsewhere:
--   * It is disclosed in docs/privacy.md, including the practical effect on the user
--     (the address cannot be reused for signup). An undisclosed exception to a published
--     deletion promise would make that page false.
--   * Only two call sites may touch it: `record_tombstone` on purge and
--     `tombstone_for_email` at signup. It is not a data source for reports, analytics, or
--     any agent, and `backend/tests/test_tombstone_and_reports.py` asserts that the
--     nightly reporting jobs do not read it.
--
-- Any rows already present are dropped rather than migrated: an HMAC cannot be turned
-- back into an address, so there is no value to carry across. This is safe at the time of
-- writing because the table is empty in every deployment (the feature is days old and no
-- account has been purged), and a row whose email column held a hash would be a lookup
-- key that matches nobody while occupying the UNIQUE constraint.
DROP TABLE IF EXISTS deleted_accounts;

CREATE TABLE deleted_accounts (
  -- The account's public id, unchanged from 023. Already appears in `events` and in the
  -- per-student reports, so keeping it is what makes those records resolvable.
  public_id     TEXT PRIMARY KEY,

  -- Lowercased, trimmed address, exactly as `users.email` held it. NOCASE so the signup
  -- lookup matches the same way the users table does; without it, `Rina@x.com` would
  -- bypass a tombstone recorded for `rina@x.com`.
  email         TEXT NOT NULL UNIQUE COLLATE NOCASE,

  -- The display name at the time of deletion. Nullable: the column is only as good as
  -- what the account had set, and a blank name is not an error.
  display_name  TEXT,

  deleted_at    TEXT NOT NULL,

  -- 'self' when the student asked, 'moderator' when an account was removed for abuse.
  -- The distinction matters: a self-deletion should be re-registerable after a cooling
  -- period if that is ever wanted, and a ban should not be.
  reason        TEXT NOT NULL DEFAULT 'self' CHECK (reason IN ('self', 'moderator')),

  -- How many times this address has been through signup and deletion. A single cycle is
  -- an ordinary change of mind; a dozen is the spam pattern this table exists to see.
  cycle_count   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_deleted_accounts_email ON deleted_accounts(email);
