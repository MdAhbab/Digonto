# Digonto SEO layer

Scope of this document: everything under `frontend/` that touches
discoverability — `index.html`, `frontend/public/*`, and
`frontend/src/app/lib/seo.tsx`. It is written to be read by whoever picks up
the next step (prerendering/SSR, or wiring `<Seo>`/`<RouteSeo>` into the
routed tree), so it states plainly what is done, what is scaffolded but not
wired up, and what is not solved at all yet.

## 1. Indexing policy per route

Digonto has 12 routes declared in `src/app/App.tsx`. The policy is binary —
indexable or not — and is enforced in three places that must stay in sync:
`frontend/public/robots.txt` (blocks crawling), `frontend/public/sitemap.xml`
(lists only what should be indexed), and `SEO_ROUTES` in
`frontend/src/app/lib/seo.tsx` (per-route `noindex` flag + meta content for
whatever eventually renders `<Seo>`/`<RouteSeo>`).

| Route | Indexable? | Why |
| --- | --- | --- |
| `/` (Landing) | Yes | Primary entry point; the page most likely to rank for "study abroad Bangladesh" style queries. |
| `/destinations` | Yes | Country/university comparison content — exactly the kind of page people search for. |
| `/ledger` | Yes | The "Truth Ledger" is a differentiator (cited sources); good for trust and long-tail queries. |
| `/security` | Yes | Security/ethics posture; low search volume but legitimate, non-duplicate content. |
| `/about` | Yes | Standard trust-building page; also expected by users and by some ranking heuristics (E-E-A-T). |
| `/auth` | **No** | Public (unauthenticated users can reach it) but it is a bare sign-in/register form with `?from=` redirect-state variants. No unique content, real risk of near-duplicate URLs (`/auth`, `/auth?from=/planner`, etc.) diluting crawl budget. |
| `/planner` | **No** | Behind `RequireAuth`; anonymous crawlers get redirected to `/auth`, so there is nothing to index anyway — but robots.txt/`noindex` make the intent explicit rather than accidental. |
| `/ask` | **No** | Same as above — auth-gated, plus this is where a user's own free-text questions would live; nothing here is meant to be public content. |
| `/vault` | **No** | Auth-gated; contains a signed-in user's private uploaded documents. Indexing this would be a privacy incident, not just an SEO mistake. |
| `/funding` | **No** | Auth-gated, personalised financial planning. |
| `/interview` | **No** | Auth-gated, personalised interview practice. |
| `*` (NotFound) | **No** | A 404 must never be indexable; it would otherwise "succeed" for every mistyped URL and pollute the index with the same boilerplate page under many URLs. |

**Why the gated routes are excluded, concretely:** they are (a) not
crawlable in practice because `RequireAuth` bounces an anonymous request to
`/auth` before any content renders, and (b) even if a crawler somehow saw
authenticated content, it would be a single user's private data, not a page
meant to represent Digonto to the public. Excluding them is not just an SEO
nicety, it's the correct behavior for both trust and privacy. `/auth` is
public but excluded because it has no standalone informational value and
exists in many URL variants that would otherwise look like duplicate/thin
content to a crawler.

`robots.txt` disallowing a path only stops crawling — it does not guarantee
a URL that's already indexed gets removed, and a disallowed URL can still
appear in search results (title-only, "no information is available") if
something else links to it. That is why every gated route + `/auth` + the
404 also gets an explicit `noindex` entry in `SEO_ROUTES`: robots.txt keeps
crawlers out proactively, and the meta tag is the correct signal to remove a
URL that got indexed some other way (e.g. a user pasting a `/planner` link
somewhere public). They are deliberately layered, not redundant.

## 2. Hreflang / bilingual strategy

Bangla (`bn`) is the primary language: `<html lang="bn">` in `index.html`,
and `I18nProvider` (`src/app/lib/i18n.tsx`) defaults new visitors to `bn` and
toggles a `.lang-bn` class that swaps in Bangla fonts/copy. English is a
secondary, in-app toggle, **not a separate URL** — there is no `/en/...`
route prefix or `?lang=en` query convention anywhere in `App.tsx`.

This matters because standard hreflang practice assumes each language has
its own crawlable URL. Digonto doesn't have that yet, so what's implemented
is the best available approximation given the current routing:

