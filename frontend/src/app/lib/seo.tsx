import { useEffect } from "react";
import { useLocation } from "react-router";
import type { Lang } from "./i18n-context";

/**
 * Digonto SEO layer.
 *
 * No external dependency (no react-helmet / react-helmet-async): this module
 * manipulates `document.title` and a small set of <head> tags directly from a
 * `useEffect`. That is sufficient for a client-rendered SPA, but it does NOT
 * make these tags visible to a crawler that does not execute JavaScript —
 * see /docs/seo.md for the prerendering/SSR mitigation this depends on.
 */

const SITE_URL = "https://digonto.ahbab.dev";
const DEFAULT_OG_IMAGE = `${SITE_URL}/og/og-default.png`;
const DEFAULT_OG_IMAGE_ALT = "Digonto — বাংলায় স্টাডি অ্যাব্রড ও ভিসা নেভিগেটর";

export interface SeoProps {
  /** Document title. Keep it under ~60 characters, Bangla-first. */
  title: string;
  /** Meta description. Keep it under ~160 characters. */
  description: string;
  /** Route pathname, e.g. "/destinations". Used to build the canonical + og:url. */
  path: string;
  /** true for auth-gated pages, /auth, and the 404 catch-all. */
  noindex: boolean;
  /** Current UI language; drives og:locale / og:locale:alternate. */
  lang: Lang;
  /** Optional absolute image URL override for og:image / twitter:image. */
  image?: string;
}

function resolveUrl(path: string): string {
  if (path === "/") return `${SITE_URL}/`;
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return `${SITE_URL}${normalized}`;
}

function setMetaTag(attr: "name" | "property", key: string, content: string): void {
  if (typeof document === "undefined") return;
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!tag) {
    tag = document.createElement("meta");
    tag.setAttribute(attr, key);
    document.head.appendChild(tag);
  }
  tag.setAttribute("content", content);
}

function removeMetaTag(attr: "name" | "property", key: string): void {
  if (typeof document === "undefined") return;
  const tag = document.head.querySelector(`meta[${attr}="${key}"]`);
  if (tag) tag.remove();
}

function setLinkTag(rel: string, href: string): void {
  if (typeof document === "undefined") return;
  let link = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!link) {
    link = document.createElement("link");
    link.setAttribute("rel", rel);
    document.head.appendChild(link);
  }
  link.setAttribute("href", href);
}

/**
 * Adds or removes `<meta name="robots" content="noindex, nofollow">`.
 * index.html ships with NO robots tag (the indexable default), so removing
 * the tag here — rather than writing "index, follow" — is what restores that
 * default for routes that toggle back to indexable during client navigation.
 */
function setRobots(noindex: boolean): void {
  if (typeof document === "undefined") return;
  if (noindex) {
    setMetaTag("name", "robots", "noindex, nofollow");
  } else {
    removeMetaTag("name", "robots");
  }
}

/**
 * `<Seo>` renders nothing. Mount one per route (typically inside the page
 * component, or centrally wherever the route is resolved) to keep
 * document.title, the canonical link, robots, and Open Graph / Twitter tags
 * in sync with client-side navigation.
 */
export function Seo({ title, description, path, noindex, lang, image }: SeoProps): null {
  useEffect(() => {
    if (typeof document === "undefined") return;

    const url = resolveUrl(path);
    const ogImage = image ?? DEFAULT_OG_IMAGE;

    document.title = title;

    setMetaTag("name", "description", description);
    setRobots(noindex);
    setLinkTag("canonical", url);

    setMetaTag("property", "og:title", title);
    setMetaTag("property", "og:description", description);
    setMetaTag("property", "og:url", url);
    setMetaTag("property", "og:image", ogImage);
    setMetaTag("property", "og:locale", lang === "bn" ? "bn_BD" : "en_US");
    setMetaTag("property", "og:locale:alternate", lang === "bn" ? "en_US" : "bn_BD");

    setMetaTag("name", "twitter:title", title);
    setMetaTag("name", "twitter:description", description);
    setMetaTag("name", "twitter:image", ogImage);
    setMetaTag("name", "twitter:image:alt", image ? title : DEFAULT_OG_IMAGE_ALT);
  }, [title, description, path, noindex, lang, image]);

  return null;
}

/* -------------------------------------------------------------------------
 * SEO_ROUTES — bilingual title/description + indexing policy for every
 * route declared in src/app/App.tsx (5 public + 5 gated + /auth + 404 = 12).
 * ---------------------------------------------------------------------- */

