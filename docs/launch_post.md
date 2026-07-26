# Facebook launch post

Free for everyone until 31 July 2026. Written to the project's own style rules: short
sentences, no metaphors, no informal wording, every claim true of the deployed build.

---

## English (158 words)

**Digonto is free for every student until 31 July.**

Studying abroad should not require paying someone to read English for you.

Digonto answers your study abroad and visa questions in Bangla, and every answer
quotes the official page it came from, with the date. When no official source covers
your question, it says so instead of guessing.

It also watches 27 official embassy, university and scholarship portals. When a rule
changes, you are told which line changed.

You can build a timeline, check your documents before you submit them, find
scholarships, and practise your visa interview.

Your files stay on our own server. They are never sent to any outside company. Delete
your account and everything is erased within 30 days.

No fees, no commission, no advertising.

Thank you to Google for releasing Gemma, the open model Digonto runs on.

Try it: digonto.ahbab.dev
Tell us what to fix using the form at the bottom of the home page.

---

## বাংলা

**৩১ জুলাই পর্যন্ত দিগন্ত সব শিক্ষার্থীর জন্য সম্পূর্ণ বিনামূল্যে।**

বিদেশে পড়তে যাওয়ার জন্য ইংরেজি পড়িয়ে দেওয়ার লোক ভাড়া করতে হবে না।

দিগন্ত আপনার পড়াশোনা ও ভিসার প্রশ্নের উত্তর দেয় বাংলায়। প্রতিটি উত্তরের সঙ্গে থাকে সেই
সরকারি পাতার উদ্ধৃতি ও তারিখ। কোনো সরকারি সূত্রে উত্তর না থাকলে দিগন্ত অনুমান করে না, বলে
দেয় যে তথ্য নেই।

দিগন্ত ২৭টি সরকারি দূতাবাস, বিশ্ববিদ্যালয় ও বৃত্তির পোর্টাল পর্যবেক্ষণ করে। নিয়ম বদলালে কোন
লাইনটি বদলেছে তা আপনাকে জানানো হয়।

আপনি সময়রেখা তৈরি করতে পারেন, জমা দেওয়ার আগে কাগজপত্র যাচাই করতে পারেন, যোগ্য
বৃত্তি খুঁজতে পারেন, এবং ভিসা সাক্ষাৎকারের অভ্যাস করতে পারেন।

আপনার ফাইল আমাদের নিজের সার্ভারেই থাকে। কোনো বাইরের প্রতিষ্ঠানে পাঠানো হয় না।
অ্যাকাউন্ট মুছে দিলে ৩০ দিনের মধ্যে সব তথ্য মুছে যায়।

কোনো ফি নেই, কমিশন নেই, বিজ্ঞাপন নেই।

গুগলকে ধন্যবাদ, Gemma মুক্ত মডেলটি প্রকাশ করার জন্য, যার উপর দিগন্ত চলে।

দেখুন: digonto.ahbab.dev
কী ঠিক করতে হবে জানান: হোম পেজের নিচের ফর্মে।

---

## Notes on the wording

Every sentence maps to something the build actually does.

- "27 official portals" is the number a fresh deployment crawls, not the 31 the
  registry migration inserts. Three refuse automated clients and one moved; see
  `docs/database.md`.
- "every answer quotes the official page it came from, with the date" is the citation
  contract, and a citation naming a passage that was not retrieved is discarded.
- "it says so instead of guessing" is the refusal contract, enforced by the output
  schema rather than by prompt wording.
- "never sent to any outside company" is true because inference is self-hosted and the
  router refuses to send document content to the remote fallback.
- "erased within 30 days" is the deletion window in `019_account_deletion_window.sql`.
  The post does not claim "everything without exception", because two things do survive
  and both are listed in `docs/privacy.md`: events with the user id removed, and
  aggregate counts that name nobody.

Deliberately absent: any claim about accuracy rates, student numbers, or comparisons
against consultancies. None of those are measured yet, and the paper marks them as
targets rather than results.
