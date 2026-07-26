-- Shonchari's question bank, as production data.
--
-- `interview_bank` was created by 008_interview.sql and then never populated by
-- anything: not by a migration, and not even by `app/db/seed_demo.py`. So the
-- Interview Room answered every request with "No interview questions are available
-- for this country yet", in development and in production alike. The repository query
-- (`InterviewRepo.pick_questions`) was correct the whole time and had nothing to
-- select, which is the same failure the portal registry had before 015: a table with
-- a working query, a working UI, and no rows.
--
-- A migration rather than seed data, for the same reason 015 is a migration:
-- `seed_demo.py` does not run when `APP_ENV=production`, so seeding there would leave
-- the deployed product with the feature permanently dead.
--
-- `country_code IS NULL` means the question applies to every destination, and
-- `pick_questions` admits those alongside country-specific ones. Most questions belong
-- there: a visa officer asking why you chose this course is doing the same thing in
-- London and in Tokyo. Country rows exist only where the question turns on a rule
-- specific to that country.
--
-- `probes` is the part a student cannot get from a list of questions elsewhere: what
-- the officer is actually testing. Shonchari scores an answer against the probe, not
-- against a model answer, because there is no single right answer to "why this
-- university" and there is a definite thing being checked.
--
-- `difficulty` orders the session: 'opening' first, then 'standard', then 'pressure',
-- which is how a real interview escalates. `snapshot_id` is NULL throughout: these are
-- interview technique, not a claim about any official rule, so there is nothing to
-- cite and a fabricated citation would be worse than none.

INSERT INTO interview_bank (country_code, visa_type, text_en, text_bn, probes, difficulty, category) VALUES

-- ---------------------------------------------------------------- opening
(NULL, NULL,
 'Why did you choose this course?',
 'আপনি এই কোর্সটি কেন বেছে নিয়েছেন?',
 'Whether the course was chosen for a reason the applicant can state in their own words, or chosen by an agent. A rehearsed answer that does not connect to the applicant''s own background is the single most common credibility failure.',
 'opening', 'academic'),

(NULL, NULL,
 'Why this university, rather than another one offering the same course?',
 'একই কোর্স অন্য অনেক বিশ্ববিদ্যালয়ে থাকলেও আপনি এই বিশ্ববিদ্যালয়টি কেন বেছে নিলেন?',
 'Specific knowledge of the institution: a module, a supervisor, a facility. Naming rankings alone suggests the choice was made from a list handed over by somebody else.',
 'opening', 'academic'),

(NULL, NULL,
 'Who is paying for your studies?',
 'আপনার পড়াশোনার খরচ কে দিচ্ছেন?',
 'That the applicant knows their own funding arrangement. Someone who cannot name their sponsor or state the amount is describing a plan somebody else made.',
 'opening', 'finance'),

(NULL, NULL,
 'What is your highest qualification, and when did you finish it?',
 'আপনার সর্বোচ্চ শিক্ষাগত যোগ্যতা কী, এবং কখন শেষ করেছেন?',
 'Consistency with the transcripts on file. An unexplained gap between finishing and applying is a follow-up question, not a problem in itself.',
 'opening', 'academic'),

-- ---------------------------------------------------------------- standard
(NULL, NULL,
 'How does this course fit what you have studied and done so far?',
 'এই কোর্সটি আপনার এখন পর্যন্ত পড়াশোনা ও কাজের সঙ্গে কীভাবে মেলে?',
 'A continuous line from the applicant''s past to this course. A sharp change of field is allowed and often genuine, but it has to be explained rather than left for the officer to guess at.',
 'standard', 'academic'),

(NULL, NULL,
 'What will you do after you finish the course?',
 'কোর্স শেষ করার পরে আপনি কী করবেন?',
 'A plan specific enough to be checked. This is the intent question in disguise: an answer that avoids saying where the applicant will be is heard as an answer they do not want to give.',
 'standard', 'post_study'),

