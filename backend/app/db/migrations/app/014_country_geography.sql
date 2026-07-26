-- Adds the four columns `GET /destinations` and `GET /me/shortlist` need.
--
-- Why this migration exists: DestinationOut (app/models/destination.py)
-- requires lat, lng, note_en and note_bn, because the destinations globe in
-- the frontend places each country by coordinate and shows a one-line note on
-- hover. The original `countries` table (docs/database.md section 3.2) had no
-- such columns, so both endpoints raised rather than invent geography.
--
-- The coordinates below are the capital city of each country, rounded to four
-- decimal places. These are published reference values, not estimates, and
-- they carry no citation column because a capital's latitude is not a claim
-- about immigration policy. Nothing in the app treats them as advice.
--
-- The notes are deliberately factual and non-advisory. They name the visa
-- route and the responsible authority and nothing else. They do not state a
-- fee, a deadline, a processing time, or an eligibility rule, because every
-- such value in this system must come from a crawled snapshot with a citation
-- (docs/backend.md section 4), and a static seed cannot carry one.

ALTER TABLE countries ADD COLUMN lat REAL;
ALTER TABLE countries ADD COLUMN lng REAL;
ALTER TABLE countries ADD COLUMN note_en TEXT;
ALTER TABLE countries ADD COLUMN note_bn TEXT;

UPDATE countries SET
  lat = 51.5074, lng = -0.1278,
  note_en = 'Student route visas are decided by UK Visas and Immigration, after a licensed sponsor issues a Confirmation of Acceptance for Studies.',
  note_bn = 'শিক্ষার্থী রুটের ভিসা সিদ্ধান্ত নেয় ইউকে ভিসাস অ্যান্ড ইমিগ্রেশন, লাইসেন্সপ্রাপ্ত স্পনসর কনফার্মেশন অব অ্যাকসেপট্যান্স ফর স্টাডিজ দেওয়ার পর।'
WHERE code = 'uk';

UPDATE countries SET
  lat = 38.9072, lng = -77.0369,
  note_en = 'The F-1 student visa is issued by a United States embassy or consulate after the university sends a Form I-20 and the SEVIS fee is paid.',
  note_bn = 'বিশ্ববিদ্যালয় ফর্ম আই-২০ পাঠানোর এবং সেভিস ফি পরিশোধের পর যুক্তরাষ্ট্রের দূতাবাস বা কনস্যুলেট এফ-১ শিক্ষার্থী ভিসা দেয়।'
WHERE code = 'us';

UPDATE countries SET
  lat = 45.4215, lng = -75.6972,
  note_en = 'A study permit is decided by Immigration, Refugees and Citizenship Canada, and requires a letter of acceptance from a designated learning institution.',
  note_bn = 'স্টাডি পারমিটের সিদ্ধান্ত নেয় ইমিগ্রেশন, রেফিউজিস অ্যান্ড সিটিজেনশিপ কানাডা, এবং এর জন্য নির্ধারিত শিক্ষাপ্রতিষ্ঠানের গ্রহণপত্র লাগে।'
WHERE code = 'ca';

UPDATE countries SET
  lat = -35.2809, lng = 149.1300,
  note_en = 'The Subclass 500 student visa is decided by the Department of Home Affairs, and requires a Confirmation of Enrolment from a registered provider.',
  note_bn = 'সাবক্লাস ৫০০ শিক্ষার্থী ভিসার সিদ্ধান্ত নেয় ডিপার্টমেন্ট অব হোম অ্যাফেয়ার্স, এবং এর জন্য নিবন্ধিত প্রতিষ্ঠানের কনফার্মেশন অব এনরোলমেন্ট লাগে।'
WHERE code = 'au';

UPDATE countries SET
  lat = 52.5200, lng = 13.4050,
  note_en = 'A national visa for study is issued by the German mission abroad, and public universities in most states charge no tuition fee.',
  note_bn = 'পড়াশোনার জন্য জাতীয় ভিসা দেয় বিদেশে জার্মান মিশন, এবং বেশিরভাগ রাজ্যের সরকারি বিশ্ববিদ্যালয় কোনো টিউশন ফি নেয় না।'
WHERE code = 'de';

UPDATE countries SET
  lat = 52.3676, lng = 4.9041,
  note_en = 'The university applies for the entry visa and residence permit on the student behalf through the Immigration and Naturalisation Service.',
  note_bn = 'বিশ্ববিদ্যালয় শিক্ষার্থীর পক্ষে ইমিগ্রেশন অ্যান্ড ন্যাচারালাইজেশন সার্ভিসের মাধ্যমে প্রবেশ ভিসা ও রেসিডেন্স পারমিটের আবেদন করে।'
WHERE code = 'nl';

UPDATE countries SET
  lat = 59.3293, lng = 18.0686,
  note_en = 'A residence permit for studies is decided by the Swedish Migration Agency, and is applied for after the university confirms admission.',
  note_bn = 'পড়াশোনার জন্য রেসিডেন্স পারমিটের সিদ্ধান্ত নেয় সুইডিশ মাইগ্রেশন এজেন্সি, এবং বিশ্ববিদ্যালয় ভর্তি নিশ্চিত করার পর এর আবেদন করা হয়।'
WHERE code = 'se';

UPDATE countries SET
  lat = 35.6762, lng = 139.6503,
  note_en = 'A Certificate of Eligibility is obtained by the university from the Immigration Services Agency before the student applies for the visa.',
  note_bn = 'শিক্ষার্থী ভিসার আবেদন করার আগে বিশ্ববিদ্যালয় ইমিগ্রেশন সার্ভিসেস এজেন্সি থেকে সার্টিফিকেট অব এলিজিবিলিটি সংগ্রহ করে।'
WHERE code = 'jp';
