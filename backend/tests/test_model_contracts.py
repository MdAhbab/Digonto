"""Contract tests against the live model.

These are not unit tests. They check the four assumptions the whole architecture
rests on, against a real Ollama serving gemma4:e2b. If any of them fails, the
design does not work and no amount of application code will save it:

  1. The model emits native tool calls with a valid enum argument.
  2. Schema-constrained output produces parseable JSON every time.
  3. Given no supporting passage, the model refuses instead of inventing a
     figure. This is the single most important behaviour in the product.
  4. Given a passage, it answers in natural Bangla and cites the exact snapshot.

Run:  pytest backend/tests/test_model_contracts.py -v -s
Skips automatically when Ollama is not reachable, so CI without a model does not
report false failures.

Measured on an Apple Silicon development machine, 26 July 2026:
  cold load        24.3 s   (first call after the model is evicted)
  warm tool call    1.16 s  total, 46 tokens per second
  warm refusal      1.91 s
  warm grounded     5.13 s  (longer answer plus a citation object)

The cold number is why keep_alive is pinned. It is the difference between an
unusable product and a fast one, and it costs nothing but memory.

These figures are from a development machine, not the production virtual
machine. They are not the numbers the paper reports as production latency.
"""

from __future__ import annotations

import json
import os
import time

import httpx
import pytest

OLLAMA = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.environ.get("GEMMA_MODEL", "gemma4:e2b")
TIMEOUT = 180.0


def _up() -> bool:
    try:
        return httpx.get(f"{OLLAMA}/api/tags", timeout=3.0).status_code == 200
    except httpx.HTTPError:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="Ollama is not running")


def _chat(payload: dict) -> dict:
    payload.setdefault("model", MODEL)
    payload.setdefault("stream", False)
    payload.setdefault("think", False)
    payload.setdefault("keep_alive", "30m")
    started = time.monotonic()
    r = httpx.post(f"{OLLAMA}/api/chat", json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    data = r.json()
    data["_wall_ms"] = int((time.monotonic() - started) * 1000)
    return data


GROUNDED_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_bn": {"type": "string"},
        "answer_en": {"type": "string"},
        "is_refusal": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordinal": {"type": "integer"},
                    "snapshot_id": {"type": "string"},
                    "quoted_span": {"type": "string"},
                },
                "required": ["ordinal", "snapshot_id", "quoted_span"],
            },
        },
        "confidence": {"type": "number"},
    },
    # refusal_reason is required even on the success path. The model returned an
    # empty string for it when it was optional, which would violate the CHECK
    # constraint on the answers table. Requiring it and telling the model to
    # write "not applicable" when answering is what fixed it.
    "required": [
        "answer_bn", "answer_en", "is_refusal",
        "refusal_reason", "citations", "confidence",
    ],
}

GROUNDED_SYSTEM = (
    "Answer ONLY from the SOURCE passages. Cite each factual claim with its "
    "snapshot_id and the exact quoted span. If no passage supports an answer, "
    "set is_refusal true. refusal_reason must ALWAYS be a non-empty string: "
    "give the reason when refusing, or 'not applicable' when answering. "
    "answer_bn must be natural, plain Bangla that a first-time applicant "
    "understands."
)


def test_model_reports_required_capabilities() -> None:
    """Tool support is what makes the agents real rather than a regex parser.

    The published model library page has listed this incorrectly for the E
    variants, so this is checked against the local manifest rather than trusted.
    """
    r = httpx.post(f"{OLLAMA}/api/show", json={"model": MODEL}, timeout=30.0)
    r.raise_for_status()
    caps = r.json().get("capabilities", [])
    print(f"\ncapabilities: {caps}")
    for required in ("completion", "tools", "vision"):
        assert required in caps, f"{MODEL} does not report {required}"


