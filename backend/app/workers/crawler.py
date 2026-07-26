"""Portal crawler: the recurrent loop's first stage.

Each enabled portal is fetched on its own cron (`portals.crawl_cron`,
docs/database.md section 3.3). The cheap and common path is "the page did
not change": sha256 of the normalised text is compared to the latest
snapshot and, on a match, nothing is written beyond the fetch timestamp.
Only a real content change pays for an HTML write, a passage split, and a
`portal.changed` event, which is what makes polling dozens of portals
affordable on one small VM.

No DB write transaction here ever spans the HTTP fetch: the request
happens first, fully, then a short transaction records what came back.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.db.connection import Databases
from app.events.bus import EventBus, EventType
from app.repositories._util import new_ulid, utc_now_iso
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo

log = logging.getLogger(__name__)

# Identifies the project and gives a real contact point. An anonymous UA
# hitting a government or embassy site on a schedule is how a watcher gets
# IP-banned; this is the whole point of asking for one explicitly.
USER_AGENT = (
    "DigontoPortalWatch/1.0 (+https://digonto.ahbab.dev; "
    "free visa-information watcher for Bangladeshi students; "
    "contact: moderator@digonto.ahbab.dev)"
)

FETCH_TIMEOUT_SECONDS = 20.0

# Consecutive failures at which last_status flips to 'unreachable' and the
# moderator console (GET /mod/portals, /mod/health) starts surfacing it.
# Below this, a single blip does not page anyone.
FAILURE_THRESHOLD = 3

# Minimum gap between two requests to the same host, regardless of how many
# watched portals happen to live on it. Politeness policy, not a limit
# imposed on us, so it is a worker constant rather than a Settings field.
MIN_HOST_INTERVAL_SECONDS = 3.0

# Upper bound on a host's own `Crawl-delay`. A published delay is honoured, but a
# very large one (or a typo: `Crawl-delay: 3600` appears in the wild) must not let
# a single source hold a crawl slot for an hour. Past the cap the source is crawled
# at the cap and the discrepancy is logged, so a reviewer can decide whether to keep
# watching it at all rather than having the crawler silently stall.
MAX_HONOURED_CRAWL_DELAY_SECONDS = 30.0

# Ceiling on one page's body. See _fetch: the previous code read `response.content`,
# which httpx does not bound, so the size of a snapshot was decided by a third
# party. 5 MB is roughly forty times the largest page in the registry.
MAX_RESPONSE_BYTES = 5 * 1024 * 1024

# How many portal fetches may be in flight across the whole worker.
#
# Every portal in migration 015 carries one of two cron expressions, so twenty of
# them fire at 00:00 and eleven at each six-hour mark. APScheduler's
# `max_instances=1` bounds re-entry of a single job, not the number of jobs, so
# that was twenty simultaneous outbound requests from a one-CPU VM, several of them
# to the same host. The scheduler now jitters start times and this caps what gets
# through even when the jitter clusters.
MAX_CONCURRENT_FETCHES = 4

# A host that asks us to slow down has not failed, so it must not count toward
# FAILURE_THRESHOLD: doing so would mark a healthy, popular source unreachable for
# being busy and send a reviewer looking for a fault that does not exist. See
# _fetch for which codes qualify and _record_rate_limited for what happens next.
#
# Longest Retry-After we will carry into the host throttle. Beyond this the next
# scheduled crawl arrives first anyway, so there is nothing to hold.
MAX_HONOURED_RETRY_AFTER_SECONDS = 900.0

# Chrome to remove before extracting passages.
#
# `script, style, nav` alone was not enough, and a live crawl showed exactly how:
# the first passage extracted from every gov.uk page was "We use some essential
# cookies to make this website work." A cookie banner is not a visa requirement,
# but it is a `<p>` inside `<body>`, so it became a passage, got embedded, and was
# retrievable — meaning a student could in principle be shown a citation to a
# cookie notice as evidence about their visa. Site chrome has to go before the
# content survey, not be filtered out afterwards by guessing at its wording.
_STRIP_SELECTOR = (
    "script, style, nav, header, footer, aside, noscript, iframe, form, "
    "svg, button, "
    # Cookie and consent banners. Matched on the attribute conventions these
    # actually use, since there is no semantic element for them.
    "[role=banner], [role=navigation], [role=complementary], "
    "[class*=cookie], [id*=cookie], [class*=consent], [id*=consent], "
    "[class*=banner], [class*=skip-link], [class*=breadcrumb], "
    "[data-module*=cookie], [aria-label*=okie], "
    # Text present for screen readers only, and decorative nodes hidden from them.
    #
    # A live crawl of study-in-germany.de produced the section path "Step 1:
    # Determine the type of Stay Determine the type of Stay", because the heading is
    # `<h2><span class="sr-only">Step 1: Determine the type of Stay</span>Determine
    # the type of Stay</h2>` and deep text extraction concatenates both. Every
    # citation under that heading would have carried the doubled text.
    #
    # Removing the hidden copy rather than the visible one is deliberate: a citation
    # should read the way the page reads when a student opens it. gov.uk uses the
    # same convention at scale for "(opens in a new tab)" and "Skip to main
    # content", so this removes noise across the registry, not just one page.
    "[class*=sr-only], [class*=visually-hidden], [class*=visuallyhidden], "
    "[class*=screen-reader], [class*=show-for-sr], [aria-hidden=true], [hidden]"
)

# A passage shorter than this is navigation debris, a lone label, or a fragment,
# not a statement a citation can rest on.
MIN_PASSAGE_CHARS = 40

# Status codes that mean "this host refuses automated clients", as distinct from
# "something went wrong". Several government sites sit behind a WAF that returns
# 403 to any non-browser client no matter how well-formed and polite the request:
# a live check found travel.state.gov, immi.homeaffairs.gov.au and mofa.go.jp all
# doing this while their robots.txt permits crawling.
#
# These are not transient, so retrying on a six-hour cron forever wastes the crawl
# budget and hammers a host that has already said no. The portal is disabled once
# and surfaced to a reviewer, who can register a reachable alternative — every
# affected country in the registry has one.
#
# Note what is deliberately *not* done here: the User-Agent is not changed to
# impersonate a browser. It exists to say honestly who we are and give a contact
# address, and defeating a block by disguise would contradict the same
# transparency this product asks of everyone else.
_REFUSES_AUTOMATION = frozenset({401, 403})

# Alternate renderings of a page we already have. Crawling these stores the same
# passages twice under two snapshot ids.
_DUPLICATE_VIEW = re.compile(r"/(print|printable|share|email)/?$", re.I)
_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}
_CONTENT_TAGS = {"p", "li", "td", "th", "blockquote", "dd", "dt", "figcaption", "caption"}
_WS_RE = re.compile(r"\s+")
_BANGLA_RE = re.compile(r"[ঀ-৿]")

# --- Bounded same-site expansion --------------------------------------------
#
# A registered portal is a starting point, not the whole source. `gov.uk/student-visa`
# is an index whose real content ("money", "documents you'll need", "knowledge of
# English") sits one click down, so fetching only the registered URL captured
# almost none of what a student actually asks about. Following links makes each
# portal a small site crawl.
#
# Every bound here exists to keep that from becoming an open-ended web crawl on a
# machine with one CPU and a politeness obligation to government sites:
#   * same registrable domain only, so a link out is never followed;
#   * one level down, because the value is in a section's own pages, not the
#     whole site;
#   * a hard page cap per portal per run;
#   * robots.txt and the existing per-host throttle apply to every child fetch,
#     which is what makes the cap a floor on wall-clock time too.
MAX_CHILD_PAGES = 8
MAX_CRAWL_DEPTH = 1

# Extensions that are never worth fetching as a passage source.
_SKIP_SUFFIXES = (
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".zip", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".mp4", ".mp3", ".css", ".js", ".xml", ".json", ".rss",
)

# Link text or href fragments that mark a page as worth following. Untargeted
# expansion wastes the page budget on cookie policies and press releases; these
# are the words that actually appear on the pages a visa applicant needs.
#
# Deliberately stems, not whole words. "financial" missed studyinnl.org's
# "Financing your studies" and its /finances path, and "study" misses "studies",
# which is how a genuinely relevant page gets skipped. Stems cost a little
# precision — the path-prefix rule and the chrome strip are what supply precision
# here — in exchange for not silently dropping the page a student needs.
# The list grew once `_below_prefix` made the filter actually run. While it was
# matching the whole path it admitted every child of every portal, so words that a
# student visa page cannot do without were missing and nobody noticed: "course" was
# not a hint, which would have dropped gov.uk/student-visa/course the moment the
# filter started working. The additions below are all words that name a cost, a
# document, a condition, or an outcome an applicant asks about, and none of them
# match the chrome pages that share a section prefix (cookies, privacy, terms,
# accessibility, feedback, sitemap).
_RELEVANT_HINTS = (
    "visa", "stud", "financ", "fee", "cost", "money", "fund", "tuition",
    "maintenance", "docum", "requir", "eligib", "appl", "admis", "enrol",
    "deadline", "date", "scholar", "award", "grant", "bursar",
    "english", "ielts", "toefl", "languag",
    "permit", "residen", "extend", "depend", "biometric", "interview",
    "proof", "bank", "solvenc", "sponsor", "insur", "accommodat", "housing",
    "cours", "eviden", "surcharg", "health", "medical", "work", "famil",
    "translat", "refus", "switch", "arriv", "renew", "decision", "process",
)


def registrable_domain(host: str) -> str:
    """Best-effort registrable domain, good enough to keep a crawl on one site.

    Deliberately not a public-suffix-list dependency: this only has to answer
    "is this the same site", and it errs toward *narrower* matching, which fails
    closed by skipping a link rather than by wandering off the site.
    """
    # Strip a leading www. first, or `www.gov.uk` and `gov.uk` compare unequal and
    # a site's links to its own bare domain look off-site.
    host = (host or "").lower().removeprefix("www.")
    parts = host.split(".")
    if len(parts) <= 2:
        return ".".join(parts)
    # Two-part public suffixes we actually encounter on this registry:
    # gov.uk, ac.uk, co.uk, gov.au, edu.au, go.jp, gov.bd, ac.bd, org.bd.
    if parts[-2] in {"gov", "ac", "co", "edu", "or", "go", "org", "com", "net"} and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def discover_links(html: str, base_url: str, *, limit: int = MAX_CHILD_PAGES) -> list[str]:
    """Same-site, relevance-filtered child URLs for one page.

    Returned in document order and de-duplicated, so the budget is spent on the
    links a site puts first, which on a government page is its own navigation
    into the section rather than the footer.
    """
    base = urlparse(base_url)
    base_domain = registrable_domain(base.netloc)
    # A child must live under the parent's own path. A live crawl of
    # gov.uk/student-visa without this rule returned gov.uk/browse/tax, because
    # the site-wide navigation link "Money and tax" matched the "money" hint. The
    # relevance hints alone cannot tell a section's own sub-pages from a global
    # menu that happens to use the same vocabulary; the path can.
    base_prefix = base.path.rstrip("/")

    seen: set[str] = set()
    out: list[str] = []

    try:
        tree = HTMLParser(html)
    except Exception:  # noqa: BLE001 - malformed markup is not worth raising for
        return []

    # Strip chrome before looking for links, for the same reason extraction does:
    # headers, footers and nav are where the irrelevant same-site links live.
    for node in tree.css(_STRIP_SELECTOR):
        node.decompose()

    for node in tree.css("a"):
        href = (node.attributes or {}).get("href") or ""
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue

        # Same-site, same-section, not a duplicate rendering, not a binary. The
        # gate is shared with sitemap reading (`_acceptable_child`) so the two
        # discovery routes can never apply different bounds. It is also where the
        # fragment and the query string are dropped: gov.uk decorates its own
        # navigation with `?step-by-step-nav=<uuid>`, which made
        # `/student-visa/course` and `/student-visa/course?step-by-step-nav=...`
        # look like two different pages.
        clean = _acceptable_child(
            urljoin(base_url, href), base_domain=base_domain, base_prefix=base_prefix
        )
        if clean is None:
            continue
        if clean in seen or clean.rstrip("/") == base_url.rstrip("/"):
            continue

        # Only the part of the path below the parent counts, plus the link text.
        # See _below_prefix: matching the whole path made this filter admit
        # everything, because the parent's own path is a prefix of every child's.
        haystack = (
            f"{_below_prefix(urlparse(clean).path, base_prefix)} "
            f"{(node.text() or '').lower()}"
        )
        if not any(hint in haystack for hint in _RELEVANT_HINTS):
            continue

        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break

    return out


def _below_prefix(path: str, base_prefix: str) -> str:
    """The part of a child's path that is not inherited from its parent.

    Relevance hints have to be matched against this, not against the whole path,
    and getting that wrong made the hint filter a no-op for child expansion. Every
    child of `gov.uk/student-visa` has "visa" and "stud" in its path by definition,
    because the parent's own path is a prefix of it. So `/student-visa/cookies`
    matched the "stud" hint and was admitted as relevant, and the same held for
    `/study-permit.html`, `/student-500` and most of the registry.

    The path-prefix rule was carrying the entire precision burden while the hints
    looked like they were helping. Comparing only the segments below the parent
    restores the filter: `/cookies` matches nothing, `/money` matches "money".
    """
    if not base_prefix:
        return path.lower()
    trimmed = path.rstrip("/")
    base_lower = base_prefix.lower().rstrip("/")
    trimmed_lower = trimmed.lower()
    if trimmed_lower == base_lower:
        return ""
    if trimmed_lower.startswith(f"{base_lower}/"):
        return trimmed_lower[len(base_lower) :]
    return trimmed_lower


def _acceptable_child(absolute: str, *, base_domain: str, base_prefix: str) -> str | None:
    """Shared gate for a candidate child URL. Returns a cleaned URL or None.

    Factored out so link scraping and sitemap reading cannot drift apart. A URL
    arriving from a sitemap is not more trustworthy than one scraped from an
    anchor: it must clear the same same-site, same-section, not-a-duplicate and
    relevance tests, or the sitemap becomes a way to bypass every bound the
    expansion has.
    """
    parsed = urlparse(absolute)
    if parsed.scheme not in ("http", "https"):
        return None
    if registrable_domain(parsed.netloc) != base_domain:
        return None
    if parsed.path.lower().endswith(_SKIP_SUFFIXES):
        return None
    if base_prefix and not parsed.path.rstrip("/").startswith(f"{base_prefix}/"):
        return None
    if _DUPLICATE_VIEW.search(parsed.path):
        return None
    return parsed._replace(fragment="", query="").geturl()


# Bounds on reading a site's own sitemap. Sitemaps are routinely tens of megabytes
# and index files nest, so every dimension is capped: bytes on the wire, how many
# index children are opened, and how many <loc> entries are considered at all.
MAX_SITEMAP_BYTES = 2 * 1024 * 1024
MAX_SITEMAP_FILES = 3
MAX_SITEMAP_LOCS = 5_000
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.I)
_SITEMAP_INDEX_RE = re.compile(r"<sitemapindex", re.I)


def parse_sitemap_locs(xml: str, *, limit: int = MAX_SITEMAP_LOCS) -> tuple[list[str], bool]:
    """URLs from a sitemap or sitemap index, and whether it was an index.

    Read with a regular expression rather than an XML parser on purpose. This is
    hostile input from a third party, and Python's stdlib XML parsers are documented
    as unsafe against entity-expansion attacks on untrusted data; pulling in defusedxml
    to read one element type would be a dependency for nothing. A sitemap's grammar
    for what we need is a single flat element, so there is no structure to lose.
    """
    return _LOC_RE.findall(xml)[:limit], bool(_SITEMAP_INDEX_RE.search(xml))


async def discover_from_sitemap(
    client: httpx.AsyncClient,
    portal_url: str,
    *,
    limit: int,
) -> list[str]:
    """Child URLs for `portal_url` taken from the sitemaps its robots.txt declares.

    Link scraping finds what a page chooses to link. That is usually enough and is
    always the better first source, because a link is the site's own statement that
    one page leads to another. But a section's index often links only the first few
    of its pages behind a "show all" control that needs JavaScript, and the pages a
    student needs are the ones further down. A sitemap is the site's own machine-
    readable list of what exists, published for exactly this purpose.

    Only consulted when scraping under-fills the budget, and every URL still has to
    clear `_acceptable_child`, so this widens coverage without widening the bounds.
    """
    if limit <= 0:
        return []
    try:
        declared = await _robots.sitemaps(client, portal_url)
    except Exception as exc:  # noqa: BLE001 - never fail a crawl over a sitemap
        log.debug("sitemap lookup failed for %s: %s", portal_url, exc)
        return []
    if not declared:
        return []

    base = urlparse(portal_url)
    base_domain = registrable_domain(base.netloc)
    base_prefix = base.path.rstrip("/")
    # A portal at the site root has no prefix to filter on, so a sitemap would offer
    # the entire site. The relevance hints alone are not a strong enough bound for
    # that, so sitemap reading is skipped and link scraping stands on its own.
    if not base_prefix:
        return []

    out: list[str] = []
    seen: set[str] = set()
    queue = list(declared[:MAX_SITEMAP_FILES])
    opened = 0

    while queue and opened < MAX_SITEMAP_FILES and len(out) < limit:
        sitemap_url = queue.pop(0)
        if registrable_domain(urlparse(sitemap_url).netloc) != base_domain:
            continue
        opened += 1
        await _throttle.wait(sitemap_url)
        try:
            fetched = await _fetch(client, sitemap_url)
        except Exception as exc:  # noqa: BLE001 - a missing sitemap is normal
            log.debug("sitemap fetch failed %s: %s", sitemap_url, exc)
            continue
        if len(fetched.content) > MAX_SITEMAP_BYTES:
            continue

        locs, is_index = parse_sitemap_locs(fetched.text)
        if is_index:
            # One level of index recursion, and only into children whose own URL
            # looks like it covers this section, so a site-wide index does not cost
            # three unrelated fetches.
            for loc in locs:
                if len(queue) + opened >= MAX_SITEMAP_FILES:
                    break
                if base_prefix.strip("/").split("/")[0] in loc:
                    queue.append(loc)
            continue

        for loc in locs:
            clean = _acceptable_child(
                urljoin(sitemap_url, loc), base_domain=base_domain, base_prefix=base_prefix
            )
            if clean is None or clean in seen:
                continue
            if clean.rstrip("/") == portal_url.rstrip("/"):
                continue
            # A sitemap gives a URL and nothing else, so the path below the parent
            # is the only evidence of relevance available here. There is no link
            # text to fall back on, which is one more reason anchors are consulted
            # first.
            haystack = _below_prefix(urlparse(clean).path, base_prefix)
            if not any(hint in haystack for hint in _RELEVANT_HINTS):
                continue
            seen.add(clean)
            out.append(clean)
            if len(out) >= limit:
                break

    return out


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _collapse_ws(text: str) -> str:
    return _WS_RE.sub(" ", text).strip()


def _detect_lang(text: str) -> str:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return "en"
    bangla = len(_BANGLA_RE.findall(text))
    return "bn" if bangla / len(letters) > 0.3 else "en"


# Where a page's own content lives, most specific first. Stripping chrome removes
# what is recognisably chrome; this positively selects what is recognisably content,
# which also excludes the parts of a page that are neither, such as a related-links
# rail or a feedback panel that uses none of the conventions _STRIP_SELECTOR knows.
_CONTENT_ROOT_SELECTORS = (
    "main",
    "[role=main]",
    "#main-content",
    "#content",
    ".govuk-main-wrapper",
    "article",
)

# A content region holding less than this is a wrapper the site uses for something
# else, not the page body, so fall back to <body> rather than trust the selector.
MIN_CONTENT_ROOT_CHARS = 200


def _descendants(node: Any) -> Any:
    """Every element under `node`, in document order, and not one element more.

    Neither of selectolax's obvious tools does this, and both failures are quiet.

    `Node.traverse()` does not stop at the end of the subtree: called on a `<main>`,
    it keeps going into the elements that follow it in the document. That was
    harmless while the root was always `<body>`, since nothing follows the body, and
    became a leak as soon as a narrower content region was selected: chrome before
    the region was excluded and chrome after it was not.

    `Node.css("h1, h2, p, li, ...")` is correctly scoped to the subtree but returns
    matches grouped by simple selector rather than in document order, so every
    heading arrives before every paragraph. That silently destroys the heading
    breadcrumb, which is what makes a citation read "Money you need > Course fees"
    instead of a bare snapshot id, and it also scrambles the passage ordinal.

    An explicit pre-order walk over direct children is scoped and ordered. HTML
    nesting depth is small enough that recursion is not a concern here.
    """
    for child in node.iter(include_text=False):
        yield child
        yield from _descendants(child)


def _content_root(tree: HTMLParser) -> Any:
    """The narrowest element that plausibly holds the page's own content.

    Guarded by a length floor in both directions. A site that puts `<main>` around
    a sidebar, or that opens `<main>` and closes it immediately, must not reduce a
    page to nothing: in that case the whole body is used, which is the previous
    behaviour and is never worse than empty.
    """
    for selector in _CONTENT_ROOT_SELECTORS:
        try:
            node = tree.css_first(selector)
        except Exception:  # noqa: BLE001 - a selector must never fail a crawl
            continue
        if node is None:
            continue
        if len(_collapse_ws(node.text(separator=" ", strip=True))) >= MIN_CONTENT_ROOT_CHARS:
            return node
    return tree.body or tree.root


def normalise_and_extract(html: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip script/style/nav chrome; return (normalised_page_text, passages).

    Each passage keeps `section_path`, the heading breadcrumb it sits under
    (docs/database.md section 3.3), which is what lets a citation read
    "Requirements > Financial evidence" instead of just a snapshot id.
    """
    tree = HTMLParser(html)
    for node in tree.css(_STRIP_SELECTOR):
        node.decompose()

    root = _content_root(tree)
    if root is None:
        return "", []

    normalised_text = _collapse_ws(root.text(separator=" ", strip=True))

    passages: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []
    # Repeated text within one page, deduplicated by hash. Government pages repeat
    # a standing sentence in several sections ("You must show you have enough money
    # to support yourself", "Check the guidance before you apply"), and each copy
    # used to become its own passage: embedded separately, stored separately, and
    # retrievable separately, so one fact could fill several of the shortlist slots
    # a grounded answer has to choose from.
    seen_hashes: set[str] = set()
    ordinal = 0
    for node in _descendants(root):
        tag = node.tag
        if tag in _HEADING_LEVELS:
            level = _HEADING_LEVELS[tag]
            text = _collapse_ws(node.text(deep=True, separator=" ", strip=True))
            if text:
                heading_stack[:] = [h for h in heading_stack if h[0] < level]
                heading_stack.append((level, text))
            continue
        if tag not in _CONTENT_TAGS:
            continue
        text = _collapse_ws(node.text(deep=True, separator=" ", strip=True))
        if len(text) < MIN_PASSAGE_CHARS:
            continue
        text_hash = sha256_hex(text)
        if text_hash in seen_hashes:
            continue
        seen_hashes.add(text_hash)
        passages.append(
            {
                "ordinal": ordinal,
                "section_path": " > ".join(h[1] for h in heading_stack) or None,
                "text": text,
                "text_hash": text_hash,
                "lang": _detect_lang(text),
                "char_count": len(text),
            }
        )
        ordinal += 1
    return normalised_text, passages


