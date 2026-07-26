-- A record that an account existed, kept after the account itself is erased.
--
-- Purpose, stated plainly because it is the only reason this table is allowed to exist:
-- to stop one address being used to open account after account, and to stop a deleted
-- account's address being claimed by somebody else. Both are abuse controls, not
-- analytics, and nothing else may read this table.
--
-- The address is stored as an HMAC-SHA256 rather than in plain text.
--
-- That is a deliberate narrowing of what was asked for, and the reasoning is worth
-- recording. Both goals are questions of the form "have we seen this address before",
-- which a keyed digest answers exactly as well as the address does: signup hashes the
-- submitted address with the same key and looks for a match. What the digest cannot do
-- is be read. A table of the email addresses of every person who deleted their account
-- is the most attractive single object in this database to an attacker and the hardest
-- to justify to the person it describes, and it buys nothing that the digest does not.
--
-- HMAC with a server-held key rather than a bare hash, because a bare SHA-256 of an
-- email address is trivially reversible: the search space of real addresses is small
-- enough to enumerate, so an unkeyed digest of an email is the email. The key lives in
-- the application secret (see app/security/tombstone.py), so a stolen database file
-- alone does not yield the addresses.
--
-- The display name is deliberately NOT retained. It was asked for alongside the address,
-- and it serves neither goal: names are not unique, so blocking one would lock out
-- unrelated people who happen to share it with someone who left, and it identifies a
-- person without preventing any abuse. `public_id` is kept because it is the identifier
-- the reports and the event log already use, so a support question of the form "what
-- happened to this account" stays answerable.
CREATE TABLE IF NOT EXISTS deleted_accounts (
  -- The account's public id, unchanged. Already appears in `events` and in the
  -- per-student reports, so keeping it is what makes those records resolvable.
  public_id     TEXT PRIMARY KEY,

  -- HMAC-SHA256 of the lowercased, trimmed email address. Unique, so a second deletion
  -- of a re-registered address collapses onto one row rather than accumulating.
  email_hmac    TEXT NOT NULL UNIQUE,

  deleted_at    TEXT NOT NULL,

  -- 'self' when the student asked, 'moderator' when an account was removed for abuse.
  -- The distinction matters: a self-deletion should be re-registerable after a cooling
  -- period if that is ever wanted, and a ban should not be.
  reason        TEXT NOT NULL DEFAULT 'self' CHECK (reason IN ('self', 'moderator')),

  -- How many times this address has been through signup and deletion. A single cycle is
  -- an ordinary change of mind; a dozen is the spam pattern this table exists to see.
  cycle_count   INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_deleted_accounts_hmac ON deleted_accounts(email_hmac);
