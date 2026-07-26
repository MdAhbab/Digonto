-- Solvency rules and FX rates for all eight destination countries.
--
-- Before this migration `solvency_rules` held one row (uk/student) and
-- `fx_rates` held one (GBP->BDT), against programmes priced in GBP, CAD, EUR,
-- USD, AUD, SEK and JPY. The effect was not a visibly missing feature but a
-- silent wrong answer: `compose_budget` leaves tuition at 0 when no rate
-- exists, and `solvency_required_bdt` stayed NULL for seven of eight
-- countries — the single most decision-relevant number in the Funding Studio.
--
-- WHY THESE ROWS CARRY A verified = 0 FLAG.
--
-- Migration 014 states the house rule: a static seed cannot carry a citation,
-- so it may not assert a policy figure. These rows *are* policy figures, so
-- rather than break that rule or leave the tables empty, the schema is widened
-- to record exactly how much trust each row has earned:
--
--   * `source_portal_id` points at the official page in the registry that
--     governs the figure, so the citation is a foreign key the UI can link
--     through, not a sentence in a note.
--   * `verified = 0` means "seeded from published guidance, not yet confirmed
--     against a crawled snapshot". The crawler sets it to 1 and fills
--     `snapshot_id` when the figure is confirmed from the source itself.
--
-- Every consumer must therefore treat an unverified row as provisional and say
-- so. A number presented as confirmed when it is not is precisely the
-- confidently-wrong answer this product exists to replace; a number presented
-- as provisional, with the official page one click away, is useful and honest.
--
-- `effective_from` is the date each figure was published by its authority, not
-- the date of this migration, so that staleness is visible rather than
-- disguised as freshness.
--
-- WHICH PORTAL EACH RULE CITES.
--
-- Every citation below points at a portal that migration 017 left *enabled*.
-- The obvious deep links for the United States and Australia
-- (travel.state.gov, immi.homeaffairs.gov.au) are in the registry but disabled
-- there, because both return 403 to any non-browser client; citing one would
-- have produced a figure whose source the crawler can never fetch, so it could
-- never graduate past verified = 0. Those two cite the reachable alternatives
-- that migration 017 names for exactly this purpose — educationusa.state.gov
-- and studyaustralia.gov.au. Canada cites `study-permit.html` rather than the
-- financial-proof deep link, which migration 017 deletes as a 404.

ALTER TABLE solvency_rules ADD COLUMN source_portal_id INTEGER REFERENCES portals(id);
ALTER TABLE solvency_rules ADD COLUMN verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1));

-- On a development box the UK student rule already exists, seeded against a
-- real snapshot by `seed_demo.py`; there it keeps its verified status and gains
-- the structural pointer the others get.
UPDATE solvency_rules
   SET verified = 1,
       source_portal_id = (SELECT id FROM portals WHERE url = 'https://www.gov.uk/student-visa/money')
 WHERE country_code = 'uk' AND visa_type = 'student';

-- On a *production* box it does not exist at all. `seed_demo.py` is demo data
-- and does not run there, and no migration ever created the UK maintenance
-- rule or the GBP->BDT rate — so the one country with a fully worked funding
-- example on a developer's machine had neither in production. The guards make
-- both inserts a no-op wherever the demo seed already ran, so the two paths
-- converge instead of duplicating.
INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'uk', 'student', 13347, 'GBP', 28,
  'Courses in London: 1,483 pounds of living costs per month, for a maximum of nine months, held for 28 consecutive days.',
  'লন্ডনের কোর্সের ক্ষেত্রে: মাসে ১,৪৮৩ পাউন্ড জীবনযাত্রার খরচ, সর্বোচ্চ নয় মাসের জন্য, টানা ২৮ দিন ধরে রাখতে হবে।',
  (SELECT id FROM portals WHERE url = 'https://www.gov.uk/student-visa/money'),
  '2024-01-01', 0
 WHERE NOT EXISTS (
   SELECT 1 FROM solvency_rules WHERE country_code = 'uk' AND visa_type = 'student'
 );

