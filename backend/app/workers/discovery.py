"""Official-source discovery: turn a question nobody could answer into a source.

**The gap this closes.** When retrieval finds nothing, `app/rag/pipeline.py`
refuses and tells the student which portals are being watched. That is the right
answer, but on its own it is a dead end: the same question refuses forever unless
a human happens to notice and register the missing page. This module is the
feedback edge that closes the recurrent loop — a refusal becomes a search, the
search becomes a registered portal, the portal becomes a crawled snapshot, and the
next student who asks gets a cited answer.

**Why this does not weaken the grounding guarantee.** Nothing found here is ever
handed to the model as context. A search result contributes exactly one thing: a
URL, which is registered as a portal and then goes through the ordinary crawl,
snapshot, hash, passage-split, and embed path like every other source. The model
still only ever sees passages that came from a stored snapshot with a citable id,
so the Truth Ledger holds by construction rather than by discipline.

**Why the domain allowlist is not optional.** Open web search would let a blog, a
consultancy's marketing page, or an SEO farm become a cited source, and "every
claim traces to an official source" is the entire product. Only hosts on
`OFFICIAL_SUFFIXES` are admissible. That is a deliberately conservative filter: it
rejects plenty of legitimate pages, and rejecting a real source is a recoverable
mistake (a reviewer can register it by hand) while admitting a fake one is not.

**Cost.** DuckDuckGo's HTML endpoint needs no API key and no account, which keeps
the zero-marginal-cost property the whole deployment depends on. It is queried
politely, rate limited, and treated as untrusted markup.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

import httpx
from selectolax.parser import HTMLParser

from app.db.connection import Databases
from app.repositories.portal_repo import PortalRepo
from app.workers.crawler import USER_AGENT, registrable_domain

log = logging.getLogger(__name__)

_SEARCH_ENDPOINT = "https://html.duckduckgo.com/html/"
_SEARCH_TIMEOUT_SECONDS = 15.0

# Minimum gap between searches. The endpoint is a courtesy, not a contract, and
# hammering it is how this stops working for everyone.
MIN_SEARCH_INTERVAL_SECONDS = 10.0

# Candidate URLs considered per query, before the allowlist is applied.
MAX_RESULTS_CONSIDERED = 20
# Newly registered portals per query. A cap keeps one unlucky question from
# adding fifty pages to the crawl budget.
MAX_REGISTERED_PER_QUERY = 3

# Hosts and suffixes that may become a cited source.
#
# Government and inter-governmental suffixes, plus the specific non-.gov domains
# that are the authoritative publisher for their own programme. The named entries
# are all bodies that run a scholarship or an English test a Bangladeshi student
# applies through, and each is the primary source for its own rules.
OFFICIAL_SUFFIXES: tuple[str, ...] = (
    # Government and academic suffixes
    ".gov", ".gov.uk", ".gov.au", ".gov.bd", ".gov.in", ".gov.sg",
    ".gc.ca", ".canada.ca", ".go.jp", ".go.kr",
    ".ac.uk", ".edu", ".edu.au", ".edu.bd", ".ac.jp", ".ac.nz",
    ".europa.eu", ".int",
    # Immigration and foreign ministries that do not sit on a .gov suffix
    "homeaffairs.gov.au", "auswaertiges-amt.de", "migrationsverket.se",
    "ind.nl", "mofa.go.jp", "ustraveldocs.com",
    # Programme owners: primary source for their own award or test
    "chevening.org", "cscuk.fcdo.gov.uk", "daad.de", "fulbrightonline.org",
    "jasso.go.jp", "studyinjapan.go.jp", "study-in-germany.de",
    "studyinnl.org", "studyinsweden.se", "studyaustralia.gov.au",
    "erasmus-plus.ec.europa.eu", "ielts.org", "ets.org",
    "bb.org.bd", "ugc.gov.bd", "moedu.gov.bd",
)

# Never admissible, even if a URL somehow also matches above. Aggregators and
# question sites are exactly the "confidently wrong" sources this product exists
# to replace, and a student cannot tell them apart from an official page.
BLOCKED_HOSTS: tuple[str, ...] = (
    "wikipedia.org", "quora.com", "reddit.com", "medium.com", "blogspot.com",
    "wordpress.com", "facebook.com", "youtube.com", "linkedin.com", "x.com",
    "twitter.com", "shiksha.com", "collegedunia.com", "leverageedu.com",
    "yocket.com", "idp.com", "studyabroad.com", "timesofindia.com",
)

_SKIP_SUFFIXES = (".pdf", ".doc", ".docx", ".zip", ".jpg", ".png", ".xml")


def is_official(url: str) -> bool:
    """Whether a URL may become a cited source."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    # Scheme matters: an ftp:// or file:// URL on an allowlisted host is not a
    # page the crawler can fetch, and admitting one would register a portal that
    # can never produce a snapshot.
    if parsed.scheme not in ("http", "https"):
        return False

    host = (parsed.netloc or "").lower().split(":")[0].removeprefix("www.")
    if not host:
        return False

    domain = registrable_domain(host)
    if any(domain == b or domain.endswith(f".{b}") for b in BLOCKED_HOSTS):
        return False

    def _matches_suffix(host_name: str, suffix: str) -> bool:
        bare = suffix.lstrip(".")
        if host_name == bare:
            return True
        dotted = suffix if suffix.startswith(".") else f".{suffix}"
        return host_name.endswith(dotted)

    return any(_matches_suffix(host, suffix) for suffix in OFFICIAL_SUFFIXES)