class _RobotsCache:
    """One `RobotFileParser` per host, refreshed hourly.

    Fetches robots.txt through our own httpx client (real UA, real timeout)
    rather than `RobotFileParser.read()`'s blocking urllib opener.

    The same parsed file answers three questions, so all three are read from here
    rather than being guessed at elsewhere: may we fetch this path, how long has
    the host asked us to wait between requests, and which sitemaps does it
    publish.
    """

    def __init__(self) -> None:
        self._parsers: dict[str, tuple[RobotFileParser, float]] = {}
        # One lock per host, so twenty portals on gov.uk starting at the same
        # minute fetch robots.txt once between them instead of twenty times.
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = self._locks[host] = asyncio.Lock()
        return lock

    async def _parser(self, client: httpx.AsyncClient, url: str) -> RobotFileParser:
        parsed = urlparse(url)
        host = parsed.netloc
        async with self._lock_for(host):
            now = time.monotonic()
            cached = self._parsers.get(host)
            if cached is not None and now - cached[1] <= 3600:
                return cached[0]
            parser = RobotFileParser()
            robots_url = f"{parsed.scheme}://{host}/robots.txt"
            try:
                r = await client.get(robots_url, timeout=10.0)
                # A 404 (no robots.txt at all) is the common case for the
                # small government/university sites this watches and is not
                # a reason to refuse to watch a public page.
                parser.parse(r.text.splitlines() if r.status_code == 200 else [])
            except httpx.HTTPError:
                parser.parse([])
            self._parsers[host] = (parser, now)
            return parser

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parser = await self._parser(client, url)
        return parser.can_fetch(USER_AGENT, url)

    async def crawl_delay(self, client: httpx.AsyncClient, url: str) -> float | None:
        """The host's requested gap between requests, in seconds, if it states one.

        `Crawl-delay` is not in the original robots.txt specification, but it is
        widely served and `RobotFileParser` has parsed it since Python 3.6. Ignoring
        a delay a host went out of its way to publish, while claiming in the
        User-Agent to be a polite watcher, would be the wrong way round.
        """
        parser = await self._parser(client, url)
        try:
            declared = parser.crawl_delay(USER_AGENT)
        except Exception:  # noqa: BLE001 - a malformed value must not stop a crawl
            return None
        if declared is None:
            return None
        try:
            return float(declared)
        except (TypeError, ValueError):
            return None

    async def sitemaps(self, client: httpx.AsyncClient, url: str) -> list[str]:
        parser = await self._parser(client, url)
        return list(parser.site_maps() or [])


