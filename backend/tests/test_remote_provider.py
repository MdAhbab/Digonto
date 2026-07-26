"""What the router sends to the remote provider, and what it does with a useless reply.

Written after a live failure that no existing test could have caught. The fast tasks were
routed to gemini-3.6-flash, which thinks by default and charges thinking tokens against
`maxOutputTokens`. A TRANSLITERATE call asking for 80 tokens spent 72 of them on thoughts
and returned `finishReason: MAX_TOKENS` carrying the string "Transliterate/". Nothing
raised. The Banglish transliteration of a student's question was replaced by a fragment of
the word "transliterate", and the request carried on as though that were the answer.

Two properties follow, and both are tested against a mocked transport so the suite stays
offline: the reserve has to be added to the caller's budget, and a reply with no usable text
has to raise rather than be returned.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.config import Settings
from app.llm.router import (
    _THINKING_RESERVE,
    DocumentContentLeak,
    LLMRequest,
    ModelRouter,
    TaskKind,
)

KEY = "test-key-not-a-real-one"


def _settings(**over) -> Settings:
    over.setdefault("fallback_models", "m-primary:5:20")
    return Settings(gemini_api_key=KEY, fallback_enabled=True, **over)


def _gemini_reply(text: str, finish: str = "STOP") -> dict:
    parts = [{"text": text}] if text else []
    return {
        "candidates": [{"content": {"parts": parts, "role": "model"}, "finishReason": finish}],
        "usageMetadata": {"promptTokenCount": 22, "candidatesTokenCount": 4, "thoughtsTokenCount": 72},
    }


def _ollama_reply(text: str) -> dict:
    return {"message": {"content": text}, "prompt_eval_count": 10, "eval_count": 5}


def _quota_error(per_day: bool) -> dict:
    """Shaped like a real Google quota rejection, including the field the classifier reads."""
    metric = (
        "generativelanguage.googleapis.com/generate_content_free_tier_requests"
        if per_day
        else "generativelanguage.googleapis.com/generate_requests_per_model_per_minute"
    )
    return {
        "error": {
            "code": 429,
            "status": "RESOURCE_EXHAUSTED",
            "message": "You exceeded your current quota.",
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {
                            "quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
                            if per_day
                            else "GenerateRequestsPerMinutePerProjectPerModel-FreeTier",
                            "quotaMetric": metric,
                        }
                    ],
                }
            ],
        }
    }


class _Recorder:
    """Captures request bodies and serves canned replies, keyed by host.

    `per_model` overrides the reply for one model name, which is how the chain tests make an
    early model fail and a later one succeed.
    """

    def __init__(
        self,
        *,
        gemini: dict,
        ollama: dict | None = None,
        gemini_status: int = 200,
        per_model: dict[str, tuple[int, dict]] | None = None,
    ) -> None:
        self.sent: list[dict] = []
        self.models: list[str] = []
        self._gemini = gemini
        self._ollama = ollama or _ollama_reply("local answer")
        self._gemini_status = gemini_status
        self._per_model = per_model or {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.sent.append({"host": request.url.host, "body": body})
        if "generativelanguage" in request.url.host:
            # ".../v1beta/models/<name>:generateContent"
            model = request.url.path.rsplit("/", 1)[-1].split(":")[0]
            self.models.append(model)
            if model in self._per_model:
                status, payload = self._per_model[model]
                return httpx.Response(status, json=payload)
            return httpx.Response(self._gemini_status, json=self._gemini)
        return httpx.Response(200, json=self._ollama)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))

    def to(self, host_fragment: str) -> list[dict]:
        return [s["body"] for s in self.sent if host_fragment in s["host"]]


FAST = LLMRequest(
    kind=TaskKind.TRANSLITERATE,
    messages=[{"role": "user", "content": "ami bidesh e porte jete chai"}],
    max_tokens=80,
)


# --- the output budget --------------------------------------------------------


@pytest.mark.asyncio
async def test_the_thinking_reserve_is_added_to_the_callers_budget():
    """`max_tokens` means "visible text" to every local caller. On this model it is a
    combined budget for thoughts plus text, so passing it through truncates the answer."""
    rec = _Recorder(gemini=_gemini_reply("আমি বিদেশে পড়তে যেতে চাই"))
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        await router.complete(FAST)

    cfg = rec.to("generativelanguage")[0]["generationConfig"]
    assert cfg["maxOutputTokens"] == 80 + _THINKING_RESERVE
    assert _THINKING_RESERVE >= 512, "measured thought counts reached 290 for a one-line prompt"


@pytest.mark.asyncio
async def test_thinking_is_pinned_to_the_lowest_level_the_model_accepts():
    """Not "off": the API rejects that value for this model family, and `thinkingBudget: 0`
    returns 400. `low` is the floor, so it has to be requested explicitly rather than left
    to whatever the service defaults to."""
    rec = _Recorder(gemini=_gemini_reply("ok"))
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        await router.complete(FAST)

    assert rec.to("generativelanguage")[0]["generationConfig"]["thinkingConfig"] == {
        "thinkingLevel": "low"
    }


@pytest.mark.asyncio
async def test_the_local_model_is_not_given_the_reserve():
    """Ollama's `num_predict` counts visible tokens only, so the reserve would just raise
    the ceiling on how long a local reply may run."""
    rec = _Recorder(gemini=_gemini_reply("x"), ollama=_ollama_reply("local"))
    async with rec.client() as c:
        router = ModelRouter(_settings(fast_path_provider="gemma"), client=c)
        await router.complete(FAST)

    assert rec.to("localhost")[0]["options"]["num_predict"] == 80


# --- a reply that cannot be used ---------------------------------------------


@pytest.mark.asyncio
async def test_a_truncated_reply_falls_back_to_the_local_model():
    """The regression guard for the live failure.

    The caller cannot tell "Transliterate/" from a transliteration, so returning it is
    worse than failing. The router already retries locally on an exception, which is the
    behaviour this makes reachable.
    """
    rec = _Recorder(
        gemini=_gemini_reply("", finish="MAX_TOKENS"),
        ollama=_ollama_reply("আমি বিদেশে পড়তে যেতে চাই"),
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        resp = await router.complete(FAST)

    assert resp.provider == "gemma"
    assert resp.text == "আমি বিদেশে পড়তে যেতে চাই"
    assert rec.to("generativelanguage"), "the remote provider should have been tried first"


@pytest.mark.asyncio
async def test_whitespace_only_counts_as_no_reply():
    """`finishReason: STOP` with a blank body is the same problem wearing a success code."""
    rec = _Recorder(gemini=_gemini_reply("   \n  "), ollama=_ollama_reply("local answer"))
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        resp = await router.complete(FAST)

    assert resp.provider == "gemma"


@pytest.mark.asyncio
async def test_an_http_failure_also_falls_back():
    rec = _Recorder(gemini={"error": {"message": "quota"}}, gemini_status=429)
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        resp = await router.complete(FAST)

    assert resp.provider == "gemma"


# --- what may never be routed out --------------------------------------------


@pytest.mark.asyncio
async def test_document_content_never_reaches_the_remote_provider_even_on_the_fast_path():
    """The fast path is configured to a remote provider, so this is the guard that keeps a
    passport scan local. Two mechanisms: routing prefers the local model for these
    requests, and the provider itself refuses one if it is ever called directly."""
    rec = _Recorder(gemini=_gemini_reply("should never be reached"))
    doc = LLMRequest(
        kind=TaskKind.SUMMARISE_SHORT,
        messages=[{"role": "user", "content": "passport number AB123456"}],
        contains_user_documents=True,
        max_tokens=80,
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        assert router._preferred(doc) == "gemma"
        await router.complete(doc)
        assert not rec.to("generativelanguage"), "document content was sent off the machine"

        with pytest.raises(DocumentContentLeak):
            await router.gemini.complete(doc)


@pytest.mark.asyncio
async def test_an_image_bearing_request_stays_local():
    rec = _Recorder(gemini=_gemini_reply("should never be reached"))
    vision = LLMRequest(
        kind=TaskKind.SUMMARISE_SHORT,
        messages=[{"role": "user", "content": "what does this say"}],
        images=[b"\x89PNG\r\n"],
        max_tokens=80,
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        assert router._preferred(vision) == "gemma"
        await router.complete(vision)
        assert not rec.to("generativelanguage")


@pytest.mark.asyncio
async def test_a_tool_calling_request_stays_local():
    """The agents were designed and evaluated against the local model's tool-call format."""
    rec = _Recorder(gemini=_gemini_reply("should never be reached"))
    tooled = LLMRequest(
        kind=TaskKind.SUMMARISE_SHORT,
        messages=[{"role": "user", "content": "find a scholarship"}],
        tools=[{"type": "function", "function": {"name": "search", "parameters": {}}}],
        max_tokens=80,
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(), client=c)
        assert router._preferred(tooled) == "gemma"
        await router.complete(tooled)
        assert not rec.to("generativelanguage")


