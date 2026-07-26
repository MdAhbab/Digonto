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
    "[data-module*=cookie], [aria-label*=okie]"
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
_RELEVANT_HINTS = (
    "visa", "stud", "financ", "fee", "cost", "money", "fund", "tuition",
    "maintenance", "docum", "requir", "eligib", "appl", "admis", "enrol",
    "deadline", "date", "scholar", "award", "grant", "bursar",
    "english", "ielts", "toefl", "languag",
    "permit", "residen", "extend", "depend", "biometric", "interview",
    "proof", "bank", "solvenc", "sponsor", "insur", "accommodat", "housing",
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

        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https"):
            continue
        if registrable_domain(parsed.netloc) != base_domain:
            continue
        if parsed.path.lower().endswith(_SKIP_SUFFIXES):
            continue
        # Must be a descendant of the parent's path, not merely on the same site.
        # An empty prefix (the site root is the portal) admits any path, which is
        # correct: for a portal like studyinnl.org the whole site is the section.
        if base_prefix and not parsed.path.rstrip("/").startswith(f"{base_prefix}/"):
            continue

        # Print views duplicate a page's content at a different URL, so they would
        # be crawled, hashed, and embedded as a second copy of passages already
        # held — inflating the store and letting the same fact be cited twice from
        # two snapshots.
        if _DUPLICATE_VIEW.search(parsed.path):
            continue

        # Drop the fragment *and* the query string. gov.uk decorates its own
        # navigation with `?step-by-step-nav=<uuid>`, which made
        # `/student-visa/course` and `/student-visa/course?step-by-step-nav=...`
        # look like two different pages. Query strings on these registries are
        # navigation state, not content identity.
        clean = parsed._replace(fragment="", query="").geturl()
        if clean in seen or clean.rstrip("/") == base_url.rstrip("/"):
            continue

        haystack = f"{parsed.path.lower()} {(node.text() or '').lower()}"
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


def normalise_and_extract(html: str) -> tuple[str, list[dict[str, Any]]]:
    """Strip script/style/nav chrome; return (normalised_page_text, passages).

    Each passage keeps `section_path`, the heading breadcrumb it sits under
    (docs/database.md section 3.3), which is what lets a citation read
    "Requirements > Financial evidence" instead of just a snapshot id.
    """
    tree = HTMLParser(html)
    for node in tree.css(_STRIP_SELECTOR):
        node.decompose()

    root = tree.body or tree.root
    if root is None:
        return "", []

    normalised_text = _collapse_ws(root.text(separator=" ", strip=True))

    passages: list[dict[str, Any]] = []
    heading_stack: list[tuple[int, str]] = []
    ordinal = 0
    for node in root.traverse(include_text=False):
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
        passages.append(
            {
                "ordinal": ordinal,
                "section_path": " > ".join(h[1] for h in heading_stack) or None,
                "text": text,
                "text_hash": sha256_hex(text),
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
    """

    def __init__(self) -> None:
        self._parsers: dict[str, tuple[RobotFileParser, float]] = {}

    async def allowed(self, client: httpx.AsyncClient, url: str) -> bool:
        parsed = urlparse(url)
        host = parsed.netloc
        now = time.monotonic()
        cached = self._parsers.get(host)
        if cached is None or now - cached[1] > 3600:
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
            cached = (parser, now)
            self._parsers[host] = cached
        return cached[0].can_fetch(USER_AGENT, url)


class _HostThrottle:
    def __init__(self, min_interval: float) -> None:
        self._min_interval = min_interval
        self._last: dict[str, float] = {}

    async def wait(self, url: str) -> None:
        host = urlparse(url).netloc
        now = time.monotonic()
        last = self._last.get(host)
        if last is not None:
            remaining = self._min_interval - (now - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last[host] = time.monotonic()


_robots = _RobotsCache()
_throttle = _HostThrottle(MIN_HOST_INTERVAL_SECONDS)


def _is_retryable(exc: BaseException) -> bool:
    # A 4xx is the site telling us something concrete (gone, forbidden,
    # moved); retrying it just delays surfacing a real failure. A 5xx or a
    # network-level fault is exactly the transient case retry exists for.
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


@retry(
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=1.5, min=1, max=30),
    retry=retry_if_exception(_is_retryable),
    reraise=True,
)
async def _fetch(client: httpx.AsyncClient, url: str) -> httpx.Response:
    r = await client.get(url, timeout=FETCH_TIMEOUT_SECONDS)
    r.raise_for_status()
    return r


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
        log.info("robots.txt disallows portal_id=%s url=%s; skipping", portal_id, portal["url"])
        return

    await _throttle.wait(portal["url"])

    try:
        response = await _fetch(http_client, portal["url"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in _REFUSES_AUTOMATION:
            await _record_blocked(portals, bus, portal, exc.response.status_code)
            return
        await _record_failure(portals, bus, portal, exc)
        return
    except Exception as exc:  # noqa: BLE001 - every other fetch failure mode
        await _record_failure(portals, bus, portal, exc)
        return

    normalised_text, passages = normalise_and_extract(response.text)
    content_hash = sha256_hex(normalised_text)
    now = utc_now_iso()

    previous = await snapshots.latest_for_portal(portal_id)
    if previous is not None and previous["content_hash"] == content_hash:
        await portals.patch(
            portal_id, {"last_fetch_at": now, "last_status": "ok", "consecutive_failures": 0}
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
        response=response,
        passages=passages,
        content_hash=content_hash,
        now=now,
    )
    await portals.patch(
        portal_id, {"last_fetch_at": now, "last_status": "ok", "consecutive_failures": 0}
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
            portal=portal, html=response.text, portals=portals, http_client=http_client
        )


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


async def _write_changed_snapshot(
    *,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    portal: dict[str, Any],
    previous: dict[str, Any] | None,
    response: httpx.Response,
    passages: list[dict[str, Any]],
    content_hash: str,
    now: str,
) -> None:
    raw_bytes = response.content
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
                response.status_code,
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
