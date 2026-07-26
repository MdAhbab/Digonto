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
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import httpx
from selectolax.parser import HTMLParser
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.config import Settings
from app.db.connection import Databases
from app.events.bus import EventBus, EventStream, EventType
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

_STRIP_SELECTOR = "script, style, nav"
_HEADING_LEVELS = {f"h{i}": i for i in range(1, 7)}
_CONTENT_TAGS = {"p", "li", "td", "th", "blockquote", "dd", "dt", "figcaption", "caption"}
_WS_RE = re.compile(r"\s+")
_BANGLA_RE = re.compile(r"[ঀ-৿]")


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
        if not text:
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
    except Exception as exc:  # noqa: BLE001 - every fetch failure mode lands here
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
            EventStream.CRAWL,
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
        EventStream.CRAWL,
        EventType.PORTAL_FETCHED,
        payload={"portal_id": portal["id"], "portal_public_id": portal["public_id"], "changed": True},
        actor="worker:crawler",
        subject_type="portal",
        subject_id=portal["public_id"],
    )
    await bus.publish(
        EventStream.CRAWL,
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
            EventStream.CRAWL,
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
