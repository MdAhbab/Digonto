"""Shared runtime for the seven agents.

Every agent is the same shape: build a prompt, ask the model for output that
matches a schema, validate it, and use it. Three things are centralised here
because getting them wrong in seven places would be seven separate defects.

**Structured output with one repair attempt.** A small model occasionally emits
JSON that parses but violates the schema, usually by omitting an optional-looking
field or returning a bare string where an object was asked for. Rather than
failing the user, the precise schema error is fed back once. If the second
attempt also fails, the caller gets an exception and the agent run is recorded as
failed. It never guesses on the caller's behalf.

**Validation means the whole schema, not the top-level keys.** An earlier version
of this module checked only that each name in `required` was present. That admits
`{"findings": "none"}` where a list of objects was specified, which then fails
somewhere far away in a repository or a template with a much less obvious error.
`validate_against_schema` walks the schema: types, nested `required`, `enum`
membership, array `items`, and numeric bounds. It is deliberately a small
recursive function rather than a `jsonschema` dependency, because the schemas in
this codebase use a narrow, known subset of JSON Schema and a new runtime
dependency on an 8 GB VM has to justify itself.

**The data-only rule travels with the data.** Any agent that frames untrusted
text (`app.security.framing`) needs the matching instruction in its system
prompt, or the fence is decoration. Rather than trusting seven prompts to
remember, `structured` detects a fence in the user content and appends the rule
itself. A frame can therefore never ship without its instruction.

**Bilingual output is required, not requested.** Every user-facing string an
agent produces carries an English and a Bangla variant. The schema requires both,
so a missing translation is a validation failure rather than an empty panel in
the interface.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.llm.router import LLMRequest, ModelRouter, TaskKind
from app.security.framing import DATA_ONLY_RULE

log = logging.getLogger(__name__)

MAX_REPAIR_ATTEMPTS = 1

# Matches the nonce fence app.security.framing.frame_untrusted emits.
_FENCE_PRESENT = re.compile(r"<<<[A-Z_]+#[0-9a-f]{12}")

# Reported errors are capped so a wholly wrong reply cannot produce a repair
# prompt longer than the original request.
_MAX_REPORTED_ERRORS = 6


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


# --- schema validation -------------------------------------------------------

_TYPE_CHECKS: dict[str, Any] = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    # bool is a subclass of int in Python; a boolean is not an acceptable number.
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def validate_against_schema(
    value: Any, schema: dict[str, Any], *, path: str = "$"
) -> list[str]:
    """Return a list of human-readable violations. Empty means valid.

    Supports the subset this codebase uses: `type`, `properties`, `required`,
    `items`, `enum`, `minimum`, `maximum`. Unknown keywords are ignored rather
    than treated as failures, so adding a `description` never breaks a call.
    """
    errors: list[str] = []

    expected = schema.get("type")
    if isinstance(expected, str):
        check = _TYPE_CHECKS.get(expected)
        if check is not None and not check(value):
            got = type(value).__name__
            return [f"{path}: expected {expected}, got {got}"]

    if (enum := schema.get("enum")) and value not in enum:
        errors.append(f"{path}: {value!r} is not one of {enum}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if (lo := schema.get("minimum")) is not None and value < lo:
            errors.append(f"{path}: {value} is below the minimum {lo}")
        if (hi := schema.get("maximum")) is not None and value > hi:
            errors.append(f"{path}: {value} is above the maximum {hi}")

    if isinstance(value, dict):
        for name in schema.get("required", []):
            if name not in value:
                errors.append(f"{path}: missing required field {name!r}")
        for name, subschema in (schema.get("properties") or {}).items():
            if name in value and isinstance(subschema, dict):
                errors.extend(
                    validate_against_schema(
                        value[name], subschema, path=f"{path}.{name}"
                    )
                )

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        for i, item in enumerate(value):
            errors.extend(
                validate_against_schema(item, schema["items"], path=f"{path}[{i}]")
            )

    return errors


# --- the one call every agent makes ------------------------------------------


def _system_prompt(call: AgentCall) -> str:
    """The agent's system prompt, plus the data-only rule when it frames data."""
    if _FENCE_PRESENT.search(call.user) and DATA_ONLY_RULE not in call.system:
        return f"{call.system}\n{DATA_ONLY_RULE}"
    return call.system


async def structured(router: ModelRouter, call: AgentCall) -> dict[str, Any]:
    """Run one schema-constrained call, repairing once on validation failure."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_prompt(call)},
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

        violations = validate_against_schema(data, call.schema)
        if violations:
            shown = violations[:_MAX_REPORTED_ERRORS]
            if len(violations) > _MAX_REPORTED_ERRORS:
                shown.append(f"and {len(violations) - _MAX_REPORTED_ERRORS} more")
            last_error = "; ".join(shown)
            log.warning(
                "agent output failed schema attempt=%d kind=%s violations=%d",
                attempt, call.kind, len(violations),
            )
            continue

        if not isinstance(data, dict):
            # Every agent schema in this codebase is an object at the root, and
            # callers index the result. A valid non-object would still break them.
            last_error = f"root must be a JSON object, got {type(data).__name__}"
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
    """Coerce a model-supplied confidence into 0..1.

    Models return a percentage where a fraction was asked for often enough to be
    worth handling: 85 means 0.85. Anything above 100, or a value between 1 and
    100 that was already meant as a fraction, cannot be told apart, so the
    percentage reading is used up to 100 and everything beyond it saturates.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v or v in (float("inf"), float("-inf")):  # NaN or infinity
        return default
    if v > 1.0:
        v = v / 100.0 if v <= 100.0 else 1.0
    return max(0.0, min(1.0, v))


REFUSAL_NOTE = (
    "You never help a student misrepresent, conceal, or fabricate anything. "
    "If asked to do so, refuse and explain the legal consequences plainly. "
    "You report what documents and official sources say. You do not give legal advice."
)
