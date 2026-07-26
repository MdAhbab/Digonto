# Digonto Frontend Design Instructions

Brief for Claude Opus (Claude Artifacts / Claude Design). Rebuild every page of Digonto from scratch. This is a design and architecture task only: produce layout systems, visual concepts, motion specifications, and component plans. Do not write production code yet; the code structure will be provided separately.

## 0. What Digonto is

A free, Bangla-first Study Abroad and Visa Navigator for Bangladeshi students. It plans the entire journey (programme choice, documents, funding, visa, interview), watches official portals for changes, and proves every claim with a cited source snapshot. Users are 18 to 28, mostly on mid-range Android phones, often on unstable connections. The product must feel like a private counsel's office, not a SaaS dashboard.

## 1. Stack (fixed, non-negotiable)

React 18 + Vite, Tailwind CSS, Three.js, GSAP (with ScrollTrigger), Lenis smooth scroll. Permitted additions: Framer Motion for micro-interactions, Radix UI primitives for accessible components, TanStack Query for data, Zustand for state, next-themes-style class strategy for theming. Fonts via self-hosted files (no external font CDNs at runtime).

## 2. Aesthetic direction

Target the register of an ultra-premium modern law firm: restraint, weight, generous negative space, editorial typography, and confidence. Think engraved letterhead translated to screen. Explicitly avoid the generic AI-generated look: no purple-to-blue gradients on dark backgrounds, no glassmorphism cards floating over blurred blobs, no emoji in UI copy, no rounded-2xl-shadow-xl on everything, no centered hero with two gradient buttons, no sparkles iconography.

**You have creative freedom over typography.** Constraints only: one high-contrast editorial serif for display (must render Bangla gracefully next to Latin; pair a Bangla display face such as a high-quality Bengali serif with the Latin display face and match optical weight), one precise grotesk for UI, one monospace for citations, snapshot IDs, and fee figures. Bangla is a first-class script here, never a fallback font. Set Bangla line-height 1.7 or more; Bengali conjuncts clip at tight leading.

### 2.1 Dual themes, both fully designed

