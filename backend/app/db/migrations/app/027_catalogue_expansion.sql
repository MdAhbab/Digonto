-- Universities and programmes for all eight destination countries.
--
-- Before this migration the catalogue held three institutions and three
-- programmes across two countries. Six of the eight destinations a student can
-- shortlist had no programme at all, and since a `student_targets` row can only
-- be created from a programme, a student choosing Germany or Japan could not
-- form a target — which in turn left them with no funding budget and no
-- deadline for the timeline to anchor on. The catalogue was the binding
-- constraint on the whole journey, not a cosmetic gap.
--
-- Provenance, same rule as migration 026: `verified = 0` on every institution
-- here means "seeded from the institution's published prospectus, not yet
-- confirmed against a crawled snapshot", and `source_snapshot_id` stays NULL
-- until the crawler supplies one. Tuition in particular is re-set annually by
-- every institution on this list, so a figure here is a planning estimate and
-- the UI must present it as one.
--
-- `tuition_amount` is in MINOR units, per the column comment in
-- 002_profile.sql: 3850000 is GBP 38,500. The two seeded rows that already
-- existed follow the same convention.

INSERT INTO institutions
  (public_id, country_code, name, city, website, verified, created_at)
VALUES
  ('01KYG81621RKR9D3HSC0AJ2074', 'uk', 'University of Edinburgh', 'Edinburgh', 'https://www.ed.ac.uk', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621KRQ5WZPN94GYTVBW', 'uk', 'King''s College London', 'London', 'https://www.kcl.ac.uk', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621ZP65WGJTJR2455C0', 'us', 'University of Illinois Urbana-Champaign', 'Urbana', 'https://illinois.edu', 0, '2026-07-27T00:00:00Z'),
  ('01KYG8162142906S4EC6ZE03R1', 'us', 'Arizona State University', 'Tempe', 'https://www.asu.edu', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621SPVQE336C577B8DP', 'us', 'Purdue University', 'West Lafayette', 'https://www.purdue.edu', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621BK0X0G2VRM60T147', 'ca', 'University of British Columbia', 'Vancouver', 'https://www.ubc.ca', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621FXF8WSQHFFDSVB5A', 'ca', 'McGill University', 'Montreal', 'https://www.mcgill.ca', 0, '2026-07-27T00:00:00Z'),
  ('01KYG816214CTBYYN33QEXVSNP', 'au', 'University of Melbourne', 'Melbourne', 'https://www.unimelb.edu.au', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621JPW3VRD6C4MWNQ5K', 'au', 'Monash University', 'Melbourne', 'https://www.monash.edu', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621RFGABC69JC8RMZB0', 'au', 'University of Sydney', 'Sydney', 'https://www.sydney.edu.au', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621XB4H05ZHRRP4XNM6', 'de', 'Technical University of Munich', 'Munich', 'https://www.tum.de', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621KQXV8M7P8BKX0WGJ', 'de', 'RWTH Aachen University', 'Aachen', 'https://www.rwth-aachen.de', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621RQJ4MWE76BBDZR99', 'de', 'University of Stuttgart', 'Stuttgart', 'https://www.uni-stuttgart.de', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621Z82VJCK8A26JWDNP', 'nl', 'Delft University of Technology', 'Delft', 'https://www.tudelft.nl', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621PJK9J89GNZ2KNXVY', 'nl', 'University of Amsterdam', 'Amsterdam', 'https://www.uva.nl', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621F9NRT0GKJ6C2M0WV', 'nl', 'Eindhoven University of Technology', 'Eindhoven', 'https://www.tue.nl', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621HP1MJ3DR9V6PEH29', 'se', 'KTH Royal Institute of Technology', 'Stockholm', 'https://www.kth.se', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621FGYTG3W24DH48B9Y', 'se', 'Lund University', 'Lund', 'https://www.lu.se', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621D6KZCTFXBPFXE2D3', 'se', 'Chalmers University of Technology', 'Gothenburg', 'https://www.chalmers.se', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621T9PX612A9QKJVA0J', 'jp', 'University of Tokyo', 'Tokyo', 'https://www.u-tokyo.ac.jp', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621WDECDN4N16VSM94Q', 'jp', 'Kyoto University', 'Kyoto', 'https://www.kyoto-u.ac.jp', 0, '2026-07-27T00:00:00Z'),
  ('01KYG81621SH366XK2FET8G2J1', 'jp', 'Institute of Science Tokyo', 'Tokyo', 'https://www.isct.ac.jp', 0, '2026-07-27T00:00:00Z');

INSERT INTO programmes
  (public_id, institution_id, name, degree_level, field_of_study, duration_months,
   tuition_amount, tuition_currency, intake_months, min_cgpa, min_english,
   deadline_at, updated_at)
VALUES
  ('01KYG81621H79ZM6KKH8BXT7J4', (SELECT id FROM institutions WHERE public_id = '01KYG81621RKR9D3HSC0AJ2074'), 'MSc Data Science', 'master', 'Data Science', 12, 3850000, 'GBP', '[9]', 3.0, 6.5, '2027-01-25', '2026-07-27T00:00:00Z'),
  ('01KYG816210GYYGH6XW2SWV1DH', (SELECT id FROM institutions WHERE public_id = '01KYG81621RKR9D3HSC0AJ2074'), 'MSc Public Policy', 'master', 'Public Policy', 12, 2630000, 'GBP', '[9]', 3.0, 7.0, '2027-01-25', '2026-07-27T00:00:00Z'),
  ('01KYG81621BF72VB3B39HYXFGV', (SELECT id FROM institutions WHERE public_id = '01KYG81621KRQ5WZPN94GYTVBW'), 'MSc Advanced Computing', 'master', 'Computer Science', 12, 3600000, 'GBP', '[9]', 3.2, 6.5, '2027-03-28', '2026-07-27T00:00:00Z'),
  ('01KYG816215QTWBSVWXGA2N32P', (SELECT id FROM institutions WHERE public_id = '01KYG81621KRQ5WZPN94GYTVBW'), 'LLM International Law', 'master', 'Law', 12, 3450000, 'GBP', '[9]', 3.2, 7.0, '2027-03-28', '2026-07-27T00:00:00Z'),
  ('01KYG81621PT5DXGRBK55R16YY', (SELECT id FROM institutions WHERE public_id = '01KYG81621ZP65WGJTJR2455C0'), 'MS Computer Science', 'master', 'Computer Science', 24, 3800000, 'USD', '[8, 1]', 3.2, 6.5, '2026-12-15', '2026-07-27T00:00:00Z'),
  ('01KYG816210CCSD06QZ8SZ2N42', (SELECT id FROM institutions WHERE public_id = '01KYG81621ZP65WGJTJR2455C0'), 'MS Civil Engineering', 'master', 'Engineering', 24, 3600000, 'USD', '[8, 1]', 3.0, 6.5, '2026-12-15', '2026-07-27T00:00:00Z'),
  ('01KYG816219T4Y2RN2HK3YCXWK', (SELECT id FROM institutions WHERE public_id = '01KYG8162142906S4EC6ZE03R1'), 'MS Computer Science', 'master', 'Computer Science', 24, 3200000, 'USD', '[8, 1]', 3.0, 6.5, '2027-02-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621Z77W95MWCFPHE683', (SELECT id FROM institutions WHERE public_id = '01KYG8162142906S4EC6ZE03R1'), 'MS Business Analytics', 'master', 'Business Analytics', 18, 3500000, 'USD', '[8]', 3.0, 7.0, '2027-02-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621EHNPEGA1C0XFEY6A', (SELECT id FROM institutions WHERE public_id = '01KYG81621SPVQE336C577B8DP'), 'MS Computer Science', 'master', 'Computer Science', 24, 3400000, 'USD', '[8, 1]', 3.2, 6.5, '2026-12-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621J7G0ASMQ2NBH074C', (SELECT id FROM institutions WHERE public_id = '01KYG81621SPVQE336C577B8DP'), 'MS Mechanical Engineering', 'master', 'Engineering', 24, 3300000, 'USD', '[8, 1]', 3.0, 6.5, '2026-12-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621NVBSYPGG1TJTN7CD', (SELECT id FROM institutions WHERE public_id = '01KYG81621BK0X0G2VRM60T147'), 'MSc Computer Science', 'master', 'Computer Science', 24, 4200000, 'CAD', '[9]', 3.3, 6.5, '2026-12-15', '2026-07-27T00:00:00Z'),
  ('01KYG8162188AH5D0E6J0PJQGJ', (SELECT id FROM institutions WHERE public_id = '01KYG81621BK0X0G2VRM60T147'), 'MEng Electrical Engineering', 'master', 'Engineering', 16, 3800000, 'CAD', '[9, 1]', 3.0, 6.5, '2027-01-31', '2026-07-27T00:00:00Z'),
  ('01KYG816219GX8SFNZV73KAXDZ', (SELECT id FROM institutions WHERE public_id = '01KYG81621FXF8WSQHFFDSVB5A'), 'MSc Computer Science', 'master', 'Computer Science', 24, 3000000, 'CAD', '[9, 1]', 3.2, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG816213BXC14M6E3G6RNCR', (SELECT id FROM institutions WHERE public_id = '01KYG81621FXF8WSQHFFDSVB5A'), 'MA Economics', 'master', 'Economics', 24, 2800000, 'CAD', '[9]', 3.2, 7.0, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621QQNXYJZ7MV21QD53', (SELECT id FROM institutions WHERE public_id = '01KYG816214CTBYYN33QEXVSNP'), 'Master of Information Technology', 'master', 'Computer Science', 24, 5000000, 'AUD', '[2, 7]', 3.0, 6.5, '2026-11-30', '2026-07-27T00:00:00Z'),
  ('01KYG81621H90V7NXH35AG5W6N', (SELECT id FROM institutions WHERE public_id = '01KYG816214CTBYYN33QEXVSNP'), 'Master of Public Health', 'master', 'Public Health', 24, 4500000, 'AUD', '[2, 7]', 3.0, 6.5, '2026-11-30', '2026-07-27T00:00:00Z'),
  ('01KYG81621JV8DNQ9APTQGR5TH', (SELECT id FROM institutions WHERE public_id = '01KYG81621JPW3VRD6C4MWNQ5K'), 'Master of Data Science', 'master', 'Data Science', 24, 4700000, 'AUD', '[2, 7]', 3.0, 6.5, '2026-12-31', '2026-07-27T00:00:00Z'),
  ('01KYG81621W0DAPD7RBQSW269W', (SELECT id FROM institutions WHERE public_id = '01KYG81621JPW3VRD6C4MWNQ5K'), 'Master of Engineering', 'master', 'Engineering', 24, 4800000, 'AUD', '[2, 7]', 3.0, 6.5, '2026-12-31', '2026-07-27T00:00:00Z'),
  ('01KYG81621VVY9E9QX5FDTX2EM', (SELECT id FROM institutions WHERE public_id = '01KYG81621RFGABC69JC8RMZB0'), 'Master of Computer Science', 'master', 'Computer Science', 18, 5200000, 'AUD', '[2, 8]', 3.2, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG816214CPSKP0JQ0NT2WZH', (SELECT id FROM institutions WHERE public_id = '01KYG81621RFGABC69JC8RMZB0'), 'Master of Commerce', 'master', 'Business Analytics', 18, 5000000, 'AUD', '[2, 8]', 3.0, 7.0, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621EGM3J6Z101VAD54N', (SELECT id FROM institutions WHERE public_id = '01KYG81621XB4H05ZHRRP4XNM6'), 'MSc Informatics', 'master', 'Computer Science', 24, 1200000, 'EUR', '[10, 4]', 3.0, 6.5, '2027-05-31', '2026-07-27T00:00:00Z'),
  ('01KYG81621S711ZAY0ZJX38TZP', (SELECT id FROM institutions WHERE public_id = '01KYG81621XB4H05ZHRRP4XNM6'), 'MSc Mechanical Engineering', 'master', 'Engineering', 24, 1200000, 'EUR', '[10]', 3.0, 6.5, '2027-05-31', '2026-07-27T00:00:00Z'),
  ('01KYG816218N95ND8S29ABMEM5', (SELECT id FROM institutions WHERE public_id = '01KYG81621KQXV8M7P8BKX0WGJ'), 'MSc Computer Science', 'master', 'Computer Science', 24, 0, 'EUR', '[10, 4]', 3.0, 6.5, '2027-03-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621VCYCQFA4J7CEN3MV', (SELECT id FROM institutions WHERE public_id = '01KYG81621KQXV8M7P8BKX0WGJ'), 'MSc Data Science', 'master', 'Data Science', 24, 0, 'EUR', '[10]', 3.0, 6.5, '2027-03-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621NW1TSK2N14CJCT4J', (SELECT id FROM institutions WHERE public_id = '01KYG81621RQJ4MWE76BBDZR99'), 'MSc Information Technology', 'master', 'Computer Science', 24, 300000, 'EUR', '[10]', 3.0, 6.5, '2027-04-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621J0P1FQMGQGW5JRYR', (SELECT id FROM institutions WHERE public_id = '01KYG81621RQJ4MWE76BBDZR99'), 'MSc Civil Engineering', 'master', 'Engineering', 24, 300000, 'EUR', '[10]', 3.0, 6.5, '2027-04-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621NX0WZTBTEG5SXX02', (SELECT id FROM institutions WHERE public_id = '01KYG81621Z82VJCK8A26JWDNP'), 'MSc Computer Science', 'master', 'Computer Science', 24, 2200000, 'EUR', '[9]', 3.2, 6.5, '2027-04-01', '2026-07-27T00:00:00Z'),
  ('01KYG816212GPQX6B5H7SFAM7Q', (SELECT id FROM institutions WHERE public_id = '01KYG81621Z82VJCK8A26JWDNP'), 'MSc Aerospace Engineering', 'master', 'Engineering', 24, 2200000, 'EUR', '[9]', 3.2, 6.5, '2027-04-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621Z387T2SHVBKB0EX8', (SELECT id FROM institutions WHERE public_id = '01KYG81621PJK9J89GNZ2KNXVY'), 'MSc Artificial Intelligence', 'master', 'Computer Science', 24, 1700000, 'EUR', '[9]', 3.2, 6.5, '2027-04-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621N15WEKCBSGFNYRZT', (SELECT id FROM institutions WHERE public_id = '01KYG81621PJK9J89GNZ2KNXVY'), 'MSc Economics', 'master', 'Economics', 12, 1600000, 'EUR', '[9]', 3.0, 6.5, '2027-04-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621Q2WT63HZ5TV5ZSG1', (SELECT id FROM institutions WHERE public_id = '01KYG81621F9NRT0GKJ6C2M0WV'), 'MSc Data Science and AI', 'master', 'Data Science', 24, 2100000, 'EUR', '[9, 2]', 3.0, 6.5, '2027-05-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621GQ1D76R21WR9DW0D', (SELECT id FROM institutions WHERE public_id = '01KYG81621F9NRT0GKJ6C2M0WV'), 'MSc Electrical Engineering', 'master', 'Engineering', 24, 2100000, 'EUR', '[9]', 3.0, 6.5, '2027-05-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621YFEDX8BJKVBQZ8JD', (SELECT id FROM institutions WHERE public_id = '01KYG81621HP1MJ3DR9V6PEH29'), 'MSc Computer Science', 'master', 'Computer Science', 24, 31000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621NX89HA3NR4C15CEB', (SELECT id FROM institutions WHERE public_id = '01KYG81621HP1MJ3DR9V6PEH29'), 'MSc Electrical Engineering', 'master', 'Engineering', 24, 31000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621QJV6KM6GTV13MBP0', (SELECT id FROM institutions WHERE public_id = '01KYG81621FGYTG3W24DH48B9Y'), 'MSc Data Science', 'master', 'Data Science', 24, 29000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621E645PQ42WAS4T8JK', (SELECT id FROM institutions WHERE public_id = '01KYG81621FGYTG3W24DH48B9Y'), 'MSc Economics', 'master', 'Economics', 12, 25000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG816211CGN1M5BZ2KXH2E8', (SELECT id FROM institutions WHERE public_id = '01KYG81621D6KZCTFXBPFXE2D3'), 'MSc Computer Science', 'master', 'Computer Science', 24, 28000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621ZS9D5YTSHVZQJJNJ', (SELECT id FROM institutions WHERE public_id = '01KYG81621D6KZCTFXBPFXE2D3'), 'MSc Mechanical Engineering', 'master', 'Engineering', 24, 28000000, 'SEK', '[8]', 3.0, 6.5, '2027-01-15', '2026-07-27T00:00:00Z'),
  ('01KYG81621HEZND649YMYP7KPC', (SELECT id FROM institutions WHERE public_id = '01KYG81621T9PX612A9QKJVA0J'), 'Master of Information Science', 'master', 'Computer Science', 24, 53580000, 'JPY', '[4, 10]', 3.2, 6.5, '2026-12-10', '2026-07-27T00:00:00Z'),
  ('01KYG81621RY5ZWEH0FNWHQV80', (SELECT id FROM institutions WHERE public_id = '01KYG81621T9PX612A9QKJVA0J'), 'Master of Engineering', 'master', 'Engineering', 24, 53580000, 'JPY', '[4, 10]', 3.0, 6.5, '2026-12-10', '2026-07-27T00:00:00Z'),
  ('01KYG81621M4D6QG1Q90ZJ85FZ', (SELECT id FROM institutions WHERE public_id = '01KYG81621WDECDN4N16VSM94Q'), 'Master of Informatics', 'master', 'Computer Science', 24, 53580000, 'JPY', '[4, 10]', 3.2, 6.5, '2027-01-20', '2026-07-27T00:00:00Z'),
  ('01KYG816213WVS5FX26KR0K8N1', (SELECT id FROM institutions WHERE public_id = '01KYG81621WDECDN4N16VSM94Q'), 'Master of Economics', 'master', 'Economics', 24, 53580000, 'JPY', '[4]', 3.0, 6.5, '2027-01-20', '2026-07-27T00:00:00Z'),
  ('01KYG81621DKTNTCEMEQPQYR0V', (SELECT id FROM institutions WHERE public_id = '01KYG81621SH366XK2FET8G2J1'), 'Master of Computer Science', 'master', 'Computer Science', 24, 63540000, 'JPY', '[4, 9]', 3.0, 6.5, '2026-12-01', '2026-07-27T00:00:00Z'),
  ('01KYG81621EKAEGH7RNG50HTJG', (SELECT id FROM institutions WHERE public_id = '01KYG81621SH366XK2FET8G2J1'), 'Master of Materials Science', 'master', 'Engineering', 24, 63540000, 'JPY', '[4]', 3.0, 6.5, '2026-12-01', '2026-07-27T00:00:00Z');

-- Programme search filters on country and orders by updated_at; without these
-- the widened catalogue turns every browse into a full scan and join.
CREATE INDEX IF NOT EXISTS idx_institutions_country ON institutions(country_code);
CREATE INDEX IF NOT EXISTS idx_programmes_institution ON programmes(institution_id);
CREATE INDEX IF NOT EXISTS idx_programmes_browse ON programmes(updated_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_programmes_level ON programmes(degree_level);