class _HostThrottle:
    """Serialises requests to one host, whatever the calling concurrency.

    The previous version had a race that made it decorative under exactly the
    conditions it existed for. It read the last-request time, slept the remainder,
    and *then* recorded the timestamp. Two coroutines entering together both read
    the same stale timestamp, both computed the same remaining delay, both slept it,
    and both fired at the same instant. The registry has three portals on gov.uk and
    three on canada.ca sharing one cron, so that was reachable in production.

    The fix is to reserve a slot rather than measure a gap. Under a per-host lock,
    each caller takes the next free instant and immediately publishes the one after
    it, then sleeps outside the lock. N callers get N staggered slots instead of N
    identical ones, and the lock is never held across a sleep.
    """

    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._next_free: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock_for(self, host: str) -> asyncio.Lock:
        lock = self._locks.get(host)
        if lock is None:
            lock = self._locks[host] = asyncio.Lock()
        return lock

    async def wait(self, url: str, *, min_interval: float | None = None) -> None:
        host = urlparse(url).netloc
        interval = self._min_interval
        if min_interval is not None:
            # A host asking for longer is honoured; a host asking for less than our
            # own politeness floor is not, because the floor is our policy.
            interval = max(interval, min_interval)

        async with self._lock_for(host):
            now = time.monotonic()
            start = max(now, self._next_free.get(host, 0.0))
            self._next_free[host] = start + interval
            delay = start - now

        if delay > 0:
            await asyncio.sleep(delay)

    async def penalise(self, url: str, seconds: float) -> None:
        """Hold back every request to this host for `seconds`.

        Called when a host returns 429. The portal that was refused gives up on
        this cycle, but the useful part is the effect on its neighbours: the
        registry has three portals on gov.uk and three on canada.ca, and a rate
        limit is a property of the host, not of the one URL that happened to hit
        it. Without this, the other two would walk into the same limit minutes
        later and each conclude separately that it should back off.
        """
        host = urlparse(url).netloc
        capped = max(0.0, min(seconds, MAX_HONOURED_RETRY_AFTER_SECONDS))
        async with self._lock_for(host):
            self._next_free[host] = max(
                self._next_free.get(host, 0.0), time.monotonic() + capped
            )


