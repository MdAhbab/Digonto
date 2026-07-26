-- The funding index as production data.
--
-- `scholarships` and `scholarship_criteria` were populated only by
-- `seed_demo.py`, which does not run in production. A production deployment
-- therefore had an empty funding index: Khoji had nothing to match a student
-- against and the Funding Studio's award list was blank. This is the same gap
-- migration 015 closed for `portals`, and it closes the same way — the rows
-- that are real reference data move into a migration, and the demo seed stays
-- for the fixtures that are genuinely demonstration-only.
--
-- Five of the eight destinations (us, au, nl, se, jp) had no award at all even
-- on a developer's machine, so the enrichment here is not padding: a student
-- shortlisting Japan previously saw an empty funding page whatever they did.
--
-- Provenance follows migration 026. `verified = 0` and `snapshot_id IS NULL`
-- mean "seeded from the awarding body's published page, not yet confirmed
-- against a crawled snapshot"; `url` is the page the crawler will confirm it
-- from. Deadlines in particular move every cycle, so the UI must present these
-- as provisional until a snapshot backs them.
--
-- Every insert is guarded on `url`, which is the natural key here, so running
-- this against a machine where the demo seed already inserted the award is a
-- no-op rather than a duplicate.

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJH3HR7B3PKJ7D1S88', 'Chevening Scholarship', 'UK Foreign, Commonwealth & Development Office', 'uk', '["master"]',
       NULL, 'full', NULL, 'GBP', '2026-11-03',
       'https://www.chevening.org/scholarships/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.chevening.org/scholarships/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJH3HR7B3PKJ7D1S88';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'eq', 'master', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJH3HR7B3PKJ7D1S88';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'work_experience_years', 'gte', '2', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJH3HR7B3PKJ7D1S88';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJRG1HX8YQGTWDC7YC', 'Commonwealth Shared Scholarship', 'Commonwealth Scholarship Commission', 'uk', '["master"]',
       NULL, 'full', NULL, 'GBP', '2027-01-15',
       'https://cscuk.fcdo.gov.uk/scholarships/commonwealth-shared-scholarships/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://cscuk.fcdo.gov.uk/scholarships/commonwealth-shared-scholarships/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJRG1HX8YQGTWDC7YC';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'eq', 'master', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJRG1HX8YQGTWDC7YC';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'cgpa_min', 'gte', '3.0', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJRG1HX8YQGTWDC7YC';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJNGZJE2YYTDC1ZF74', 'Fulbright Foreign Student Program', 'United States Department of State', 'us', '["master", "phd"]',
       NULL, 'full', NULL, 'USD', '2027-05-15',
       'https://foreign.fulbrightonline.org/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://foreign.fulbrightonline.org/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJNGZJE2YYTDC1ZF74';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'in', '["master", "phd"]', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJNGZJE2YYTDC1ZF74';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'cgpa_min', 'gte', '3.0', 0, 0.8
  FROM scholarships WHERE public_id = '01KYG9CMSJNGZJE2YYTDC1ZF74';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJM091CC8Q2PWANCWS', 'Hubert H. Humphrey Fellowship Program', 'United States Department of State', 'us', '["master"]',
       NULL, 'full', NULL, 'USD', '2026-10-01',
       'https://exchanges.state.gov/non-us/program/hubert-h-humphrey-fellowship-program', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://exchanges.state.gov/non-us/program/hubert-h-humphrey-fellowship-program');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJM091CC8Q2PWANCWS';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'work_experience_years', 'gte', '5', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJM091CC8Q2PWANCWS';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJVD3NV22YXS2ZCD1T', 'Australia Awards Scholarships', 'Australian Department of Foreign Affairs and Trade', 'au', '["master"]',
       NULL, 'full', NULL, 'AUD', '2027-04-30',
       'https://www.dfat.gov.au/people-to-people/australia-awards', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.dfat.gov.au/people-to-people/australia-awards');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJVD3NV22YXS2ZCD1T';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'eq', 'master', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJVD3NV22YXS2ZCD1T';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'work_experience_years', 'gte', '2', 0, 0.7
  FROM scholarships WHERE public_id = '01KYG9CMSJVD3NV22YXS2ZCD1T';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJKNQSETEE7HZ26DHE', 'Australian Government Research Training Program', 'Australian Government', 'au', '["master", "phd"]',
       NULL, 'tuition_only', NULL, 'AUD', '2026-10-31',
       'https://www.education.gov.au/research-training-program', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.education.gov.au/research-training-program');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'in', '["master", "phd"]', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJKNQSETEE7HZ26DHE';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'cgpa_min', 'gte', '3.5', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJKNQSETEE7HZ26DHE';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJN792M27M7B281GVZ', 'Holland Scholarship', 'Dutch Ministry of Education, Culture and Science', 'nl', '["bachelor", "master"]',
       NULL, 'partial', 500000, 'EUR', '2027-05-01',
       'https://www.studyinnl.org/finances/holland-scholarship', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.studyinnl.org/finances/holland-scholarship');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJN792M27M7B281GVZ';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'in', '["bachelor", "master"]', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJN792M27M7B281GVZ';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJ5DJD82BFVEA5N2SR', 'Orange Knowledge Programme', 'Nuffic', 'nl', '["master"]',
       NULL, 'full', NULL, 'EUR', '2027-02-10',
       'https://www.nuffic.nl/en/subjects/orange-knowledge-programme', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.nuffic.nl/en/subjects/orange-knowledge-programme');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJ5DJD82BFVEA5N2SR';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'eq', 'master', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJ5DJD82BFVEA5N2SR';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'work_experience_years', 'gte', '2', 0, 0.6
  FROM scholarships WHERE public_id = '01KYG9CMSJ5DJD82BFVEA5N2SR';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJWXNZ8DJHN0CVS6X9', 'Swedish Institute Scholarships for Global Professionals', 'Swedish Institute', 'se', '["master"]',
       NULL, 'full', NULL, 'SEK', '2027-02-15',
       'https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://si.se/en/apply/scholarships/swedish-institute-scholarships-for-global-professionals/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJWXNZ8DJHN0CVS6X9';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'eq', 'master', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJWXNZ8DJHN0CVS6X9';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'work_experience_years', 'gte', '3', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJWXNZ8DJHN0CVS6X9';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJWA422ZHC2MC8SQ0A', 'MEXT Scholarship (Research Student)', 'Japanese Ministry of Education, Culture, Sports, Science and Technology', 'jp', '["master", "phd"]',
       NULL, 'full', NULL, 'JPY', '2027-05-31',
       'https://www.studyinjapan.go.jp/en/planning/scholarship/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.studyinjapan.go.jp/en/planning/scholarship/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'nationality', 'eq', 'Bangladesh', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJWA422ZHC2MC8SQ0A';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'in', '["master", "phd"]', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJWA422ZHC2MC8SQ0A';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'cgpa_min', 'gte', '3.2', 0, 0.8
  FROM scholarships WHERE public_id = '01KYG9CMSJWA422ZHC2MC8SQ0A';

