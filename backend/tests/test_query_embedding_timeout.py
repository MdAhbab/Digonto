"""The query embedding is bounded, because a slow failure here is invisible.

Every question embeds its query before it retrieves anything. On a machine where Ollama can
hold one model at a time, that request waits for a runner slot the generation model owns for
the length of `OLLAMA_KEEP_ALIVE`, so it does not fail: it hangs.

Measured on the running app: 186 seconds per question. The retriever's keyword fallback was
working correctly the whole time and answered as soon as the embedding gave up, so nothing
looked broken, and the only symptom was that every answer took three minutes. With the
timeout the same question degraded at 25 seconds and finished in 36.

These tests hold the two properties that matter: the ceiling is applied to the interactive
call, and it is well below the timeout of the client that carries the request.
"""

from __future__ import annotations

import httpx
import pytest

from app.rag.embeddings import EMBED_DIM, QUERY_EMBED_TIMEOUT_SECONDS, Embedder


def test_the_ceiling_is_short_enough_to_matter_and_long_enough_to_work():
    """Below the generation read timeout by a wide margin, and above a cold model load.

    A cold bge-m3 load on CPU is a few seconds. If the bound were tighter than that, the
    vector index would be abandoned on the first question after every restart.
    """
    assert 10.0 <= QUERY_EMBED_TIMEOUT_SECONDS <= 45.0


@pytest.mark.asyncio
async def test_the_interactive_call_carries_the_ceiling_not_the_clients_default():
    """The shared client is configured for generation, which legitimately takes minutes. An
    embedding inheriting that is the bug this guards."""
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["timeout"] = request.extensions.get("timeout")
        return httpx.Response(200, json={"embeddings": [[0.1] * EMBED_DIM]})

    # A deliberately long client timeout, standing in for the generation client.
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), timeout=httpx.Timeout(180.0)
    ) as c:
        vector = await Embedder(client=c).embed_one("uk student visa funds")

    assert len(vector) == EMBED_DIM
    applied = seen["timeout"]
    assert isinstance(applied, dict)
    assert applied["read"] == QUERY_EMBED_TIMEOUT_SECONDS, (
        f"embed_one used the client default {applied['read']} rather than its own ceiling"
    )


@pytest.mark.asyncio
async def test_a_timeout_propagates_so_the_retriever_can_fall_back():
    """It must raise rather than return an empty vector. An empty vector would be searched
    against the index and match arbitrary passages, which is worse than keyword retrieval:
    the citations would be real but unrelated to the question."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("no runner slot", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
        with pytest.raises(httpx.ReadTimeout):
            await Embedder(client=c).embed_one("uk student visa funds")
