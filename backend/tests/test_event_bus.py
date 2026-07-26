"""Event bus delivery semantics, against a real events.db and a stub Redis.

The defect these pin down: `INSERT INTO applied_events` used to sit inside the
handler's retry `try`. A UNIQUE violation on (consumer, event_id) — which is the
*normal* outcome of a redelivery, or of two replicas of one group racing — was
therefore caught as a handler failure. The handler ran again for its side effects,
and an event that had already been processed successfully ended up in
`dead_letters`. At-least-once delivery turned into at-least-twice execution
precisely when the idempotency ledger was doing its job.

Redis is stubbed rather than mocked out: the bus's contract with it is small
(xadd, xack, xreadgroup, xautoclaim, xgroup_create) and a stub that records calls
lets the trimming and ack behaviour be asserted without a server.
"""

from __future__ import annotations

import pathlib
import tempfile
from typing import Any

import pytest

from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.events.bus import STREAM_MAXLEN, EventBus, EventType


class StubRedis:
    """Records what the bus asks of Redis. No server involved."""

    def __init__(self) -> None:
        self.added: list[dict[str, Any]] = []
        self.acked: list[str] = []
        self.fail_xadd = False
        self.streams: dict[str, list[tuple[str, dict[str, Any]]]] = {}

    async def xadd(self, key: str, fields: dict[str, Any], **kwargs: Any) -> str:
        if self.fail_xadd:
            from redis import exceptions as redis_exceptions

            raise redis_exceptions.RedisError("stub xadd failure")
        self.added.append({"key": key, "fields": fields, **kwargs})
        mid = f"{len(self.streams.get(key, [])) + 1}-1"
        self.streams.setdefault(key, []).append((mid, dict(fields)))
        return mid

    async def xrange(self, key: str, *, min: str = "-", max: str = "+", count: int | None = None):  # noqa: A002
        entries = list(self.streams.get(key, []))
        if count is not None:
            entries = entries[:count]
        return entries

    async def xack(self, _key: str, _group: str, message_id: str) -> int:
        self.acked.append(message_id)
        return 1


@pytest.fixture
async def dbs():
    directory = pathlib.Path(tempfile.mkdtemp())
    databases = Databases(directory / "app.db", directory / "events.db", directory / "learn.db")
    await databases.connect_all()
    await run_migrations(databases)
    yield databases
    await databases.close_all()


@pytest.fixture
def redis() -> StubRedis:
    return StubRedis()


@pytest.fixture
def bus(redis: StubRedis, dbs) -> EventBus:
    return EventBus(redis, dbs.events)  # type: ignore[arg-type]


def _message(event_id: str = "01J8EVENT") -> dict[str, str]:
    return {"event_id": event_id, "type": EventType.PORTAL_CHANGED.value, "payload": "{}"}


async def _handle(bus: EventBus, handler, event_id: str = "01J8EVENT", retries: int = 3) -> None:
    await bus._handle_one(
        redis_stream_key="ev:crawl",
        group="diff_worker",
        message_id="1-1",
        fields=_message(event_id),
        handler=handler,
        max_retries=retries,
    )


# --- publish -----------------------------------------------------------------


async def test_publish_archives_then_delivers(bus: EventBus, redis: StubRedis, dbs) -> None:
    event_id = await bus.publish(
        EventType.PORTAL_CHANGED, payload={"portal_id": 1}, subject_type="portal"
    )
    row = await dbs.events.fetch_one("SELECT * FROM events WHERE event_id = ?", (event_id,))
    assert row is not None, "events.db is the durable archive and must be written"
    assert row["stream"] == "crawl", "stream is derived from the type, not passed in"
    assert len(redis.added) == 1


async def test_publish_bounds_the_stream(bus: EventBus, redis: StubRedis) -> None:
    """An unbounded Redis stream is a slow memory leak; events.db is the archive."""
    await bus.publish(EventType.PORTAL_CHANGED, payload={})
    assert redis.added[0]["maxlen"] == STREAM_MAXLEN
    assert redis.added[0]["approximate"] is True


async def test_publish_survives_redis_failure_and_relay_delivers(
    bus: EventBus, redis: StubRedis, dbs
) -> None:
    redis.fail_xadd = True
    event_id = await bus.publish(EventType.PORTAL_CHANGED, payload={"portal_id": 7})
    assert await dbs.events.fetch_val("SELECT 1 FROM events WHERE event_id = ?", (event_id,))
    assert len(redis.added) == 0

    redis.fail_xadd = False
    relayed = await bus.relay_pending()
    assert relayed == 1
    assert len(redis.added) == 1
    assert redis.added[0]["fields"]["event_id"] == event_id


