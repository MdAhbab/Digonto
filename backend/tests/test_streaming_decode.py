"""Incremental decoding of the answer field out of partially arrived JSON.

`stream_grounded_answer` shows the answer word by word while the model is still
writing the JSON object that contains it, so it has to read a string field out of
a buffer that is not valid JSON yet. Every case here is a state the buffer really
passes through mid-stream, including the ones that only appear with Bangla: a
`\\uXXXX` escape can be split across two chunks, and a Bengali conjunct is several
code points that must not be emitted half-decoded.
"""

from __future__ import annotations

import json

import pytest

from app.rag.pipeline import ANSWER_SCHEMA, _chunks, _partial_string_field


def test_reads_a_complete_field() -> None:
    buf = '{"answer_bn": "সম্পূর্ণ উত্তর", "confidence": 0.9}'
    assert _partial_string_field(buf, "answer_bn") == "সম্পূর্ণ উত্তর"


def test_reads_a_field_that_is_still_arriving() -> None:
    assert _partial_string_field('{"answer_bn": "আংশিক উ', "answer_bn") == "আংশিক উ"


def test_absent_field_returns_empty() -> None:
    assert _partial_string_field('{"answer_en": "hi"}', "answer_bn") == ""


def test_empty_buffer_returns_empty() -> None:
    assert _partial_string_field("", "answer_bn") == ""


def test_escapes_are_decoded() -> None:
    buf = r'{"answer_bn": "line\none\ttab \"quoted\" back\\slash"}'
    out = _partial_string_field(buf, "answer_bn")
    assert out == 'line\none\ttab "quoted" back\\slash'


def test_escaped_quote_does_not_end_the_field_early() -> None:
    """The bug this guards: \\" is not a terminator."""
    buf = r'{"answer_bn": "he said \"no\" clearly", "confidence": 1}'
    assert _partial_string_field(buf, "answer_bn") == 'he said "no" clearly'


def test_lone_trailing_backslash_is_held_back() -> None:
    """A half-arrived escape must not be emitted as a stray backslash.

    One backslash, not two: `\\\\` is a *complete* escape for a literal backslash
    and should decode, which is the next test.
    """
    buf = '{"answer_bn": "before' + "\\"
    assert _partial_string_field(buf, "answer_bn") == "before"


def test_complete_escaped_backslash_is_decoded() -> None:
    assert _partial_string_field(r'{"answer_bn": "before\\"}', "answer_bn") == "before\\"


def test_split_unicode_escape_is_held_back() -> None:
    """`\\u09` has arrived but the rest has not; emitting now would be wrong."""
    assert _partial_string_field(r'{"answer_bn": "ab\u09', "answer_bn") == "ab"


def test_complete_unicode_escape_is_decoded() -> None:
    # ক is BENGALI LETTER KA.
    assert _partial_string_field(r'{"answer_bn": "কা"}', "answer_bn") == "কা"


def test_bengali_conjunct_round_trips_through_json_escaping() -> None:
    """A conjunct is several code points; all of them must survive."""
    original = "শিক্ষার্থী"  # contains ক্ষ and র্থ
    buf = json.dumps({"answer_bn": original}, ensure_ascii=True)
    assert _partial_string_field(buf, "answer_bn") == original


def test_field_name_appearing_inside_the_text_is_tolerated() -> None:
    """The first match wins, which is the one the model is writing."""
    buf = '{"answer_bn": "the key \\"answer_bn\\" is odd"}'
    assert _partial_string_field(buf, "answer_bn").startswith("the key")


def test_lone_surrogate_does_not_raise() -> None:
    """Malformed \\ud800 must degrade, not crash the stream."""
    out = _partial_string_field(r'{"answer_bn": "x\ud800y"}', "answer_bn")
    assert "x" in out and "y" in out


# --- chunking ----------------------------------------------------------------


def test_chunks_preserve_the_text_exactly() -> None:
    text = "একটি দীর্ঘ বাংলা বাক্য যা শব্দে শব্দে দেখানো হবে এবং কিছুই হারাবে না"
    assert "".join(_chunks(text)) == text


def test_chunks_of_empty_text_is_empty() -> None:
    assert _chunks("") == []


def test_chunks_do_not_split_mid_word() -> None:
    for piece in _chunks("alpha beta gamma delta epsilon zeta"):
        assert piece == piece.rstrip() or piece.endswith(" ")


# --- the schema the stream is decoded against --------------------------------


def test_answer_schema_requires_the_refusal_contract() -> None:
    """`refusal_reason` must always be present: the answers table CHECK needs it."""
    for field in ("answer_bn", "answer_en", "is_refusal", "refusal_reason", "citations"):
        assert field in ANSWER_SCHEMA["required"]


def test_citation_items_require_a_resolvable_snapshot() -> None:
    item = ANSWER_SCHEMA["properties"]["citations"]["items"]
    assert set(item["required"]) == {"ordinal", "snapshot_id", "quoted_span"}