(NULL, NULL,
 'How much are your tuition fees and living costs for the first year?',
 'প্রথম বছরের টিউশন ফি ও জীবনযাত্রার খরচ কত?',
 'Whether the applicant knows their own numbers. Being wrong by a small margin is fine; not knowing the order of magnitude means somebody else is managing the money.',
 'standard', 'finance'),

(NULL, NULL,
 'What does your sponsor do for a living, and what do they earn?',
 'আপনার স্পনসর কী কাজ করেন, এবং তাঁর আয় কত?',
 'That the declared income plausibly supports the declared funds. An applicant who cannot describe their own family''s work is a strong signal the paperwork was assembled for them.',
 'standard', 'finance'),

(NULL, NULL,
 'Do you have family or relatives in the country you are applying to?',
 'আপনি যে দেশে আবেদন করছেন সেখানে আপনার পরিবার বা আত্মীয় আছে কি?',
 'Honesty above all. Having relatives there is not a refusal ground; concealing them and being found out is. Answer this one plainly.',
 'standard', 'ties'),

(NULL, NULL,
 'What ties you to Bangladesh, and what will you come back to?',
 'বাংলাদেশের সঙ্গে আপনার কী বন্ধন আছে, এবং আপনি কীসের কাছে ফিরে আসবেন?',
 'Concrete ties rather than sentiment: dependent family, property, a job to return to, a business. "I love my country" answers nothing that is being asked.',
 'standard', 'ties'),

(NULL, NULL,
 'Why are you studying abroad instead of in Bangladesh?',
 'বাংলাদেশে না পড়ে বিদেশে পড়ছেন কেন?',
 'That the applicant can name something this course offers that is genuinely unavailable at home. Answers that criticise Bangladeshi institutions in general read as rehearsed and are not what is being asked.',
 'standard', 'intent'),

(NULL, NULL,
 'Have you ever been refused a visa for any country?',
 'আপনি কি কখনো কোনো দেশের ভিসা প্রত্যাখ্যাত হয়েছেন?',
 'Disclosure. A previous refusal is recoverable and is routinely disclosed successfully; a concealed one that surfaces later is treated as deception and is far more damaging.',
 'standard', 'intent'),

-- ---------------------------------------------------------------- pressure
(NULL, NULL,
 'Your bank balance appeared only recently. Where did that money come from?',
 'আপনার ব্যাংক ব্যালান্স সম্প্রতি জমা হয়েছে। এই টাকা কোথা থেকে এলো?',
 'A traceable source for the funds. This is asked because borrowed money returned after the visa decision is a known pattern; a genuine recent deposit with a documented origin is not a problem.',
 'pressure', 'finance'),

(NULL, NULL,
 'This course costs several years of your family income. How is that a reasonable decision?',
 'এই কোর্সের খরচ আপনার পরিবারের কয়েক বছরের আয়ের সমান। এটি যুক্তিসঙ্গত সিদ্ধান্ত কীভাবে?',
 'Whether the applicant has thought about the return on the spending, rather than reciting the cost. This is a hard question asked deliberately, and it is a fair one.',
 'pressure', 'finance'),

(NULL, NULL,
 'What stops you from staying and working after your visa ends?',
 'ভিসার মেয়াদ শেষে থেকে গিয়ে কাজ করা থেকে আপনাকে কী আটকাবে?',
 'A calm, specific answer. This is the question the whole interview is built around. Getting defensive reads worse than the honest reply, which is usually a concrete plan and a reason to return.',
 'pressure', 'intent'),

(NULL, NULL,
 'Your statement of purpose does not read like the way you are speaking now. Who wrote it?',
 'আপনার স্টেটমেন্ট অব পারপাস আপনার এখনকার বলার ধরনের সঙ্গে মিলছে না। এটি কে লিখেছে?',
 'That the applicant can discuss their own written material unprompted. Help with language is ordinary; not recognising your own stated reasons is not.',
 'pressure', 'academic'),

