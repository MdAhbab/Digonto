# Self-hosted fonts — download instructions

The design brief mandates **no external font CDN calls at runtime** (users are on
slow mobile connections in Bangladesh), so all five typefaces used by Digonto must
be vendored as local `.woff2` files instead of loaded from
`fonts.googleapis.com`.

`src/styles/fonts.css` already contains the `@font-face` rules that expect these
files at `/fonts/<file>.woff2`, which Vite serves from **`public/fonts/`**. This
directory (`frontend/fonts-vendor/`) is just the drop staging area / documentation
— it is not a directory Vite serves. Run the download steps below, then copy (or
directly download into) `public/fonts/` once that directory exists.

> The `public/` directory is intentionally **not** created by this pass (owned by
> another agent). Until the 29 files listed below exist at `public/fonts/...`,
> every page will 404 on its font requests and fall back to the CSS `font-family`
> stack's next entry (system serif/sans/mono) — the app still renders, it just
> won't have the intended type until the fonts are vendored.

## Families, exact weights, and exact files

Two families (Noto Serif Bengali, Hind Siliguri) are split into separate
**latin** and **bengali** subset files per weight, each with its own
`unicode-range` in `fonts.css`, so a page that is 100% Bengali (or 100% Latin)
only downloads the subset it actually renders — important on 3G.

| # | Family | Role | Weights | Subsets | Files |
|---|--------|------|---------|---------|-------|
| 1 | Fraunces | Display serif (Latin) | 400, 500, 600, 700 | latin only | 4 |
| 2 | Space Grotesk | UI grotesk (Latin) | 400, 500, 600, 700 | latin only | 4 |
| 3 | JetBrains Mono | Monospace (citations/fees/IDs) | 400, 500, 600 | latin only | 3 |
| 4 | Noto Serif Bengali | Display serif (Bangla) | 400, 500, 600, 700 | latin + bengali | 8 |
| 5 | Hind Siliguri | UI (Bangla) | 300, 400, 500, 600, 700 | latin + bengali | 10 |

**Total: 29 `.woff2` files.**

Exact filenames expected by `fonts.css` (all live at `public/fonts/<name>`):

```
fraunces-400.woff2
fraunces-500.woff2
fraunces-600.woff2
fraunces-700.woff2

space-grotesk-400.woff2
space-grotesk-500.woff2
space-grotesk-600.woff2
space-grotesk-700.woff2

jetbrains-mono-400.woff2
jetbrains-mono-500.woff2
jetbrains-mono-600.woff2

noto-serif-bengali-400-latin.woff2
noto-serif-bengali-400-bengali.woff2
noto-serif-bengali-500-latin.woff2
noto-serif-bengali-500-bengali.woff2
noto-serif-bengali-600-latin.woff2
noto-serif-bengali-600-bengali.woff2
noto-serif-bengali-700-latin.woff2
noto-serif-bengali-700-bengali.woff2

hind-siliguri-300-latin.woff2
hind-siliguri-300-bengali.woff2
hind-siliguri-400-latin.woff2
hind-siliguri-400-bengali.woff2
hind-siliguri-500-latin.woff2
hind-siliguri-500-bengali.woff2
hind-siliguri-600-latin.woff2
hind-siliguri-600-bengali.woff2
hind-siliguri-700-latin.woff2
hind-siliguri-700-bengali.woff2
```

Note on Fraunces: the original Google Fonts request used the variable optical-size
axis (`opsz,wght@9..144,...`). For static self-hosted files we pin the optical
size at **`opsz=72`** (a display-weight optical size appropriate for headline
serif use) rather than shipping the full variable-font binary. If you'd rather
have the variable font (smaller total transfer if you use many opsz values),
request `Fraunces:opsz,wght@9..144,<weight>` instead of `Fraunces:wght@<weight>`
in the command below and adjust `fonts.css` to drop the fixed `font-optical-sizing`
assumption.

## Download command

Requires `curl`. This uses the legacy `fonts.googleapis.com/css` endpoint (not
`css2`) because it lets us pass `&subset=latin,bengali` and get back separate,
clearly commented `@font-face` blocks per subset — much easier to script than
diffing `unicode-range` values out of the `css2` response. Passing a modern
Chrome User-Agent string makes Google return `.woff2` URLs (the default/no-UA
response is `.woff`/`.ttf`).

Run this from `frontend/` (creates the files under `fonts-vendor/dist/`, then you
copy that into `public/fonts/`; or edit `OUT_DIR` below to point straight at
`public/fonts` once that directory exists):

```bash
#!/usr/bin/env bash
set -euo pipefail

UA="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
OUT_DIR="fonts-vendor/dist"
mkdir -p "$OUT_DIR"

# fetch_family <output-prefix> <google-family-query> <subset-list> <weights...>
fetch_family() {
  local prefix="$1" family_query="$2" subsets="$3"
  shift 3
  local weights="$*"
  local weights_csv
  weights_csv="$(echo "$weights" | tr ' ' ',')"

  local css
  css="$(curl -sA "$UA" "https://fonts.googleapis.com/css?family=${family_query}:${weights_csv}&subset=${subsets}&display=swap")"

  for subset in $(echo "$subsets" | tr ',' ' '); do
    for weight in $weights; do
      # pull the @font-face block whose /* subset */ comment matches, then
      # take the LAST url(...) in that block (css v1 lists woff2 last-ish per
      # src fallback chain when a modern UA is used, so grab the woff2 one).
      url="$(awk -v s="/\\* ${subset} \\*/" -v w="font-weight: ${weight};" '
        $0 ~ s {grab=1}
        grab && $0 ~ w {inrule=1}
        grab && /}/ {grab=0; inrule=0}
        inrule && /url\(/ {print}
      ' <<<"$css" | grep -o 'https://fonts.gstatic.com/[^)]*\.woff2' | tail -1)"

      if [ -z "$url" ]; then
        echo "WARN: no woff2 url found for ${prefix} ${subset} ${weight}" >&2
        continue
      fi

      if [ "$subsets" = "latin" ]; then
        out="${OUT_DIR}/${prefix}-${weight}.woff2"
      else
        out="${OUT_DIR}/${prefix}-${weight}-${subset}.woff2"
      fi
      curl -sL "$url" -o "$out"
      echo "wrote $out"
    done
  done
}

fetch_family fraunces           "Fraunces:opsz@72"     "latin"          400 500 600 700
fetch_family space-grotesk      "Space+Grotesk"        "latin"          400 500 600 700
fetch_family jetbrains-mono     "JetBrains+Mono"       "latin"          400 500 600
fetch_family noto-serif-bengali "Noto+Serif+Bengali"   "latin,bengali"  400 500 600 700
fetch_family hind-siliguri      "Hind+Siliguri"        "latin,bengali"  300 400 500 600 700

echo "Done. Copy $OUT_DIR/*.woff2 into public/fonts/ (create public/fonts/ if needed)."
```

Save the block above as `fonts-vendor/download-fonts.sh`, `chmod +x` it, and run
it, or paste it into a shell directly. Afterward:

```bash
mkdir -p public/fonts
cp fonts-vendor/dist/*.woff2 public/fonts/
```

If Google changes the legacy `css` endpoint response shape, the more robust
long-term fallback is [`google-webfonts-helper`](https://gwfh.mranftl.com/fonts)
(pick each family, select the exact weights above, subsets Latin + Bengali where
listed, download the `.woff2`-only package, and rename files to match the exact
names in the table above).
