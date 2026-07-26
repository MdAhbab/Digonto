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


class _Budget:
    """Rate and daily-count ceiling for the remote provider."""

    def __init__(self, max_qps: float, daily_budget: int) -> None:
        self._min_interval = 1.0 / max_qps if max_qps > 0 else 0.0
        self._daily_budget = daily_budget
        self._last_call = 0.0
        self._day = time.gmtime().tm_yday
        self._count = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            today = time.gmtime().tm_yday
            if today != self._day:
                self._day, self._count = today, 0
            if self._count >= self._daily_budget:
                return False
            wait = self._min_interval - (time.monotonic() - self._last_call)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_call = time.monotonic()
            self._count += 1
            return True


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


class GeminiProvider:
    """Remote provider used for non-authoritative, latency-sensitive turns."""

    name = "gemini"

    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._s = settings
        self._c = client
        self.model = settings.fallback_model
        self._budget = _Budget(settings.fallback_max_qps, settings.fallback_daily_budget)
        self._base = "https://generativelanguage.googleapis.com/v1beta"

    async def available(self) -> bool:
        return bool(self._s.gemini_api_key) and self._s.fallback_enabled

    async def complete(self, req: LLMRequest) -> LLMResponse:
        if req.contains_user_documents:
            raise DocumentContentLeak(
                "refusing to send vault-derived content to a remote provider"
            )
        if not await self._budget.acquire():
            raise RuntimeError("remote provider daily budget exhausted")

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
                "maxOutputTokens": req.max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if req.json_schema:
            body["generationConfig"]["responseMimeType"] = "application/json"
            body["generationConfig"]["responseSchema"] = req.json_schema

        r = await self._c.post(
            f"{self._base}/models/{self.model}:generateContent",
            params={"key": self._s.gemini_api_key},
            json=body,
            timeout=60.0,
        )
        r.raise_for_status()
        data = r.json()
        text = ""
        for cand in data.get("candidates", []):
            for part in (cand.get("content") or {}).get("parts", []):
                text += part.get("text", "")
        usage = data.get("usageMetadata", {}) or {}
        return LLMResponse(
            text=text,
            provider=self.name,
            model=self.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
        )


class ModelRouter:
    def __init__(self, settings: Settings | None = None) -> None:
        self._s = settings or get_settings()
        self._client = httpx.AsyncClient()
        self.gemma = GemmaProvider(self._s, self._client)
        self.gemini = GeminiProvider(self._s, self._client)

    async def aclose(self) -> None:
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
                resp = await self.gemini.complete(req)
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
