"""Shared runtime for the seven agents.

Every agent is the same shape: build a prompt, ask the model for output that
matches a schema, validate it, and use it. Two things are centralised here
because getting them wrong in seven places would be seven separate defects.

**Structured output with one repair attempt.** A small model occasionally emits
JSON that parses but violates the schema, usually by omitting an optional-looking
field. Rather than failing the user, the schema error is fed back once. If the
second attempt also fails, the caller gets an exception and the agent run is
recorded as failed. It never guesses on the caller's behalf.

**Bilingual output is required, not requested.** Every user-facing string an
agent produces carries an English and a Bangla variant. The schema requires both,
so a missing translation is a validation failure rather than an empty panel in
the interface.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from app.llm.router import LLMRequest, ModelRouter, TaskKind

log = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 1


class AgentOutputError(RuntimeError):
    """The model could not produce output matching the schema."""


@dataclass(slots=True)
class AgentCall:
    """One structured request to the model."""

    kind: TaskKind
    system: str
    user: str
    schema: dict[str, Any]
    images: list[bytes] | None = None
    thinking: bool = False
    temperature: float = 0.1
    max_tokens: int = 2048
    # Set by any agent whose prompt contains vault-derived text or images. The
    # model router refuses to send these to a remote provider.
    contains_user_documents: bool = False


async def structured(router: ModelRouter, call: AgentCall) -> dict[str, Any]:
    """Run one schema-constrained call, repairing once on validation failure."""
    messages = [
        {"role": "system", "content": call.system},
        {"role": "user", "content": call.user},
    ]
    if call.images:
        messages[-1]["images"] = call.images  # Ollama takes images on the message

    last_error: str | None = None
    for attempt in range(MAX_REPAIR_ATTEMPTS + 1):
        if last_error:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Your previous reply was not valid for the schema: {last_error}. "
                        "Reply again with valid JSON only. Do not explain."
                    ),
                }
            )

        response = await router.complete(
            LLMRequest(
                kind=call.kind,
                messages=messages,
                json_schema=call.schema,
                images=call.images or [],
                thinking=call.thinking,
                temperature=call.temperature,
                max_tokens=call.max_tokens,
                contains_user_documents=call.contains_user_documents,
            )
        )

        try:
            data = json.loads(response.text)
        except ValueError as exc:
            last_error = f"not parseable as JSON ({exc})"
            log.warning("agent output unparseable attempt=%d kind=%s", attempt, call.kind)
            continue

        missing = [k for k in call.schema.get("required", []) if k not in data]
        if missing:
            last_error = f"missing required fields {missing}"
            log.warning("agent output missing fields=%s kind=%s", missing, call.kind)
            continue

        return data

    raise AgentOutputError(f"{call.kind.value}: {last_error}")


def bilingual(description: str) -> dict[str, Any]:
    """Schema fragment for a required English and Bangla pair."""
    return {
        "type": "object",
        "properties": {
            "en": {"type": "string", "description": description},
            "bn": {"type": "string", "description": f"{description}, in natural Bangla"},
        },
        "required": ["en", "bn"],
    }


def enum_field(values: list[str], description: str = "") -> dict[str, Any]:
    return {"type": "string", "enum": values, "description": description}


def clamp01(value: Any, default: float = 0.0) -> float:
    """Models occasionally return a percentage where a fraction was asked for."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v > 1.0:
        v = v / 100.0 if v <= 100.0 else 1.0
    return max(0.0, min(1.0, v))


REFUSAL_NOTE = (
    "You never help a student misrepresent, conceal, or fabricate anything. "
    "If asked to do so, refuse and explain the legal consequences plainly. "
    "You report what documents and official sources say. You do not give legal advice."
)