_robots = _RobotsCache()
_throttle = _HostThrottle(MIN_HOST_INTERVAL_SECONDS)

# Module-level, so every crawl job in the worker shares one budget. Safe to build
# at import time: since Python 3.10 an asyncio.Semaphore binds to the running loop
# on first use rather than at construction.
_fetch_slots = asyncio.Semaphore(MAX_CONCURRENT_FETCHES)


class ResponseTooLarge(Exception):
    """A portal served more bytes than a page of text can justify."""


class RateLimited(Exception):
    """The host asked us to slow down. Not a fault, and not retryable here."""

    def __init__(self, status_code: int, retry_after: float | None) -> None:
        super().__init__(f"HTTP {status_code}, retry_after={retry_after}")
        self.status_code = status_code
        self.retry_after = retry_after


class Fetched:
    """What the crawler needs from a response, detached from the HTTP client.

    `httpx.Response` cannot be passed around here any more: the body is now read
    under a byte budget rather than by touching `.content`, and a 304 has no body
    at all. Carrying an explicit result also means extraction and snapshot writing
    can be tested without constructing a transport.
    """

    __slots__ = ("status_code", "content", "text", "etag", "last_modified")

    def __init__(
        self,
        *,
        status_code: int,
        content: bytes,
        text: str,
        etag: str | None,
        last_modified: str | None,
    ) -> None:
        self.status_code = status_code
        self.content = content
        self.text = text
        self.etag = etag
        self.last_modified = last_modified

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


