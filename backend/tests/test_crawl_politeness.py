"""Conditional requests, concurrency, rate limits, and the body-size ceiling.

These are the parts of the crawler that decide how it behaves toward hosts it does
not own. Three of the registry's sources already return 403 to any automated client
(migration 017), so the cost of getting this wrong is not theoretical: it is losing
access to the official page a student needs.

Everything here runs against an in-process transport rather than the network, so the
tests pin our behaviour rather than a government site's current configuration.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from app.workers.crawler import (
    MAX_HONOURED_RETRY_AFTER_SECONDS,
    MAX_RESPONSE_BYTES,
    Fetched,
    RateLimited,
    ResponseTooLarge,
    _fetch,
    _HostThrottle,
    _parse_retry_after,
    _validator_fields,
    conditional_headers,
)


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Conditional requests ----------------------------------------------------


def test_conditional_headers_sends_both_validators_when_both_are_stored():
    headers = conditional_headers({"etag": 'W/"abc"', "last_modified": "Wed, 21 Oct 2015 07:28:00 GMT"})
    assert headers == {
        "If-None-Match": 'W/"abc"',
        "If-Modified-Since": "Wed, 21 Oct 2015 07:28:00 GMT",
    }


def test_conditional_headers_omits_absent_and_blank_validators():
    assert conditional_headers({"etag": None, "last_modified": None}) == {}
    assert conditional_headers({"etag": "   ", "last_modified": ""}) == {}
    # A portal row from before migration 018 has neither key at all.
    assert conditional_headers({}) == {}


@pytest.mark.asyncio
async def test_304_returns_a_bodyless_result_flagged_not_modified():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.headers)
        return httpx.Response(304)

    async with _client(handler) as client:
        fetched = await _fetch(
            client, "https://example.gov/x", headers={"If-None-Match": '"v1"'}
        )

    assert fetched.not_modified is True
    assert fetched.status_code == 304
    assert fetched.content == b""
    assert fetched.text == ""
    assert seen["if-none-match"] == '"v1"'


@pytest.mark.asyncio
async def test_200_captures_the_validators_the_host_returned():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            text="<html><body><p>Body</p></body></html>",
            headers={"ETag": 'W/"7"', "Last-Modified": "Wed, 21 Oct 2015 07:28:00 GMT"},
        )

    async with _client(handler) as client:
        fetched = await _fetch(client, "https://example.gov/x")

    assert fetched.not_modified is False
    assert fetched.etag == 'W/"7"'
    assert _validator_fields(fetched) == {
        "etag": 'W/"7"',
        "last_modified": "Wed, 21 Oct 2015 07:28:00 GMT",
    }


def test_a_missing_validator_does_not_erase_the_stored_one():
    """A host that omits an ETag on one response has not withdrawn it.

    If this wrote NULL, a host that sends ETag inconsistently would never get a
    usable conditional request, which is the whole point of storing it.
    """
    partial = Fetched(
        status_code=200, content=b"x", text="x", etag=None, last_modified="Thu, 01 Jan 2026 00:00:00 GMT"
    )
    assert _validator_fields(partial) == {"last_modified": "Thu, 01 Jan 2026 00:00:00 GMT"}

    neither = Fetched(status_code=200, content=b"x", text="x", etag=None, last_modified=None)
    assert _validator_fields(neither) == {}


# --- Rate limiting -----------------------------------------------------------


@pytest.mark.asyncio
async def test_429_raises_rate_limited_and_is_not_retried():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(429, headers={"Retry-After": "120"})

    async with _client(handler) as client:
        with pytest.raises(RateLimited) as caught:
            await _fetch(client, "https://example.gov/x")

    assert caught.value.status_code == 429
    assert caught.value.retry_after == 120.0
    # Retrying a 429 on our own exponential schedule would ignore the delay the
    # host asked for, so tenacity must not touch it.
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_503_with_retry_after_is_a_rate_limit_but_a_bare_503_is_retried():
    """The distinction matters: only one of these is the host scheduling us."""
    with_header = {"n": 0}
    without_header = {"n": 0}

    def stated(request: httpx.Request) -> httpx.Response:
        with_header["n"] += 1
        return httpx.Response(503, headers={"Retry-After": "30"})

    def bare(request: httpx.Request) -> httpx.Response:
        without_header["n"] += 1
        return httpx.Response(503)

    async with _client(stated) as client:
        with pytest.raises(RateLimited):
            await _fetch(client, "https://example.gov/x")
    assert with_header["n"] == 1

    async with _client(bare) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await _fetch(client, "https://example.gov/x")
    # An ordinary transient server fault stays on the retry path.
    assert without_header["n"] == 4


def test_retry_after_accepts_both_forms_the_spec_allows():
    assert _parse_retry_after("60") == 60.0
    # An HTTP-date in the past means "now", never a negative delay.
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0.0
    # A date in the future resolves to a positive number of seconds.
    assert (_parse_retry_after("Fri, 01 Jan 2100 00:00:00 GMT") or 0) > 0
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("soon please") is None
    assert _parse_retry_after("-5") == 0.0


@pytest.mark.asyncio
async def test_a_rate_limit_holds_back_every_portal_on_that_host():
    """The registry has three portals on gov.uk and three on canada.ca.

    A rate limit is a property of the host, not of the URL that happened to hit
    it, so the penalty has to apply to the host or the other two walk into the
    same limit minutes later.
    """
    throttle = _HostThrottle(0.0)
    await throttle.penalise("https://www.gov.uk/student-visa", 0.30)

    started = time.monotonic()
    await throttle.wait("https://www.gov.uk/student-visa/money")
    assert time.monotonic() - started >= 0.25

    # A different host is unaffected.
    started = time.monotonic()
    await throttle.wait("https://www.canada.ca/study-permit")
    assert time.monotonic() - started < 0.20


@pytest.mark.asyncio
async def test_an_absurd_retry_after_is_capped():
    throttle = _HostThrottle(0.0)
    await throttle.penalise("https://example.gov/x", 86_400.0)
    host = "example.gov"
    held_for = throttle._next_free[host] - time.monotonic()
    assert held_for <= MAX_HONOURED_RETRY_AFTER_SECONDS + 1


# --- Host throttle concurrency ----------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_callers_to_one_host_are_staggered_not_stampeded():
    """This is the bug the rewrite fixes, stated as a test.

    The previous throttle read the last-request time, slept the remainder, and only
    then recorded the timestamp. Coroutines entering together all read the same
    stale value, all slept the same delay, and all fired at once, which is exactly
    the case a shared cron produces.
    """
    interval = 0.10
    throttle = _HostThrottle(interval)
    fired: list[float] = []

    async def one() -> None:
        await throttle.wait("https://www.gov.uk/student-visa")
        fired.append(time.monotonic())

    await asyncio.gather(*(one() for _ in range(4)))

    fired.sort()
    gaps = [b - a for a, b in zip(fired, fired[1:])]
    assert len(gaps) == 3
    for gap in gaps:
        assert gap >= interval * 0.8, f"requests were not staggered: gaps={gaps}"


@pytest.mark.asyncio
async def test_a_host_crawl_delay_is_honoured_over_our_own_floor():
    throttle = _HostThrottle(0.02)
    await throttle.wait("https://example.gov/a", min_interval=0.30)

    started = time.monotonic()
    await throttle.wait("https://example.gov/b")
    assert time.monotonic() - started >= 0.25


@pytest.mark.asyncio
async def test_a_host_asking_for_less_than_our_floor_does_not_get_it():
    """Our politeness floor is our policy, not the host's to lower."""
    throttle = _HostThrottle(0.30)
    await throttle.wait("https://example.gov/a", min_interval=0.0)

    started = time.monotonic()
    await throttle.wait("https://example.gov/b", min_interval=0.0)
    assert time.monotonic() - started >= 0.25