INSERT INTO scholarships
  (public_id, name, provider, country_code, degree_levels, fields, coverage_type,
   amount, currency, deadline_at, url, snapshot_id, verified, active, updated_at)
SELECT '01KYG9CMSJJ3A2J7RTWNBNBGA6', 'JASSO Student Exchange Support Program', 'Japan Student Services Organization', 'jp', '["bachelor", "master"]',
       NULL, 'stipend_only', 4800000, 'JPY', '2027-03-31',
       'https://www.jasso.go.jp/en/study_j/scholarships/', NULL, 0, 1, '2026-07-27T00:00:00Z'
 WHERE NOT EXISTS (SELECT 1 FROM scholarships WHERE url = 'https://www.jasso.go.jp/en/study_j/scholarships/');
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'degree_level', 'in', '["bachelor", "master"]', 1, 1.0
  FROM scholarships WHERE public_id = '01KYG9CMSJJ3A2J7RTWNBNBGA6';
INSERT INTO scholarship_criteria
  (scholarship_id, criterion_key, operator, value, is_hard, weight)
SELECT id, 'cgpa_min', 'gte', '3.0', 0, 0.6
  FROM scholarships WHERE public_id = '01KYG9CMSJJ3A2J7RTWNBNBGA6';

CREATE INDEX IF NOT EXISTS idx_scholarship_criteria_award
  ON scholarship_criteria(scholarship_id);