def _parse_retry_after(value: str | None) -> float | None:
    """Seconds from a Retry-After header, which may be a delay or an HTTP date."""
    if not value:
        return None
    raw = value.strip()
    try:
        return max(0.0, float(raw))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if when is None:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _is_retryable(exc: BaseException) -> bool:
    # A 4xx is the site telling us something concrete (gone, forbidden,
    # moved); retrying it just delays surfacing a real failure. A 5xx or a
    # network-level fault is exactly the transient case retry exists for.
    #
    # 429 is excluded on purpose even though it is the one 4xx that means "try
    # again": tenacity would retry it on our own exponential schedule, ignoring
    # the delay the host actually asked for. It is raised as RateLimited and
    # handled by the caller, which can read Retry-After.
    if isinstance(exc, RateLimited):
        return False
    if isinstance(exc, ResponseTooLarge):
        return False
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


def conditional_headers(portal: dict[str, Any]) -> dict[str, str]:
    """If-None-Match / If-Modified-Since from the validators the host gave us.

    Sent as a pair when both are stored. RFC 9110 has the origin server prefer
    If-None-Match when both are present, so sending both is not ambiguous and
    covers hosts that support only one.
    """
    headers: dict[str, str] = {}
    etag = (portal.get("etag") or "").strip()
    last_modified = (portal.get("last_modified") or "").strip()
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    return headers


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1.5, min=1, max=30),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _fetch(
    client: httpx.AsyncClient, url: str, *, headers: dict[str, str] | None = None
) -> Fetched:
    """Fetch one page under a byte budget, honouring conditional requests.

    Streamed rather than read whole. `response.content` imposes no limit, so a
    portal that started serving a large file (a mirrored dataset, an error page
    with an embedded core dump, a misconfigured export endpoint) would have been
    downloaded in full, written to the snapshot volume, and hashed. On a VM whose
    whole value proposition is that it is small, that is a disk-exhaustion path
    reachable by a third party changing a page we do not control.
    """
    async with client.stream(
        "GET", url, headers=headers or None, timeout=FETCH_TIMEOUT_SECONDS
    ) as response:
        if response.status_code == 304:
            # No body, and none expected. The stored validators stay as they are.
            return Fetched(
                status_code=304, content=b"", text="", etag=None, last_modified=None
            )
        retry_after = _parse_retry_after(response.headers.get("retry-after"))
        # 429 always means "not now". A 503 means it only when the host says when
        # to come back; a bare 503 is an ordinary transient server fault and stays
        # on the retry path above, which is what tenacity's backoff is for.
        if response.status_code == 429 or (
            response.status_code == 503 and retry_after is not None
        ):
            raise RateLimited(response.status_code, retry_after)
        response.raise_for_status()

        # Trust a declared length enough to refuse before spending the bandwidth,
        # but never enough to skip counting what actually arrives.
        declared = response.headers.get("content-length", "")
        if declared.isdigit() and int(declared) > MAX_RESPONSE_BYTES:
            raise ResponseTooLarge(f"{url} declares {declared} bytes")

        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ResponseTooLarge(f"{url} exceeded {MAX_RESPONSE_BYTES} bytes")

        raw = bytes(body)
        # errors="replace" rather than raising: one bad byte in a government page
        # should cost that character, not the whole crawl of that source.
        text = raw.decode(response.encoding or "utf-8", errors="replace")
        return Fetched(
            status_code=response.status_code,
            content=raw,
            text=text,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
        )


