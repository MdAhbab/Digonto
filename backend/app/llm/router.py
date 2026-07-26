"""Model routing.

Two providers sit behind one interface. Which one serves a call is decided by the
kind of work, never by the call site guessing.

The split exists for one reason: some work is the product and some work is
plumbing-free preprocessing. Grounded answering, every agent, portal-change
classification, document vision, and interview scoring are the product, and they
run on the local Gemma model. Short, latency-sensitive, non-authoritative turns
(normalising a query, transliterating Banglish, naming a conversation) can run on
whichever provider is configured as the fast path.

Three constraints are enforced here rather than trusted to callers:

  1. `TaskKind.CORE` work never leaves the machine unless the operator has
     explicitly configured it to, and it degrades back to local on any doubt.
  2. A request carrying `contains_user_documents=True` can never be sent to a
     remote provider. It raises instead. This is what makes the promise that
     student documents never leave the deployment structurally true rather than
     a matter of review discipline.
  3. Remote calls are budgeted and rate limited, so an outage cannot produce a
     surprise bill.
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.config import Settings, get_settings

log = logging.getLogger(__name__)


class TaskKind(str, enum.Enum):
    """What a call is for. Determines routing, never the call site."""

    # --- Core: the product itself. Local model by default. -----------------
    GROUNDED_ANSWER = "grounded_answer"
    AGENT_TOOL = "agent_tool"
    CLASSIFY_CHANGE = "classify_change"
    VISION_EXTRACT = "vision_extract"
    INTERVIEW_SCORE = "interview_score"
    ELIGIBILITY_SCORE = "eligibility_score"

    # --- Fast: preprocessing and chrome. Routable. -------------------------
    NORMALISE_QUERY = "normalise_query"
    TRANSLITERATE = "transliterate"
    TITLE_CONVERSATION = "title_conversation"
    SUGGEST_FOLLOWUP = "suggest_followup"
    SUMMARISE_SHORT = "summarise_short"

    @property
    def is_core(self) -> bool:
        return self in _CORE_KINDS

    @property
    def num_ctx(self) -> int:
        """Context window to request for this kind of call.

        This has to be set explicitly. `gemma4:e2b` advertises a 131,072-token
        context, and the KV cache for a window that size is far larger than the
        weights: leaving it unset means the footprint is whatever the Ollama
        build happens to default to, which makes memory on the deployment VM
        non-deterministic and, on a bad default, fatal.

        Ollama allocates the KV cache per slot from the largest `num_ctx` it has
        been asked for, so the ceiling matters more than the average. These
        values are sized to what each task actually needs: a classification sees
        two short passages, a grounded answer sees four reranked passages plus
        two answers, and vision calls carry image tokens.
        """
        return _NUM_CTX.get(self, 4096)


_CORE_KINDS = frozenset(
    {
        TaskKind.GROUNDED_ANSWER,
        TaskKind.AGENT_TOOL,
        TaskKind.CLASSIFY_CHANGE,
        TaskKind.VISION_EXTRACT,
        TaskKind.INTERVIEW_SCORE,
        TaskKind.ELIGIBILITY_SCORE,
    }
)

# Per-kind context windows. Deliberately modest: on a CPU-only 8 GB VM the KV
# cache competes directly with the model weights, and every one of these tasks
# has a bounded, known prompt shape. Raise a single entry when a real prompt is
# measured against it, never the whole table for headroom.
_NUM_CTX: dict[TaskKind, int] = {
    # Four reranked passages (capped at 12k chars each by the framing helper is
    # the worst case, but reranking cuts to 4 and passages are ~1-2k chars),
    # a system prompt, and two full answers out.
    TaskKind.GROUNDED_ANSWER: 8192,
    TaskKind.AGENT_TOOL: 8192,
    # Two fenced passage diffs and a one-object reply.
    TaskKind.CLASSIFY_CHANGE: 4096,
    # Image tokens dominate; a single page at Gemma's tiling is the driver.
    TaskKind.VISION_EXTRACT: 8192,
    TaskKind.INTERVIEW_SCORE: 8192,
    TaskKind.ELIGIBILITY_SCORE: 8192,
    # Chrome. A few hundred tokens in, a few dozen out.
    TaskKind.NORMALISE_QUERY: 2048,
    TaskKind.TRANSLITERATE: 2048,
    TaskKind.TITLE_CONVERSATION: 2048,
    TaskKind.SUGGEST_FOLLOWUP: 2048,
    TaskKind.SUMMARISE_SHORT: 4096,
}


class DocumentContentLeak(RuntimeError):
    """Raised when user document content would be sent to a remote provider."""


@dataclass(slots=True)
class LLMRequest:
    kind: TaskKind
    messages: list[dict[str, Any]]
    tools: list[dict[str, Any]] | None = None
    json_schema: dict[str, Any] | None = None
    images: list[bytes] = field(default_factory=list)
    thinking: bool = False
    temperature: float = 0.2
    max_tokens: int = 1024
    # Set True by any caller whose prompt includes vault-derived text or images.
    # The router refuses to send these off the machine. Default False, but every
    # vault code path sets it explicitly.
    contains_user_documents: bool = False


@dataclass(slots=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    latency_ms: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    degraded: bool = False


class RemoteExhausted(RuntimeError):
    """No model in the remote chain has capacity. The caller should use the local model."""


class _RateLimited(RuntimeError):
    """One remote model refused with 429 or 503. Another may still have capacity."""

    def __init__(self, message: str, *, per_day: bool, retry_after: float) -> None:
        super().__init__(message)
        self.per_day = per_day
        self.retry_after = retry_after


# How long a model sits out after the API itself rejects a call, when the response gives no
# usable `Retry-After`. A per-minute rejection clears on its own within the minute; a
# per-day one does not, so it is held until the next UTC day, which is when Google's daily
# counters reset.
_RPM_COOLDOWN_SECONDS = 65.0
_SECONDS_PER_DAY = 86_400.0


class _ModelSlot:
    """One remote model, with the two ceilings it is subject to.

    Both are needed and neither is sufficient. The local counters stop this process from
    spending quota it knows it does not have, which is cheap and precise for its own
    traffic. The cooldown handles what the counters cannot see: the same API key used from
    a second machine, a shared project, or a limit that moved. When the two disagree, the
    API is right, so an observed 429 always wins.
    """

    __slots__ = ("name", "_max_rpm", "_daily_budget", "_recent", "_day", "_day_count", "_cooldown_until")

    def __init__(self, name: str, *, max_rpm: int, daily_budget: int) -> None:
        self.name = name
        self._max_rpm = max_rpm
        self._daily_budget = daily_budget
        self._recent: list[float] = []
        self._day = time.gmtime().tm_yday
        self._day_count = 0
        self._cooldown_until = 0.0

    def _roll_day(self) -> None:
        today = time.gmtime().tm_yday
        if today != self._day:
            self._day, self._day_count = today, 0

    def has_capacity(self, now: float) -> bool:
        self._roll_day()
        if now < self._cooldown_until:
            return False
        if self._daily_budget > 0 and self._day_count >= self._daily_budget:
            return False
        if self._max_rpm > 0:
            # A sliding window rather than a fixed interval. The published limit is a count
            # per minute, so two calls a second apart are fine at 5 per minute and a fixed
            # interval would have made the second one wait.
            self._recent = [t for t in self._recent if now - t < 60.0]
            if len(self._recent) >= self._max_rpm:
                return False
        return True

    def take(self, now: float) -> None:
        self._recent.append(now)
        self._day_count += 1

    def penalise(self, *, per_day: bool, retry_after: float, now: float) -> None:
        seconds = retry_after if retry_after > 0 else (
            _SECONDS_PER_DAY if per_day else _RPM_COOLDOWN_SECONDS
        )
        self._cooldown_until = max(self._cooldown_until, now + seconds)
        if per_day:
            # Stop the local counter disagreeing with the API for the rest of the day.
            self._day_count = max(self._day_count, self._daily_budget)

    def seconds_until_free(self, now: float) -> float:
        """0 when usable now. Exact for a cooldown and for the sliding window; a day-long
        block reports the remainder of the day, because that counter is cleared by the UTC
        date rolling over rather than by a timer held here."""
        if now < self._cooldown_until:
            return self._cooldown_until - now
        self._roll_day()
        if self._daily_budget > 0 and self._day_count >= self._daily_budget:
            return _SECONDS_PER_DAY
        if self._max_rpm > 0:
            self._recent = [t for t in self._recent if now - t < 60.0]
            if len(self._recent) >= self._max_rpm:
                return max(0.0, 60.0 - (now - self._recent[0]))
        return 0.0


class _ModelPool:
    """The remote chain, in priority order, with one slot per model.

    `pick` reserves capacity, so the count is incremented before the call rather than after
    it. Counting on success would let a burst of concurrent requests all pass the check and
    then all exceed the limit, which is the failure the limit exists to prevent.
    """

    def __init__(self, chain: list[tuple[str, int, int]]) -> None:
        self._slots = [
            _ModelSlot(name, max_rpm=rpm, daily_budget=rpd) for name, rpm, rpd in chain
        ]
        self._lock = asyncio.Lock()

    @property
    def names(self) -> list[str]:
        return [s.name for s in self._slots]

    async def pick(self, *, skip: set[str] | None = None) -> str | None:
        """The first model in the chain with capacity, or None."""
        skip = skip or set()
        async with self._lock:
            now = time.monotonic()
            for slot in self._slots:
                if slot.name in skip:
                    continue
                if slot.has_capacity(now):
                    slot.take(now)
                    return slot.name
        return None

    async def penalise(self, name: str, *, per_day: bool, retry_after: float) -> None:
        async with self._lock:
            now = time.monotonic()
            for slot in self._slots:
                if slot.name == name:
                    slot.penalise(per_day=per_day, retry_after=retry_after, now=now)
                    return

    async def status(self) -> dict[str, float]:
        """Per model, seconds until it is usable again. 0 means available now.

        For the health endpoint and for diagnosing "why did that answer come from the local
        model", which is otherwise invisible.
        """
        async with self._lock:
            now = time.monotonic()
            return {s.name: s.seconds_until_free(now) for s in self._slots}


class GemmaProvider:
    """Local Gemma 4 E2B through Ollama's OpenAI-compatible endpoint."""

    name = "gemma"

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._s = settings
        self._c = client
        self.model = settings.gemma_model

    async def available(self) -> bool:
        try:
            r = await self._c.get(f"{self._s.ollama_base_url}/api/tags", timeout=3.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def _payload(self, req: LLMRequest, *, stream: bool) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": self.model,
            "messages": req.messages,
            "stream": stream,
            "options": {
                "temperature": req.temperature,
                "num_predict": req.max_tokens,
                # Pinned per task kind rather than left to the server default.
                # See TaskKind.num_ctx for why this is not optional.
                "num_ctx": req.kind.num_ctx,
            },
            "keep_alive": self._s.ollama_keep_alive,
        }
        if req.tools:
            body["tools"] = req.tools
        if req.json_schema:
            body["format"] = req.json_schema
        # Thinking is a per-call decision. Off for classification and retrieval
        # answering where it only adds latency; on where reasoning quality pays.
        body["think"] = bool(req.thinking)
        return body

    async def complete(self, req: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        r = await self._c.post(
            f"{self._s.ollama_base_url}/api/chat",
            json=self._payload(req, stream=False),
            timeout=180.0,
        )
        r.raise_for_status()
        data = r.json()
        msg = data.get("message", {}) or {}
        return LLMResponse(
            text=msg.get("content", "") or "",
            provider=self.name,
            model=self.model,
            tool_calls=msg.get("tool_calls", []) or [],
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        async with self._c.stream(
            "POST",
            f"{self._s.ollama_base_url}/api/chat",
            json=self._payload(req, stream=True),
            timeout=180.0,
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line.strip():
                    continue
                import json as _json

                try:
                    chunk = _json.loads(line)
                except ValueError:
                    continue
                piece = (chunk.get("message") or {}).get("content")
                if piece:
                    yield piece
                if chunk.get("done"):
                    break


# Extra output budget requested from the remote provider, on top of what the caller asked
# for, to pay for thinking tokens.
#
# Gemini 3.x counts thinking against `maxOutputTokens`, and thinking cannot be switched off
# on this model family: `thinkingLevel: "off"` is rejected as an invalid enum value and
# `thinkingBudget: 0` returns 400. Every local task uses `max_tokens` to mean "at most this
# much visible text", so passing it through unchanged is a silent failure rather than a
# small one. Measured: a TRANSLITERATE call with `max_tokens=80` spent 72 tokens on thoughts
# and returned `finishReason: MAX_TOKENS` with the fragment "Transliterate/" where the
# Bangla should have been.
#
# Sized from measurement against gemini-3.6-flash at `thinkingLevel: "low"`: 0 thought
# tokens when a response schema is set, 215 to 290 for a one-line free-text prompt. This is
# roughly triple the worst case seen, and an unused reserve costs nothing because generation
# stops at the stop token.
_THINKING_RESERVE = 1024


def _rate_limited(model: str, r: httpx.Response) -> _RateLimited:
    """Classify a 429 or 503 into "wait a minute" or "wait until tomorrow".

    The distinction decides how long the model sits out, and getting it wrong is expensive in
    both directions: treating a daily exhaustion as a minute means retrying a model that
    cannot answer until tomorrow on every request, and treating a per-minute limit as daily
    throws away a model for a day over a one-second burst.

    Google signals which one in the quota violation's id and metric, so those are read first.
    `Retry-After` is honoured when present because it is the server's own answer.
    """
    body = ""
    try:
        body = r.text[:2000]
    except Exception:  # noqa: BLE001 - a body we cannot read must not mask the 429 itself
        pass

    lowered = body.lower()
    per_day = "perday" in lowered.replace("_", "") or "per day" in lowered

    retry_after = 0.0
    header = r.headers.get("retry-after", "")
    if header.strip().isdigit():
        retry_after = float(header.strip())

    return _RateLimited(
        f"{model} returned {r.status_code}", per_day=per_day, retry_after=retry_after
    )


class GeminiProvider:
    """Remote provider used for non-authoritative, latency-sensitive turns."""

    name = "gemini"

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._s = settings
        self._c = client
        self.model = settings.fallback_model
        self._pool = _ModelPool(settings.fallback_model_chain)
        self._base = "https://generativelanguage.googleapis.com/v1beta"

    async def available(self) -> bool:
        return bool(self._s.gemini_api_key) and self._s.fallback_enabled

    async def status(self) -> dict[str, float]:
        """Per model in the chain, seconds until it can serve again."""
        return await self._pool.status()

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Walk the chain until one model answers.

        A rate-limited model is set aside and the next one is tried, because the models have
        separate quotas: four at 20 requests a day is 80, where a single model would have
        stopped at 20 and sent everything to the local model for the rest of the day.

        Only a refusal that another model could survive advances the chain. A 400 means the
        request itself is wrong, so retrying it three more times would spend three more
        models' quota to collect the same error.
        """
        if req.contains_user_documents:
            raise DocumentContentLeak(
                "refusing to send vault-derived content to a remote provider"
            )

        tried: set[str] = set()
        last: Exception | None = None
        while (model := await self._pool.pick(skip=tried)) is not None:
            tried.add(model)
            try:
                return await self._generate(model, req)
            except _RateLimited as exc:
                await self._pool.penalise(
                    model, per_day=exc.per_day, retry_after=exc.retry_after
                )
                log.warning(
                    "remote model %s rate limited (per_day=%s); trying next in chain",
                    model,
                    exc.per_day,
                )
                last = exc

        raise RemoteExhausted(
            f"no remote model has capacity (chain: {', '.join(self._pool.names)})"
        ) from last

    async def _generate(self, model: str, req: LLMRequest) -> LLMResponse:
        started = time.monotonic()
        contents, system = [], None
        for m in req.messages:
            role = m.get("role")
            if role == "system":
                system = m.get("content")
                continue
            contents.append(
                {
                    "role": "user" if role == "user" else "model",
                    "parts": [{"text": m.get("content", "")}],
                }
            )

        body: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": req.temperature,
                "maxOutputTokens": req.max_tokens + _THINKING_RESERVE,
                # "low" is the floor this model accepts; see _THINKING_RESERVE.
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if req.json_schema:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = req.json_schema

        r = await self._c.post(
            f"{self._base}/models/{model}:generateContent",
            params={"key": self._s.gemini_api_key},
            json=body,
            timeout=60.0,
        )
        # 429 is quota. 503 is the model being temporarily overloaded, which is somebody
        # else's saturation rather than ours: both are answerable by a different model, and
        # neither says the request was wrong.
        if r.status_code in (429, 503):
            raise _rate_limited(model, r)
        r.raise_for_status()
        data = r.json()
        candidates = data.get("candidates") or []
        text = ""
        for cand in candidates:
            for part in (cand.get("content") or {}).get("parts", []):
                text += part.get("text", "")

        if not text.strip():
            # A blank or truncated remote reply is worse than no remote reply. The fast
            # tasks feed this straight into a retrieval query, a conversation title or a
            # transliteration, so a fragment is not visibly an error: it is a wrong value
            # that the rest of the request treats as correct. Raising hands the request
            # back to the caller's fallback, which is the local model.
            finish = candidates[0].get("finishReason") if candidates else None
            raise RuntimeError(f"remote provider returned no text (finishReason={finish})")

        usage = data.get("usageMetadata", {}) or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            # The model that actually served it, not the head of the chain. An event log
            # saying every remote answer came from gemini-3.6-flash would be wrong from the
            # twenty-first call of the day onwards.
            model=model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )


class ModelRouter:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._s = settings or get_settings()
        # A caller that already owns an httpx client should pass it: the router
        # is constructed once per process, and the remote-provider budget below
        # only means anything while the instance lives. Building a router (and
        # therefore a fresh budget) per request would reset the daily ceiling on
        # every call.
        self._client = client or httpx.AsyncClient()
        self._owns_client = client is None
        self.gemma = GemmaProvider(self._s, self._client)
        self.gemini = GeminiProvider(self._s, self._client)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _preferred(self, req: LLMRequest) -> str:
        # Anything touching documents is local, unconditionally.
        if req.contains_user_documents or req.images:
            return "gemma"
        # Tool calling and structured grounding stay on the model the agents
        # were designed and evaluated against.
        if req.tools:
            return "gemma"
        configured = (
            self._s.core_path_provider if req.kind.is_core else self._s.fast_path_provider
        )
        return configured

    async def complete(self, req: LLMRequest) -> LLMResponse:
        preferred = self._preferred(req)

        if preferred == "gemini" and await self.gemini.available():
            try:
                return await self.gemini.complete(req)
            except DocumentContentLeak:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("remote provider failed kind=%s err=%s", req.kind, exc)

        try:
            return await self.gemma.complete(req)
        except Exception as exc:  # noqa: BLE001
            log.error("local model failed kind=%s err=%s", req.kind, exc)
            # Last resort only, and never for document work.
            if (
                self._s.fallback_enabled
                and not req.contains_user_documents
                and not req.images
                and await self.gemini.available()
            ):
                try:
                    resp = await self.gemini.complete(req)
                except Exception:  # noqa: BLE001
                    # Both providers are unusable. Raise the local failure rather than the
                    # remote one: the local model is what this request was meant to run on,
                    # so its error is the one that explains the outage.
                    raise exc from None
                resp.degraded = True
                return resp
            raise

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        """Streaming is local-only.

        Every streamed surface in this product is a grounded answer, and grounded
        answers are core work. Keeping the stream on one provider also keeps
        citation markers consistent, which the client parses positionally.
        """
        async for piece in self.gemma.stream(req):
            yield piece
