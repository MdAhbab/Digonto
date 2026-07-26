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
        db: Any | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._emb = embedder
        self._q = qdrant or AsyncQdrantClient(url=self._s.qdrant_url)
        # app.db, for `lexical_only`. Optional so a caller that only ever uses the
        # dense path (the embedder's own verification, tests) need not supply one;
        # `lexical_only` returns nothing rather than raising when it is absent, which
        # keeps "no fallback configured" and "fallback found nothing" the same outcome
        # for the pipeline: refuse.
        self._db = db

    async def ensure_collections(self) -> None:
        """Create the cache collection if absent. The knowledge collection is
        created by the embedder worker, which owns versioning."""
        try:
            existing = {c.name for c in (await self._q.get_collections()).collections}
            if CACHE_COLLECTION not in existing:
                await self._q.create_collection(
                    collection_name=CACHE_COLLECTION,
                    vectors_config=qm.VectorParams(size=EMBED_DIM, distance=qm.Distance.COSINE),
                )
        except Exception as exc:  # noqa: BLE001
            log.warning("could not connect to Qdrant or create collection: %s", exc)

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

    async def lexical_only(
        self, query: str, *, country: str | None, limit: int
    ) -> list[Passage]:
        """Retrieve straight from SQLite, with no vector store involved.

        This exists because the vector store is a single point of failure for the
        entire product, and it was behaving like one. `dense()` correctly returns an
        empty list when no collection is live, `search()` correctly returns nothing,
        and the pipeline correctly refuses. Each step is right and the composition is
        a service that answers nothing at all: a fresh deployment, a Qdrant restart,
        or an unfinished first embedding pass takes every question down, including the
        ones whose answer is sitting in `passages` in the same database as the
        question.

        The fallback is lexical rather than approximate-dense because `passages`
        already holds the text and BM25 needs nothing but the text. Citations stay
        exactly as trustworthy: every row here carries the real snapshot it came from,
        so an answer built from these passages is verifiable in the Truth Ledger in
        the same way as one built from a vector hit. What degrades is recall on
        paraphrase, which is the honest cost and is reported as
        `served_by = "degraded"` rather than hidden.

        Candidate generation is a LIKE scan over the query's own tokens. That is
        crude, and it is bounded on purpose: this path runs when the good path is
        broken, so its job is to be simple enough to be trustworthy under exactly the
        conditions that broke the other one.
        """
        if self._db is None:
            return []
        tokens = [t for t in tokenise(query) if len(t) > 2][:12]
        if not tokens:
            return []

        # One OR of LIKEs, plus the country filter the dense path applies as a
        # Qdrant filter. NULL country is admitted for both, because a Bangladesh Bank
        # remittance rule or an IELTS band applies to every destination.
        like_sql = " OR ".join("p.text LIKE ?" for _ in tokens)
        params: list[Any] = [f"%{t}%" for t in tokens]
        country_sql = ""
        if country:
            country_sql = " AND (po.country_code = ? OR po.country_code IS NULL)"
            params.append(country)
        params.append(limit * 4)

        rows = await self._db.fetch_all(
            f"""SELECT p.id AS passage_id, p.text, p.section_path,
                       s.id AS snapshot_id, s.public_id AS snapshot_public_id,
                       s.fetched_at AS captured,
                       po.label AS portal, po.url AS portal_url
                  FROM passages p
                  JOIN snapshots s ON s.id = p.snapshot_id
                  JOIN portals   po ON po.id = s.portal_id
                 WHERE ({like_sql}){country_sql}
                   AND s.retired_at IS NULL
                 ORDER BY s.fetched_at DESC
                 LIMIT ?""",
            tuple(params),
        )
        candidates = [
            Passage(
                passage_id=int(r["passage_id"]),
                snapshot_id=int(r["snapshot_id"]),
                snapshot_public_id=str(r["snapshot_public_id"]),
                portal=str(r["portal"] or ""),
                portal_url=str(r["portal_url"] or ""),
                captured=str(r["captured"] or ""),
                text=str(r["text"] or ""),
                section_path=str(r["section_path"] or ""),
                payload={"degraded": True},
            )
            for r in rows
        ]
        if not candidates:
            return []

        # BM25 over the shortlist decides the order, exactly as it does on the dense
        # path. Without a dense ranking to fuse with, the lexical rank *is* the rank.
        self.lexical(query, candidates)
        candidates.sort(key=lambda c: c.lexical_rank or 10**6)
        return candidates[:limit]

    async def search(
        self, query: str, *, country: str | None = None
    ) -> tuple[list[Passage], bool]:
        """Dense search, lexical re-rank, fuse, and cut to the rerank width.

        Returns `(passages, degraded)`. `degraded` is True when the answer was built
        without the vector store, so the caller can label it instead of presenting a
        lexical-only result as though the full pipeline had run.
        """
        # An embedding failure is not a reason to answer nothing. The embedding model can
        # be cold, evicted, or briefly unreachable, and none of those mean the archive has
        # no answer: the passages are in SQLite and BM25 needs no vector at all. Before
        # the shared client's timeout was corrected in app/main.py this was the single
        # most common way for a question to fail, and it failed *before* reaching the
        # fallback that existed to cover exactly this.
        try:
            vector = await self._emb.embed_one(query)
            candidates = await self.dense(vector, country=country, limit=self._s.retrieval_top_k)
        except Exception as exc:  # noqa: BLE001 - degrade, never fail the question
            log.warning("dense retrieval unavailable (%s); falling back to lexical", exc)
            candidates = []
        if not candidates:
            fallback = await self.lexical_only(
                query, country=country, limit=self._s.retrieval_rerank_to
            )
            if fallback:
                log.warning(
                    "no dense candidates for %r; answered from the SQLite lexical "
                    "fallback with %d passage(s)", query[:60], len(fallback),
                )
            return fallback, True

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
        return ranked[: self._s.retrieval_rerank_to], False
