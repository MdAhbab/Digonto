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

# Entries retained per Redis stream. The durable archive is `events.db`, so this
# only has to be deep enough that a consumer restarting cannot miss work.
STREAM_MAXLEN = 10_000

# A message a consumer took but never acked stays in that group's pending list
# forever, because XREADGROUP with ">" only ever returns new messages. Without a
# reclaim pass, one worker crash silently strands work: the event is neither
# processed nor dead-lettered, and nothing reports it. These two settings drive
# the reclaim sweep in `consume`.
PENDING_RECLAIM_IDLE_MS = 60_000
PENDING_RECLAIM_EVERY_S = 30.0


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

    `USER_DELETED` is one addition beyond backend.md's table: it is named
    explicitly in docs/database.md sections 7 and 13 ("write a final
    user.deleted event") but was left off the section 2.1 catalogue, so it is
    placed on the `user` stream alongside the other account-scoped events.

    `PLAN_CHANGED`, `AUDIT_UPDATED`, `FUNDING_UPDATED`, `USER_SUSPENDED`,
    `USER_BANNED`, and `USER_REINSTATED` are six more additions, found while
    wiring the router layer to the (authoritative, unmodified)
    app/services/*.py files: `planner_service.simulate`,
    `vault_service.start_audit`, `funding_service.rematch`/`add_source`/
    `remove_source`, and `moderation_service.suspend_user`/`ban_user`/
    `reinstate_user` all reference one of these on `EventType` that did not
    exist, which raised `AttributeError` the moment any of those methods
    ran. Every other one of this module's 25 call sites across the service
    layer already matched a real member.
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
    PLAN_CHANGED = "plan.changed"
    PROFILE_UPDATED = "profile.updated"
    USER_DELETED = "user.deleted"
    AUDIT_UPDATED = "audit.updated"
    FUNDING_UPDATED = "funding.updated"
    USER_SUSPENDED = "user.suspended"
    USER_BANNED = "user.banned"
    USER_REINSTATED = "user.reinstated"
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
    EventType.PLAN_CHANGED: EventStream.USER,
    EventType.PROFILE_UPDATED: EventStream.USER,
    EventType.USER_DELETED: EventStream.USER,
    EventType.AUDIT_UPDATED: EventStream.USER,
    EventType.FUNDING_UPDATED: EventStream.USER,
    EventType.USER_SUSPENDED: EventStream.USER,
    EventType.USER_BANNED: EventStream.USER,
    EventType.USER_REINSTATED: EventStream.USER,
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
        type: EventType | str,  # noqa: A002 - matches the spec'd parameter name
        *,
        payload: dict[str, Any],
        user_id: int | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        actor: str | None = None,
        schema_version: int = 1,
    ) -> str:
        """Publish one event. Returns the ULID event_id.

        Writes to events.db first, then Redis: events.db is the durable
        record (docs/database.md section 9, "events.db is the durable archive
        ... not the bus"), so if only one of the two writes can succeed, the
        one that must not be silently lost is the durable one, not the
        delivery.

        Signature note: this used to take `stream` and `actor` as separate
        required parameters, ahead of `type`/`payload` positionally. Every
        one of this module's 25 call sites across app/services/*.py
        (authoritative, not modified here) calls it as
        `publish(EventType.X, user_id=..., subject_type=..., subject_id=...,
        payload=...)`, i.e. `type` positional and everything else by
        keyword, never `stream` or `actor`. Since `_STREAM_BY_TYPE` already
        maps every `EventType` to exactly one `EventStream` (a passed-in
        `stream` could only ever be redundant with it or wrong), `stream` is
        now derived rather than accepted, and `actor` defaults to
        `"user:<id>"`/`"system"` rather than being required, matching how
        every caller actually uses this method.
        """
        type_enum = type if isinstance(type, EventType) else EventType(type)
        stream_enum = _STREAM_BY_TYPE[type_enum]
        resolved_actor = actor or (f"user:{user_id}" if user_id is not None else "system")

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
                event_id, stream_enum.value, type_enum.value, resolved_actor,
                subject_type, subject_id, user_id, payload_json,
                schema_version, created_at,
            ),
        )

        redis_stream_key = f"{_STREAM_KEY_PREFIX}:{stream_enum.value}"
        fields = self._stream_fields(
            event_id=event_id,
            type_value=type_enum.value,
            actor=resolved_actor,
            user_id=user_id,
            subject_type=subject_type,
            subject_id=subject_id,
            payload_json=payload_json,
            schema_version=schema_version,
            created_at=created_at,
        )
        try:
            await self._redis_xadd(redis_stream_key, fields)
        except redis_exceptions.RedisError as exc:
            log.error(
                "redis xadd failed after events.db insert event=%s stream=%s err=%s",
                event_id, stream_enum.value, exc,
            )
        return event_id

    @staticmethod
    def _stream_fields(
        *,
        event_id: str,
        type_value: str,
        actor: str,
        user_id: int | None,
        subject_type: str | None,
        subject_id: str | None,
        payload_json: str,
        schema_version: int,
        created_at: str,
    ) -> dict[str, str]:
        return {
            "event_id": event_id,
            "type": type_value,
            "actor": actor,
            "user_id": "" if user_id is None else str(user_id),
            "subject_type": subject_type or "",
            "subject_id": subject_id or "",
            "payload": payload_json,
            "schema_version": str(schema_version),
            "created_at": created_at,
        }

    async def _redis_xadd(self, redis_stream_key: str, fields: dict[str, str]) -> str:
        return await self._redis.xadd(
            redis_stream_key,
            maxlen=STREAM_MAXLEN,
            approximate=True,
            fields=fields,
        )

    async def relay_pending(self, *, batch_size: int = 200) -> int:
        """Xadd archived events that are not present on their Redis stream."""
        scan_limit = max(batch_size * 4, batch_size)
        rows = await self._events_db.fetch_all(
            """SELECT event_id, stream, type, actor, subject_type, subject_id,
                      user_id, payload, schema_version, created_at
               FROM events ORDER BY event_id DESC LIMIT ?""",
            (scan_limit,),
        )
        if not rows:
            return 0

        present_by_key: dict[str, set[str]] = {}
        for stream_enum in EventStream:
            redis_stream_key = f"{_STREAM_KEY_PREFIX}:{stream_enum.value}"
            try:
                entries = await self._redis.xrange(
                    redis_stream_key, min="-", max="+", count=STREAM_MAXLEN
                )
            except redis_exceptions.RedisError as exc:
                log.warning("outbox relay could not read stream=%s err=%s", stream_enum.value, exc)
                entries = []
            present_by_key[redis_stream_key] = {
                (fields or {}).get("event_id", "")
                for _mid, fields in entries
                if fields
            }

        relayed = 0
        for row in rows:
            if relayed >= batch_size:
                break
            redis_stream_key = f"{_STREAM_KEY_PREFIX}:{row['stream']}"
            if row["event_id"] in present_by_key.get(redis_stream_key, set()):
                continue
            fields = self._stream_fields(
                event_id=row["event_id"],
                type_value=row["type"],
                actor=row["actor"],
                user_id=row["user_id"],
                subject_type=row["subject_type"],
                subject_id=row["subject_id"],
                payload_json=row["payload"],
                schema_version=int(row["schema_version"]),
                created_at=row["created_at"],
            )
            try:
                await self._redis_xadd(redis_stream_key, fields)
            except redis_exceptions.RedisError as exc:
                log.warning(
                    "outbox relay xadd failed event=%s stream=%s err=%s",
                    row["event_id"], row["stream"], exc,
                )
                continue
            present_by_key.setdefault(redis_stream_key, set()).add(row["event_id"])
            relayed += 1
        return relayed

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

        next_reclaim = 0.0
        while True:
            # Reclaim before reading. A message another consumer took and never
            # acked (process killed mid-handler) is invisible to ">" reads and
            # would otherwise be stranded in the pending list indefinitely.
            now = asyncio.get_running_loop().time()
            if now >= next_reclaim:
                next_reclaim = now + PENDING_RECLAIM_EVERY_S
                await self._reclaim_pending(
                    redis_stream_key=redis_stream_key,
                    group=group,
                    consumer=consumer,
                    handler=handler,
                    max_retries=max_retries,
                    batch_size=batch_size,
                )

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

    async def _reclaim_pending(
        self,
        *,
        redis_stream_key: str,
        group: str,
        consumer: str,
        handler: Callable[[dict[str, Any]], Awaitable[None]],
        max_retries: int,
        batch_size: int,
    ) -> None:
        """Take over messages idle longer than PENDING_RECLAIM_IDLE_MS.

        XAUTOCLAIM reassigns them to this consumer and returns them, so they run
        through the same idempotent path as a fresh delivery. An event already
        recorded in `applied_events` is simply acked, which is what makes taking
        over another consumer's in-flight work safe.
        """
        try:
            _cursor, messages, _deleted = await self._redis.xautoclaim(
                redis_stream_key,
                group,
                consumer,
                min_idle_time=PENDING_RECLAIM_IDLE_MS,
                count=batch_size,
            )
        except redis_exceptions.RedisError as exc:
            log.warning("xautoclaim failed key=%s group=%s err=%s", redis_stream_key, group, exc)
            return

        if not messages:
            return
        log.info("reclaimed %d stranded message(s) key=%s group=%s", len(messages), redis_stream_key, group)
        for message_id, fields in messages:
            # XAUTOCLAIM can return (id, None) for entries trimmed out of the
            # stream while still pending. There is nothing to hand a handler, so
            # ack to clear the pending entry.
            if not fields:
                await self._redis.xack(redis_stream_key, group, message_id)
                continue
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
            except Exception as exc:  # noqa: BLE001 - must not crash the consumer loop
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "event handler failed group=%s event=%s attempt=%d/%d err=%s",
                    group, event_id, attempt, max_retries, last_error,
                )
                if attempt < max_retries:
                    await asyncio.sleep(min(0.5 * attempt, 2.0))
                continue

            # The handler succeeded. Recording that and acking are bookkeeping,
            # and they sit outside the retry `try` on purpose. `INSERT OR IGNORE`
            # matters: a plain INSERT raises on the UNIQUE (consumer, event_id)
            # constraint when this event was already applied (a redelivery, or a
            # second replica of the same group), and if that raise were caught as
            # a handler failure the handler would be run again for its side
            # effects and a successfully processed event would land in
            # `dead_letters`.
            try:
                await self._events_db.execute(
                    "INSERT OR IGNORE INTO applied_events (consumer, event_id, applied_at) "
                    "VALUES (?, ?, ?)",
                    (group, event_id, _now_iso()),
                )
            except Exception as exc:  # noqa: BLE001
                # Losing the idempotency marker only risks re-processing later,
                # which consumers are required to tolerate. Losing the ack would
                # guarantee it.
                log.error(
                    "could not record applied_events group=%s event=%s err=%s",
                    group, event_id, exc,
                )
            await self._redis.xack(redis_stream_key, group, message_id)
            return

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
