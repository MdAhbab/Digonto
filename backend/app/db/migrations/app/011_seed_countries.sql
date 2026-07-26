-- docs/database.md section 6 lists this as the seed migration for `countries`.
--
-- Judgement call on `code`: database.md's column comment says ISO-3166-1
-- alpha-2, which for the United Kingdom is formally 'GB'. But
-- docs/api_contract.md section 1 states the rule for exactly this kind of
-- conflict: "Where those two disagreed, the frontend won and the database
-- was shaped to serve it." The frontend and every example payload in the API
-- contract (Destinations.tsx's `Country.id`, `/ask`'s `country` field, the
-- `GET /destinations` sample response) use lowercase 'uk', never 'gb'. So
-- these codes are lowercase and use 'uk' rather than 'gb'; the other seven
-- happen to be their lowercased ISO-3166-1 alpha-2 codes anyway.
--
-- visa_types are the realistic, commonly used labels for each country's
-- student-route immigration status, kept short and snake_case so the API and
-- frontend can treat them as stable keys rather than display strings.

INSERT INTO countries (code, name_en, name_bn, visa_types, active, sort_order)
VALUES
  ('uk', 'United Kingdom', 'যুক্তরাজ্য',
   '["student","short_study","graduate"]', 1, 10),

  ('us', 'United States', 'যুক্তরাষ্ট্র',
   '["f1","j1","opt"]', 1, 20),

  ('ca', 'Canada', 'কানাডা',
   '["study_permit","pgwp"]', 1, 30),

  ('au', 'Australia', 'অস্ট্রেলিয়া',
   '["subclass_500","subclass_485"]', 1, 40),

  ('de', 'Germany', 'জার্মানি',
   '["national_visa","student_applicant"]', 1, 50),

  ('nl', 'Netherlands', 'নেদারল্যান্ডস',
   '["mvv","residence_permit"]', 1, 60),

  ('se', 'Sweden', 'সুইডেন',
   '["residence_permit_study"]', 1, 70),

  ('jp', 'Japan', 'জাপান',
   '["student","dependent"]', 1, 80)
ON CONFLICT (code) DO NOTHING;