async def test_publish_rejects_an_unknown_type(bus: EventBus) -> None:
    with pytest.raises(ValueError):
        await bus.publish("portal.invented", payload={})


# --- idempotency, the regression that matters --------------------------------


async def test_handler_runs_once_and_is_recorded(bus: EventBus, dbs) -> None:
    calls = []
    await _handle(bus, lambda m: calls.append(m) or _done())
    assert len(calls) == 1
    assert await dbs.events.fetch_val(
        "SELECT COUNT(*) FROM applied_events WHERE consumer = ?", ("diff_worker",)
    ) == 1


async def test_redelivery_does_not_run_the_handler_again(bus: EventBus, redis: StubRedis) -> None:
    calls = []

    async def handler(message):
        calls.append(message)

    await _handle(bus, handler)
    await _handle(bus, handler)  # same event_id redelivered
    assert len(calls) == 1, "an already-applied event must be acked, not re-run"
    assert len(redis.acked) == 2, "and it must still be acked so it stops being redelivered"


async def test_duplicate_applied_row_does_not_dead_letter(bus: EventBus, dbs) -> None:
    """The core defect: a pre-existing ledger row must not look like a failure.

    A second replica of the same group inserts the marker first. The handler here
    still succeeds, so the event must be acked and must NOT be recorded as a
    dead letter, and the handler must not be retried for its side effects.
    """
    await dbs.events.execute(
        "INSERT INTO applied_events (consumer, event_id, applied_at) VALUES (?, ?, ?)",
        ("other_group", "01J8EVENT", "2026-07-26T00:00:00Z"),
    )
    calls = []

    async def handler(message):
        calls.append(message)

    await _handle(bus, handler)
    assert len(calls) == 1
    assert await dbs.events.fetch_val("SELECT COUNT(*) FROM dead_letters") == 0


async def test_failing_handler_retries_then_dead_letters(bus: EventBus, dbs, redis: StubRedis) -> None:
    attempts = []

    async def handler(_message):
        attempts.append(1)
        raise RuntimeError("portal payload is malformed")

    await _handle(bus, handler, retries=3)
    assert len(attempts) == 3, "every retry should be used before giving up"
    row = await dbs.events.fetch_one("SELECT * FROM dead_letters WHERE event_id = ?", ("01J8EVENT",))
    assert row is not None and "RuntimeError" in row["last_error"]
    assert redis.acked == ["1-1"], "a dead letter is durable, so leaving it pending would loop"
    assert await dbs.events.fetch_val("SELECT COUNT(*) FROM applied_events") == 0


async def test_handler_succeeding_on_a_later_attempt_is_not_dead_lettered(bus: EventBus, dbs) -> None:
    attempts = []

    async def handler(_message):
        attempts.append(1)
        if len(attempts) < 2:
            raise RuntimeError("transient")

    await _handle(bus, handler)
    assert len(attempts) == 2
    assert await dbs.events.fetch_val("SELECT COUNT(*) FROM dead_letters") == 0
    assert await dbs.events.fetch_val("SELECT COUNT(*) FROM applied_events") == 1


async def test_payload_is_decoded_for_the_handler(bus: EventBus) -> None:
    seen = {}

    async def handler(message):
        seen.update(message)

    await bus._handle_one(
        redis_stream_key="ev:crawl",
        group="g",
        message_id="1-1",
        fields={"event_id": "E1", "type": "portal.changed", "payload": '{"portal_id": 42}'},
        handler=handler,
        max_retries=1,
    )
    assert seen["payload"] == {"portal_id": 42}


async def test_malformed_payload_reaches_the_handler_as_a_string(bus: EventBus) -> None:
    """A bad payload is the handler's problem to report, not the bus's to swallow."""
    seen = {}

    async def handler(message):
        seen.update(message)

    await bus._handle_one(
        redis_stream_key="ev:crawl",
        group="g",
        message_id="1-1",
        fields={"event_id": "E2", "type": "portal.changed", "payload": "{not json"},
        handler=handler,
        max_retries=1,
    )
    assert seen["payload"] == "{not json"


def _done():
    """Small helper so a lambda handler can be a coroutine."""
    async def _noop():
        return None
    return _noop()
