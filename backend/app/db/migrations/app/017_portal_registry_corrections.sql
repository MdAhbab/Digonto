-- Corrections from checking all 31 registry URLs against the live web.
--
-- 25 of 31 returned 200. This migration deals with the six that did not, because
-- a registry entry that can never be fetched is worse than no entry: it consumes
-- crawl budget on a six-hour cron forever and shows as a permanent failure in the
-- moderator console, which trains a reviewer to ignore that signal.
--
-- Three groups, handled differently on purpose.

-- 1. Gone (404). canada.ca moved its financial-proof page. Rather than guess a
--    replacement deep link that may move again, the entry is dropped: the parent
--    `study-permit.html` is reachable (200), stays in the registry, and the
--    bounded same-site expansion in app/workers/crawler.py will reach the funds
--    page from it. This is the argument migration 015 made for preferring
--    canonical landing pages, applied.
--
--    Deleted rather than disabled because it is the only one of the six that is
--    genuinely wrong rather than merely unreachable from one network.
DELETE FROM portals
 WHERE public_id = 'PORTAL-REG-CA-FINANCIALPROOF'
   AND NOT EXISTS (SELECT 1 FROM snapshots WHERE snapshots.portal_id = portals.id);

-- 2. Refuses automated clients (403 behind a WAF, while robots.txt permits
--    crawling). travel.state.gov, immi.homeaffairs.gov.au and mofa.go.jp all
--    return 403 to any non-browser client regardless of how well-formed the
--    request is; adding standard Accept headers changes nothing. The User-Agent
--    is deliberately not disguised to get around this.
--
--    Disabled, not deleted: the row documents that the source is known and
--    intentionally unwatched, and a reviewer can re-enable it if the block lifts.
--    Every affected country keeps a reachable source — the US has
--    educationusa.state.gov and ustraveldocs.com/bd, Australia has
--    studyaustralia.gov.au, Japan has studyinjapan.go.jp and jasso.go.jp — so no
--    destination loses coverage.
--
--    The crawler now detects this case itself (`_record_blocked`) and disables on
--    the first 403 rather than retrying to the failure threshold. Doing it here
--    too means a fresh deployment never spends those requests at all.
UPDATE portals
   SET enabled = 0,
       last_status = 'unreachable',
       consecutive_failures = 3
 WHERE public_id IN (
        'PORTAL-REG-US-STUDENTVISA',
        'PORTAL-REG-AU-STUDENT500',
        'PORTAL-REG-JP-MOFA'
       );

-- 3. Unreachable from the development network, but left enabled. ugc.gov.bd did
--    not resolve and dfat.gov.au timed out from where this was checked. Both are
--    plausibly reachable from the production VM, which sits on a different network
--    in a different region, and disabling a live source because of one vantage
--    point would be the wrong inference from the evidence. The existing
--    consecutive_failures path is exactly the mechanism for this: it will surface
--    them to a reviewer if they really are down, without a guess being baked into
--    the schema.
--
--    Recorded here as a deliberate decision rather than an oversight.