export type SeoRoutePath =
  | "/"
  | "/destinations"
  | "/ledger"
  | "/security"
  | "/about"
  | "/auth"
  | "/planner"
  | "/ask"
  | "/vault"
  | "/funding"
  | "/interview"
  | "/moderator"
  | "*";

export interface SeoRouteMeta {
  path: SeoRoutePath;
  title: Record<Lang, string>;
  description: Record<Lang, string>;
  /** true = excluded from indexing (auth-gated, /auth, or the 404 catch-all). */
  noindex: boolean;
}

export const SEO_ROUTES: Record<SeoRoutePath, SeoRouteMeta> = {
  "/": {
    path: "/",
    title: {
      bn: "দিগন্ত — বাংলায় স্টাডি অ্যাব্রড ও ভিসা গাইড",
      en: "Digonto — Bangla Study Abroad & Visa Guide",
    },
    description: {
      bn: "বাংলাদেশি শিক্ষার্থীদের জন্য বিনামূল্যে, সৎ ও উৎস-উদ্ধৃত স্টাডি অ্যাব্রড ও ভিসা পরিকল্পনা — প্রোগ্রাম থেকে সাক্ষাৎকার পর্যন্ত।",
      en: "Digonto is a free, honest, source-cited study-abroad and visa planner for Bangladeshi students — from programme choice to interview.",
    },
    noindex: false,
  },
  "/destinations": {
    path: "/destinations",
    title: {
      bn: "গন্তব্য — দিগন্ত",
      en: "Destinations — Digonto",
    },
    description: {
      bn: "দেশ ও বিশ্ববিদ্যালয় অনুযায়ী ভর্তি, খরচ ও ভিসার শর্ত তুলনা করুন, প্রতিটি তথ্যের উৎসসহ।",
      en: "Compare admission, cost, and visa requirements across countries and universities, each fact backed by a cited source.",
    },
    noindex: false,
  },
  "/ledger": {
    path: "/ledger",
    title: {
      bn: "সত্য খতিয়ান — দিগন্ত",
      en: "Truth Ledger — Digonto",
    },
    description: {
      bn: "প্রতিটি নিয়ম ও তথ্যের পেছনের সরকারি উৎস ও স্ন্যাপশট দেখুন — কোনো অনুমান নয়, শুধু প্রমাণ।",
      en: "See the official source snapshot behind every rule Digonto shows — no guesswork, only evidence.",
    },
    noindex: false,
  },
  "/security": {
    path: "/security",
    title: {
      bn: "নিরাপত্তা ও নীতি — দিগন্ত",
      en: "Security & Ethics — Digonto",
    },
    description: {
      bn: "দিগন্ত আপনার তথ্য কীভাবে সংরক্ষণ করে এবং আমাদের নীতিগত অঙ্গীকার সম্পর্কে জানুন।",
      en: "Learn how Digonto protects your data and the ethical commitments behind the product.",
    },
    noindex: false,
  },
  "/about": {
    path: "/about",
    title: {
      bn: "পরিচিতি — দিগন্ত",
      en: "About — Digonto",
    },
    description: {
      bn: "দিগন্ত কেন তৈরি হয়েছে, কারা তৈরি করেছে এবং বিনামূল্যে সেবাটি কীভাবে টিকে থাকে জানুন।",
      en: "Why Digonto exists, who built it, and how the free service is sustained.",
    },
    noindex: false,
  },
  "/auth": {
    path: "/auth",
    title: {
      bn: "প্রবেশ — দিগন্ত",
      en: "Sign in — Digonto",
    },
    description: {
      bn: "দিগন্তে প্রবেশ করুন বা নিবন্ধন করুন — আপনার যাত্রা পরিকল্পক, ভল্ট ও তহবিল স্টুডিও ব্যবহার করতে।",
      en: "Sign in or register to use Digonto's planner, document vault, and funding studio.",
    },
    // Public route, but a bare sign-in form has no independent search value
    // and duplicates across ?from= redirect variants — kept out of the index.
    noindex: true,
  },
  "/planner": {
    path: "/planner",
    title: {
      bn: "যাত্রা পরিকল্পক — দিগন্ত",
      en: "Journey Planner — Digonto",
    },
    description: {
      bn: "আপনার ব্যক্তিগত স্টাডি অ্যাব্রড সময়রেখা তৈরি করুন — সাইন-ইন প্রয়োজন।",
      en: "Build your personal study-abroad timeline — sign-in required.",
    },
    noindex: true,
  },
  "/ask": {
    path: "/ask",
    title: {
      bn: "জিজ্ঞাসা — দিগন্ত",
      en: "Ask Digonto",
    },
    description: {
      bn: "উৎস-উদ্ধৃত উত্তরসহ দিগন্তকে প্রশ্ন করুন — সাইন-ইন প্রয়োজন।",
      en: "Ask Digonto questions and get source-cited answers — sign-in required.",
    },
    noindex: true,
  },
  "/vault": {
    path: "/vault",
    title: {
      bn: "দলিল ভল্ট — দিগন্ত",
      en: "Document Vault — Digonto",
    },
    description: {
      bn: "আপনার ভিসা ও ভর্তি দলিল নিরাপদে সংরক্ষণ ও সংগঠিত করুন — সাইন-ইন প্রয়োজন।",
      en: "Store and organise your visa and admission documents securely — sign-in required.",
    },
    noindex: true,
  },
  "/funding": {
    path: "/funding",
    title: {
      bn: "তহবিল স্টুডিও — দিগন্ত",
      en: "Funding Studio — Digonto",
    },
    description: {
      bn: "বৃত্তি ও তহবিলের উৎস খুঁজুন এবং আর্থিক সচ্ছলতার প্রমাণ পরিকল্পনা করুন — সাইন-ইন প্রয়োজন।",
      en: "Find scholarships and funding sources and plan your proof of finances — sign-in required.",
    },
    noindex: true,
  },
  "/interview": {
    path: "/interview",
    title: {
      bn: "সাক্ষাৎকার কক্ষ — দিগন্ত",
      en: "Interview Room — Digonto",
    },
    description: {
      bn: "ভিসা সাক্ষাৎকারের জন্য বাস্তব প্রশ্ন দিয়ে অনুশীলন করুন — সাইন-ইন প্রয়োজন।",
      en: "Practice for your visa interview with realistic questions — sign-in required.",
    },
    noindex: true,
  },
  "/moderator": {
    path: "/moderator",
    title: {
      bn: "মডারেটর কনসোল — দিগন্ত",
      en: "Moderator Console — Digonto",
    },
    description: {
      bn: "পরিবর্তন পর্যালোচনা, উত্তর যাচাই ও ব্যবহারকারী তদারকির মডারেটর কনসোল — সাইন-ইন প্রয়োজন।",
      en: "The moderator console for change review, answer verification, and user oversight — sign-in required.",
    },
    noindex: true,
  },
  "*": {
    path: "*",
    title: {
      bn: "পাওয়া যায়নি — দিগন্ত",
      en: "Page not found — Digonto",
    },
    description: {
      bn: "যে পাতাটি খুঁজছেন তা পাওয়া যায়নি। হোমপেজে ফিরে যান।",
      en: "The page you're looking for could not be found. Return to the homepage.",
    },
    noindex: true,
  },
};