# --- the model chain ---------------------------------------------------------

CHAIN = "m-a:5:20,m-b:5:20,m-c:15:500"


@pytest.mark.asyncio
async def test_a_rate_limited_model_hands_over_to_the_next_in_the_chain():
    """The reason the chain exists. The strongest models allow 20 requests a day, so a single
    model would send everything local from the twenty-first question onwards."""
    rec = _Recorder(
        gemini=_gemini_reply("served"),
        per_model={"m-a": (429, _quota_error(per_day=True))},
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        resp = await router.complete(FAST)

    assert rec.models == ["m-a", "m-b"], "should have tried the head first, then moved on"
    assert resp.provider == "gemini"
    assert resp.model == "m-b", "the response must name the model that served it"


@pytest.mark.asyncio
async def test_a_model_exhausted_for_the_day_is_not_tried_again():
    """A per-day rejection means every later request would also fail, so retrying it costs a
    round trip per question for the rest of the day."""
    rec = _Recorder(
        gemini=_gemini_reply("served"),
        per_model={"m-a": (429, _quota_error(per_day=True))},
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        await router.complete(FAST)
        rec.models.clear()
        await router.complete(FAST)

    assert "m-a" not in rec.models
    assert rec.models == ["m-b"]


@pytest.mark.asyncio
async def test_the_whole_chain_being_spent_falls_back_to_the_local_model():
    """Which is the point of it being a fallback chain and not a dependency."""
    rec = _Recorder(
        gemini=_quota_error(per_day=True),
        gemini_status=429,
        ollama=_ollama_reply("local answer"),
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        resp = await router.complete(FAST)

    assert rec.models == ["m-a", "m-b", "m-c"], "every model should have been offered the work"
    assert resp.provider == "gemma"
    assert resp.text == "local answer"


@pytest.mark.asyncio
async def test_the_daily_ceiling_is_enforced_locally_before_a_request_is_spent():
    """Without this the first sign of exhaustion is a 429, which costs a round trip to learn
    something the process already knew."""
    rec = _Recorder(gemini=_gemini_reply("served"))
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models="m-a:100:3,m-b:100:100"), client=c)
        for _ in range(4):
            await router.complete(FAST)

    assert rec.models == ["m-a", "m-a", "m-a", "m-b"], "the fourth call exceeds m-a's daily 3"


@pytest.mark.asyncio
async def test_the_per_minute_ceiling_moves_traffic_on_without_waiting():
    """The old implementation slept until the interval elapsed. At 5 requests a minute that
    is a twelve second pause on a path whose whole purpose is to be fast, when another model
    was free the entire time."""
    rec = _Recorder(gemini=_gemini_reply("served"))
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models="m-a:2:100,m-b:2:100"), client=c)
        for _ in range(3):
            await router.complete(FAST)

    assert rec.models == ["m-a", "m-a", "m-b"]