class _SearchThrottle:
    """One global gap between searches, shared by every caller in the process."""

    def __init__(self, min_interval: float) -> None:
        self._min = min_interval
        self._last = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            gap = self._min - (time.monotonic() - self._last)
            if gap > 0:
                await asyncio.sleep(gap)
            self._last = time.monotonic()


_throttle = _SearchThrottle(MIN_SEARCH_INTERVAL_SECONDS)

_DDG_REDIRECT = re.compile(r"^/l/\?.*uddg=", re.I)


def _extract_result_urls(html: str, *, limit: int) -> list[str]:
    """Pull result URLs out of the HTML endpoint's markup.

    The endpoint wraps results in its own redirector (`/l/?uddg=<encoded>`), so
    the real URL has to be unwrapped from the query string. Treated as untrusted
    markup throughout: anything that does not parse into an http(s) URL is
    dropped rather than repaired.
    """
    out: list[str] = []
    seen: set[str] = set()
    try:
        tree = HTMLParser(html)
    except Exception:  # noqa: BLE001
        return []

    for node in tree.css("a"):
        href = (node.attributes or {}).get("href") or ""
        if not href:
            continue

        url = href
        if _DDG_REDIRECT.search(href) or "uddg=" in href:
            qs = parse_qs(urlparse(href).query)
            target = (qs.get("uddg") or [""])[0]
            if not target:
                continue
            url = target

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if parsed.path.lower().endswith(_SKIP_SUFFIXES):
            continue

        clean = parsed._replace(fragment="").geturl()
        if clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
        if len(out) >= limit:
            break

    return out


