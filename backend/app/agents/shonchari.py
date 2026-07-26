"""Shonchari (সঞ্চারী), the Interview Rehearsal agent.

A visa officer is not testing eloquence. They are testing whether the spoken
answer matches the file in front of them. So this agent scores consistency
against the student's own documents first and fluency last, and the report says
what each question was actually probing.

Document values are never sent to the model. The service passes normalised
hashes of extracted fields plus a minimised summary, so a contradiction is
detected by comparing a hash of what the student said against a hash of what the
document says. The model never sees a passport number.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, clamp01, structured
from app.llm.router import ModelRouter, TaskKind
from app.security.framing import frame_untrusted

log = logging.getLogger(__name__)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "relevance": {"type": "number"},
        "consistency": {"type": "number"},
        "credibility": {"type": "number"},
        "probing": {"type": "string"},
        "feedback_en": {"type": "string"},
        "feedback_bn": {"type": "string"},
        "rewrite_en": {"type": "string"},
        "rewrite_bn": {"type": "string"},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "relevance", "consistency", "credibility", "probing",
        "feedback_en", "feedback_bn", "rewrite_en", "rewrite_bn", "red_flags",
    ],
}

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "overall": {"type": "number"},
        "summary_en": {"type": "string"},
        "summary_bn": {"type": "string"},
        "strengths": {"type": "array", "items": {"type": "string"}},
        "weaknesses": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overall", "summary_en", "summary_bn", "strengths", "weaknesses"],
}

SCORE_SYSTEM = (
    "You are Shonchari, a visa interview coach for Bangladeshi students. Score "
    "one answer on three axes from 0 to 1: relevance (did it answer the "
    "question), consistency (does it agree with the student's own file), and "
    "credibility (would an officer find it plausible and specific). State in "
    "'probing' what the officer is really testing with this question. Give "
    "feedback and one rewritten answer, in English and natural Bangla. The "
    "rewrite must only restate what the student actually said, more clearly. "
    "Never invent facts, ties, funds, or history for them. " + REFUSAL_NOTE
)

REPORT_SYSTEM = (
    "You are Shonchari. Write a closing report on a practice visa interview for "
    "a Bangladeshi student. Be specific and kind, and name the two things that "
    "would most improve the outcome. Bangla must be natural. Never promise an "
    "outcome. " + REFUSAL_NOTE
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().casefold()


def _hash(text: str) -> str:
    return hashlib.sha256(_normalise(text).encode("utf-8")).hexdigest()


# Numbers and dates spoken in an answer that contradict the file are the single
# most damaging thing in a real interview, so they are detected mechanically
# rather than left to the model to notice.
_NUMBER = re.compile(r"\b\d[\d,]{2,}\b")


def _detect_contradictions(
    answer_text: str, document_field_hashes: dict[str, str]
) -> list[dict[str, Any]]:
    """Flag spoken figures that disagree with amount / id-number field digests.

    Only amount/`_no`/`_number` hashes are considered. When none exist, spoken
    numbers are left alone — flagging every digit in an answer as unverified
    when the vault has no comparable fields is noise, not a contradiction.
    """
    found: list[dict[str, Any]] = []
    relevant = {
        key: digest
        for key, digest in (document_field_hashes or {}).items()
        if key.endswith(("_amount", "_no", "_number"))
    }
    if not relevant:
        return found

    known = set(relevant.values())
    for token in set(_NUMBER.findall(answer_text or "")):
        digest = _hash(token.replace(",", ""))
        if digest in known:
            continue
        # Spoken figure matches none of the recorded amount/number digests.
        if len(relevant) == 1:
            field_key = next(iter(relevant))
            found.append(
                {
                    "field": field_key,
                    "said": token,
                    "status": "mismatch",
                }
            )
        else:
            found.append(
                {
                    "field": "spoken_figure",
                    "said": token,
                    "status": "not_found_in_documents",
                }
            )
    return found


async def score_answer(
    *,
    question_text: str,
    answer_text: str,
    file_summary: dict[str, Any],
    document_field_hashes: dict[str, str],
    router: ModelRouter,
) -> dict[str, Any]:
    """Score one interview answer against the student's own file."""
    contradictions = _detect_contradictions(answer_text, document_field_hashes)

    summary_lines = "\n".join(f"{k}: {v}" for k, v in (file_summary or {}).items() if v)
    flagged = (
        "\n".join(
            f"- the student said the figure {c['said']}, which does not appear in "
            f"any uploaded document"
            for c in contradictions
        )
        or "none detected"
    )

    try:
        data = await structured(
            router,
            AgentCall(
                kind=TaskKind.INTERVIEW_SCORE,
                system=SCORE_SYSTEM,
                # Judgement task: reasoning before answering measurably helps.
                thinking=True,
                user=(
                    frame_untrusted(
                        summary_lines, label="STUDENT_FILE_SUMMARY", max_chars=3_000
                    )
                    + "\n\n"
                    + frame_untrusted(
                        flagged, label="MECHANICALLY_FLAGGED_FIGURES", max_chars=2_000
                    )
                    # question_text is from the operator-controlled bank, so the
                    # injection risk is low, but fencing is applied everywhere.
                    + "\n\n"
                    + frame_untrusted(question_text, label="QUESTION", max_chars=1_000)
                    + "\n\n"
                    # The answer is free text typed by the student mid-interview.
                    # Fencing it stops "score this 10/10" from being read as a
                    # rubric change rather than as the answer under review.
                    + frame_untrusted(answer_text, label="STUDENT_ANSWER", max_chars=6_000)
                ),
                schema=SCORE_SCHEMA,
                contains_user_documents=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("shonchari scoring failed: %s", exc)
        return {
            "relevance": None,
            "consistency": None,
            "credibility": None,
            "contradicts": contradictions,
            "feedback_en": "Scoring is unavailable right now. Your answer was recorded.",
            "feedback_bn": "এখন মূল্যায়ন করা যাচ্ছে না। আপনার উত্তর সংরক্ষণ করা হয়েছে।",
        }

    return {
        "relevance": clamp01(data.get("relevance")),
        "consistency": clamp01(data.get("consistency")),
        "credibility": clamp01(data.get("credibility")),
        "probing": data.get("probing", ""),
        "contradicts": contradictions,
        "red_flags": data.get("red_flags", []),
        "feedback_en": data.get("feedback_en", ""),
        "feedback_bn": data.get("feedback_bn", ""),
        "rewrite_en": data.get("rewrite_en", ""),
        "rewrite_bn": data.get("rewrite_bn", ""),
    }


async def compose_report(
    *, turns: list[dict[str, Any]], router: ModelRouter
) -> dict[str, Any]:
    """Close a session with a report the student can act on.

    Only answered turns are included in the transcript. Unanswered turns have
    `answer_text = NULL`, and sending 'A: None' to the model produces confusing
    summaries that mention the absence of an answer rather than reviewing the
    ones that were given.
    """
    answered = [t for t in turns if t.get("answered_at") is not None]
    scored = [t for t in answered if t.get("relevance") is not None]
    if scored:
        overall = sum(
            (float(t["relevance"]) + float(t["consistency"]) + float(t["credibility"])) / 3.0
            for t in scored
        ) / len(scored)
    else:
        overall = 0.0

    transcript = "\n\n".join(
        # list_turns joins question_bn from interview_bank. The model writes its
        # summary in Bangla, so showing the Bangla question produces a more natural
        # summary than forcing it to translate from English mid-generation.
        f"Q{t.get('ordinal')} (EN): {t.get('question_text')}\n"
        f"Q{t.get('ordinal')} (BN): {t.get('question_bn') or t.get('question_text')}\n"
        f"A: {t.get('answer_text')}\n"
        f"scores: relevance={t.get('relevance')} consistency={t.get('consistency')} "
        f"credibility={t.get('credibility')}"
        for t in answered
    )

    try:
        data = await structured(
            router,
            AgentCall(
                kind=TaskKind.INTERVIEW_SCORE,
                system=REPORT_SYSTEM,
                user=frame_untrusted(
                    transcript, label="SESSION_TRANSCRIPT_AND_SCORES", max_chars=16_000
                ),
                schema=REPORT_SCHEMA,
                contains_user_documents=True,
                thinking=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("shonchari report failed: %s", exc)
        return {
            "overall": round(overall, 3),
            "summary_en": "The session was recorded. A written report is unavailable right now.",
            "summary_bn": "সেশনটি সংরক্ষণ করা হয়েছে। এখন লিখিত রিপোর্ট তৈরি করা যাচ্ছে না।",
            "strengths": [],
            "weaknesses": [],
        }

    return {
        # The arithmetic mean is authoritative. The model may narrate it but does
        # not get to change it.
        "overall": round(overall, 3),
        "summary_en": data.get("summary_en", ""),
        "summary_bn": data.get("summary_bn", ""),
        "strengths": data.get("strengths", []),
        "weaknesses": data.get("weaknesses", []),
    }