# --- Body size ---------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_declared_oversize_body_is_refused_before_it_is_downloaded():
    served = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        served["n"] += 1
        return httpx.Response(
            200, content=b"x", headers={"Content-Length": str(MAX_RESPONSE_BYTES + 1)}
        )

    async with _client(handler) as client:
        with pytest.raises(ResponseTooLarge):
            await _fetch(client, "https://example.gov/huge")

    assert served["n"] == 1  # refused, and not retried


@pytest.mark.asyncio
async def test_an_undeclared_oversize_body_is_cut_off_while_streaming():
    """A missing or lying Content-Length must not defeat the ceiling.

    `response.content` imposed no limit, so before this the size of a snapshot was
    decided by whoever operates the page. On a VM whose entire premise is that it
    is small, that is a disk-exhaustion path a third party can reach.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"y" * (MAX_RESPONSE_BYTES + 4096))

    async with _client(handler) as client:
        with pytest.raises(ResponseTooLarge):
            await _fetch(client, "https://example.gov/huge")


@pytest.mark.asyncio
async def test_an_ordinary_page_is_read_whole_and_decoded():
    body = "<html><body><p>ভিসার শর্ত</p></body></html>".encode()

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=body, headers={"Content-Type": "text/html; charset=utf-8"}
        )

    async with _client(handler) as client:
        fetched = await _fetch(client, "https://example.gov/bn")

    assert fetched.content == body
    assert "ভিসার শর্ত" in fetched.text


@pytest.mark.asyncio
async def test_undecodable_bytes_cost_a_character_not_the_crawl():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"<p>fee is \xff\xfe GBP</p>",
            headers={"Content-Type": "text/html; charset=utf-8"},
        )

    async with _client(handler) as client:
        fetched = await _fetch(client, "https://example.gov/x")

    assert "fee is" in fetched.text and "GBP" in fetched.text