- `index.html` carries `<link rel="alternate" hreflang="bn">`,
  `hreflang="en"`, and `hreflang="x-default"` — all three currently pointing
  at the same URL (`https://digonto.ahbab.dev/`).
- `sitemap.xml` repeats the same pattern for all 5 indexable routes.

**Be honest about what this buys you:** self-referencing hreflang to the
same URL for two different `hreflang` values is a known, debated pattern.
It correctly tells Google "this URL is a reasonable result for both bn and
en searchers" (harmless, arguably mildly useful), but it does **not** give
Google two distinct pages to rank separately, and it will not produce a
"this page is available in English" search-result annotation the way true
per-language URLs would. If English search visibility becomes a real goal,
the fix is a routing change (e.g. `/en/destinations`) — that's a product
decision outside this task's scope, flagged here so it isn't silently lost.

`og:locale` (`bn_BD`) / `og:locale:alternate` (`en_US`) in `index.html` are
static for the document's default state. `Seo`/`RouteSeo`
(`src/app/lib/seo.tsx`) update `og:locale`/`og:locale:alternate` per the
`lang` prop at runtime so a social-share screenshot taken after the user
toggles to English reflects that — but again, this only affects clients that
execute JS before scraping OG tags (most link-unfurlers do not).

## 3. Client-rendered SPA: the actual SEO risk, and mitigation ranked

**This is the single biggest honest caveat in this whole layer, so it's
stated plainly: the 5 public routes are currently rendered entirely
client-side by React (Vite SPA, `BrowserRouter`, no SSR, no prerendering).**
`index.html` served to a crawler (or curl) contains the generic
`<title>`/`<meta>`/JSON-LD written into the static HTML in this change, plus
an empty `<div id="root"></div>` and a `<script type="module" src="/src/main.tsx">`
tag. Everything route-specific — the per-page title/description that
`Seo`/`RouteSeo` would set, and the actual visible content of
`/destinations`, `/ledger`, `/security`, `/about` — only exists after the
browser downloads, parses, and executes the JS bundle and React mounts.

Concretely, what this means:

- **Static-only checks are wrong for anything but `/`.** `curl` or `view-source`
  on `/destinations` returns the *same* generic `index.html` shell as `/` —
  none of the route-specific meta from `SEO_ROUTES` is present, because
  `Seo`/`RouteSeo` haven't been rendered by anything yet (see §3.1) and even
  once they are, they only run in the browser.
- **Googlebot does execute JavaScript** (it uses an evergreen headless
  Chromium), so it *can* eventually see the rendered content and the
  `Seo`-set tags — but rendering happens in a second wave after initial
  crawling/indexing ("index now, render later"), it costs Google compute
  budget that smaller/newer sites get less of, and it is strictly worse than
  serving real HTML immediately. Bing, and many non-Google crawlers, social
  unfurlers (Facebook/WhatsApp/Telegram link previews — highly relevant for
  a Bangladeshi audience), and any tool that just fetches HTML will only
  ever see the static shell.
- **Do not read this SEO layer as "SEO is solved."** It fixes the things
  that were actively broken or missing (the blanket `noindex, nofollow`,
  the placeholder description, robots.txt/sitemap not existing, no
  structured data, no per-route metadata model) and it makes the eventual
  render-time state correct. It does not make the 5 public routes visible
  to a crawler or link-unfurler that doesn't execute JS. That gap is real
  and unresolved by this change.

### 3.1 `Seo`/`RouteSeo` are built but not wired into the app yet

`frontend/src/app/lib/seo.tsx` exports `Seo` (imperative `useEffect` that
sets `document.title`, the meta description, robots, canonical, and
OG/Twitter tags) and `RouteSeo` (reads `useLocation()` and renders `<Seo>`
with the matching `SEO_ROUTES` entry). Per this task's file-ownership split,
nothing in `App.tsx`, `Layout.tsx`, or any page component was modified to
actually render `<RouteSeo lang={lang} />` — that integration is one line
(e.g. inside `Layout`, next to its existing `useLocation()` call) but is left
for whoever owns those files, since editing them wasn't in scope here.
**Until that line is added, none of the per-route title/description/
canonical/robots logic in `seo.tsx` executes at runtime** — only the static
`index.html` tags are live. This is the most important immediate follow-up.