@pytest.mark.asyncio
async def test_a_bad_request_does_not_burn_the_rest_of_the_chain():
    """A 400 is the request being wrong. Retrying it on three more models spends three more
    models' quota to collect the same error."""
    rec = _Recorder(
        gemini={"error": {"code": 400, "message": "Invalid value"}},
        gemini_status=400,
        ollama=_ollama_reply("local answer"),
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        resp = await router.complete(FAST)

    assert rec.models == ["m-a"], "only the first model should have been charged"
    assert resp.provider == "gemma"


@pytest.mark.asyncio
async def test_an_overloaded_model_advances_the_chain_too():
    """503 is somebody else's saturation, not ours, and another model can answer."""
    rec = _Recorder(
        gemini=_gemini_reply("served"),
        per_model={"m-a": (503, {"error": {"code": 503, "message": "overloaded"}})},
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        resp = await router.complete(FAST)

    assert rec.models == ["m-a", "m-b"]
    assert resp.model == "m-b"


@pytest.mark.asyncio
async def test_status_reports_which_models_are_available():
    """So that "why did this answer come from the local model" is answerable."""
    rec = _Recorder(
        gemini=_gemini_reply("served"),
        per_model={"m-a": (429, _quota_error(per_day=True))},
    )
    async with rec.client() as c:
        router = ModelRouter(_settings(fallback_models=CHAIN), client=c)
        await router.complete(FAST)
        status = await router.gemini.status()

    assert status["m-a"] > 0, "the exhausted model must report as unavailable"
    assert status["m-c"] == 0.0


# --- configuration -----------------------------------------------------------


def test_the_chain_parses_per_model_limits():
    """The limits differ by a factor of twenty five across the chain, so one shared number
    would either overrun the small quotas or waste the large ones.

    The defaults are passed explicitly because this repository has a real `.env` that
    pydantic-settings reads, so relying on them would test the environment rather than the
    parser.
    """
    s = Settings(fallback_models="a:5:20, b:15:500 ,c", fallback_max_rpm=5, fallback_daily_budget=20)
    assert s.fallback_model_chain == [("a", 5, 20), ("b", 15, 500), ("c", 5, 20)]
    assert s.fallback_model == "a", "the head of the chain is the preferred model"


def test_a_malformed_limit_falls_back_to_the_default_rather_than_failing_startup():
    """A typo in one entry of an environment variable should cost that entry its tuning, not
    stop the process from booting."""
    s = Settings(fallback_models="a:notanumber:20,b:5:alsonot", fallback_max_rpm=5, fallback_daily_budget=20)
    assert s.fallback_model_chain == [("a", 5, 20), ("b", 5, 20)]


def test_no_model_in_the_chain_has_a_wildly_wrong_ceiling():
    """Guards the bug this replaced: the shipped default was 2 requests a second, which is
    120 a minute against a real limit of 5, so the local ceiling could never trip first."""
    for name, rpm, rpd in Settings().fallback_model_chain:
        assert 0 < rpm <= 15, name
        assert 0 < rpd <= 500, name


# --- provider configuration --------------------------------------------------


def test_a_deployment_without_a_key_routes_everything_locally():
    """The remote provider is an optimisation, not a dependency: with no key the whole
    product still runs, rather than the fast path failing on every call."""
    s = Settings(gemini_api_key="", fallback_enabled=True, fast_path_provider="gemini")
    assert s.fast_path_provider == "gemma"
    assert s.core_path_provider == "gemma"
    assert s.fallback_enabled is False


def test_core_tasks_are_local_in_the_shipped_configuration():
    """Grounded answering, vision extraction and scoring are the product. If a default ever
    moves them off the machine, the claim in docs/privacy.md stops being true."""
    assert Settings().core_path_provider == "gemma"
