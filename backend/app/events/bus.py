"""Redis Streams event bus.

Every state change in the product is an event: published to Redis Streams for
live consumers and appended to `events.db` in the same call, since that table
is the durable archive and idempotency ledger (backend/backend.md section 2,
docs/database.md section 4 and section 9). Consumer groups give at-least-once
delivery with per-consumer idempotency via `applied_events`, and a poison
message lands in `dead_letters` after 3 attempts rather than looping forever.

This module expects the Redis client to have been constructed with
`decode_responses=True` (see app/main.py), so stream field values below are
plain `str`, not `bytes`.
"""

from __future__ import annotations

import asyncio
import enum
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

from redis import exceptions as redis_exceptions
from redis.asyncio import Redis
from ulid import ULID

from app.db.connection import Database

log = logging.getLogger(__name__)

_STREAM_KEY_PREFIX = "ev"  # Redis key: f"{_STREAM_KEY_PREFIX}:{stream}", e.g. "ev:crawl"


class EventStream(str, enum.Enum):
    """Matches the CHECK constraint on events.stream, docs/database.md section 4."""

    CRAWL = "crawl"
    KB = "kb"
    CHAT = "chat"
    AGENT = "agent"
    USER = "user"
    LEARN = "learn"


class EventType(str, enum.Enum):
    """Every event named in docs/database.md and backend/backend.md section 2.1.

    `USER_DELETED` is the one addition beyond backend.md's table: it is named
    explicitly in docs/database.md sections 7 and 13 ("write a final
    user.deleted event") but was left off the section 2.1 catalogue, so it is
    placed on the `user` stream alongside the other account-scoped events.
    """

    # ev:crawl
    PORTAL_FETCHED = "portal.fetched"
    PORTAL_CHANGED = "portal.changed"
    PORTAL_UNREACHABLE = "portal.unreachable"
    # ev:kb
    KB_CHUNK_UPDATED = "kb.chunk.updated"
    KB_VERSION_PUBLISHED = "kb.version.published"
    # ev:chat
    QUERY_RECEIVED = "query.received"
    ANSWER_GENERATED = "answer.generated"
    ANSWER_CORRECTED = "answer.corrected"
    ANSWER_FAILED = "answer.failed"
    # ev:agent
    AGENT_TRIGGERED = "agent.triggered"
    AGENT_TOOL_CALL = "agent.tool_call"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    # ev:user
    VAULT_DOC_ADDED = "vault.doc.added"
    PLAN_STEP_CHANGED = "plan.step.changed"
    PROFILE_UPDATED = "profile.updated"
    USER_DELETED = "user.deleted"
    # ev:learn
    REPLAY_SAMPLE_ADDED = "replay.sample.added"
    ADAPTER_TRAINED = "adapter.trained"
    ADAPTER_PROMOTED = "adapter.promoted"
    ADAPTER_ROLLED_BACK = "adapter.rolled_back"