### 3.2 Mitigation options, ranked

1. **Prerender the 5 public routes at build time (recommended first step).**
   Run the 5 known-static, non-personalised URLs (`/`, `/destinations`,
   `/ledger`, `/security`, `/about`) through a headless-Chromium prerender
   step after `vite build` (e.g. `vite-plugin-ssg`/`vite-plugin-prerender`,
   or a small custom Puppeteer/Playwright script that visits each route and
   overwrites `dist/<route>/index.html` with the fully rendered DOM), so
   each gets **real, route-specific static HTML** — correct `<title>`, meta
   description, canonical, OG tags, and visible content — with zero runtime
   architecture change (still a client-hydrated SPA after that first paint).
   This is the best effort-to-benefit ratio here: the app stays a pure
   static SPA to host (works on any CDN/static host, no Node server to run
   or keep alive), and only 5 fixed, low-cardinality routes need to be
   generated, which matches this app's route count exactly (no dynamic
   per-ID pages to enumerate).
2. **Full SSR (server-side rendering on every request).** Correct and
   general (handles any future dynamic public route automatically), but a
   materially bigger lift: requires a Node runtime in production (or an
   edge-SSR platform), React server rendering set up for this exact router
   version, careful handling of anything in the component tree that assumes
   `window`/`document` (e.g. today's direct `document.*` calls in
   `Seo`/`I18nProvider`/`ThemeProvider` would need guards or a different
   pattern), and ongoing infra to keep a server alive vs. today's "upload a
   static folder" deployment. Only worth it if/when public routes become
   genuinely dynamic (e.g. per-university or per-scholarship pages) where
   build-time prerendering would mean regenerating on every content change.
3. **Dynamic rendering (serve prerendered HTML only to detected
   bots/crawlers, SPA to real users).** Explicitly **not recommended** as a
   destination architecture: Google has been walking back official support
   for it, it requires user-agent sniffing that is brittle and easy to get
   subtly wrong (link-unfurlers and some crawlers don't announce themselves
   the way Googlebot does), and it produces a real cloaking risk if the
   bot-served and user-served content ever drift — which is exactly the
   failure mode a small team without dedicated SEO tooling is likely to hit.
   Mentioned only for completeness/ranking, not as a plan.

**Recommendation:** do (1) next, scoped to exactly the 5 routes in the
`robots.txt`/`sitemap.xml` allowlist above. Revisit (2) only if a public,
content-heavy, frequently-changing route type gets added later.

## 4. Core Web Vitals budget (mid-range Android, Bangladeshi mobile networks)

Target profile: a mid-range Android device (the realistic median for
Bangladeshi students — think a ~2–3 year old MediaTek/Snapdragon 4-series
phone, 3–4GB RAM) on a throttled connection representative of Bangladeshi
mobile broadband outside the strongest 4G coverage (closer to Lighthouse's
"Slow 4G"/"Fast 3G" mobile throttling profile than to a home broadband or
US/EU 4G/5G baseline). Budgets below are field-target (real-user, p75),
which is what Google's Core Web Vitals assessment actually uses — not just
a single lab run.