async def crawl_portal(
    *,
    portal_id: int,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    http_client: httpx.AsyncClient,
) -> None:
    """Fetch one portal. Stop on an unchanged hash; snapshot and emit on a
    real change; back off and surface on repeated failure. Never fabricates
    a snapshot: a failed fetch touches only `portals`, never `snapshots`."""
    portals = PortalRepo(dbs.app)
    snapshots = SnapshotRepo(dbs.app)

    portal = await portals.get(portal_id)
    if portal is None or not portal["enabled"]:
        return

    if not await _robots.allowed(http_client, portal["url"]):
        await portals.patch(portal_id, {"last_fetch_at": utc_now_iso()})
        log.info("robots.txt disallows portal_id=%s url=%s; skipping", portal_id, portal["url"])
        return

    declared_delay = await _robots.crawl_delay(http_client, portal["url"])
    if declared_delay is not None and declared_delay > MAX_HONOURED_CRAWL_DELAY_SECONDS:
        log.info(
            "host declares Crawl-delay=%.0fs for %s; crawling at the %.0fs cap instead",
            declared_delay, portal["url"], MAX_HONOURED_CRAWL_DELAY_SECONDS,
        )
        declared_delay = MAX_HONOURED_CRAWL_DELAY_SECONDS

    # The semaphore is taken around the throttle wait as well as the fetch, so a
    # coroutine queued behind a host delay does not also hold a fetch slot open.
    async with _fetch_slots:
        await _throttle.wait(portal["url"], min_interval=declared_delay)
        try:
            fetched = await _fetch(
                http_client, portal["url"], headers=conditional_headers(portal)
            )
        except RateLimited as exc:
            await _record_rate_limited(portals, portal, exc)
            return
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code in _REFUSES_AUTOMATION:
                await _record_blocked(portals, bus, portal, exc.response.status_code)
                return
            await _record_failure(portals, bus, portal, exc)
            return
        except Exception as exc:  # noqa: BLE001 - every other fetch failure mode
            await _record_failure(portals, bus, portal, exc)
            return

    now = utc_now_iso()

    # The host answered the question without sending the page. Nothing to extract,
    # nothing to hash, nothing to compare: recorded as 'unchanged' rather than 'ok'
    # so a reviewer can see this outcome came from a validator and not from a body
    # we actually read (migration 018).
    if fetched.not_modified:
        await portals.patch(
            portal_id,
            {"last_fetch_at": now, "last_status": "unchanged", "consecutive_failures": 0},
        )
        await bus.publish(
            EventType.PORTAL_FETCHED,
            payload={
                "portal_id": portal_id,
                "portal_public_id": portal["public_id"],
                "changed": False,
                "not_modified": True,
            },
            actor="worker:crawler",
            subject_type="portal",
            subject_id=portal["public_id"],
        )
        return

    normalised_text, passages = normalise_and_extract(fetched.text)
    content_hash = sha256_hex(normalised_text)

    # Store whatever validators came back even when the content is unchanged: a host
    # that rotates its ETag on every deploy would otherwise never get a usable
    # conditional request, because the one we hold would always be stale.
    validators = _validator_fields(fetched)

    previous = await snapshots.latest_for_portal(portal_id)
    if previous is not None and previous["content_hash"] == content_hash:
        if await _repair_incomplete_snapshot(
            dbs=dbs,
            bus=bus,
            portal=portal,
            snapshot=previous,
            snapshots=snapshots,
            passages=passages,
            now=now,
        ):
            await portals.patch(
                portal_id,
                {
                    "last_fetch_at": now,
                    "last_status": "ok",
                    "consecutive_failures": 0,
                    **validators,
                },
            )
            return

        await portals.patch(
            portal_id,
            {
                "last_fetch_at": now,
                "last_status": "ok",
                "consecutive_failures": 0,
                **validators,
            },
        )
        await bus.publish(
            EventType.PORTAL_FETCHED,
            payload={
                "portal_id": portal_id,
                "portal_public_id": portal["public_id"],
                "changed": False,
            },
            actor="worker:crawler",
            subject_type="portal",
            subject_id=portal["public_id"],
        )
        return

    await _write_changed_snapshot(
        dbs=dbs,
        bus=bus,
        settings=settings,
        portal=portal,
        previous=previous,
        fetched=fetched,
        passages=passages,
        content_hash=content_hash,
        now=now,
    )
    await portals.patch(
        portal_id,
        {
            "last_fetch_at": now,
            "last_status": "ok",
            "consecutive_failures": 0,
            **validators,
        },
    )

    # Expand only curated registry roots, and only when the page actually
    # changed. Both conditions matter: expanding a discovered page would make the
    # crawl unbounded in depth, and re-discovering links from an unchanged index
    # every six hours would be pure waste, since the links cannot have moved
    # either. `discovered_at IS NULL` is the root test rather than a NULL parent,
    # because a portal found by search (app/workers/discovery.py) has no parent
    # row but is still not a root.
    if portal["discovered_at"] is None:
        await _expand_children(
            portal=portal, html=fetched.text, portals=portals, http_client=http_client
        )


