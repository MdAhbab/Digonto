"""Shared Qdrant + Ollama-embedding primitives.

Factored out of `app/workers/embedder.py` because `app/workers/learner.py`
needs the exact same two things for the benchmark promotion gate: embed a
question through the same `embed_model`, and read whichever Qdrant
collection the `kb_live` alias currently points at. Duplicating this would
risk the two workers quietly disagreeing about how the live collection is
found.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient, models

from app.config import Settings

log = logging.getLogger(__name__)

# Stable name the (not-yet-built) RAG pipeline is expected to query against,
# per backend/backend.md section 3.2 ("kb.version.published flips a
# collection alias atomically"). Never a collection name directly, so a
# reader never has to know the current version number.
KB_ALIAS = "kb_live"

# backend/backend.md section 4: "Semantic cache: ... Qdrant `cache`
# collection". Nothing in this codebase creates it yet (app/rag/pipeline.py
# is an explicit stub), so every reader here must tolerate its absence.
CACHE_COLLECTION = "cache"

_EMBED_BATCH_SIZE = 64


async def embed_texts(
    http_client: httpx.AsyncClient, settings: Settings, texts: list[str]
) -> list[list[float]]:
    """Ollama `POST /api/embed`, batched. One vector per input, in order."""
    if not texts:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(texts), _EMBED_BATCH_SIZE):
        batch = texts[start : start + _EMBED_BATCH_SIZE]
        r = await http_client.post(
            f"{settings.ollama_base_url}/api/embed",
            json={"model": settings.embed_model, "input": batch},
            timeout=120.0,
        )
        r.raise_for_status()
        embeddings = r.json().get("embeddings") or []
        if len(embeddings) != len(batch):
            raise RuntimeError(
                f"ollama /api/embed returned {len(embeddings)} vectors for {len(batch)} inputs"
            )
        vectors.extend(embeddings)
    return vectors


async def ensure_collection(client: AsyncQdrantClient, name: str, vector_size: int) -> None:
    if await client.collection_exists(name):
        return
    await client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=vector_size, distance=models.Distance.COSINE),
    )


async def flip_alias(client: AsyncQdrantClient, alias: str, new_collection: str) -> None:
    """Atomically point `alias` at `new_collection`, dropping any prior target.

    Every operation in one `update_collection_aliases` call is applied as a
    single request server-side, which is what makes the flip atomic: a
    reader resolving the alias mid-flip sees either the old or the new
    collection, never a moment where the alias resolves to nothing.
    """
    ops: list[Any] = []
    try:
        current = await client.get_aliases()
        for a in current.aliases:
            if a.alias_name == alias:
                ops.append(
                    models.DeleteAliasOperation(delete_alias=models.DeleteAlias(alias_name=alias))
                )
                break
    except Exception as exc:  # noqa: BLE001 - a brand new Qdrant has no aliases yet
        log.info("no existing alias %s to drop before flip (%s)", alias, exc)
    ops.append(
        models.CreateAliasOperation(
            create_alias=models.CreateAlias(collection_name=new_collection, alias_name=alias)
        )
    )
    await client.update_collection_aliases(change_aliases_operations=ops)


async def invalidate_cache_for_snapshots(
    client: AsyncQdrantClient, superseded_snapshot_ids: set[int]
) -> int:
    """Drop semantic-cache entries whose citations point at a superseded
    snapshot. Filters in Python rather than a Qdrant payload-index query,
    because nothing in this codebase creates the `cache` collection yet (the
    RAG pipeline that would write it is an explicit stub) and its payload
    shape is therefore not this worker's to assume; when it does not exist,
    that is a fact, not an error.
    """
    if not superseded_snapshot_ids:
        return 0
    if not await client.collection_exists(CACHE_COLLECTION):
        log.info("no %s collection yet; nothing to invalidate", CACHE_COLLECTION)
        return 0

    stale_ids: list[Any] = []
    offset = None
    while True:
        records, offset = await client.scroll(
            CACHE_COLLECTION, limit=256, offset=offset, with_payload=True, with_vectors=False,
        )
        for rec in records:
            citations = (rec.payload or {}).get("citations") or []
            if any(
                isinstance(c, dict) and c.get("snapshot_id") in superseded_snapshot_ids
                for c in citations
            ):
                stale_ids.append(rec.id)
        if offset is None:
            break

    if stale_ids:
        await client.delete(CACHE_COLLECTION, points_selector=models.PointIdsList(points=stale_ids))
        log.info("invalidated %d semantic cache entries citing superseded snapshots", len(stale_ids))
    return len(stale_ids)