| Metric | Budget (p75, mobile) | Why this number, for this audience |
| --- | --- | --- |
| **LCP** (Largest Contentful Paint) | ≤ 2.5s (target "good"); treat > 4s as a hard regression | This is the metric most sensitive to exactly the two things this task touched: font loading (hence preloading `hind-siliguri-400-bengali.woff2` and `noto-serif-bengali-500-bengali.woff2` — the Bengali subset, at the exact weights `body`/`h1`–`h4` actually use in `theme.css` — since the Bangla `h1`/body text is almost certainly the LCP element for a `bn`-default visitor) and JS-bundle-then-render latency (the SPA risk in §3). On a throttled connection, every unnecessary render-blocking request (a Google Fonts CSS import, in particular — see the flag below) can push LCP well past the 2.5s "good" threshold. |
| **INP** (Interaction to Next Paint) | ≤ 200ms (target "good") | Mid-range Android CPUs are the constraint here, not network — this is about JS execution/hydration cost, not download time. Keep an eye on any heavy libraries already in `package.json` (`gsap`, `three`, `motion`, `recharts`, `embla-carousel`) — none of these are used on the 5 indexable routes today as far as this audit went, but if that changes, code-splitting them out of the initial bundle for public routes is what keeps INP in budget. |
| **CLS** (Cumulative Layout Shift) | ≤ 0.1 (target "good") | Bangla and Latin scripts have different line-height/metrics; a FOUT/FOIT swap between a system-font fallback and Hind Siliguri/Noto Serif Bengali is a classic CLS source if `font-display` and fallback metrics aren't matched. Preloading the 2 critical fonts (done in this change) reduces the swap-delay window; explicit `font-display: swap` (or `optional`) plus size-matched fallback fonts in `src/styles/fonts.css`/`theme.css` is the remaining piece (owned by the styles agent, flagged here). |
| **TTFB** (Time to First Byte) | ≤ 800ms on the throttled profile | Relevant regardless of SPA-vs-prerendered, but especially important if/when SSR (§3.2 option 2) is ever adopted — TTFB is the metric most likely to regress from a static-host baseline the moment there's a server doing work per-request. |
| **Total transferred JS (initial route)** | ≤ ~180KB gzipped as a soft budget for the 5 public routes | Not an official CWV metric, but the leading indicator for LCP/INP on this hardware/network combination. `package.json` currently ships MUI + Radix + Emotion + GSAP + Three.js + Recharts + Framer/Motion as shared dependencies; whether they're all present in the bundle actually served for `/`, `/destinations`, `/ledger`, `/security`, `/about` is worth auditing (e.g. with `vite build --mode production` + a bundle visualizer) — this document flags the risk, it does not resolve it. |

**Why "Slow 4G" and not a faster profile:** Bangladesh's mobile data
experience is unevenly distributed — strong LTE in Dhaka/Chittagong city
centers, materially worse outside them, and load-shedding-adjacent network
instability is enough of a known issue that `Layout.tsx` already ships an
streaming answer surface. Budgeting for the median
realistic case (not the best case) is the only way these targets mean
anything.

## 5. Outstanding binary assets (blocking, not yet produced)

None of these exist in `frontend/public/` yet. `index.html` and
`site.webmanifest` already reference all of these paths, so nothing fails to
*build*, but favicons, the PWA install experience, and social-share previews
are all broken/missing until a designer produces them. Full detail
(including *why* each dimension/format was chosen) is in
`frontend/public/README.md`; the exact list:

- `favicon.svg` — scalable favicon
- `favicon.ico` — legacy fallback, multi-size ICO
- `apple-touch-icon.png` — exactly 180×180px
- `icons/icon-192.png` — exactly 192×192px
- `icons/icon-512.png` — exactly 512×512px (also referenced as the
  `Organization.logo` in the JSON-LD in `index.html`)
- `icons/icon-maskable-512.png` — exactly 512×512px, safe-zone-aware for
  Android's adaptive-icon crop
- `og/og-default.png` — exactly 1200×630px, the default `og:image`/
  `twitter:image`

Two font files are also referenced (`/fonts/hind-siliguri-400-bengali.woff2`,
`/fonts/noto-serif-bengali-500-bengali.woff2`, preloaded in `index.html`,
matching the 29-file naming scheme and weights documented in
`frontend/fonts-vendor/README.md`) but are explicitly owned by another agent
producing the self-hosted font pipeline; if the filenames they land on
differ, the two `<link rel="preload">` tags in `index.html` need updating to
match, or the preload is wasted bytes.

## 6. Summary — what's actually true right now

- Fixed: the blanket `noindex, nofollow` that was blocking all indexing is
  gone; the Figma-placeholder description is replaced; `robots.txt`,
  `sitemap.xml`, `site.webmanifest`, full OG/Twitter tags, and 3 JSON-LD
  blocks (Organization, WebSite+SearchAction, FAQPage) now exist and are
  valid.
- Scaffolded but not active: `Seo`/`RouteSeo` in `src/app/lib/seo.tsx`
  compile clean under `tsc --strict --noEmit` and cover all 12 routes'
  bilingual metadata, but nothing renders them yet (§3.1) — that's a
  one-line integration left for the layout owner.
- Not solved: the 5 public routes are still 100% client-rendered. A
  crawler or link-unfurler that doesn't execute JavaScript sees the same
  generic shell for every route. Build-time prerendering of those 5 routes
  (§3.2, option 1) is the recommended next step, not yet implemented.