def _validator_fields(fetched: Fetched) -> dict[str, Any]:
    """Only overwrite a stored validator when the host sent a replacement.

    A host that sends an ETag on one response and omits it on the next has not
    withdrawn it, so writing NULL there would throw away a working conditional
    request for no reason.
    """
    fields: dict[str, Any] = {}
    if fetched.etag:
        fields["etag"] = fetched.etag
    if fetched.last_modified:
        fields["last_modified"] = fetched.last_modified
    return fields


async def _expand_children(
    *,
    portal: dict[str, Any],
    html: str,
    portals: PortalRepo,
    http_client: httpx.AsyncClient,
) -> None:
    """Register up to MAX_CHILD_PAGES same-site child pages of `portal`.

    Registration only. The pages are not fetched here: they become ordinary
    portals and the scheduler crawls them on their own cron, which keeps one
    crawl tick bounded in time no matter how many links a page has, and means a
    child gets the same robots, throttle, snapshot, and diff treatment as
    anything else. Discovery is therefore cheap and the work is spread out.
    """
    try:
        candidates = discover_links(html, portal["url"], limit=MAX_CHILD_PAGES)
    except Exception as exc:  # noqa: BLE001 - discovery must never fail a crawl
        log.warning("link discovery failed portal_id=%s err=%s", portal["id"], exc)
        candidates = []

    # Top up from the site's own sitemap only if its links did not fill the budget.
    # Anchors come first because a link is the site asserting that one page leads to
    # another, which is better evidence of relevance than mere existence.
    if len(candidates) < MAX_CHILD_PAGES:
        from_sitemap = await discover_from_sitemap(
            http_client, portal["url"], limit=MAX_CHILD_PAGES - len(candidates)
        )
        already = {c.rstrip("/") for c in candidates}
        candidates += [u for u in from_sitemap if u.rstrip("/") not in already]

    if not candidates:
        return

    registered = 0
    for url in candidates:
        # robots.txt is checked at registration as well as at fetch time, so a
        # disallowed path never even enters the watch list a student can see.
        if not await _robots.allowed(http_client, url):
            continue
        if await portals.register_discovered(url=url, parent=portal) is not None:
            registered += 1

    if registered:
        log.info(
            "discovered %d child page(s) under portal_id=%s (%s)",
            registered, portal["id"], portal["label"],
        )


async def _portal_changed_emitted(dbs: Databases, snapshot_id: int) -> bool:
    row = await dbs.events.fetch_val(
        """SELECT 1 FROM events
           WHERE type = ? AND json_extract(payload, '$.snapshot_id') = ?
           LIMIT 1""",
        (EventType.PORTAL_CHANGED.value, snapshot_id),
    )
    return row is not None


