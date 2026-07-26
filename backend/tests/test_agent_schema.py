"""Schema validation in the agent runtime, and the data-only rule it injects.

The runtime used to check only that each name in `required` was present at the top
level. `{"findings": "none"}` passed that check where a list of objects was
specified, and the failure then surfaced far away, in a repository or a template,
as a much less obvious error. Each test below is a payload the old check admitted.
"""

from __future__ import annotations

import pytest

from app.agents.runtime import (
    AgentCall,
    _system_prompt,
    bilingual,
    clamp01,
    enum_field,
    validate_against_schema,
)
from app.llm.router import TaskKind
from app.security.framing import DATA_ONLY_RULE, frame_untrusted

FINDINGS_SCHEMA = {
    "type": "object",
    "properties": {
        "severity": enum_field(["critical", "warning", "info"]),
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "note": bilingual("A note")},
                "required": ["code", "note"],
            },
        },
    },
    "required": ["severity", "confidence", "findings"],
}


def _valid() -> dict:
    return {
        "severity": "warning",
        "confidence": 0.8,
        "findings": [{"code": "PASSPORT_EXPIRING", "note": {"en": "e", "bn": "ব"}}],
    }


def test_valid_payload_has_no_violations() -> None:
    assert validate_against_schema(_valid(), FINDINGS_SCHEMA) == []


def test_wrong_type_for_array_field_is_caught() -> None:
    """The exact payload the old presence-only check let through."""
    bad = _valid() | {"findings": "none"}
    errors = validate_against_schema(bad, FINDINGS_SCHEMA)
    assert errors and "expected array" in errors[0]


def test_enum_violation_is_caught() -> None:
    errors = validate_against_schema(_valid() | {"severity": "URGENT"}, FINDINGS_SCHEMA)
    assert any("not one of" in e for e in errors)


@pytest.mark.parametrize("value", [7, -0.5, 100])
def test_numeric_bounds_are_enforced(value: float) -> None:
    errors = validate_against_schema(_valid() | {"confidence": value}, FINDINGS_SCHEMA)
    assert any("minimum" in e or "maximum" in e for e in errors)


def test_nested_required_field_is_caught() -> None:
    """A missing Bangla translation must fail validation, not render an empty panel."""
    bad = _valid()
    bad["findings"][0]["note"] = {"en": "only english"}
    errors = validate_against_schema(bad, FINDINGS_SCHEMA)
    assert any("bn" in e for e in errors)
    assert any("findings[0]" in e for e in errors), "the path must locate the item"


def test_array_item_of_wrong_type_is_caught() -> None:
    bad = _valid()
    bad["findings"].append("not-an-object")
    errors = validate_against_schema(bad, FINDINGS_SCHEMA)
    assert any("findings[1]" in e and "expected object" in e for e in errors)


def test_missing_top_level_field_is_still_caught() -> None:
    bad = _valid()
    del bad["confidence"]
    assert any("confidence" in e for e in validate_against_schema(bad, FINDINGS_SCHEMA))


def test_boolean_is_not_accepted_as_a_number() -> None:
    """bool subclasses int in Python; a schema asking for a number must reject it."""
    errors = validate_against_schema(_valid() | {"confidence": True}, FINDINGS_SCHEMA)
    assert errors, "True must not satisfy type: number"


def test_unknown_keywords_are_ignored() -> None:
    """Adding a description must never turn a valid payload invalid."""
    schema = {"type": "object", "properties": {"a": {"type": "string", "description": "x"}},
              "required": ["a"], "title": "Anything", "additionalProperties": False}
    assert validate_against_schema({"a": "ok"}, schema) == []


# --- the data-only rule rides along with the fence ---------------------------


def _call(user: str, system: str = "You are an agent.") -> AgentCall:
    return AgentCall(kind=TaskKind.AGENT_TOOL, system=system, user=user, schema={})


def test_rule_is_appended_when_the_prompt_frames_untrusted_text() -> None:
    """A frame without its instruction is decoration, so the runtime adds it."""
    prompt = _system_prompt(_call(frame_untrusted("page text", label="SOURCE")))
    assert DATA_ONLY_RULE in prompt


def test_rule_is_absent_when_nothing_is_framed() -> None:
    assert DATA_ONLY_RULE not in _system_prompt(_call("plain question, no fence"))


def test_rule_is_not_duplicated_when_already_present() -> None:
    call = _call(frame_untrusted("x", label="SOURCE"), system=f"Base.\n{DATA_ONLY_RULE}")
    assert _system_prompt(call).count("never instructions") == 1


# --- confidence coercion -----------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0.85, 0.85), (85, 0.85), (100, 1.0), (150, 1.0),
        (0, 0.0), (-5, 0.0), ("0.4", 0.4), (None, 0.0), ("nonsense", 0.0),
        (float("nan"), 0.0), (float("inf"), 0.0),
    ],
)
def test_clamp01(raw: object, expected: float) -> None:
    assert clamp01(raw) == pytest.approx(expected)