async def search_official(
    query: str,
    *,
    http_client: httpx.AsyncClient,
    limit: int = MAX_RESULTS_CONSIDERED,
) -> list[str]:
    """Search the open web, return only URLs that pass the allowlist."""
    await _throttle.wait()
    try:
        response = await http_client.post(
            _SEARCH_ENDPOINT,
            data={"q": query, "kl": "wt-wt"},
            headers={"User-Agent": USER_AGENT},
            timeout=_SEARCH_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 - discovery is best-effort by design
        log.warning("official-source search failed q=%r err=%s", query[:80], exc)
        return []

    candidates = _extract_result_urls(response.text, limit=limit)
    admitted = [u for u in candidates if is_official(u)]
    log.info(
        "search q=%r -> %d candidates, %d official",
        query[:80], len(candidates), len(admitted),
    )
    return admitted


def build_query(question: str, *, country_name: str | None) -> str:
    """Turn a student's question into a search that favours official pages.

    The question is used almost as written: the phrasing a student chose is the
    best available signal, and rewriting it with a model here would spend a
    generation to lose information. Only two things are added — the destination
    country when known, and the words that bias results toward primary sources.
    """
    parts = [question.strip()]
    if country_name:
        parts.append(country_name)
    parts.append("official student visa requirement site")
    return " ".join(p for p in parts if p)[:400]


async def discover_for_question(
    *,
    question: str,
    country_code: str | None,
    country_name: str | None,
    dbs: Databases,
    http_client: httpx.AsyncClient,
) -> list[int]:
    """Search for sources that could answer `question`; register what qualifies.

    Returns the ids of newly watched portals. Registration only: the crawler
    fetches them on its own schedule, so this returns quickly and one expensive
    question cannot stall the worker.
    """
    portals = PortalRepo(dbs.app)
    urls = await search_official(
        build_query(question, country_name=country_name), http_client=http_client
    )
    if not urls:
        return []

    # A synthetic parent, so a discovered-by-search portal is marked with the
    # same provenance mechanism as a discovered-by-link one and is never itself
    # expanded. `id` is None: `discovered_from_portal_id` is nullable and there is
    # no real parent row, but the `discovered_at` stamp still distinguishes it
    # from the curated registry.
    parent: dict[str, Any] = {
        "id": None,
        "kind": "government",
        "country_code": country_code,
        "parser_key": "generic",
    }

    registered: list[int] = []
    for url in urls[:MAX_REGISTERED_PER_QUERY]:
        portal_id = await portals.register_discovered(url=url, parent=parent)
        if portal_id is not None:
            registered.append(portal_id)

    if registered:
        log.info(
            "registered %d new source(s) from a question with no answer: %r",
            len(registered), question[:80],
        )
    return registered


# --- the consumer that closes the loop ---------------------------------------

CONSUMER_GROUP = "discovery"

# Questions per hour that may trigger a search. Discovery is the slowest thing
# this worker does and it talks to a third party, so it is capped well below the
# rate at which refusals can arrive. Anything over the cap is skipped rather than
# queued: the next student to ask the same thing re-triggers it, so nothing is
# permanently lost by dropping one.
MAX_DISCOVERIES_PER_HOUR = 20


async def consume(
    bus: Any,
    dbs: Databases,
    http_client: httpx.AsyncClient,
    *,
    consumer_name: str = "discovery-1",
) -> None:
    """Watch `ev:chat` for refusals and look for the source that was missing.

    Subscribes to `answer.generated` rather than introducing a new event type:
    the refusal flag is already on that event, and a consumer group is the
    documented way to add a new reader without touching the producer.
    """
    from app.events.bus import EventStream, EventType

    window_started = time.monotonic()
    used = 0

    async def handler(message: dict[str, Any]) -> None:
        nonlocal window_started, used

        if message.get("type") != EventType.ANSWER_GENERATED.value:
            return
        payload = message.get("payload")
        if not isinstance(payload, dict) or not payload.get("is_refusal"):
            return
        question = (payload.get("question") or "").strip()
        if not question:
            return

        if time.monotonic() - window_started > 3600:
            window_started, used = time.monotonic(), 0
        if used >= MAX_DISCOVERIES_PER_HOUR:
            log.info("discovery budget spent for this hour; skipping %r", question[:60])
            return
        used += 1

        country_code = payload.get("country")
        country_name = None
        if country_code:
            row = await dbs.app.fetch_one(
                "SELECT name_en FROM countries WHERE code = ?", (country_code,)
            )
            country_name = row["name_en"] if row else None

        await discover_for_question(
            question=question,
            country_code=country_code,
            country_name=country_name,
            dbs=dbs,
            http_client=http_client,
        )

    await bus.consume(EventStream.CHAT, CONSUMER_GROUP, consumer_name, handler)
