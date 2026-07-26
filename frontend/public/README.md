# public/ — outstanding binary assets

This directory holds Digonto's static, build-time SEO assets. The text/config
files (`robots.txt`, `sitemap.xml`, `site.webmanifest`) are already in place.
The binary image assets listed below are **not** in this directory yet — they
need to be produced by a designer and dropped in at the exact paths and
dimensions below. `index.html` and `site.webmanifest` already reference these
paths, so the build will 404 on them (favicons/OG image) until they exist;
nothing will fail to *build*, but crawlers, browser tabs, PWA installs, and
social-share previews will be broken or missing until they're added.

| Path | Purpose | Exact spec |
| --- | --- | --- |
| `favicon.svg` | Modern scalable favicon, referenced first in `<head>` | SVG, square artboard, should read clearly at 16–32px |
| `favicon.ico` | Legacy favicon fallback (old browsers, some crawlers) | ICO, multi-size (16x16, 32x32, 48x48 embedded) |
| `apple-touch-icon.png` | iOS/iPadOS home-screen icon | PNG, exactly 180x180px, no transparency (iOS ignores alpha and will show it as black) |
| `icons/icon-192.png` | Web app manifest icon (`purpose: any`) | PNG, exactly 192x192px |
| `icons/icon-512.png` | Web app manifest icon (`purpose: any`); also the `logo` referenced in the Organization JSON-LD in `index.html` | PNG, exactly 512x512px |
| `icons/icon-maskable-512.png` | Web app manifest icon (`purpose: maskable`) — Android adaptive icon | PNG, exactly 512x512px, with the safe zone (central ~80%) containing all meaningful content since Android will crop to a circle/squircle/rounded-square |
| `og/og-default.png` | Default Open Graph / Twitter card image (`og:image`, `twitter:image` in `index.html`) | PNG, exactly 1200x630px, must look correct cropped to both 1.91:1 (Facebook/LinkedIn) and roughly square (some Twitter clients) — keep key text/logo centered |

## Fonts (self-hosted, owned by another agent)

`index.html` preloads two of the 29 woff2 files documented in
`frontend/fonts-vendor/README.md`, expected to land at:

- `/fonts/hind-siliguri-400-bengali.woff2` (Bangla UI body text — `body`'s
  `font-family: var(--font-sans-bn)` under `.lang-bn`, at the browser
  default weight 400 since `body` sets no explicit `font-weight`)
- `/fonts/noto-serif-bengali-500-bengali.woff2` (Bangla display/headline
  font — `h1`–`h4` under `.lang-bn` use `font-family: var(--font-serif-bn)`
  at `font-weight: var(--font-weight-medium)`, which resolves to **500**
  in `src/styles/theme.css`, not 400 or 600)

These two were chosen — and the **bengali** subset specifically, over the
**latin** subset also produced by the fonts-vendor script — because Bangla
is the default/primary language (`<html lang="bn">`, `.lang-bn` applied by
default in `I18nProvider`), so the hero `<h1>` (likely the LCP element) and
the surrounding body copy are Bangla glyphs that must paint first. If the
fonts-vendor pipeline's output filenames or the weight actually used for
headings changes, update the two `<link rel="preload">` entries in
`index.html` to match — a preload that doesn't match a real fetched resource
is wasted bandwidth and shows as a console warning ("was preloaded but not
used").

## Why these live in `public/` and not `src/assets/`

Everything in `public/` is copied to the build output root untouched (no
hashing, no bundling), which is required for `robots.txt`, `sitemap.xml`,
`site.webmanifest`, and any URL referenced by absolute path from `index.html`
or third-party crawlers/OS chrome (favicons, manifest icons, OG image) — none
of these can go through Vite's module graph.