def test_native_tool_calling_with_enum() -> None:
    """Porter's change triage depends on this exact shape."""
    out = _chat(
        {
            "messages": [
                {
                    "role": "system",
                    "content": "You classify changes to official visa portal "
                               "pages. Use the classify_change tool exactly once.",
                },
                {
                    "role": "user",
                    "content": "A UK embassy page changed. Old: 'Applications "
                               "must be submitted by 15 November 2026.' New: "
                               "'Applications must be submitted by 1 November 2026.'",
                },
            ],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "classify_change",
                        "description": "Classify a portal change and state confidence.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string",
                                    "enum": [
                                        "deadline", "fee", "document_requirement",
                                        "policy", "cosmetic",
                                    ],
                                },
                                "confidence": {"type": "number"},
                                "reason": {"type": "string"},
                            },
                            "required": ["category", "confidence", "reason"],
                        },
                    },
                }
            ],
        }
    )
    calls = out["message"].get("tool_calls")
    assert calls, f"no tool call emitted; content was {out['message'].get('content')!r}"

    args = calls[0]["function"]["arguments"]
    if isinstance(args, str):
        args = json.loads(args)
    print(f"\ntool call: {args}  ({out['_wall_ms']} ms)")

    assert args["category"] == "deadline", f"misclassified as {args['category']}"
    assert 0.0 <= float(args["confidence"]) <= 1.0


def test_refuses_when_no_passage_supports_the_answer() -> None:
    """The most important behaviour in the product.

    A confident wrong number here costs a family a visa fee and a year.
    """
    out = _chat(
        {
            "options": {"temperature": 0.1},
            "format": GROUNDED_SCHEMA,
            "messages": [
                {"role": "system", "content": GROUNDED_SYSTEM},
                {
                    "role": "user",
                    "content": "SOURCE PASSAGES:\n[none provided]\n\n"
                               "QUESTION: How much money must I show in my bank "
                               "account for a UK student visa?",
                },
            ],
        }
    )
    obj = json.loads(out["message"]["content"])
    print(f"\nrefusal: {obj.get('answer_bn')!r} ({out['_wall_ms']} ms)")

    assert obj["is_refusal"] is True, "model invented an answer with no sources"
    assert obj["refusal_reason"].strip(), "refusal_reason empty; violates the answers CHECK"
    # It must not state a figure it cannot support.
    assert "1483" not in obj["answer_bn"].replace(",", "")


def test_grounded_answer_cites_the_exact_snapshot() -> None:
    out = _chat(
        {
            "options": {"temperature": 0.1},
            "format": GROUNDED_SCHEMA,
            "messages": [
                {"role": "system", "content": GROUNDED_SYSTEM},
                {
                    "role": "user",
                    "content": 'SOURCE PASSAGES:\n[SNAP-01J8X: "You must have '
                               "enough money to cover course fees and GBP 1,483 "
                               "per month for living costs in London, for up to "
                               '9 months."]\n\n'
                               "QUESTION: লন্ডনে পড়তে গেলে ব্যাংকে কত টাকা দেখাতে হবে?",
                },
            ],
        }
    )
    obj = json.loads(out["message"]["content"])
    print(f"\nbn: {obj['answer_bn']}\n({out['_wall_ms']} ms)")

    assert obj["is_refusal"] is False
    assert obj["refusal_reason"].strip(), "refusal_reason must be non-empty even when answering"
    assert obj["citations"], "answered without citing anything"
    assert obj["citations"][0]["snapshot_id"] == "SNAP-01J8X"

    # The answer must actually be Bangla, not English in a Bangla-named field.
    bengali = sum(1 for ch in obj["answer_bn"] if "ঀ" <= ch <= "৿")
    assert bengali > 20, f"answer_bn does not look like Bangla: {obj['answer_bn']!r}"


def test_keep_alive_makes_the_second_call_fast() -> None:
    """Documents the cold-load penalty that pinning the model avoids."""
    payload = {
        "messages": [{"role": "user", "content": "Reply with the single word: ok"}],
        "options": {"num_predict": 5},
    }
    first = _chat(payload)
    second = _chat(payload)
    print(
        f"\nfirst {first['_wall_ms']} ms, second {second['_wall_ms']} ms, "
        f"load_duration {round(second.get('load_duration', 0) / 1e6)} ms"
    )
    # Warm calls should be well under a second for a five token reply.
    assert second["_wall_ms"] < 3000, "warm call is slow; is keep_alive being sent?"