(NULL, NULL,
 'You have a job here already. Why give it up for a course?',
 'আপনার এখানে চাকরি আছে। কোর্সের জন্য সেটি ছাড়ছেন কেন?',
 'That leaving employment is a considered step with a stated gain, not an escape. An applicant in work has stronger ties, so this question is an opportunity rather than a trap.',
 'pressure', 'intent'),

-- ---------------------------------------------------------------- country specific
('uk', 'student',
 'Your sponsor issued your Confirmation of Acceptance for Studies. What conditions were attached to it?',
 'আপনার স্পনসর CAS ইস্যু করেছে। এর সঙ্গে কী কী শর্ত জুড়ে দেওয়া হয়েছিল?',
 'That the applicant has read their own CAS. Conditions on it are the sponsor''s statement about the applicant, and not knowing them is treated as a credibility point in a UK interview.',
 'standard', 'academic'),

('uk', 'student',
 'How long must you hold the maintenance funds before you apply, and why does the date matter?',
 'আবেদনের আগে কত দিন ধরে টাকা ব্যাংকে রাখতে হয়, এবং তারিখটি কেন গুরুত্বপূর্ণ?',
 'Knowledge of the 28-day consecutive holding period and the 31-day window before applying. This is a rule an applicant is expected to know about their own application.',
 'standard', 'finance'),

('us', 'f1',
 'Why did you apply to this specific university in the United States?',
 'যুক্তরাষ্ট্রে ঠিক এই বিশ্ববিদ্যালয়েই আবেদন করলেন কেন?',
 'Non-immigrant intent plus a specific academic reason. United States interviews are short, so the first sentence carries most of the weight; lead with the reason, not with the ranking.',
 'opening', 'academic'),

('us', 'f1',
 'Do you intend to return to Bangladesh after your programme?',
 'প্রোগ্রাম শেষে আপনি কি বাংলাদেশে ফিরে আসার ইচ্ছা রাখেন?',
 'Section 214(b) requires the applicant to overcome the presumption of immigrant intent. The answer has to be direct and has to be supported by ties already stated, not asserted at the end.',
 'pressure', 'intent'),

('ca', 'study_permit',
 'How will this programme help your career when you return?',
 'ফিরে আসার পর এই প্রোগ্রামটি আপনার কর্মজীবনে কীভাবে সাহায্য করবে?',
 'A stated benefit connected to work the applicant can name. Canadian assessment weighs whether the study plan is reasonable for the applicant''s history and stage of career.',
 'standard', 'post_study'),

('au', 'student_500',
 'Explain why this course is a genuine step for you rather than a route to staying.',
 'এই কোর্সটি আপনার জন্য প্রকৃত পদক্ষেপ, থেকে যাওয়ার পথ নয়, তা ব্যাখ্যা করুন।',
 'The Genuine Student requirement, which Australia assesses explicitly. The answer should cover the applicant''s circumstances, the value of the course, and their intentions, in that order.',
 'pressure', 'intent'),

('de', 'student',
 'How will you cover your living costs, and what is in your blocked account?',
 'আপনার জীবনযাত্রার খরচ কীভাবে মেটাবেন, এবং আপনার ব্লকড অ্যাকাউন্টে কত আছে?',
 'Knowledge of the blocked account requirement and the monthly amount released from it. Germany treats this as a documentary matter, so the figure should match the paperwork exactly.',
 'standard', 'finance'),

('jp', 'student',
 'Who is your guarantor in Japan, and what is their relationship to you?',
 'জাপানে আপনার গ্যারান্টর কে, এবং তাঁর সঙ্গে আপনার সম্পর্ক কী?',
 'That the applicant knows the guarantor arrangement in their own application. The relationship, not just the name, is what is being checked.',
 'standard', 'finance');
