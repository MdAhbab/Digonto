-- Portal provenance, so the registry can grow itself.
--
-- A registered portal is an entry point, not a document. `gov.uk/student-visa`
-- is an index; the maintenance-funds figure a student needs lives on a child
-- page. The crawler now follows a bounded set of same-site links
-- (app/workers/crawler.py, MAX_CHILD_PAGES / MAX_CRAWL_DEPTH) and registers each
-- one as its own portal row rather than folding it into the parent.
--
-- Registering rather than folding is what keeps the Truth Ledger intact.
-- `snapshots` is keyed (portal_id, content_hash) and carries no URL of its own,
-- so a snapshot's URL *is* its portal's URL. Storing a child page's snapshot
-- under the parent's id would make every citation to it point at the wrong page,
-- which is precisely the guarantee this product is built on.
--
-- The payoff is that nothing downstream needed changing: a discovered portal is
-- an ordinary portal, so the existing crawl, diff, embed, alias-flip, and Porter
-- chain picks it up on its own cron with no new code path.

ALTER TABLE portals ADD COLUMN discovered_from_portal_id INTEGER
  REFERENCES portals(id) ON DELETE SET NULL;

-- NULL for the curated registry in 015, set for anything the crawler found.
ALTER TABLE portals ADD COLUMN discovered_at TEXT;

-- Depth is enforced by only expanding roots: a portal with a non-NULL
-- discovered_from is never itself expanded, which caps the crawl at one level
-- below the registry without needing a depth counter.
CREATE INDEX IF NOT EXISTS idx_portals_discovered
  ON portals(discovered_from_portal_id) WHERE discovered_from_portal_id IS NOT NULL;