- **Light, "Sheet Kagoj" (winter paper):** warm porcelain grounds (off-white with a slight cream cast), ink-black text, one deep accent (suggest deep teal or bottle green, the colour of old passports), hairline rules, engraved-style numerals. Feels: morning, paperwork done calmly.
- **Dark, "Rat-Digonto" (night horizon):** deep near-black with a blue-green undertone (not pure #000), warm off-white text, the same accent lifted two steps in luminance, plus a restrained gold used only for citation marks and completed milestones. Feels: the horizon at night, seen from a departing aircraft.
- Both themes get full colour token tables, elevation strategy (borders and tone shifts, not shadows), and state colours. Design both, not light-first with an inverted afterthought. Persist choice; respect `prefers-color-scheme`; theme switch animates as a slow cross-fade of the page's lighting, 400 ms, never a hard flip.

## 3. Signature motion system

Lenis provides inertia scroll; GSAP ScrollTrigger drives scenes. Rules: no generic fade-up cards. Every animated element must transform in a way that expresses what it does. Respect `prefers-reduced-motion` with a fully static, still-beautiful variant. All scenes must degrade on mobile to cheaper transforms (opacity, clip-path, translate only).

Three.js is used in exactly two places (performance budget): the hero flight-path scene and the globe in the destination chooser. Everything else is DOM + GSAP.

## 4. Pages, one by one

### 4.1 Landing, "The Horizon"

1. **Hero:** a Three.js scene of a thin luminous flight path (a curved line with a slowly drifting camera) rising from a stylised map point (Dhaka) into open space. No plane model, only the path and particle-thin waypoints. Headline in Bangla with English subline. As the user scrolls, the camera travels along the path; copy sections dock at waypoints. This is the one big 3D moment.
2. **The problem strip:** the statistics (52,799 students abroad; 667 million dollars spent in FY25; 2,000 consultancies, 400 registered) appear as engraved counters that roll up like mechanical flip counters when pinned, then lock. Numbers are typeset in the monospace.
3. **How Digonto works:** a pinned horizontal sequence where a single document sheet travels through four stations (Crawl, Verify, Explain, Watch). The sheet itself morphs (clip-path and rotation) at each station. The section unpins only after the sheet reaches the seal.
4. **The Truth Ledger teaser:** a claim sentence assembles word by word, then its citation stamp presses onto the page (scale-down with a slight ink-spread effect) as the user crosses the trigger. Scroll further and the stamp lifts to reveal the source snapshot beneath.
5. **Agents introduction:** four columns for Porter, Prohori, Khoji, Shonchari. On scroll, each column's rule line draws downward, then the agent's monogram is drawn stroke by stroke (SVG stroke-dashoffset), staggered.
6. Footer: sitemap set like a legal letterhead, licence, SDG statement.

### 4.2 Journey Planner, "The Timeline Reactor"

The centrepiece app screen. A vertical master timeline (mobile) or a two-column ledger (desktop): left column fixed months, right column steps as ledger entries. When a dependency changes, affected entries visibly re-flow: entries slide with a paper-shuffle motion and their connecting threads redraw. Provide a "what changed" drawer with the triggering event and source. Scroll behaviour: the current month heading is pinned; completed steps get an embossed check seal; future steps are set at 60 percent ink.

### 4.3 Ask Digonto (conversation surface)

A reading-first layout, not a chat bubble app: questions as margin notes, answers as typeset body text with citation superscripts. Each citation opens the Truth Ledger side sheet showing the portal snapshot with the quoted span highlighted. Streaming text renders as if typeset line by line, no cursor blink cliché. Bangla/English toggle per answer. Refusals are designed states, not errors: a calm card stating what is unknown and which portal will be watched for the answer.

### 4.4 Document Vault, "Prohori's Desk"

A shelf metaphor rendered flat: document classes as archival folders with hairline outlines. Upload is drag-to-desk with a settling animation. Prohori's audit renders as a legal memo: findings, severities, actions. Expiring documents get a date stamp that tilts as expiry approaches (subtle rotation mapped to days remaining). Security cues are visual and real: an "encrypted at rest" seal on every folder linking to the security page.

### 4.5 Funding Studio, "Khoji's Ledger"

Scholarship matches as a sortable broadsheet table (not cards). A budget composition bar composes itself as the user adds funding sources; the bank-solvency requirement line is drawn as a threshold the bar must cross. The Agent Fee Reality Check lives here: a two-column comparison, quoted fee versus itemised fair fee, with each line item citing its source.

### 4.6 Interview Room, "Shonchari"

A deliberately quiet, near-empty page: single question line, a recording control, a progress thread along the page edge. After the session, the weakness report unrolls as a printed transcript with margin annotations in the accent colour. Optional voice mode UI states (listening, thinking, speaking) expressed through the thread's motion, not through pulsing orbs.

### 4.7 Supporting pages

Destination chooser with the second Three.js globe (restrained: monochrome globe, route arcs only for the student's shortlisted countries); Truth Ledger public page (verify any snapshot ID); Security and Ethics page (plain-language commitments, threat model summary); About/SDG page; Auth (email OTP, one field, letterpressed card); 404 as a boarding-pass torn in half.

## 5. Responsiveness and performance

Design mobile-first at 360 px, then 768, 1024, 1440, 1920. The horizontal pinned scenes on the landing page become vertical stepped scenes under 768 px. Three.js hero swaps to a pre-rendered video or an SVG line animation on low-power devices (detect via `deviceMemory`/`hardwareConcurrency` heuristics). Budgets: LCP under 2.5 s on a mid-range Android over 3G-fast, total JS under 300 KB gzip on first load (lazy-load Three.js scenes), fonts subsetted (Bangla subset separately). Load-Shedding Mode: design the offline state for every app page (cached plan visible, actions queued, a thin amber status rule at the viewport top, never a modal).

## 6. Accessibility

WCAG 2.2 AA contrast in both themes; full keyboard paths for planner and vault; focus states designed (accent underline plus outline, not browser default); all motion gated by `prefers-reduced-motion`; Bangla screen-reader labels; touch targets 44 px minimum.

## 7. Deliverables and task breakdown

Work in this order, one deliverable per step:

1. Design tokens: both theme tables (colour, type scale, spacing, radii, rules), typography specimens with Bangla and Latin set together.
2. Component inventory: buttons, inputs, ledger rows, citation stamp, seals, drawers, tables, empty/offline/refusal states.
3. Landing page: full-fidelity concept for both themes, desktop and mobile, with a written motion script per section (trigger points, pinned ranges, transforms, durations, easings).
4. Journey Planner concept, both themes, including the re-flow motion script.
5. Ask Digonto and Truth Ledger side sheet concepts.
6. Vault, Funding Studio, Interview Room concepts.
7. Supporting pages and the offline/error state family.
8. Motion bible: a single document listing every ScrollTrigger scene, its mobile fallback, and its reduced-motion variant.
9. Handoff notes: component-to-route map matching the React + Vite structure that will be supplied.

Number every artefact. Where you make a judgement call, state it and continue; do not stall on questions.