ALTER TABLE fx_rates ADD COLUMN verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0,1));

INSERT INTO fx_rates (base, quote, rate, source, as_of, verified)
SELECT 'GBP', 'BDT', 152.0, 'seeded indicative planning rate, pending refresh', '2026-07-26', 0
 WHERE NOT EXISTS (SELECT 1 FROM fx_rates WHERE base = 'GBP' AND quote = 'BDT');

-- -- solvency ---------------------------------------------------------------
--
-- One row per country and the visa_type its own `countries.visa_types` names,
-- so a lookup keyed on the student's target actually resolves.

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'uk', 'graduate', 13347, 'GBP', 28,
  'Same maintenance basis as the student route: London rates, nine months, held for 28 consecutive days.',
  'শিক্ষার্থী রুটের মতোই একই ভিত্তি: লন্ডনের হার, নয় মাস, টানা ২৮ দিন ধরে রাখতে হবে।',
  (SELECT id FROM portals WHERE url = 'https://www.gov.uk/student-visa/money'),
  '2026-07-26', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'ca', 'study_permit', 22895, 'CAD', 0,
  'Living costs for one year for a single applicant outside Quebec, on top of first-year tuition and travel. No fixed holding period applies; funds must be shown to be available.',
  'কুইবেকের বাইরে একজন আবেদনকারীর এক বছরের জীবনযাত্রার খরচ, প্রথম বছরের টিউশন ও ভ্রমণ খরচ ছাড়াও। নির্দিষ্ট কোনো সময় ধরে রাখার শর্ত নেই; তহবিল আছে তা দেখাতে হবে।',
  (SELECT id FROM portals WHERE url = 'https://www.canada.ca/en/immigration-refugees-citizenship/services/study-canada/study-permit.html'),
  '2025-01-01', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'au', 'subclass_500', 29710, 'AUD', 0,
  'Annual living costs for a single student, in addition to tuition and travel. Evidence of funds is required rather than a fixed holding period.',
  'একজন শিক্ষার্থীর বার্ষিক জীবনযাত্রার খরচ, টিউশন ও ভ্রমণ খরচের অতিরিক্ত। নির্দিষ্ট সময় ধরে রাখার বদলে তহবিলের প্রমাণ দিতে হয়।',
  (SELECT id FROM portals WHERE url = 'https://www.studyaustralia.gov.au/'),
  '2024-05-10', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'de', 'national_visa', 11904, 'EUR', 0,
  'Blocked account (Sperrkonto) for one year, released in equal monthly instalments. The blocked account itself is the holding mechanism, so no separate hold period applies.',
  'এক বছরের জন্য ব্লকড অ্যাকাউন্ট (স্পেরকন্টো), সমান মাসিক কিস্তিতে ছাড় হয়। ব্লকড অ্যাকাউন্টই সংরক্ষণের ব্যবস্থা, তাই আলাদা কোনো সময়সীমা নেই।',
  (SELECT id FROM portals WHERE url = 'https://www.auswaertiges-amt.de/en/visa-service'),
  '2025-01-01', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'nl', 'residence_permit', 13800, 'EUR', 0,
  'Approximate annual living costs the university must see before it applies to the Immigration and Naturalisation Service on the student behalf. The university sets the exact figure.',
  'আনুমানিক বার্ষিক জীবনযাত্রার খরচ, যা বিশ্ববিদ্যালয়কে দেখাতে হয় শিক্ষার্থীর পক্ষে ইমিগ্রেশন ও ন্যাচারালাইজেশন সার্ভিসে আবেদনের আগে। সঠিক পরিমাণ বিশ্ববিদ্যালয় নির্ধারণ করে।',
  (SELECT id FROM portals WHERE url = 'https://ind.nl/en/residence-permits/study'),
  '2024-01-01', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'se', 'residence_permit_study', 103140, 'SEK', 0,
  'Ten months of living costs at the monthly rate the Swedish Migration Agency requires, shown for each year of study.',
  'সুইডিশ মাইগ্রেশন এজেন্সির নির্ধারিত মাসিক হারে দশ মাসের জীবনযাত্রার খরচ, অধ্যয়নের প্রতি বছরের জন্য দেখাতে হয়।',
  (SELECT id FROM portals WHERE url = 'https://www.migrationsverket.se/English/Private-individuals/Studying-and-researching-in-Sweden.html'),
  '2024-01-01', 0;

