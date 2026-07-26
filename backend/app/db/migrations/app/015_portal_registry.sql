-- The watched-portal registry.
--
-- Why this is a migration and not seed data. Until now the only rows in
-- `portals` came from app/db/seed_demo.py, which runs only when APP_ENV is not
-- production. A production deployment therefore watched *zero* portals: the
-- crawler had nothing to fetch, the diff worker nothing to diff, Porter nothing
-- to classify, and the knowledge store stayed empty, so every question fell
-- through to a refusal. The recurrent loop described in backend/backend.md
-- section 3.2 was real code with no inputs. Portals are infrastructure, not
-- fixtures, so they belong here where every environment gets them.
--
-- `INSERT OR IGNORE` on the UNIQUE url: the two portals seed_demo.py already
-- inserts are in this list too, and a development database that has been seeded
-- must not fail this migration.
--
-- On URL accuracy. Official sites reorganise without notice, which is the
-- premise of this whole product, so no list of deep links stays correct
-- forever. That is handled rather than assumed: a URL that 404s or moves is
-- recorded as `last_status='unreachable'`, increments `consecutive_failures`,
-- and surfaces in GET /mod/health for a reviewer, and the crawler emits a
-- single `portal.unreachable` event rather than inventing content. Canonical
-- section landing pages are preferred over deep links for that reason, since
-- they are the most stable URL a site has, and the bounded same-site crawl
-- (app/workers/crawler.py) walks down from them to the specific pages.

-- ---------------------------------------------------------------------------
-- United Kingdom
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-UK-STUDENTVISA', 'https://www.gov.uk/student-visa',
   'government', 'uk', 'gov.uk/student-visa', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-UK-MONEY', 'https://www.gov.uk/student-visa/money',
   'government', 'uk', 'gov.uk/student-visa/money', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-UK-UKVI', 'https://www.gov.uk/government/organisations/uk-visas-and-immigration',
   'government', 'uk', 'gov.uk/ukvi', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-UK-CHEVENING', 'https://www.chevening.org/scholarships/',
   'scholarship', 'uk', 'chevening.org', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-UK-COMMONWEALTH', 'https://cscuk.fcdo.gov.uk/scholarships/',
   'scholarship', 'uk', 'cscuk.fcdo.gov.uk', 'generic', '0 0 */1 * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- United States
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-US-STUDENTVISA',
   'https://travel.state.gov/content/travel/en/us-visas/study/student-visa.html',
   'government', 'us', 'travel.state.gov/student-visa', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-US-BDPOST', 'https://www.ustraveldocs.com/bd/',
   'embassy', 'us', 'ustraveldocs.com/bd', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-US-EDUCATIONUSA', 'https://educationusa.state.gov/',
   'government', 'us', 'educationusa.state.gov', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-US-FULBRIGHT', 'https://foreign.fulbrightonline.org/',
   'scholarship', 'us', 'foreign.fulbrightonline.org', 'generic', '0 0 */1 * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Canada
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-CA-STUDYPERMIT',
   'https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit.html',
   'government', 'ca', 'canada.ca/study-permit', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-CA-FINANCIALPROOF',
   'https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit/financial-proof.html',
   'government', 'ca', 'canada.ca/study-permit/financial-proof', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-CA-IRCC',
   'https://www.canada.ca/en/services/immigration-citizenship.html',
   'government', 'ca', 'canada.ca/immigration', 'generic', '0 0 */1 * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Australia
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-AU-STUDENT500',
   'https://immi.homeaffairs.gov.au/visas/getting-a-visa/visa-listing/student-500',
   'government', 'au', 'immi.homeaffairs.gov.au/student-500', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-AU-AWARDS', 'https://www.dfat.gov.au/people-to-people/australia-awards',
   'scholarship', 'au', 'dfat.gov.au/australia-awards', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-AU-STUDYAUS', 'https://www.studyaustralia.gov.au/',
   'government', 'au', 'studyaustralia.gov.au', 'generic', '0 0 */1 * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Germany
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-DE-STUDYIN', 'https://www.study-in-germany.de/en/',
   'government', 'de', 'study-in-germany.de', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-DE-DAAD', 'https://www.daad.de/en/studying-in-germany/',
   'scholarship', 'de', 'daad.de', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-DE-VISA', 'https://www.auswaertiges-amt.de/en/visa-service',
   'embassy', 'de', 'auswaertiges-amt.de/visa', 'generic', '0 */6 * * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Japan
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-JP-STUDYINJAPAN', 'https://www.studyinjapan.go.jp/en/',
   'government', 'jp', 'studyinjapan.go.jp', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-JP-JASSO', 'https://www.jasso.go.jp/en/',
   'scholarship', 'jp', 'jasso.go.jp', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-JP-MOFA', 'https://www.mofa.go.jp/j_info/visit/visa/',
   'embassy', 'jp', 'mofa.go.jp/visa', 'generic', '0 */6 * * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Netherlands and Sweden
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-NL-STUDYINNL', 'https://www.studyinnl.org/',
   'government', 'nl', 'studyinnl.org', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-NL-IND', 'https://ind.nl/en/residence-permits/study',
   'government', 'nl', 'ind.nl/study', 'generic', '0 */6 * * *', 1, datetime('now')),
  ('PORTAL-REG-SE-STUDYIN', 'https://studyinsweden.se/',
   'government', 'se', 'studyinsweden.se', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-SE-MIGRATION',
   'https://www.migrationsverket.se/English/Private-individuals/Studying-and-researching-in-Sweden.html',
   'government', 'se', 'migrationsverket.se/studying', 'generic', '0 */6 * * *', 1, datetime('now'));

-- ---------------------------------------------------------------------------
-- Cross-border and origin-side sources.
--
-- country_code is NULL on purpose. app/rag/retrieval.py filters dense results by
-- the student's target country but admits passages with no country, so these
-- answer questions for every destination: an outward-remittance rule from
-- Bangladesh Bank or an IELTS band requirement applies regardless of where the
-- student is going.
-- ---------------------------------------------------------------------------
INSERT OR IGNORE INTO portals
  (public_id, url, kind, country_code, label, parser_key, crawl_cron, enabled, created_at)
VALUES
  ('PORTAL-REG-XX-ERASMUS',
   'https://erasmus-plus.ec.europa.eu/opportunities/individuals/students',
   'scholarship', NULL, 'erasmus-plus.ec.europa.eu', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-BD-BANGLADESHBANK', 'https://www.bb.org.bd/',
   'bank', NULL, 'bb.org.bd', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-BD-UGC', 'https://ugc.gov.bd/',
   'government', NULL, 'ugc.gov.bd', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-BD-MOEDU', 'https://moedu.gov.bd/',
   'government', NULL, 'moedu.gov.bd', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-XX-IELTS', 'https://ielts.org/',
   'government', NULL, 'ielts.org', 'generic', '0 0 */1 * *', 1, datetime('now')),
  ('PORTAL-REG-XX-TOEFL', 'https://www.ets.org/toefl.html',
   'government', NULL, 'ets.org/toefl', 'generic', '0 0 */1 * *', 1, datetime('now'));