/**
 * Looks up SEO_ROUTES by exact pathname, falling back to the 404 entry for
 * anything unrecognized (mirrors the `*` catch-all in App.tsx).
 */
export function getRouteMeta(pathname: string): SeoRouteMeta {
  const normalized = pathname === "" ? "/" : pathname;
  for (const key of Object.keys(SEO_ROUTES) as SeoRoutePath[]) {
    if (key !== "*" && key === normalized) {
      return SEO_ROUTES[key];
    }
  }
  return SEO_ROUTES["*"];
}

/**
 * Convenience component that reads the current route from react-router and
 * renders `<Seo>` with the matching SEO_ROUTES entry. Not wired into
 * App.tsx/Layout.tsx by this change (those files are owned elsewhere); drop
 * `<RouteSeo lang={lang} />` once inside the routed tree (e.g. in Layout,
 * alongside the existing `useLocation()` call) to activate per-route meta
 * app-wide without touching every page individually.
 */
export function RouteSeo({ lang }: { lang: Lang }): JSX.Element {
  const { pathname } = useLocation();
  const meta = getRouteMeta(pathname);
  return (
    <Seo
      title={meta.title[lang]}
      description={meta.description[lang]}
      path={pathname}
      noindex={meta.noindex}
      lang={lang}
    />
  );
}