async def _repair_incomplete_snapshot(
    *,
    dbs: Databases,
    bus: EventBus,
    portal: dict[str, Any],
    snapshot: dict[str, Any],
    snapshots: SnapshotRepo,
    passages: list[dict[str, Any]],
    now: str,
) -> bool:
    """Re-finish a hash-matched snapshot that never got passages or portal.changed."""
    snapshot_id = snapshot["id"]
    stored_passages = await snapshots.list_passages(snapshot_id)
    missing_passages = bool(passages) and not stored_passages
    missing_event = not await _portal_changed_emitted(dbs, snapshot_id)
    if not missing_passages and not missing_event:
        return False

    if missing_passages:
        async with dbs.app.transaction() as tx:
            for p in passages:
                await tx.execute(
                    """INSERT INTO passages
                       (snapshot_id, ordinal, section_path, text, text_hash, lang, char_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        p["ordinal"],
                        p["section_path"],
                        p["text"],
                        p["text_hash"],
                        p["lang"],
                        p["char_count"],
                    ),
                )

    if missing_event:
        prev_row = await dbs.app.fetch_one(
            """SELECT id FROM snapshots
               WHERE portal_id = ? AND id != ?
               ORDER BY fetched_at DESC LIMIT 1""",
            (portal["id"], snapshot_id),
        )
        await bus.publish(
            EventType.PORTAL_FETCHED,
            payload={
                "portal_id": portal["id"],
                "portal_public_id": portal["public_id"],
                "changed": True,
                "repaired": True,
            },
            actor="worker:crawler",
            subject_type="portal",
            subject_id=portal["public_id"],
        )
        await bus.publish(
            EventType.PORTAL_CHANGED,
            payload={
                "portal_id": portal["id"],
                "portal_public_id": portal["public_id"],
                "snapshot_id": snapshot_id,
                "snapshot_public_id": snapshot["public_id"],
                "previous_snapshot_id": prev_row["id"] if prev_row else None,
                "repaired": True,
            },
            actor="worker:crawler",
            subject_type="snapshot",
            subject_id=snapshot["public_id"],
        )
    log.info(
        "repaired incomplete snapshot portal_id=%s snapshot_id=%s passages=%s event=%s",
        portal["id"], snapshot_id, missing_passages, missing_event,
    )
    return True


async def _write_changed_snapshot(
    *,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    portal: dict[str, Any],
    previous: dict[str, Any] | None,
    fetched: Fetched,
    passages: list[dict[str, Any]],
    content_hash: str,
    now: str,
) -> None:
    raw_bytes = fetched.content
    storage_path = settings.snapshot_dir / f"{content_hash}.html"
    # Content-addressed: if two portals (or two fetches) ever normalise to
    # the same hash, the file is already there and is not rewritten.
    if not storage_path.exists():
        storage_path.write_bytes(raw_bytes)

    snapshot_public_id = new_ulid()
    async with dbs.app.transaction() as tx:
        await tx.execute(
            """INSERT INTO snapshots
               (public_id, portal_id, content_hash, storage_path, http_status,
                byte_size, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_public_id,
                portal["id"],
                content_hash,
                str(storage_path),
                fetched.status_code,
                len(raw_bytes),
                now,
            ),
        )
    snapshot_row = await dbs.app.fetch_one(
        "SELECT id FROM snapshots WHERE public_id = ?", (snapshot_public_id,)
    )
    assert snapshot_row is not None
    snapshot_id = snapshot_row["id"]

    if passages:
        async with dbs.app.transaction() as tx:
            for p in passages:
                await tx.execute(
                    """INSERT INTO passages
                       (snapshot_id, ordinal, section_path, text, text_hash, lang, char_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        snapshot_id,
                        p["ordinal"],
                        p["section_path"],
                        p["text"],
                        p["text_hash"],
                        p["lang"],
                        p["char_count"],
                    ),
                )

    await bus.publish(
        EventType.PORTAL_FETCHED,
        payload={"portal_id": portal["id"], "portal_public_id": portal["public_id"], "changed": True},
        actor="worker:crawler",
        subject_type="portal",
        subject_id=portal["public_id"],
    )
    await bus.publish(
        EventType.PORTAL_CHANGED,
        payload={
            "portal_id": portal["id"],
            "portal_public_id": portal["public_id"],
            "snapshot_id": snapshot_id,
            "snapshot_public_id": snapshot_public_id,
            "previous_snapshot_id": previous["id"] if previous else None,
        },
        actor="worker:crawler",
        subject_type="snapshot",
        subject_id=snapshot_public_id,
    )


async def _record_failure(
    portals: PortalRepo, bus: EventBus, portal: dict[str, Any], exc: Exception
) -> None:
    failures = int(portal["consecutive_failures"]) + 1
    now = utc_now_iso()
    fields: dict[str, Any] = {"last_fetch_at": now, "consecutive_failures": failures}
    if failures >= FAILURE_THRESHOLD:
        # Only flip the visible status once the threshold is crossed, so a
        # single transient blip does not make a healthy portal look down on
        # the moderator dashboard.
        fields["last_status"] = "unreachable"
    await portals.patch(portal["id"], fields)
    log.warning(
        "crawl failed portal_id=%s url=%s consecutive_failures=%d err=%s",
        portal["id"], portal["url"], failures, exc,
    )
    if failures >= FAILURE_THRESHOLD:
        await bus.publish(
            EventType.PORTAL_UNREACHABLE,
            payload={
                "portal_id": portal["id"],
                "portal_public_id": portal["public_id"],
                "consecutive_failures": failures,
                "error": str(exc),
            },
            actor="worker:crawler",
            subject_type="portal",
            subject_id=portal["public_id"],
        )


async def _record_rate_limited(
    portals: PortalRepo, portal: dict[str, Any], exc: RateLimited
) -> None:
    """Give up on this cycle without recording a failure or raising an alert.

    Three things deliberately do not happen here. `consecutive_failures` is not
    incremented, because a rate limit says the source is working and busy, and
    letting three busy days disable a portal would be the opposite of the intended
    behaviour. No PORTAL_UNREACHABLE event is published, because nothing is
    unreachable and a moderator alert would be noise. And there is no inline retry:
    sleeping out a Retry-After would hold one of MAX_CONCURRENT_FETCHES slots doing
    nothing, when the portal's own cron is already a retry that costs nothing.

    What does happen is that the whole host is held back, so the other portals
    sharing it do not each rediscover the same limit.
    """
    wait_for = exc.retry_after if exc.retry_after is not None else MIN_HOST_INTERVAL_SECONDS * 10
    await _throttle.penalise(portal["url"], wait_for)
    # last_fetch_at is still stamped: the attempt happened, and leaving it stale
    # would make PortalRepo.count_silent report the portal as unwatched.
    await portals.patch(portal["id"], {"last_fetch_at": utc_now_iso()})
    log.info(
        "portal asked us to slow down, deferring to next cron portal_id=%s url=%s "
        "http=%d retry_after=%s",
        portal["id"], portal["url"], exc.status_code, exc.retry_after,
    )


async def _record_blocked(
    portals: PortalRepo, bus: EventBus, portal: dict[str, Any], status_code: int
) -> None:
    """Record a host that refuses automated clients, and stop asking.

    Distinct from `_record_failure`: this is a decision by the host, not an
    outage, so there is nothing to retry into. The portal is disabled immediately
    rather than after FAILURE_THRESHOLD attempts, and the event carries the status
    code so a reviewer can see it was a refusal rather than a timeout.
    """
    await portals.patch(
        portal["id"],
        {
            "enabled": 0,
            "last_fetch_at": utc_now_iso(),
            "last_status": "unreachable",
            "consecutive_failures": FAILURE_THRESHOLD,
        },
    )
    log.warning(
        "portal refuses automated clients, disabling portal_id=%s url=%s http=%d",
        portal["id"], portal["url"], status_code,
    )
    await bus.publish(
        EventType.PORTAL_UNREACHABLE,
        payload={
            "portal_id": portal["id"],
            "portal_public_id": portal["public_id"],
            "http_status": status_code,
            "reason": "host refuses automated clients; disabled, needs a human to "
                      "register a reachable alternative",
            "disabled": True,
        },
        actor="worker:crawler",
        subject_type="portal",
        subject_id=portal["public_id"],
    )