-- The United States and Japan set no single statutory bank balance. Seeding a
-- figure as though they did would be a fabricated rule, so these two rows carry
-- the indicative amount actually used in practice and say plainly in the note
-- that the binding figure is the student's own I-20 or CoE application.
INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'us', 'f1', 40000, 'USD', 0,
  'There is no fixed statutory amount. The binding figure is the first-year cost of attendance printed on your own Form I-20, which varies by institution; this is an indicative one-year total for planning only.',
  'নির্দিষ্ট কোনো সরকারি পরিমাণ নেই। বাধ্যতামূলক অঙ্কটি আপনার নিজের ফর্ম আই-২০ তে লেখা প্রথম বছরের মোট খরচ, যা প্রতিষ্ঠানভেদে আলাদা; এটি কেবল পরিকল্পনার জন্য একটি আনুমানিক বার্ষিক হিসাব।',
  (SELECT id FROM portals WHERE url = 'https://educationusa.state.gov/'),
  '2024-01-01', 0;

INSERT INTO solvency_rules
  (country_code, visa_type, amount, currency, hold_days,
   basis_note_en, basis_note_bn, source_portal_id, effective_from, verified)
SELECT 'jp', 'student', 2000000, 'JPY', 0,
  'There is no fixed statutory amount. The university applies for your Certificate of Eligibility and decides what evidence of support it needs; this is an indicative figure commonly shown for one year.',
  'নির্দিষ্ট কোনো সরকারি পরিমাণ নেই। বিশ্ববিদ্যালয় আপনার সার্টিফিকেট অব এলিজিবিলিটির জন্য আবেদন করে এবং কী প্রমাণ লাগবে তা নির্ধারণ করে; এটি এক বছরের জন্য সচরাচর দেখানো একটি আনুমানিক অঙ্ক।',
  (SELECT id FROM portals WHERE url = 'https://www.studyinjapan.go.jp/en/'),
  '2024-01-01', 0;

-- -- fx --------------------------------------------------------------------
--
-- One row per currency a programme or solvency rule in this database is priced
-- in. Without these, `compose_budget` converts nothing and reports a tuition of
-- zero, which reads as "this course is free" rather than "no rate on file".
--
-- These are indicative planning rates, not dealing rates, and `source` says so
-- on every row. The worker refreshes them; nothing here is presented to a
-- student as the rate their bank will give them.

INSERT INTO fx_rates (base, quote, rate, source, as_of, verified) VALUES
  ('USD', 'BDT', 122.0,  'seeded indicative planning rate, pending refresh', '2026-07-26', 0),
  ('EUR', 'BDT', 132.0,  'seeded indicative planning rate, pending refresh', '2026-07-26', 0),
  ('CAD', 'BDT',  89.0,  'seeded indicative planning rate, pending refresh', '2026-07-26', 0),
  ('AUD', 'BDT',  80.0,  'seeded indicative planning rate, pending refresh', '2026-07-26', 0),
  ('SEK', 'BDT',  11.5,  'seeded indicative planning rate, pending refresh', '2026-07-26', 0),
  ('JPY', 'BDT',   0.82, 'seeded indicative planning rate, pending refresh', '2026-07-26', 0);

CREATE INDEX IF NOT EXISTS idx_solvency_country_visa
  ON solvency_rules(country_code, visa_type, effective_from DESC);