_STREAM_BY_TYPE: dict[EventType, EventStream] = {
    EventType.PORTAL_FETCHED: EventStream.CRAWL,
    EventType.PORTAL_CHANGED: EventStream.CRAWL,
    EventType.PORTAL_UNREACHABLE: EventStream.CRAWL,
    EventType.KB_CHUNK_UPDATED: EventStream.KB,
    EventType.KB_VERSION_PUBLISHED: EventStream.KB,
    EventType.QUERY_RECEIVED: EventStream.CHAT,
    EventType.ANSWER_GENERATED: EventStream.CHAT,
    EventType.ANSWER_CORRECTED: EventStream.CHAT,
    EventType.ANSWER_FAILED: EventStream.CHAT,
    EventType.AGENT_TRIGGERED: EventStream.AGENT,
    EventType.AGENT_TOOL_CALL: EventStream.AGENT,
    EventType.AGENT_COMPLETED: EventStream.AGENT,
    EventType.AGENT_FAILED: EventStream.AGENT,
    EventType.VAULT_DOC_ADDED: EventStream.USER,
    EventType.PLAN_STEP_CHANGED: EventStream.USER,
    EventType.PROFILE_UPDATED: EventStream.USER,
    EventType.USER_DELETED: EventStream.USER,
    EventType.REPLAY_SAMPLE_ADDED: EventStream.LEARN,
    EventType.ADAPTER_TRAINED: EventStream.LEARN,
    EventType.ADAPTER_PROMOTED: EventStream.LEARN,
    EventType.ADAPTER_ROLLED_BACK: EventStream.LEARN,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class EventBus:
    def __init__(self, redis_client: Redis, events_db: Database) -> None:
        self._redis = redis_client
        self._events_db = events_db

    async def publish(
        self,
        stream: EventStream | str,
        type: EventType | str,  # noqa: A002 - matches the spec'd parameter name
        payload: dict[str, Any],
        actor: str,
        user_id: int | None = None,
        *,
        subject_type: str | None = None,
        subject_id: str | None = None,
        schema_version: int = 1,
    ) -> str:
        """Publish one event. Returns the ULID event_id.

        Writes to events.db first, then Redis: events.db is the durable
        record (docs/database.md section 9, "events.db is the durable archive
        ... not the bus"), so if only one of the two writes can succeed, the
        one that must not be silently lost is the durable one, not the
        delivery.
        """
        stream_enum = stream if isinstance(stream, EventStream) else EventStream(stream)
        type_enum = type if isinstance(type, EventType) else EventType(type)

        expected_stream = _STREAM_BY_TYPE.get(type_enum)
        if expected_stream is not None and expected_stream is not stream_enum:
            raise ValueError(
                f"event type {type_enum.value!r} belongs on stream "
                f"{expected_stream.value!r}, not {stream_enum.value!r}"
            )

        event_id = str(ULID())
        created_at = _now_iso()
        payload_json = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)

        await self._events_db.execute(
            """
            INSERT INTO events
                (event_id, stream, type, actor, subject_type, subject_id,
                 user_id, payload, schema_version, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id, stream_enum.value, type_enum.value, actor,
                subject_type, subject_id, user_id, payload_json,
                schema_version, created_at,
            ),
        )

        redis_stream_key = f"{_STREAM_KEY_PREFIX}:{stream_enum.value}"
        await self._redis.xadd(
            redis_stream_key,
            {
                "event_id": event_id,
                "type": type_enum.value,
                "actor": actor,
                "user_id": "" if user_id is None else str(user_id),
                "subject_type": subject_type or "",
                "subject_id": subject_id or "",
                "payload": payload_json,
                "schema_version": str(schema_version),
                "created_at": created_at,
            },
        )
        return event_id

    async def consume(
        self,
        stream: EventStream | str,
        group: str,
        consumer: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        *,
        block_ms: int = 5000,
        max_retries: int = 3,
        batch_size: int = 10,
    ) -> None:
        """Run a consumer-group loop until cancelled.

        Idempotent per (group, event_id) via `applied_events`: `group` is used
        as the `consumer` column there rather than the per-process `consumer`
        name, because idempotency is a property of the logical consumer group
        (e.g. "diff_worker"), not of one ephemeral replica, so two replicas of
        the same group processing the same redelivered message must agree
        it's already done.
        """
        stream_enum = stream if isinstance(stream, EventStream) else EventStream(stream)
        redis_stream_key = f"{_STREAM_KEY_PREFIX}:{stream_enum.value}"

        try:
            await self._redis.xgroup_create(redis_stream_key, group, id="0", mkstream=True)
        except redis_exceptions.ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

        while True:
            try:
                response = await self._redis.xreadgroup(
                    group, consumer, {redis_stream_key: ">"}, count=batch_size, block=block_ms
                )
            except redis_exceptions.RedisError as exc:
                log.error("redis read failed stream=%s group=%s err=%s", stream_enum.value, group, exc)
                await asyncio.sleep(1.0)
                continue

            if not response:
                continue

            for _key, messages in response:
                for message_id, fields in messages:
                    await self._handle_one(
                        redis_stream_key=redis_stream_key,
                        group=group,
                        message_id=message_id,
                        fields=fields,
                        handler=handler,
                        max_retries=max_retries,
                    )

    async def _handle_one(
        self,
        *,
        redis_stream_key: str,
        group: str,
        message_id: str,
        fields: dict[str, str],
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        max_retries: int,
    ) -> None:
        event_id = fields.get("event_id", message_id)

        already_done = await self._events_db.fetch_val(
            "SELECT 1 FROM applied_events WHERE consumer = ? AND event_id = ?",
            (group, event_id),
        )
        if already_done:
            await self._redis.xack(redis_stream_key, group, message_id)
            return

        message: dict[str, Any] = dict(fields)
        if "payload" in message:
            try:
                message["payload"] = json.loads(message["payload"])
            except (TypeError, ValueError):
                pass  # leave the raw string; a malformed payload is the handler's problem

        last_error = ""
        for attempt in range(1, max_retries + 1):
            try:
                await handler(message)
                await self._events_db.execute(
                    "INSERT INTO applied_events (consumer, event_id, applied_at) VALUES (?, ?, ?)",
                    (group, event_id, _now_iso()),
                )
                await self._redis.xack(redis_stream_key, group, message_id)
                return
            except Exception as exc:  # noqa: BLE001 - must not crash the consumer loop
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "event handler failed group=%s event=%s attempt=%d/%d err=%s",
                    group, event_id, attempt, max_retries, last_error,
                )
                if attempt < max_retries:
                    await asyncio.sleep(min(0.5 * attempt, 2.0))

        await self._events_db.execute(
            """
            INSERT INTO dead_letters (consumer, event_id, attempts, last_error, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                group, event_id, max_retries, last_error,
                json.dumps(message, ensure_ascii=False), _now_iso(),
            ),
        )
        # Ack even on final failure: the dead letter is the durable record now,
        # and leaving it pending would just have the group redeliver it forever.
        await self._redis.xack(redis_stream_key, group, message_id)
