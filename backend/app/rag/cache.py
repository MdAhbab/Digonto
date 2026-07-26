"""Semantic cache: serve a repeated question without regenerating it.

Visa questions cluster tightly. A few dozen concerns account for most of what
students ask, phrased a hundred different ways, which is exactly the shape a
cache keyed by meaning rather than by exact text can exploit.

The correctness rule matters more than the speed. A cached answer is served only
when the similarity clears the threshold AND it was produced under the knowledge
version that is live right now AND the country filter matches. Serving an answer
generated under a superseded knowledge version would mean telling a student a
rule that has since changed, which is the precise failure this whole system
exists to prevent. That is a correctness bug, not a stale cache.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from qdrant_client import AsyncQdrantClient, models as qm

from app.config import Settings, get_settings
from app.rag.embeddings import EMBED_DIM, Embedder
from app.rag.retrieval import CACHE_COLLECTION

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CachedAnswer:
    answer_primary: str
    answer_alt: str
    alt_lang: str
    citations: list[dict[str, Any]]
    confidence: float | None
    is_refusal: bool
    refusal_reason_en: str
    refusal_reason_bn: str
    similarity: float


class SemanticCache:
    def __init__(
        self,
        embedder: Embedder,
        settings: Settings | None = None,
        qdrant: AsyncQdrantClient | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._emb = embedder
        self._q = qdrant or AsyncQdrantClient(url=self._s.qdrant_url)

    async def lookup(
        self,
        question: str,
        *,
        kb_version_id: int | None,
        country: str | None,
        lang: str,
    ) -> CachedAnswer | None:
        if kb_version_id is None:
            return None
        try:
            vector = await self._emb.embed_one(question)
            must: list[qm.Condition] = [
                qm.FieldCondition(
                    key="kb_version_id", match=qm.MatchValue(value=int(kb_version_id))
                ),
                qm.FieldCondition(key="lang", match=qm.MatchValue(value=lang)),
            ]
            # A cached answer scoped to one country must not be served to
            # another. An unscoped answer is reusable for any country.
            must.append(
                qm.FieldCondition(key="country", match=qm.MatchValue(value=country or ""))
            )

            hits = await self._q.search(
                collection_name=CACHE_COLLECTION,
                query_vector=vector,
                query_filter=qm.Filter(must=must),
                limit=1,
                with_payload=True,
                score_threshold=self._s.semantic_cache_threshold,
            )
        except Exception as exc:  # noqa: BLE001 - a cache failure must not fail the answer
            log.warning("semantic cache lookup failed: %s", exc)
            return None

        if not hits:
            return None

        p = hits[0].payload or {}
        return CachedAnswer(
            answer_primary=str(p.get("answer_primary", "")),
            answer_alt=str(p.get("answer_alt", "")),
            alt_lang=str(p.get("alt_lang", "en")),
            citations=list(p.get("citations", []) or []),
            confidence=p.get("confidence"),
            is_refusal=bool(p.get("is_refusal", False)),
            refusal_reason_en=str(p.get("refusal_reason_en", "")),
            refusal_reason_bn=str(p.get("refusal_reason_bn", "")),
            similarity=float(hits[0].score),
        )

    async def store(
        self,
        question: str,
        *,
        kb_version_id: int | None,
        country: str | None,
        lang: str,
        answer_primary: str,
        answer_alt: str,
        alt_lang: str,
        citations: list[dict[str, Any]],
        confidence: float | None,
        is_refusal: bool,
        refusal_reason_en: str = "",
        refusal_reason_bn: str = "",
        snapshot_ids: list[int] | None = None,
    ) -> None:
        if kb_version_id is None:
            return
        try:
            vector = await self._emb.embed_one(question)
            await self._q.upsert(
                collection_name=CACHE_COLLECTION,
                points=[
                    qm.PointStruct(
                        id=str(uuid.uuid4()),
                        vector=vector,
                        payload={
                            "question": question,
                            "kb_version_id": int(kb_version_id),
                            "country": country or "",
                            "lang": lang,
                            "answer_primary": answer_primary,
                            "answer_alt": answer_alt,
                            "alt_lang": alt_lang,
                            "citations": citations,
                            "confidence": confidence,
                            "is_refusal": is_refusal,
                            "refusal_reason_en": refusal_reason_en,
                            "refusal_reason_bn": refusal_reason_bn,
                            # Retained so a superseded snapshot can invalidate
                            # precisely the entries that cited it.
                            "snapshot_ids": snapshot_ids or [],
                        },
                    )
                ],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("semantic cache store failed: %s", exc)

    async def invalidate_by_snapshot(self, snapshot_ids: list[int]) -> int:
        """Drop every cached answer that cited any of these snapshots.

        Called by the embedder worker when a new knowledge version supersedes a
        page. Version filtering already prevents a stale answer being served, so
        this is housekeeping rather than the correctness guarantee.
        """
        if not snapshot_ids:
            return 0
        try:
            await self._q.delete(
                collection_name=CACHE_COLLECTION,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        should=[
                            qm.FieldCondition(
                                key="snapshot_ids", match=qm.MatchAny(any=snapshot_ids)
                            )
                        ]
                    )
                ),
            )
            return len(snapshot_ids)
        except Exception as exc:  # noqa: BLE001
            log.warning("semantic cache invalidation failed: %s", exc)
            return 0
