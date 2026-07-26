"""Text embedding through the same Ollama runtime that serves the model.

One runtime for generation and embedding is a deliberate choice: a second
service would be a second thing to keep resident in the memory of a machine that
is already holding a language model.

Every embedding is cached in Redis keyed by a hash of the text. The crawl loop
re-embeds only changed passages, so a cache miss is the exception rather than
the rule, and a query that repeats costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Sequence

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)

# bge-m3 produces 1024-dimensional vectors. Declared here because the Qdrant
# collection has to be created with a matching size before anything is written.
EMBED_DIM = 1024

# Ceiling on a single query embedding, which is the first thing every question does.
#
# It has to be much shorter than the generation timeout, and the reason is the sentence
# above this module's docstring. Ollama serves one model runner at a time on a machine this
# size, and the generation model holds it for OLLAMA_KEEP_ALIVE. An embedding request that
# arrives while that model is resident waits for a slot that will not free for the whole
# keep-alive period, so it does not fail: it hangs.
#
# Observed on the deployment VM: every question sat for 180 seconds, the read timeout of the
# shared HTTP client, and only then fell back to keyword retrieval and answered. The
# fallback worked and was invisible, because the failure was slow rather than loud.
#
# Twenty five seconds covers a cold bge-m3 load on CPU, which is a few seconds, with room to
# spare. Past that the vector index is not going to answer this question in time, and
# keyword retrieval over the same archived sources is a far better outcome for the student
# than three more minutes of waiting.
QUERY_EMBED_TIMEOUT_SECONDS = 25.0


def text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Embedder:
    def __init__(
        self,
        settings: Settings | None = None,
        redis: object | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings or get_settings()
        self._redis = redis
        self._client = client or httpx.AsyncClient(timeout=60.0)
        self._owns_client = client is None

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _cached(self, key: str) -> list[float] | None:
        if self._redis is None:
            return None
        try:
            raw = await self._redis.get(f"emb:{key}")  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a cache miss must never fail a query
            return None
        if not raw:
            return None
        try:
            return json.loads(raw)
        except ValueError:
            return None

    async def _store(self, key: str, vector: list[float]) -> None:
        if self._redis is None:
            return
        try:
            # Thirty days. Embeddings are deterministic for a fixed model, so the
            # only reason to expire them at all is to bound memory.
            await self._redis.setex(f"emb:{key}", 60 * 60 * 24 * 30, json.dumps(vector))  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass

    async def embed_one(self, text: str) -> list[float]:
        """Embed one query. This is on the interactive path, so it is bounded tightly.

        See QUERY_EMBED_TIMEOUT_SECONDS: a stuck embedding must degrade to keyword
        retrieval quickly rather than hold the answer open for the client's read timeout.
        """
        key = text_key(text)
        hit = await self._cached(key)
        if hit is not None:
            return hit

        r = await self._client.post(
            f"{self._s.ollama_base_url}/api/embed",
            json={"model": self._s.embed_model, "input": text, "keep_alive": self._s.ollama_keep_alive},
            timeout=QUERY_EMBED_TIMEOUT_SECONDS,
        )
        r.raise_for_status()
        data = r.json()
        vectors = data.get("embeddings") or []
        if not vectors:
            raise RuntimeError(f"embedding model returned nothing for {len(text)} characters")
        vector = vectors[0]
        await self._store(key, vector)
        return vector

    async def embed_many(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, serving whatever is already cached without a call."""
        out: list[list[float] | None] = [None] * len(texts)
        pending: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            hit = await self._cached(text_key(text))
            if hit is not None:
                out[i] = hit
            else:
                pending.append((i, text))

        if pending:
            r = await self._client.post(
                f"{self._s.ollama_base_url}/api/embed",
                json={
                    "model": self._s.embed_model,
                    "input": [t for _, t in pending],
                    "keep_alive": self._s.ollama_keep_alive,
                },
            )
            r.raise_for_status()
            vectors = r.json().get("embeddings") or []
            if len(vectors) != len(pending):
                raise RuntimeError(
                    f"embedding model returned {len(vectors)} vectors for {len(pending)} inputs"
                )
            for (i, text), vector in zip(pending, vectors, strict=True):
                out[i] = vector
                await self._store(text_key(text), vector)

        return [v for v in out if v is not None]
