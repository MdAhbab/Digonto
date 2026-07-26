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
  "vault.expires": { en: "Expires", bn: "মেয়াদ শেষ" },
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
  "funding.col.amount": { en: "Coverage", bn: "কভারেজ" },
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
  "interview.listening": { en: "Listening", bn: "শুনছি" },
  "interview.thinking": { en: "Thinking", bn: "ভাবছি" },
  "interview.speaking": { en: "Speaking", bn: "বলছি" },

  // Destinations
  "dest.title": { en: "Choose a destination", bn: "গন্তব্য নির্বাচন করুন" },
  "dest.sub": { en: "Route arcs are drawn only for your shortlist. The globe stays quiet otherwise.", bn: "শুধু আপনার সংক্ষিপ্ত তালিকার জন্য রুট আঁকা হয়। অন্যথায় গ্লোব শান্ত থাকে।" },
  "dest.shortlist": { en: "Your shortlist", bn: "আপনার তালিকা" },
  "dest.add": { en: "Add to shortlist", bn: "তালিকায় যোগ" },
  "dest.remove": { en: "Remove", bn: "সরান" },

  // Security
  "sec.title": { en: "Security & Ethics", bn: "নিরাপত্তা ও নীতি" },
  "sec.sub": { en: "Plain-language commitments, and the threat model we design against.", bn: "সহজ ভাষায় অঙ্গীকার, এবং আমরা যে ঝুঁকি-মডেলের বিরুদ্ধে নকশা করি।" },
  "sec.threat": { en: "Threat model", bn: "ঝুঁকি মডেল" },

  // About
  "about.title": { en: "About Digonto", bn: "দিগন্ত সম্পর্কে" },
  "about.sub": { en: "A public-interest tool for a private decision.", bn: "ব্যক্তিগত সিদ্ধান্তের জন্য একটি জনস্বার্থ যন্ত্র।" },

  // Auth
  "auth.title": { en: "Enter Digonto", bn: "দিগন্তে প্রবেশ" },
  "auth.sub": { en: "One field. We send a code to your email — no passwords to lose.", bn: "একটি ঘর। আমরা আপনার ইমেইলে কোড পাঠাই — হারানোর মতো কোনো পাসওয়ার্ড নেই।" },
  "auth.email": { en: "Email address", bn: "ইমেইল ঠিকানা" },
  "auth.sendcode": { en: "Send code", bn: "কোড পাঠান" },
  "auth.codesent": { en: "We sent a six-digit code to", bn: "আমরা ছয় অঙ্কের কোড পাঠিয়েছি" },
  "auth.verify": { en: "Verify & enter", bn: "যাচাই করে প্রবেশ" },
  "auth.resend": { en: "Resend code", bn: "কোড পুনরায় পাঠান" },

  // Offline
  "offline.status": { en: "Load-Shedding Mode — showing your cached plan. Actions are queued and will sync when the line returns.", bn: "লোড-শেডিং মোড — আপনার সংরক্ষিত পরিকল্পনা দেখানো হচ্ছে। সংযোগ ফিরলে পদক্ষেপগুলো সিঙ্ক হবে।" },
  "offline.toggle": { en: "Toggle offline preview", bn: "অফলাইন প্রিভিউ" },

  // 404
  "nf.title": { en: "This page was torn off.", bn: "এই পৃষ্ঠাটি ছিঁড়ে গেছে।" },
  "nf.sub": { en: "Like the stub of a boarding pass, half of this is missing.", bn: "বোর্ডিং পাসের অর্ধেকের মতো, এর একটি অংশ নেই।" },
  "nf.home": { en: "Return to the horizon", bn: "দিগন্তে ফিরুন" },
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
