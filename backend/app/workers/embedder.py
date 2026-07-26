"""Embedding worker: consumes `kb.chunk.updated`, publishes new KB versions.

Only passages whose content is actually new get embedded. Every other
passage currently live is carried into the new version by copying its
existing vector, found by matching `passages.text_hash` against what the
*current* live version already has embedded — this is what "unchanged"
means here, and it needs no bookkeeping beyond the `text_hash` column that
already exists, because every crawl creates fresh `passages` rows (new ids)
even when the text itself has not changed at all.

`sync_kb_version` takes no argument naming which passage changed: it
recomputes "current passages" vs. "what the live version already has, by
hash" from the database and Qdrant directly, every time. Two things follow
from that. First, it is trivially idempotent — a redelivered or duplicate
`kb.chunk.updated` event is a cheap no-op once its passage is already
covered. Second, since `EventBus.consume` runs one handler at a time to
completion before reading the next message, a burst of events from one
crawl naturally coalesces: whichever event's handler acquires the lock
first embeds everything that is new *at that moment*, and every sibling
event still queued behind it finds nothing left to do when its turn comes.
No debounce timer, no in-memory pending set, and therefore nothing lost if
the process dies mid-batch: the next `kb.chunk.updated` (or a manual nudge)
just recomputes the same diff against the database again.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient, models

from app.config import Settings
from app.db.connection import Databases
from app.events.bus import EventBus, EventStream, EventType
from app.repositories._util import utc_now_iso
from app.workers._kb import (
    KB_ALIAS,
    embed_texts,
    ensure_collection,
    flip_alias,
    invalidate_cache_for_snapshots,
)

log = logging.getLogger(__name__)

CONSUMER_GROUP = "embedder"

# Guards against two sync passes running concurrently. Not load-bearing for
# correctness with a single consumer task (bus.consume already serialises
# handler calls), but cheap insurance if this is ever invoked from more than
# one place.
_sync_lock = asyncio.Lock()


async def _current_passages(dbs: Databases) -> list[dict[str, Any]]:
    """Every portal's most recent snapshot's passages: the complete set the
    live KB version should represent."""
    rows = await dbs.app.fetch_all(
        """SELECT pg.id, pg.snapshot_id, pg.text, pg.text_hash, sn.portal_id
           FROM passages pg
           JOIN snapshots sn ON sn.id = pg.snapshot_id
           JOIN (
               SELECT portal_id, MAX(fetched_at) AS max_fetched
               FROM snapshots GROUP BY portal_id
           ) latest ON latest.portal_id = sn.portal_id AND latest.max_fetched = sn.fetched_at"""
    )
    return [dict(r) for r in rows]


async def _superseded_snapshot_ids(dbs: Databases, portal_ids: set[int]) -> set[int]:
    superseded: set[int] = set()
    for portal_id in portal_ids:
        latest = await dbs.app.fetch_one(
            "SELECT id FROM snapshots WHERE portal_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (portal_id,),
        )
        if latest is None:
            continue
        older = await dbs.app.fetch_all(
            "SELECT id FROM snapshots WHERE portal_id = ? AND id != ?", (portal_id, latest["id"])
        )
        superseded.update(r["id"] for r in older)
    return superseded


async def sync_kb_version(
    *,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
) -> None:
    """Reconciles the live KB version against the current passage set."""
    async with _sync_lock:
        current = await _current_passages(dbs)
        if not current:
            return

        live_row = await dbs.app.fetch_one("SELECT * FROM kb_versions WHERE status = 'live'")
        live = dict(live_row) if live_row else None

        embedded_by_hash: dict[str, str] = {}
        if live is not None:
            chunk_rows = await dbs.app.fetch_all(
                """SELECT kc.qdrant_point_id, pg.text_hash FROM kb_chunks kc
                   JOIN passages pg ON pg.id = kc.passage_id
                   WHERE kc.kb_version_id = ?""",
                (live["id"],),
            )
            for r in chunk_rows:
                embedded_by_hash.setdefault(r["text_hash"], r["qdrant_point_id"])

        to_embed = [p for p in current if p["text_hash"] not in embedded_by_hash]
        if not to_embed and live is not None:
            return  # every current passage is already live, by hash; nothing to do

        # The embedding HTTP call happens before any DB write below, per the
        # "never hold a write transaction across a model call" rule.
        vectors = await embed_texts(http_client, settings, [p["text"] for p in to_embed])
        if not vectors:
            return
        vector_size = len(vectors[0])

        version_no = (live["version_no"] + 1) if live else 1
        collection_name = f"kb_v{version_no}"
        await ensure_collection(qdrant, collection_name, vector_size)

        embed_ids = {p["id"] for p in to_embed}
        points: list[models.PointStruct] = []
        chunk_rows_out: list[tuple[int, str]] = []

        for p, vec in zip(to_embed, vectors):
            point_id = str(uuid.uuid4())
            points.append(
                models.PointStruct(
                    id=point_id,
                    vector=vec,
                    payload={"passage_id": p["id"], "snapshot_id": p["snapshot_id"]},
                )
            )
            chunk_rows_out.append((p["id"], point_id))

        to_copy = [p for p in current if p["id"] not in embed_ids]
        if to_copy and live is not None:
            source_ids = [embedded_by_hash[p["text_hash"]] for p in to_copy]
            fetched = await qdrant.retrieve(
                live["qdrant_collection"], ids=source_ids, with_vectors=True
            )
            vector_by_source_id = {rec.id: rec.vector for rec in fetched}
            for p in to_copy:
                source_point_id = embedded_by_hash[p["text_hash"]]
                vec = vector_by_source_id.get(source_point_id)
                if vec is None:
                    continue  # source point vanished between lookup and retrieve; catch it next cycle
                new_point_id = str(uuid.uuid4())
                points.append(
                    models.PointStruct(
                        id=new_point_id,
                        vector=vec,
                        payload={"passage_id": p["id"], "snapshot_id": p["snapshot_id"]},
                    )
                )
                chunk_rows_out.append((p["id"], new_point_id))

        if not points:
            return

        for start in range(0, len(points), 128):
            await qdrant.upsert(collection_name, points=points[start : start + 128])

        now = utc_now_iso()
        async with dbs.app.transaction() as tx:
            if live is not None:
                await tx.execute(
                    "UPDATE kb_versions SET status = 'retired', retired_at = ? WHERE id = ?",
                    (now, live["id"]),
                )
            await tx.execute(
                """INSERT INTO kb_versions
                   (version_no, qdrant_collection, status, chunk_count, built_at, published_at)
                   VALUES (?, ?, 'live', ?, ?, ?)""",
                (version_no, collection_name, len(points), now, now),
            )
        new_version = await dbs.app.fetch_one(
            "SELECT id FROM kb_versions WHERE qdrant_collection = ?", (collection_name,)
        )
        assert new_version is not None
        kb_version_id = new_version["id"]

        async with dbs.app.transaction() as tx:
            for passage_id, point_id in chunk_rows_out:
                await tx.execute(
                    "INSERT INTO kb_chunks (kb_version_id, passage_id, qdrant_point_id, embedded_at) "
                    "VALUES (?, ?, ?, ?)",
                    (kb_version_id, passage_id, point_id, now),
                )

        await flip_alias(qdrant, KB_ALIAS, collection_name)

        await bus.publish(
            EventType.KB_VERSION_PUBLISHED,
            payload={
                "kb_version_id": kb_version_id,
                "version_no": version_no,
                "qdrant_collection": collection_name,
                "chunk_count": len(points),
                "previous_version_id": live["id"] if live else None,
            },
            actor="worker:embedder",
            subject_type="kb_version",
            subject_id=str(version_no),
        )

        portal_ids = {p["portal_id"] for p in to_embed}
        superseded = await _superseded_snapshot_ids(dbs, portal_ids)
        await invalidate_cache_for_snapshots(qdrant, superseded)


async def _handle_kb_chunk_updated(
    message: dict[str, Any],
    *,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
) -> None:
    if message.get("type") != EventType.KB_CHUNK_UPDATED.value:
        return
    payload = message.get("payload") or {}
    if payload.get("passage_id") is None:
        return
    await sync_kb_version(dbs=dbs, bus=bus, settings=settings, http_client=http_client, qdrant=qdrant)


async def consume(
    bus: EventBus,
    dbs: Databases,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
) -> None:
    consumer_name = f"{CONSUMER_GROUP}-{os.getpid()}"

    async def handler(message: dict[str, Any]) -> None:
        await _handle_kb_chunk_updated(
            message, dbs=dbs, bus=bus, settings=settings, http_client=http_client, qdrant=qdrant
        )

    await bus.consume(EventStream.KB, CONSUMER_GROUP, consumer_name, handler)
