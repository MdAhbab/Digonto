"""Hybrid retrieval: dense vectors from Qdrant, lexical scores from BM25, fused.

Two reasons this is hybrid rather than dense alone. Visa questions turn on exact
tokens, and a dense index will happily return a passage about the wrong country's
fee because it is semantically adjacent. And Bangla and English are mixed within
single questions, where a lexical match on a proper noun is often the strongest
signal available.

Reciprocal rank fusion is used rather than score normalisation because the two
scorers produce values on incomparable scales, and RRF needs no tuning to
combine them.

Tokenisation is the part worth reading. Splitting on whitespace destroys Bangla:
the script has no inter-word spacing conventions that match Latin, and naive
regex word boundaries break conjuncts. Bengali and Latin ranges are therefore
tokenised separately.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Sequence

from qdrant_client import AsyncQdrantClient, models as qm
from rank_bm25 import BM25Okapi

from app.config import Settings, get_settings
from app.rag.embeddings import EMBED_DIM, Embedder

log = logging.getLogger(__name__)

# The alias the embedder worker flips atomically when a new knowledge version is
# published. Never read a concrete collection name: doing so races the flip.
LIVE_ALIAS = "digonto_kb_live"
CACHE_COLLECTION = "digonto_cache"

# Bengali block. Kept explicit because it is the whole reason for a custom
# tokeniser rather than \w+.
_BENGALI = r"ঀ-৿"
_TOKEN = re.compile(rf"[{_BENGALI}]+|[A-Za-z]+|\d+")


def tokenise(text: str) -> list[str]:
    """Tokenise mixed Bangla and Latin text without destroying either."""
    return [t.lower() for t in _TOKEN.findall(text or "")]


@dataclass(slots=True)
class Passage:
    passage_id: int
    snapshot_id: int
    snapshot_public_id: str
    portal: str
    portal_url: str
    captured: str
    text: str
    section_path: str = ""
    dense_rank: int | None = None
    lexical_rank: int | None = None
    fused_score: float = 0.0
    payload: dict[str, Any] = field(default_factory=dict)


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = 60
) -> dict[str, float]:
    """Standard RRF. k=60 is the value from the original paper.

    Returns a mapping of identifier to fused score. Identifiers absent from a
    ranking simply contribute nothing from it, which is the property that makes
    RRF robust when one retriever returns very few results.
    """
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
    return scores


class Retriever:
    def __init__(
        self,
        embedder: Embedder,
        settings: Settings | None = None,
        qdrant: AsyncQdrantClient | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._emb = embedder
        self._q = qdrant or AsyncQdrantClient(url=self._s.qdrant_url)

    async def ensure_collections(self) -> None:
        """Create the cache collection if absent. The knowledge collection is
        created by the embedder worker, which owns versioning."""
        existing = {c.name for c in (await self._q.get_collections()).collections}
        if CACHE_COLLECTION not in existing:
            await self._q.create_collection(
                collection_name=CACHE_COLLECTION,
                vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
            )

    async def live_collection(self) -> str | None:
        """Resolve the alias to the collection currently serving reads."""
        try:
            aliases = await self._q.get_aliases()
        except Exception as exc:  # noqa: BLE001
            log.warning("could not read qdrant aliases: %s", exc)
            return None
        for a in aliases.aliases:
            if a.alias_name == LIVE_ALIAS:
                return a.collection_name
        return None

    async def dense(
        self, query_vector: list[float], *, country: str | None, limit: int
    ) -> list[Passage]:
        collection = await self.live_collection()
        if collection is None:
            # No knowledge version has been published yet. This is a legitimate
            # state on a fresh deployment, and the caller must refuse rather
            # than answer from model memory.
            return []

        flt = None
        if country:
            flt = qm.Filter(
                should=[
                    qm.FieldCondition(key="country_code", match=qm.MatchValue(value=country)),
                    qm.IsNullCondition(is_null=qm.PayloadField(key="country_code")),
                ]
            )

        hits = await self._q.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=flt,
            limit=limit,
            with_payload=True,
        )
        out: list[Passage] = []
        for rank, h in enumerate(hits, start=1):
            p = h.payload or {}
            out.append(
                Passage(
                    passage_id=int(p.get("passage_id", 0)),
                    snapshot_id=int(p.get("snapshot_id", 0)),
                    snapshot_public_id=str(p.get("snapshot_public_id", "")),
                    portal=str(p.get("portal", "")),
                    portal_url=str(p.get("portal_url", "")),
                    captured=str(p.get("captured", "")),
                    text=str(p.get("text", "")),
                    section_path=str(p.get("section_path", "")),
                    dense_rank=rank,
                    payload=p,
                )
            )
        return out

    def lexical(self, query: str, candidates: list[Passage]) -> list[Passage]:
        """Re-rank the dense candidate set lexically.

        BM25 runs over the candidates rather than the whole corpus. Building a
        corpus-wide sparse index in memory would not survive the corpus growing,
        and re-ranking a shortlist captures most of the benefit.
        """
        if not candidates:
            return []
        corpus = [tokenise(c.text) for c in candidates]
        if not any(corpus):
            return candidates
        bm25 = BM25Okapi(corpus)
        scores = bm25.get_scores(tokenise(query))
        order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
        for rank, idx in enumerate(order, start=1):
            candidates[idx].lexical_rank = rank
        return candidates

    async def search(
        self, query: str, *, country: str | None = None
    ) -> list[Passage]:
        """Dense search, lexical re-rank, fuse, and cut to the rerank width."""
        vector = await self._emb.embed_one(query)
        candidates = await self.dense(vector, country=country, limit=self._s.retrieval_top_k)
        if not candidates:
            return []

        self.lexical(query, candidates)

        by_key = {str(c.passage_id): c for c in candidates}
        dense_ranking = [
            str(c.passage_id)
            for c in sorted(
                (c for c in candidates if c.dense_rank), key=lambda c: c.dense_rank or 0
            )
        ]
        lexical_ranking = [
            str(c.passage_id)
            for c in sorted(
                (c for c in candidates if c.lexical_rank), key=lambda c: c.lexical_rank or 0
            )
        ]

        fused = reciprocal_rank_fusion([dense_ranking, lexical_ranking])
        for key, score in fused.items():
            if key in by_key:
                by_key[key].fused_score = score

        ranked = sorted(by_key.values(), key=lambda c: c.fused_score, reverse=True)
        return ranked[: self._s.retrieval_rerank_to]
