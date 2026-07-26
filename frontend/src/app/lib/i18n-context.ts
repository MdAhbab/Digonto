import { createContext, useContext } from "react";

export type Lang = "en" | "bn";

type Dict = Record<string, { en: string; bn: string }>;

/* Central translation dictionary. Bangla is a first-class script here. */
export const dict: Dict = {
  // Brand / global
  "brand.name": { en: "Digonto", bn: "দিগন্ত" },
  "brand.tagline": { en: "Your horizon, mapped and proven.", bn: "আপনার দিগন্ত, মানচিত্রিত ও প্রমাণিত।" },

  // Nav
  "nav.home": { en: "Home", bn: "শুরু" },
  "nav.planner": { en: "Journey Planner", bn: "যাত্রা পরিকল্পক" },
  "nav.ask": { en: "Ask Digonto", bn: "জিজ্ঞাসা" },
  "nav.vault": { en: "Document Vault", bn: "দলিল ভল্ট" },
  "nav.funding": { en: "Funding Studio", bn: "তহবিল স্টুডিও" },
  "nav.interview": { en: "Interview Room", bn: "সাক্ষাৎকার কক্ষ" },
  "nav.destinations": { en: "Destinations", bn: "গন্তব্য" },
  "nav.ledger": { en: "Truth Ledger", bn: "সত্য খতিয়ান" },
  "nav.security": { en: "Security & Ethics", bn: "নিরাপত্তা ও নীতি" },
  "nav.about": { en: "About", bn: "পরিচিতি" },
  "nav.signin": { en: "Sign in", bn: "প্রবেশ" },
  "nav.signout": { en: "Sign out", bn: "প্রস্থান" },
  "nav.menu": { en: "Menu", bn: "মেনু" },
  "nav.close": { en: "Close", bn: "বন্ধ" },
  "nav.gated": { en: "Sign in to use", bn: "ব্যবহারে প্রবেশ" },

  "cta.start": { en: "Begin your plan", bn: "পরিকল্পনা শুরু করুন" },
  "cta.explore": { en: "See how it works", bn: "কীভাবে কাজ করে দেখুন" },
  "common.free": { en: "Free, always", bn: "সর্বদা বিনামূল্যে" },
  "common.source": { en: "Source", bn: "উৎস" },
  "common.snapshot": { en: "Snapshot", bn: "স্ন্যাপশট" },
  "common.verified": { en: "Verified", bn: "যাচাইকৃত" },
  "common.viewsource": { en: "View source snapshot", bn: "উৎস স্ন্যাপশট দেখুন" },
  "common.back": { en: "Back", bn: "ফিরুন" },
  "common.loading": { en: "Loading…", bn: "লোড হচ্ছে…" },
  "common.retry": { en: "Try again", bn: "আবার চেষ্টা করুন" },
  "common.error": { en: "Something went wrong.", bn: "কিছু একটা সমস্যা হয়েছে।" },
  "common.empty": { en: "Nothing here yet.", bn: "এখনও কিছু নেই।" },
  "common.cancel": { en: "Cancel", bn: "বাতিল" },
  "common.save": { en: "Save", bn: "সংরক্ষণ" },
  "common.submit": { en: "Submit", bn: "জমা দিন" },
  "common.close": { en: "Close", bn: "বন্ধ" },
  "common.simulated": { en: "Simulated, demonstration only", bn: "অনুকরণ, শুধু প্রদর্শনের জন্য" },

  // Feedback form (POST /feedback). Open to signed-out students on purpose: the
  // most useful report about a product for people who struggle with official
  // English often comes from someone who never got as far as making an account.
  "feedback.eyebrow": { en: "Tell us", bn: "আমাদের বলুন" },
  "feedback.title": { en: "What did not work?", bn: "কী কাজ করেনি?" },
  "feedback.intro": {
    en: "Anything confusing, wrong, or missing. You do not need an account, and you do not need to leave your email.",
    bn: "যা কিছু অস্পষ্ট, ভুল বা অনুপস্থিত। অ্যাকাউন্ট লাগবে না, ইমেইলও দিতে হবে না।",
  },
  "feedback.kind.label": { en: "Kind", bn: "ধরন" },
  "feedback.kind.confusing": { en: "Confusing", bn: "অস্পষ্ট" },
  "feedback.kind.wrong": { en: "Wrong answer", bn: "ভুল উত্তর" },
  "feedback.kind.bug": { en: "Something broke", bn: "কিছু নষ্ট হয়েছে" },
  "feedback.kind.idea": { en: "Idea", bn: "প্রস্তাব" },
  "feedback.kind.praise": { en: "This helped", bn: "এটি কাজে লেগেছে" },
  "feedback.kind.other": { en: "Other", bn: "অন্য" },
  "feedback.message.label": { en: "Your message", bn: "আপনার বার্তা" },
  "feedback.message.placeholder": {
    en: "Write in Bangla or English, whichever is easier.",
    bn: "বাংলা বা ইংরেজি, যেটি সহজ সেটিতেই লিখুন।",
  },
  "feedback.email.label": { en: "Email, if you want a reply", bn: "উত্তর চাইলে ইমেইল" },
  "feedback.email.placeholder": { en: "Optional", bn: "ঐচ্ছিক" },
  "feedback.email.note": {
    en: "Leave this blank and your message stays unlinked to any address, even if you are signed in.",
    bn: "খালি রাখলে আপনার বার্তা কোনো ইমেইলের সঙ্গে যুক্ত থাকবে না, এমনকি আপনি প্রবেশ করা থাকলেও।",
  },
  "feedback.send": { en: "Send", bn: "পাঠান" },
  "feedback.sending": { en: "Sending", bn: "পাঠানো হচ্ছে" },
  "feedback.thanks": { en: "Received. Thank you.", bn: "পেয়েছি। ধন্যবাদ।" },
  "feedback.thanks.detail": {
    en: "A person reads every message. If you left an email, you will hear back.",
    bn: "প্রতিটি বার্তা একজন মানুষ পড়েন। ইমেইল দিলে উত্তর পাবেন।",
  },
  "feedback.again": { en: "Send another", bn: "আরেকটি পাঠান" },
  "feedback.error": { en: "Could not send that. Please try again.", bn: "পাঠানো যায়নি। আবার চেষ্টা করুন।" },

  // Scheduled account deletion (DELETE /me, POST /me/deletion/cancel).
  "del.banner.title": { en: "This account is scheduled for deletion", bn: "এই অ্যাকাউন্টটি মুছে ফেলার জন্য নির্ধারিত" },
  // The banner names the one exception. It used to say "everything is erased", which stopped
  // being true when the tombstone began keeping the name and address (migration 025), and a
  // student reading this line is at the exact moment the exception is worth knowing.
  "del.banner.body": {
    en: "Your documents, answers and profile are erased on {date}. Your name and email stay, so nobody else can claim your address. Nothing has been deleted yet, and you can stop it.",
    bn: "{date} তারিখে আপনার কাগজপত্র, উত্তর ও প্রোফাইল মুছে যাবে। নাম ও ইমেইল ঠিকানা রাখা হয়, যাতে অন্য কেউ আপনার ঠিকানা দাবি করতে না পারে। এখনো কিছুই মোছা হয়নি, আপনি এটি থামাতে পারেন।",
  },
  "del.banner.cancel": { en: "Keep my account", bn: "অ্যাকাউন্ট রাখুন" },
  "del.banner.cancelling": { en: "Cancelling", bn: "বাতিল করা হচ্ছে" },
  "del.cancelled": { en: "Your account will not be deleted.", bn: "আপনার অ্যাকাউন্ট মুছে ফেলা হবে না।" },

  // Profile page. GET/PATCH /me/profile existed from the first build and nothing in the
  // interface reached them, so the fields every agent reasons from could only be set by
  // the demo seed. Each hint says what the field is used for: "why does it want this" is
  // the question that stops people filling forms in.
  "nav.profile": { en: "Your profile", bn: "আপনার প্রোফাইল" },
  "profile.eyebrow": { en: "Your details", bn: "আপনার তথ্য" },
  "profile.title": { en: "What Digonto knows about you", bn: "দিগন্ত আপনার সম্পর্কে যা জানে" },
  "profile.sub": {
    en: "Every field is optional. The more you fill in, the more specific your answers, scholarship matches and interview practice become.",
    bn: "প্রতিটি ঘর ঐচ্ছিক। যত বেশি পূরণ করবেন, আপনার উত্তর, বৃত্তির মিল ও সাক্ষাৎকারের অভ্যাস তত বেশি নির্দিষ্ট হবে।",
  },
  "profile.unset": { en: "Not answered", bn: "দেওয়া হয়নি" },
  "profile.sec.you": { en: "You", bn: "আপনি" },
  "profile.sec.study": { en: "Your studies", bn: "আপনার পড়াশোনা" },
  "profile.sec.english": { en: "English test", bn: "ইংরেজি পরীক্ষা" },
  "profile.sec.plan": { en: "Your plan", bn: "আপনার পরিকল্পনা" },
  "profile.name": { en: "Name", bn: "নাম" },
  "profile.name.hint": { en: "How the interview room and your documents address you.", bn: "সাক্ষাৎকার কক্ষ ও আপনার নথিতে আপনাকে যেভাবে সম্বোধন করা হবে।" },
  "profile.district": { en: "Home district", bn: "নিজ জেলা" },
  "profile.district.hint": { en: "Used only for load-shedding aware reminders. Never shared.", bn: "কেবল লোডশেডিং বিবেচনায় মনে করানোর জন্য। কখনো শেয়ার করা হয় না।" },
  "profile.degree": { en: "Highest qualification", bn: "সর্বোচ্চ যোগ্যতা" },
  "profile.degree.hint": { en: "Decides which programmes you are eligible for.", bn: "আপনি কোন প্রোগ্রামের জন্য যোগ্য তা নির্ধারণ করে।" },
  "profile.field": { en: "Field of study", bn: "পড়াশোনার বিষয়" },
  "profile.field.hint": { en: "Used to match scholarships restricted to a subject.", bn: "বিষয়ভিত্তিক বৃত্তি মেলাতে ব্যবহৃত হয়।" },
  "profile.cgpa": { en: "CGPA", bn: "সিজিপিএ" },
  "profile.cgpa.hint": { en: "Checked against each programme's minimum.", bn: "প্রতিটি প্রোগ্রামের সর্বনিম্ন শর্তের সঙ্গে মেলানো হয়।" },
  "profile.scale": { en: "Out of", bn: "কত-এর মধ্যে" },
  "profile.scale.hint": { en: "4 or 5. A CGPA without its scale cannot be compared.", bn: "৪ বা ৫। স্কেল ছাড়া সিজিপিএ তুলনা করা যায় না।" },
  "profile.gradyear": { en: "Graduation year", bn: "স্নাতক শেষের বছর" },
  "profile.gradyear.hint": { en: "Some scholarships close a fixed number of years after graduating.", bn: "কিছু বৃত্তি স্নাতকের নির্দিষ্ট বছর পরে বন্ধ হয়ে যায়।" },
  "profile.gap": { en: "Study gap (years)", bn: "পড়াশোনায় বিরতি (বছর)" },
  "profile.gap.hint": { en: "A gap is not a problem, but the interview will ask about it.", bn: "বিরতি সমস্যা নয়, তবে সাক্ষাৎকারে এটি জিজ্ঞেস করা হবে।" },
  "profile.test": { en: "Test taken", bn: "যে পরীক্ষা দিয়েছেন" },
  "profile.test.hint": { en: "Leave as not answered if you have not taken one yet.", bn: "এখনো না দিলে খালি রাখুন।" },
  "profile.overall": { en: "Overall band", bn: "সামগ্রিক স্কোর" },
  "profile.overall.hint": { en: "Compared against the English requirement of each target.", bn: "প্রতিটি লক্ষ্যের ইংরেজি শর্তের সঙ্গে তুলনা করা হয়।" },
  "profile.listening": { en: "Listening", bn: "শ্রবণ" },
  "profile.reading": { en: "Reading", bn: "পঠন" },
  "profile.writing": { en: "Writing", bn: "লিখন" },
  "profile.speaking": { en: "Speaking", bn: "কথন" },
  "profile.sub.hint": {
    en: "Band scores matter: most programmes reject on the lowest band, not the overall.",
    bn: "আলাদা স্কোর গুরুত্বপূর্ণ: বেশিরভাগ প্রোগ্রাম সামগ্রিক নয়, সর্বনিম্ন স্কোর দেখে বাদ দেয়।",
  },
  "profile.budget": { en: "Budget (BDT)", bn: "বাজেট (টাকা)" },
  "profile.budget.hint": { en: "Filters programmes and shapes the funding gap in your budget.", bn: "প্রোগ্রাম ছাঁকে এবং আপনার বাজেটের ঘাটতি হিসাব করে।" },
  "profile.intake": { en: "Target intake", bn: "লক্ষ্য সেশন" },
  "profile.intake.hint": { en: "Anchors every date on your timeline.", bn: "আপনার সময়রেখার প্রতিটি তারিখ এর ভিত্তিতে ঠিক হয়।" },
  "profile.save": { en: "Save profile", bn: "প্রোফাইল সংরক্ষণ" },
  "profile.saving": { en: "Saving", bn: "সংরক্ষণ হচ্ছে" },
  "profile.saved": { en: "Saved", bn: "সংরক্ষিত হয়েছে" },
  "profile.privacy": {
    en: "These details stay on our own server and are used to make your answers specific to you. They are never sold or shared, and deleting your account erases all of them.",
    bn: "এই তথ্য আমাদের নিজের সার্ভারেই থাকে এবং আপনার উত্তর আপনার উপযোগী করতে ব্যবহৃত হয়। কখনো বিক্রি বা শেয়ার করা হয় না, এবং অ্যাকাউন্ট মুছলে সবই মুছে যায়।",
  },
  "profile.opt.bachelor": { en: "Bachelor's", bn: "স্নাতক" },
  "profile.opt.master": { en: "Master's", bn: "স্নাতকোত্তর" },
  "profile.opt.phd": { en: "PhD", bn: "পিএইচডি" },
  "profile.opt.diploma": { en: "Diploma", bn: "ডিপ্লোমা" },
  "profile.opt.ielts": { en: "IELTS", bn: "আইইএলটিএস" },
  "profile.opt.toefl": { en: "TOEFL", bn: "টофেল" },
  "profile.opt.duolingo": { en: "Duolingo English Test", bn: "ডুয়োলিঙ্গো ইংরেজি পরীক্ষা" },
  "profile.opt.pte": { en: "PTE Academic", bn: "পিটিই একাডেমিক" },
  "profile.opt.none": { en: "None yet", bn: "এখনো নয়" },

  // Theme / lang toggles
  "toggle.theme.light": { en: "Sheet Kagoj", bn: "শীট কাগজ" },
  "toggle.theme.dark": { en: "Rat-Digonto", bn: "রাত-দিগন্ত" },
  "toggle.lang": { en: "বাংলা", bn: "English" },

  // Landing hero
  "hero.eyebrow": { en: "Bangla-first Study Abroad & Visa Navigator", bn: "বাংলায় বিদেশে পড়াশোনা ও ভিসা পথপ্রদর্শক" },
  "hero.title": { en: "The distance from Dhaka to your degree, made plain.", bn: "ঢাকা থেকে আপনার ডিগ্রি পর্যন্ত পথ, স্পষ্ট করে।" },
  "hero.sub": { en: "Digonto plans the whole journey — programme, documents, funding, visa, interview — and proves every claim with a cited source snapshot.", bn: "দিগন্ত পুরো যাত্রা পরিকল্পনা করে — প্রোগ্রাম, দলিল, তহবিল, ভিসা, সাক্ষাৎকার — এবং প্রতিটি তথ্য উৎস স্ন্যাপশট দিয়ে প্রমাণ করে।" },

  // Principles strip (honest, non-fabricated)
  "principle.eyebrow": { en: "What we promise", bn: "আমাদের অঙ্গীকার" },
  "principle.title": { en: "The market is loud. Digonto is quiet, and it is honest.", bn: "বাজার কোলাহলপূর্ণ। দিগন্ত শান্ত, এবং সৎ।" },
  "principle.cited.t": { en: "Every claim is cited", bn: "প্রতিটি তথ্য উৎসসহ" },
  "principle.cited.d": { en: "No advice without a link back to the official portal it came from.", bn: "যে সরকারি পোর্টাল থেকে এসেছে তার লিঙ্ক ছাড়া কোনো পরামর্শ নয়।" },
  "principle.free.t": { en: "Free, and unbiased", bn: "বিনামূল্যে ও নিরপেক্ষ" },
  "principle.free.d": { en: "No commission, no referral fees, no agent steering your choices.", bn: "কোনো কমিশন নেই, রেফারাল ফি নেই, পছন্দে কোনো এজেন্টের প্রভাব নেই।" },
  "principle.bangla.t": { en: "Bangla, first", bn: "বাংলা, প্রথমে" },
  "principle.bangla.d": { en: "Built to be read in Bangla, not translated as an afterthought.", bn: "বাংলায় পড়ার জন্য তৈরি, পরে অনুবাদ করা নয়।" },

  // How it works
  "how.eyebrow": { en: "How Digonto works", bn: "দিগন্ত কীভাবে কাজ করে" },
  "how.title": { en: "One sheet, four stations.", bn: "একটি দলিল, চারটি স্টেশন।" },
  "how.crawl.t": { en: "Crawl", bn: "সংগ্রহ" },
  "how.crawl.d": { en: "We watch official university and embassy portals for every rule that governs your case.", bn: "আমরা প্রতিটি নিয়মের জন্য সরকারি বিশ্ববিদ্যালয় ও দূতাবাস পোর্টাল পর্যবেক্ষণ করি।" },
  "how.verify.t": { en: "Verify", bn: "যাচাই" },
  "how.verify.d": { en: "Each fact is captured as a timestamped snapshot, so nothing is hearsay.", bn: "প্রতিটি তথ্য সময়-চিহ্নিত স্ন্যাপশট হিসেবে সংরক্ষিত হয়, কোনো কিছুই গুজব নয়।" },
  "how.explain.t": { en: "Explain", bn: "ব্যাখ্যা" },
  "how.explain.d": { en: "We translate the fine print into plain Bangla and English you can act on.", bn: "আমরা জটিল শর্তগুলো সহজ বাংলা ও ইংরেজিতে অনুবাদ করি।" },
  "how.watch.t": { en: "Watch", bn: "পাহারা" },
  "how.watch.d": { en: "When a portal changes, your plan re-flows and you are told exactly what moved.", bn: "পোর্টাল বদলালে আপনার পরিকল্পনা পুনর্বিন্যস্ত হয় এবং কী বদলেছে তা জানানো হয়।" },

  // Landing: headline stats strip (GET /meta/stats)
  "stats.eyebrow": { en: "In numbers", bn: "সংখ্যায়" },
  "stats.portals": { en: "Portals watched", bn: "পর্যবেক্ষিত পোর্টাল" },
  "stats.snapshots": { en: "Snapshots archived", bn: "সংরক্ষিত স্ন্যাপশট" },
  "stats.questions": { en: "Questions answered", bn: "উত্তরিত প্রশ্ন" },

  // Truth ledger teaser
  "ledger.eyebrow": { en: "The Truth Ledger", bn: "সত্য খতিয়ান" },
  "ledger.claim": { en: "Every requirement Digonto shows you is stamped with the source it came from.", bn: "দিগন্ত যে শর্তই দেখায়, তার সাথে উৎসের সিলমোহর থাকে।" },
  "ledger.reveal": { en: "Every sentence Digonto tells you carries a stamp. Lift it, and the original portal snapshot is underneath.", bn: "দিগন্তের প্রতিটি বাক্যে একটি সিলমোহর থাকে। তুলুন, নিচে মূল পোর্টাল স্ন্যাপশট।" },
  "ledger.example": { en: "Illustrative example", bn: "উদাহরণস্বরূপ" },

  // Agents
  "agents.eyebrow": { en: "Four agents, one office", bn: "চার সহকারী, এক দপ্তর" },
  "agents.porter.t": { en: "Porter", bn: "পোর্টার" },
  "agents.porter.d": { en: "Plans the timeline and carries your case from station to station.", bn: "সময়রেখা তৈরি করে এবং আপনার কেস এক ধাপ থেকে পরের ধাপে নিয়ে যায়।" },
  "agents.prohori.t": { en: "Prohori", bn: "প্রহরী" },
  "agents.prohori.d": { en: "Guards your documents, audits them, and warns before anything expires.", bn: "আপনার দলিল পাহারা দেয়, নিরীক্ষা করে, মেয়াদ শেষের আগে সতর্ক করে।" },
  "agents.khoji.t": { en: "Khoji", bn: "খোঁজি" },
  "agents.khoji.d": { en: "Finds funding, checks solvency, and exposes unfair agent fees.", bn: "তহবিল খোঁজে, সচ্ছলতা যাচাই করে, অন্যায্য এজেন্ট ফি উন্মোচন করে।" },
  "agents.shonchari.t": { en: "Shonchari", bn: "সঞ্চারী" },
  "agents.shonchari.d": { en: "Rehearses your visa interview and reports where you must grow.", bn: "আপনার ভিসা সাক্ষাৎকারের মহড়া করায় এবং দুর্বলতা জানায়।" },

  // Footer
  "footer.product": { en: "Product", bn: "পণ্য" },
  "footer.company": { en: "Office", bn: "দপ্তর" },
  "footer.legal": { en: "Legal", bn: "আইনি" },
  "footer.sdg": { en: "Digonto supports UN SDG 4 — Quality Education — by making study-abroad guidance free and evidence-based for every Bangladeshi student.", bn: "দিগন্ত জাতিসংঘের SDG ৪ — মানসম্মত শিক্ষা — সমর্থন করে, প্রতিটি বাংলাদেশি শিক্ষার্থীর জন্য বিদেশে পড়ার নির্দেশনা বিনামূল্যে ও প্রমাণভিত্তিক করে।" },
  "footer.rights": { en: "A public-interest project. No commission, no referral fees.", bn: "একটি জনস্বার্থ প্রকল্প। কোনো কমিশন নেই, কোনো রেফারাল ফি নেই।" },

  // Planner
  "planner.title": { en: "The Timeline Reactor", bn: "সময়রেখা চুল্লি" },
  "planner.sub": { en: "Your entire journey as a living ledger. When one thing moves, everything downstream re-flows.", bn: "আপনার পুরো যাত্রা একটি জীবন্ত খতিয়ান। একটি বদলালে নিচের সবকিছু পুনর্বিন্যস্ত হয়।" },
  "planner.whatchanged": { en: "What changed", bn: "কী বদলেছে" },
  "planner.simulate": { en: "Simulate a portal change", bn: "একটি পোর্টাল পরিবর্তন অনুকরণ করুন" },
  "planner.done": { en: "Done", bn: "সম্পন্ন" },
  "planner.active": { en: "In progress", bn: "চলমান" },
  "planner.upcoming": { en: "Upcoming", bn: "আসন্ন" },
  "planner.blocked": { en: "Blocked", bn: "বাধাগ্রস্ত" },
  "planner.loaderror": { en: "Could not load your timeline.", bn: "আপনার সময়রেখা লোড করা যায়নি।" },
  "planner.simulating": { en: "Simulating…", bn: "অনুকরণ হচ্ছে…" },
  "planner.target.label": { en: "Planning for", bn: "যার জন্য পরিকল্পনা" },
  "planner.target.none": {
    en: "No programme is on your plan yet. Choose a destination, then track a programme — the timeline anchors on its deadline.",
    bn: "আপনার পরিকল্পনায় এখনও কোনো প্রোগ্রাম নেই। একটি গন্তব্য বাছুন, তারপর একটি প্রোগ্রাম অনুসরণ করুন — সময়রেখা তার সময়সীমা ধরে সাজানো হবে।",
  },
  "planner.target.choose": { en: "Choose a destination", bn: "গন্তব্য বাছুন" },
  "planner.target.generic": {
    en: "Showing a general timeline. Track a programme to anchor it on a real deadline.",
    bn: "একটি সাধারণ সময়রেখা দেখানো হচ্ছে। বাস্তব সময়সীমা ধরে সাজাতে একটি প্রোগ্রাম অনুসরণ করুন।",
  },
  "planner.step.complete": { en: "Mark done", bn: "সম্পন্ন চিহ্নিত করুন" },
  "planner.step.reopen": { en: "Reopen", bn: "পুনরায় খুলুন" },
  "planner.step.saving": { en: "Saving…", bn: "সংরক্ষণ হচ্ছে…" },
  "planner.step.due": { en: "Due", bn: "সময়সীমা" },
  "planner.regenerate": { en: "Rebuild timeline", bn: "সময়রেখা পুনর্গঠন" },
  "planner.regenerating": { en: "Rebuilding…", bn: "পুনর্গঠন হচ্ছে…" },
  "planner.regenerate.note": {
    en: "Dates are recomputed from your target's deadline. Steps you have completed stay completed.",
    bn: "আপনার লক্ষ্যের সময়সীমা থেকে তারিখ নতুন করে হিসাব হয়। সম্পন্ন ধাপগুলো সম্পন্নই থাকে।",
  },
  "planner.step.source": { en: "Source", bn: "উৎস" },
  "planner.drawer.title": { en: "Change log", bn: "পরিবর্তন তালিকা" },
  "planner.drawer.empty": { en: "No changes yet. Simulate one to see the plan re-flow.", bn: "এখনও কোনো পরিবর্তন নেই। পরিকল্পনা পুনর্বিন্যাস দেখতে একটি অনুকরণ করুন।" },

  // Ask
  "ask.title": { en: "Ask Digonto", bn: "দিগন্তকে জিজ্ঞাসা করুন" },
  "ask.sub": { en: "Answers read like counsel, not chat. Every claim is footnoted to a portal snapshot.", bn: "উত্তর পড়ে মনে হবে পরামর্শ, চ্যাট নয়। প্রতিটি তথ্যের পাদটীকা পোর্টাল স্ন্যাপশটে।" },
  "ask.placeholder": { en: "Ask about a programme, deadline, fee, or requirement…", bn: "প্রোগ্রাম, সময়সীমা, ফি বা শর্ত সম্পর্কে জিজ্ঞাসা করুন…" },
  "ask.send": { en: "Ask", bn: "জিজ্ঞাসা" },
  "ask.you": { en: "You asked", bn: "আপনি জিজ্ঞাসা করেছেন" },
  "ask.refusal.title": { en: "Not yet on record", bn: "এখনও নথিভুক্ত নয়" },
  "ask.refusal.body": { en: "Digonto will not guess. This detail is not yet published on an official portal. We have set a watch and will notify you the moment it appears.", bn: "দিগন্ত অনুমান করবে না। এই তথ্য এখনও কোনো সরকারি পোর্টালে প্রকাশিত নয়। আমরা পাহারা বসিয়েছি এবং প্রকাশ হওয়ামাত্র জানাব।" },
  "ask.watching": { en: "We watch the official portals and will notify you when this is published", bn: "আমরা সরকারি পোর্টাল পর্যবেক্ষণ করছি এবং প্রকাশ হলে জানাব" },

  // Truth ledger side sheet / page
  "sheet.title": { en: "Source snapshot", bn: "উৎস স্ন্যাপশট" },
  "sheet.captured": { en: "Captured", bn: "সংগৃহীত" },
  "sheet.portal": { en: "Portal", bn: "পোর্টাল" },
  "sheet.quoted": { en: "Quoted span", bn: "উদ্ধৃত অংশ" },
  "ledgerpage.title": { en: "Truth Ledger", bn: "সত্য খতিয়ান" },
  "ledgerpage.sub": { en: "Verify any claim Digonto has ever made. Paste a snapshot ID.", bn: "দিগন্তের যেকোনো তথ্য যাচাই করুন। একটি স্ন্যাপশট আইডি দিন।" },
  "ledgerpage.verify": { en: "Verify snapshot", bn: "স্ন্যাপশট যাচাই" },
  "ledgerpage.placeholder": { en: "e.g. EXAMPLE-2026-DEMO", bn: "যেমন EXAMPLE-2026-DEMO" },

  // Vault
  "vault.title": { en: "Prohori's Desk", bn: "প্রহরীর ডেস্ক" },
  "vault.sub": { en: "Your documents, guarded and audited. Encrypted at rest, always.", bn: "আপনার দলিল, পাহারায় ও নিরীক্ষায়। বিশ্রামে সর্বদা এনক্রিপ্টেড।" },
  "vault.drop": { en: "Drag a document to the desk", bn: "ডেস্কে একটি দলিল টেনে আনুন" },
  "vault.encrypted": { en: "Encrypted at rest", bn: "বিশ্রামে এনক্রিপ্টেড" },
  "vault.audit": { en: "Prohori's audit", bn: "প্রহরীর নিরীক্ষা" },
  "vault.expires": { en: "Expires in", bn: "মেয়াদ শেষ" },
  "vault.expired": { en: "Expired", bn: "মেয়াদ উত্তীর্ণ" },
  "vault.finding": { en: "Finding", bn: "পর্যবেক্ষণ" },
  "vault.action": { en: "Recommended action", bn: "প্রস্তাবিত পদক্ষেপ" },

  // Funding
  "funding.title": { en: "Khoji's Ledger", bn: "খোঁজির খতিয়ান" },
  "funding.sub": { en: "Scholarships as a broadsheet, solvency as a threshold, agent fees under a lamp.", bn: "বৃত্তি একটি ব্রডশিট, সচ্ছলতা একটি সীমারেখা, এজেন্ট ফি বাতির নিচে।" },
  "funding.budget": { en: "Budget composition", bn: "বাজেট গঠন" },
  "funding.threshold": { en: "Solvency requirement", bn: "সচ্ছলতার শর্ত" },
  "funding.scholarships": { en: "Scholarship matches", bn: "মানানসই বৃত্তি" },
  "funding.feecheck": { en: "Agent Fee Reality Check", bn: "এজেন্ট ফি বাস্তবতা যাচাই" },
  "funding.quoted": { en: "Quoted by agent", bn: "এজেন্টের উদ্ধৃত" },
  "funding.fair": { en: "Fair itemised cost", bn: "ন্যায্য খাতওয়ারি খরচ" },
  "funding.col.name": { en: "Scholarship", bn: "বৃত্তি" },
  "funding.col.country": { en: "Country", bn: "দেশ" },
  // "Award", not "Coverage": the column shows what the scholarship is worth in money,
  // and a header reading "Coverage" is what invited a percent sign onto a money value.
  "funding.col.amount": { en: "Award", bn: "অনুদান" },
  "funding.col.deadline": { en: "Deadline", bn: "সময়সীমা" },
  "funding.add": { en: "Add funding source", bn: "তহবিল উৎস যোগ করুন" },

  // Interview
  "interview.title": { en: "Shonchari", bn: "সঞ্চারী" },
  "interview.sub": { en: "A quiet room. One question at a time. A recorded answer, then an honest report.", bn: "একটি শান্ত কক্ষ। একবারে একটি প্রশ্ন। রেকর্ড করা উত্তর, তারপর সৎ প্রতিবেদন।" },
  "interview.start": { en: "Begin session", bn: "মহড়া শুরু" },
  "interview.record": { en: "Record answer", bn: "উত্তর রেকর্ড" },
  "interview.stop": { en: "Stop", bn: "থামান" },
  "interview.next": { en: "Next question", bn: "পরবর্তী প্রশ্ন" },
  "interview.report": { en: "Weakness report", bn: "দুর্বলতা প্রতিবেদন" },
  "interview.listening": { en: "Awaiting answer...", bn: "উত্তরের অপেক্ষায়..." },
  "interview.thinking": { en: "Thinking", bn: "ভাবছি" },
  "interview.speaking": { en: "Speaking", bn: "বলছি" },

  // Destinations
  "dest.title": { en: "Choose a destination", bn: "গন্তব্য নির্বাচন করুন" },
  "dest.sub": { en: "Route arcs are drawn only for your shortlist. The globe stays quiet otherwise.", bn: "শুধু আপনার সংক্ষিপ্ত তালিকার জন্য রুট আঁকা হয়। অন্যথায় গ্লোব শান্ত থাকে।" },
  "dest.shortlist": { en: "Your shortlist", bn: "আপনার তালিকা" },
  "dest.add": { en: "Add to shortlist", bn: "তালিকায় যোগ" },
  "dest.remove": { en: "Remove", bn: "সরান" },
  "dest.signin.prompt": {
    en: "Sign in to save countries to your shortlist.",
    bn: "আপনার সংক্ষিপ্ত তালিকায় দেশ রাখতে সাইন ইন করুন।",
  },
  "dest.signin.action": { en: "Sign in", bn: "সাইন ইন" },

  // Destinations — journey context and programme browse
  "dest.programmes.count": { en: "programmes", bn: "প্রোগ্রাম" },
  "dest.scholarships.count": { en: "scholarships", bn: "বৃত্তি" },
  "dest.solvency.label": { en: "Bank balance required", bn: "প্রয়োজনীয় ব্যাংক ব্যালেন্স" },
  "dest.solvency.hold": { en: "held for {days} days", bn: "{days} দিন ধরে রাখতে হবে" },
  "dest.solvency.provisional": { en: "Provisional", bn: "প্রাথমিক" },
  "dest.solvency.provisional.why": {
    en: "Seeded from published guidance. Not yet confirmed against a snapshot of the official page.",
    bn: "প্রকাশিত নির্দেশিকা থেকে নেওয়া। সরকারি পাতার সংরক্ষিত অনুলিপি মিলিয়ে এখনও নিশ্চিত করা হয়নি।",
  },
  "dest.solvency.verified": { en: "Verified against snapshot", bn: "সংরক্ষিত অনুলিপি মিলিয়ে যাচাই করা" },
  "dest.solvency.source": { en: "Official source", bn: "সরকারি উৎস" },
  "dest.programmes.show": { en: "View programmes", bn: "প্রোগ্রাম দেখুন" },
  "dest.programmes.hide": { en: "Hide programmes", bn: "প্রোগ্রাম লুকান" },
  "dest.programmes.empty": {
    en: "No programmes are catalogued for this country yet.",
    bn: "এই দেশের জন্য এখনও কোনো প্রোগ্রাম তালিকাভুক্ত হয়নি।",
  },
  "dest.programmes.error": {
    en: "Could not load programmes for this country.",
    bn: "এই দেশের প্রোগ্রাম লোড করা যায়নি।",
  },
  "dest.programmes.signin": {
    en: "Sign in to browse programmes and start a plan.",
    bn: "প্রোগ্রাম দেখতে ও পরিকল্পনা শুরু করতে সাইন ইন করুন।",
  },
  "dest.prog.tuition": { en: "Tuition / year", bn: "টিউশন / বছর" },
  "dest.prog.duration": { en: "Duration", bn: "সময়কাল" },
  "dest.prog.months": { en: "months", bn: "মাস" },
  "dest.prog.deadline": { en: "Deadline", bn: "সময়সীমা" },
  "dest.prog.mincgpa": { en: "Min CGPA", bn: "ন্যূনতম সিজিপিএ" },
  "dest.prog.minenglish": { en: "Min IELTS", bn: "ন্যূনতম আইইএলটিএস" },
  "dest.prog.notuition": { en: "No tuition fee", bn: "টিউশন ফি নেই" },
  "dest.prog.track": { en: "Track this programme", bn: "এই প্রোগ্রাম অনুসরণ করুন" },
  "dest.prog.tracking": { en: "Adding…", bn: "যোগ করা হচ্ছে…" },
  "dest.prog.tracked": { en: "Tracked", bn: "অনুসরণ করা হচ্ছে" },
  "dest.prog.tracked.note": {
    en: "Added to your plan. The timeline now anchors on this deadline, and the Funding Studio prices this programme.",
    bn: "আপনার পরিকল্পনায় যোগ হয়েছে। সময়রেখা এখন এই সময়সীমা ধরে সাজানো হবে, এবং ফান্ডিং স্টুডিও এই প্রোগ্রামের খরচ হিসাব করবে।",
  },
  "dest.prog.duplicate": {
    en: "That programme is already on your plan.",
    bn: "এই প্রোগ্রামটি ইতিমধ্যেই আপনার পরিকল্পনায় আছে।",
  },
  "dest.prog.goplan": { en: "Open the Journey Planner", bn: "যাত্রা পরিকল্পনা খুলুন" },
  "dest.prog.gofunding": { en: "Open the Funding Studio", bn: "ফান্ডিং স্টুডিও খুলুন" },

  // Security
  "sec.title": { en: "Security & Ethics", bn: "নিরাপত্তা ও নীতি" },
  "sec.sub": { en: "Plain-language commitments, and the threat model we design against.", bn: "সহজ ভাষায় অঙ্গীকার, এবং আমরা যে ঝুঁকি-মডেলের বিরুদ্ধে নকশা করি।" },
  "sec.threat": { en: "Threat model", bn: "ঝুঁকি মডেল" },

  // About
  "about.title": { en: "About Digonto", bn: "দিগন্ত সম্পর্কে" },
  "about.sub": { en: "A public-interest tool for a private decision.", bn: "ব্যক্তিগত সিদ্ধান্তের জন্য একটি জনস্বার্থ যন্ত্র।" },

  // Auth
  "auth.title": { en: "Enter Digonto", bn: "দিগন্তে প্রবেশ" },
  "auth.sub": { en: "Sign in with your email and password, or create a new account.", bn: "ইমেইল ও পাসওয়ার্ড দিয়ে সাইন ইন করুন, অথবা নতুন অ্যাকাউন্ট তৈরি করুন।" },
  "auth.email": { en: "Email address", bn: "ইমেইল ঠিকানা" },
  "auth.password": { en: "Password", bn: "পাসওয়ার্ড" },
  "auth.displayname": { en: "Full name", bn: "পুরো নাম" },
  "auth.mode.signin": { en: "Sign in", bn: "সাইন ইন" },
  "auth.mode.signup": { en: "Create account", bn: "অ্যাকাউন্ট তৈরি করুন" },
  "auth.submit.signin": { en: "Sign in", bn: "সাইন ইন করুন" },
  "auth.submit.signup": { en: "Create account", bn: "অ্যাকাউন্ট তৈরি করুন" },
  "auth.switch.tosignup": { en: "New to Digonto? Create an account", bn: "দিগন্তে নতুন? অ্যাকাউন্ট তৈরি করুন" },
  "auth.switch.tosignin": { en: "Already have an account? Sign in", bn: "আগে থেকেই অ্যাকাউন্ট আছে? সাইন ইন করুন" },
  "auth.error.email": { en: "Enter a valid email address.", bn: "সঠিক ইমেইল ঠিকানা দিন।" },
  "auth.error.password": { en: "Password must be at least 8 characters.", bn: "পাসওয়ার্ডে অন্তত ৮টি অক্ষর থাকতে হবে।" },
  "auth.error.displayname": { en: "Enter your name.", bn: "আপনার নাম দিন।" },
  "auth.loading.signin": { en: "Signing in…", bn: "সাইন ইন হচ্ছে…" },
  "auth.loading.signup": { en: "Creating account…", bn: "অ্যাকাউন্ট তৈরি হচ্ছে…" },

  // Offline
  "offline.status": { en: "Load-Shedding Mode — showing your cached plan. Actions are queued and will sync when the line returns.", bn: "লোড-শেডিং মোড — আপনার সংরক্ষিত পরিকল্পনা দেখানো হচ্ছে। সংযোগ ফিরলে পদক্ষেপগুলো সিঙ্ক হবে।" },
  "offline.toggle": { en: "Toggle offline preview", bn: "অফলাইন প্রিভিউ" },

  // 404
  "nf.title": { en: "This page was torn off.", bn: "এই পৃষ্ঠাটি ছিঁড়ে গেছে।" },
  "nf.sub": { en: "Like the stub of a boarding pass, half of this is missing.", bn: "বোর্ডিং পাসের অর্ধেকের মতো, এর একটি অংশ নেই।" },
  "nf.home": { en: "Return to the horizon", bn: "দিগন্তে ফিরুন" },

  // Moderator console
  "nav.moderator": { en: "Moderator", bn: "মডারেটর" },
  "mod.title": { en: "Moderator Console", bn: "মডারেটর কনসোল" },
  "mod.sub": { en: "The human in the loop. No document contents are ever shown here.", bn: "মানবিক তদারকি স্তর। এখানে কোনো নথির বিষয়বস্তু কখনো দেখানো হয় না।" },
  "mod.tab.overview": { en: "Overview", bn: "সারসংক্ষেপ" },
  "mod.tab.changes": { en: "Change review", bn: "পরিবর্তন পর্যালোচনা" },
  "mod.tab.answers": { en: "Answers", bn: "উত্তর" },
  "mod.tab.refusals": { en: "Refusal clusters", bn: "প্রত্যাখ্যান গুচ্ছ" },
  "mod.tab.scholarships": { en: "Scholarships", bn: "বৃত্তি" },
  "mod.tab.users": { en: "Users", bn: "ব্যবহারকারী" },
  "mod.tab.adapters": { en: "Adapters", bn: "অ্যাডাপ্টার" },
  "mod.overview.pending_changes": { en: "Pending changes", bn: "মুলতুবি পরিবর্তন" },
  "mod.overview.escalated_answers": { en: "Escalated answers", bn: "উর্ধ্বতনে পাঠানো উত্তর" },
  "mod.overview.unverified_scholarships": { en: "Unverified scholarships", bn: "অযাচাইকৃত বৃত্তি" },
  "mod.overview.silent_portals": { en: "Silent portals (48h+)", bn: "নীরব পোর্টাল (৪৮ ঘণ্টা+)" },
  "mod.overview.dead_letters": { en: "Dead letters", bn: "অবিতরণকৃত বার্তা" },
  "mod.overview.adapters_awaiting": { en: "Adapters awaiting promotion", bn: "উন্নীত হওয়ার অপেক্ষায় অ্যাডাপ্টার" },
  "mod.overview.new_users": { en: "New users today", bn: "আজকের নতুন ব্যবহারকারী" },
  "mod.changes.approve": { en: "Approve", bn: "অনুমোদন" },
  "mod.changes.reclassify": { en: "Reclassify", bn: "পুনঃশ্রেণীকরণ" },
  "mod.changes.discard": { en: "Discard", bn: "বাতিল" },
  "mod.changes.confidence": { en: "Confidence", bn: "আস্থা" },
  "mod.answers.verify": { en: "Verify", bn: "যাচাই" },
  "mod.answers.correct": { en: "Correct", bn: "সংশোধন" },
  "mod.refusals.addportal": { en: "Add portal", bn: "পোর্টাল যোগ করুন" },
  "mod.scholarships.verify": { en: "Mark verified", bn: "যাচাইকৃত হিসেবে চিহ্নিত করুন" },
  "mod.scholarships.reject": { en: "Mark unverified", bn: "অযাচাইকৃত হিসেবে চিহ্নিত করুন" },
  "mod.users.suspend": { en: "Suspend", bn: "স্থগিত" },
  "mod.users.ban": { en: "Ban", bn: "নিষিদ্ধ" },
  "mod.users.reinstate": { en: "Reinstate", bn: "পুনর্বহাল" },
  "mod.reason.en": { en: "Reason (English)", bn: "কারণ (ইংরেজি)" },
  "mod.reason.bn": { en: "Reason (Bangla)", bn: "কারণ (বাংলা)" },
  "mod.adapters.promote": { en: "Promote", bn: "উন্নীত করুন" },
  "mod.adapters.rollback": { en: "Rollback", bn: "প্রত্যাবর্তন" },
  "mod.forbidden": { en: "This console is only open to moderators.", bn: "এই কনসোল শুধুমাত্র মডারেটরদের জন্য উন্মুক্ত।" },
  "mod.empty": { en: "Nothing pending.", bn: "মুলতুবি কিছু নেই।" },
  "mod.loaderror": { en: "Could not load this list.", bn: "এই তালিকাটি লোড করা যায়নি।" },
  "mod.category": { en: "Category", bn: "শ্রেণী" },
  "mod.reason": { en: "Reason", bn: "কারণ" },
  "mod.notify": { en: "Notify affected students", bn: "প্রভাবিত শিক্ষার্থীদের জানান" },
  "mod.filter": { en: "Filter", bn: "ফিল্টার" },
  "mod.filter.downvoted": { en: "Downvoted", bn: "নেতিবাচক রেটিং" },
  "mod.filter.escalated": { en: "Escalated", bn: "উর্ধ্বতনে পাঠানো" },
  "mod.filter.low_confidence": { en: "Low confidence", bn: "কম আস্থা" },
  "mod.correct.en": { en: "Correction (English)", bn: "সংশোধন (ইংরেজি)" },
  "mod.correct.bn": { en: "Correction (Bangla)", bn: "সংশোধন (বাংলা)" },
  "mod.correct.note": { en: "Note (optional)", bn: "মন্তব্য (ঐচ্ছিক)" },
  "mod.addportal.url": { en: "Portal URL", bn: "পোর্টাল ইউআরএল" },
  "mod.addportal.kind": { en: "Portal kind", bn: "পোর্টালের ধরন" },
  "mod.addportal.country": { en: "Country (optional)", bn: "দেশ (ঐচ্ছিক)" },
  "mod.until": { en: "Suspended until", bn: "যতদিন স্থগিত" },
  "mod.note": { en: "Note (optional)", bn: "মন্তব্য (ঐচ্ছিক)" },
  "mod.search.placeholder": { en: "Search by email or name", bn: "ইমেইল বা নাম দিয়ে খুঁজুন" },
  "mod.adapters.status": { en: "Status", bn: "অবস্থা" },
  "mod.confirm": { en: "Confirm", bn: "নিশ্চিত করুন" },

  // Ask: history, streaming, feedback
  "ask.history.loading": { en: "Loading your past questions…", bn: "আপনার আগের প্রশ্ন লোড হচ্ছে…" },
  "ask.error": { en: "Could not get an answer. Please try again.", bn: "উত্তর পাওয়া যায়নি। আবার চেষ্টা করুন।" },
  "ask.sending": { en: "Thinking…", bn: "ভাবছি…" },

  // Vault: upload / states
  "vault.uploading": { en: "Uploading…", bn: "আপলোড হচ্ছে…" },
  "vault.scanning": { en: "Scanning…", bn: "স্ক্যান হচ্ছে…" },
  "vault.empty": { en: "No documents yet. Drop one above to begin.", bn: "এখনও কোনো নথি নেই। শুরু করতে উপরে একটি টেনে আনুন।" },
  "vault.selectkind": { en: "Document type", bn: "নথির ধরন" },

  // Funding
  "funding.sortby": { en: "Sort", bn: "সাজান" },
  "funding.eligible": { en: "Eligible", bn: "যোগ্য" },
  "funding.unverified": { en: "Unverified", bn: "অযাচাইকৃত" },
  "funding.feecheck.quotedlabel": { en: "Quoted amount (BDT)", bn: "উদ্ধৃত পরিমাণ (টাকা)" },
  "funding.feecheck.run": { en: "Run the check", bn: "যাচাই চালান" },
  "funding.notarget": { en: "Add a target programme in your plan to see your budget composition.", bn: "বাজেট গঠন দেখতে আপনার পরিকল্পনায় একটি লক্ষ্য প্রোগ্রাম যোগ করুন।" },
  "funding.addsource.kind": { en: "Source type", bn: "উৎসের ধরন" },
  "funding.addsource.amount": { en: "Amount (BDT)", bn: "পরিমাণ (টাকা)" },
  "funding.addsource.submit": { en: "Add", bn: "যোগ করুন" },
  "funding.loaderror": { en: "Could not load funding data.", bn: "তহবিলের তথ্য লোড করা যায়নি।" },
  "funding.empty": { en: "No scholarship matches yet.", bn: "এখনও কোনো মানানসই বৃত্তি নেই।" },
  "funding.remove": { en: "Remove", bn: "সরান" },

  // Interview
  "interview.connecting": { en: "Connecting…", bn: "সংযুক্ত হচ্ছে…" },

  // Resuming an interview that was left in progress. The server refuses a second session
  // while one is active, and this page used to only ever ask for a new one, so a dropped
  // connection left the room unusable with no way out. These are that way out.
  "interview.checking": { en: "Checking…", bn: "দেখা হচ্ছে…" },
  "interview.resume.title": {
    en: "You have an interview in progress",
    bn: "আপনার একটি সাক্ষাৎকার চলছে",
  },
  "interview.resume.body": {
    en: "Continue where you left off, or discard it and begin a new one. Discarding keeps the answers you have already given.",
    bn: "যেখানে থেমেছিলেন সেখান থেকে চালিয়ে যান, অথবা এটি বাতিল করে নতুন শুরু করুন। বাতিল করলেও আপনার দেওয়া উত্তরগুলো থেকে যাবে।",
  },
  "interview.resume.action": { en: "Continue", bn: "চালিয়ে যান" },
  "interview.discard.action": { en: "Discard and start new", bn: "বাতিল করে নতুন শুরু করুন" },
  "interview.typeanswer": { en: "Type your answer…", bn: "আপনার উত্তর লিখুন…" },
  "interview.submit": { en: "Submit answer", bn: "উত্তর জমা দিন" },
  "interview.question": { en: "Question", bn: "প্রশ্ন" },
  "interview.overall": { en: "Overall", bn: "সামগ্রিক" },
  "interview.strengths": { en: "Strengths", bn: "শক্তির দিক" },
  "interview.weaknesses": { en: "Areas to improve", bn: "উন্নতির জায়গা" },
  "interview.loaderror": { en: "Could not start the interview session.", bn: "সাক্ষাৎকার সেশন শুরু করা যায়নি।" },
  "interview.reporterror": { en: "Could not load the report.", bn: "প্রতিবেদন লোড করা যায়নি।" },

  // Destinations
  "dest.loading": { en: "Loading destinations…", bn: "গন্তব্য লোড হচ্ছে…" },
};

export interface I18nCtx {
  lang: Lang;
  setLang: (l: Lang) => void;
  toggleLang: () => void;
  t: (key: keyof typeof dict | string) => string;
}

/* The context object lives in its own module so its identity stays stable
   across HMR / Fast Refresh — this prevents "must be used within Provider". */
export const I18nContext = createContext<I18nCtx | null>(null);

export function useI18n() {
  const c = useContext(I18nContext);
  if (!c) throw new Error("useI18n must be used within I18nProvider");
  return c;
}
