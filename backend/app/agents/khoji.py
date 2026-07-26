"""Khoji (খোঁজি), the Scholarship Scout.

Hard criteria are filtered in code, not by the model. Whether a CGPA of 3.2
clears a 3.3 floor is arithmetic, and asking a language model to do arithmetic
that decides whether a student sees an award is a poor trade. The model scores
the soft criteria only, and it must return a reason for every criterion it
scores.

That last rule is the point of this agent. A ranked list with no reasons is an
oracle, and a student cannot act on an oracle. Every rank here decomposes into
per-criterion statements the student can check and argue with.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, clamp01, structured
from app.llm.router import ModelRouter, TaskKind
from app.security.framing import frame_untrusted

log = logging.getLogger(__name__)

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "scholarship_id": {"type": "string"},
                    "score": {"type": "number"},
                    "reasons": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "criterion_key": {"type": "string"},
                                "met": {"type": "boolean"},
                                "reason_en": {"type": "string"},
                                "reason_bn": {"type": "string"},
                            },
                            "required": ["criterion_key", "met", "reason_en", "reason_bn"],
                        },
                    },
                },
                "required": ["scholarship_id", "score", "reasons"],
            },
        }
    },
    "required": ["results"],
}

SYSTEM = (
    "You are Khoji, a scholarship matcher for Bangladeshi students. Hard "
    "eligibility has already been decided in code; do not revisit it. Score "
    "only how well this student's profile fits each award on the soft criteria "
    "given, from 0 to 1. Give a reason for every criterion you score, in "
    "English and in natural Bangla. A score is an estimate and you must phrase "
    "reasons that way. Never promise an award and never state a deadline or an "
    "amount that was not given to you. " + REFUSAL_NOTE
)


def _criterion_met(operator: str, value: str, actual: Any) -> bool | None:
    """Evaluate one `scholarship_criteria` row against a known value.

    Returns True/False, or None when the criterion cannot be judged (missing
    profile field or unparseable stored value). None is "unverified": hard
    criteria only disqualify on an explicit False.
    """
    if actual is None:
        return None
    try:
        if operator == "gte":
            return float(actual) >= float(value)
        if operator == "lte":
            return float(actual) <= float(value)
        if operator == "eq":
            return str(actual).strip().casefold() == str(value).strip().casefold()
        if operator == "in":
            options: set[str]
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    options = {str(v).strip().casefold() for v in parsed}
                else:
                    options = {v.strip().casefold() for v in str(value).split(",")}
            except (json.JSONDecodeError, TypeError):
                options = {v.strip().casefold() for v in str(value).split(",")}
            return str(actual).strip().casefold() in options
        if operator == "exists":
            return bool(actual)
    except (TypeError, ValueError):
        return None
    return None


def _profile_value(profile: dict[str, Any], criterion_key: str) -> Any:
    """Resolve a criterion key against the profile.

    `cgpa_min` normalises to a 4.0 scale (Bangladeshi institutions use both
    4.0 and 5.0). A zero or unusable scale returns None rather than dividing
    by zero — the hard check then treats the criterion as unverified.
    """
    if criterion_key == "cgpa_min":
        cgpa = profile.get("cgpa")
        if cgpa is None:
            return None
        scale = profile.get("cgpa_scale") or 4.0
        try:
            scale_f = float(scale)
        except (TypeError, ValueError):
            return None
        if scale_f == 0:
            return None
        return float(cgpa) * (4.0 / scale_f)
    return profile.get(criterion_key)


def _criterion_threshold(award: dict[str, Any], key: str) -> Any:
    for c in award.get("criteria") or []:
        if c.get("criterion_key") == key:
            return c.get("value")
    return None


def _fails_hard_criteria(profile: dict[str, Any], award: dict[str, Any]) -> str | None:
    """Return the failing hard criterion key, or None when the student qualifies.

    Real award rows carry a `criteria` list from `scholarship_criteria` (see
    funding_service.rematch). Root fields like `min_cgpa` are not populated on
    that shape, so evaluating them was a no-op.
    """
    criteria = award.get("criteria") or []
    for c in criteria:
        if not c.get("is_hard"):
            continue
        met = _criterion_met(
            str(c.get("operator") or ""),
            str(c.get("value") if c.get("value") is not None else ""),
            _profile_value(profile, str(c.get("criterion_key") or "")),
        )
        if met is False:
            return str(c.get("criterion_key") or "hard_criteria")
    return None


# How many awards are sent to the model in one scoring call. Chosen so the
# fenced award block stays well inside `frame_untrusted`'s 12,000-character
# default rather than being silently truncated by it.
_MAX_SCORED_AWARDS = 40


def _unscored_but_eligible(award: dict[str, Any]) -> dict[str, Any]:
    """An award the student qualifies for, which fit scoring did not reach.

    Used both when the model call fails and when the candidate set is larger
    than one call should carry. The student sees the award and the reason it
    qualified; what is missing is the ranking nuance, and saying so is better
    than hiding the award.
    """
    return {
        "scholarship_id": award["public_id"],
        "score": 0.5,
        "eligible": True,
        "reasons": [
            {
                "criterion_key": "hard_criteria",
                "met": True,
                "reason_en": "You meet the stated eligibility rules. "
                             "Detailed fit scoring is unavailable right now.",
                "reason_bn": "আপনি ঘোষিত যোগ্যতার শর্ত পূরণ করেন। "
                             "বিস্তারিত মিল যাচাই এখন করা যাচ্ছে না।",
            }
        ],
    }


async def score_eligibility(
    *,
    profile: dict[str, Any],
    scholarships: list[dict[str, Any]],
    router: ModelRouter,
) -> list[dict[str, Any]]:
    """Score a student against a candidate list. Every score carries reasons."""
    eligible: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []

    for award in scholarships:
        failed = _fails_hard_criteria(profile, award)
        if failed:
            results.append(
                {
                    "scholarship_id": award["public_id"],
                    "score": 0.0,
                    "eligible": False,
                    "reasons": [
                        {
                            "criterion_key": failed,
                            "met": False,
                            "reason_en": _hard_reason_en(failed, profile, award),
                            "reason_bn": _hard_reason_bn(failed, profile, award),
                        }
                    ],
                }
            )
        else:
            eligible.append(award)

    if not eligible:
        return results

    # Bound what reaches the model. The award block was fenced without a
    # `max_chars`, so it inherited `frame_untrusted`'s 12,000-character default
    # and would have been cut mid-line once the funding index grew — leaving the
    # model scoring a truncated list while `eligible` still held every award, so
    # the tail came back unscored with no indication why. Capping the count
    # instead makes the boundary explicit and keeps the block comfortably inside
    # the fence. It also caps the KV cache this call claims, which matters on a
    # machine already holding a 7.2 GB model resident.
    #
    # The overflow is not dropped. Awards past the cap are returned eligible and
    # unscored, exactly as the exception path below does, on the same reasoning:
    # missing an award a student qualifies for is the worse failure.
    overflow = eligible[_MAX_SCORED_AWARDS:]
    eligible = eligible[:_MAX_SCORED_AWARDS]
    for award in overflow:
        results.append(_unscored_but_eligible(award))

    profile_summary = (
        f"degree_level={profile.get('degree_level')} "
        f"field={profile.get('field_of_study')} "
        f"cgpa={profile.get('cgpa')}/{profile.get('cgpa_scale')} "
        f"english={profile.get('english_test')} {profile.get('english_overall')} "
        f"graduation_year={profile.get('graduation_year')} "
        f"study_gap_years={profile.get('study_gap_years')}"
    )
    award_lines = "\n".join(
        f"- id={a['public_id']} name={a['name']} provider={a['provider']} "
        f"country={a.get('country_code')} coverage={a.get('coverage_type')} "
        f"fields={a.get('fields')} soft_criteria={a.get('soft_criteria') or 'general fit'}"
        for a in eligible
    )

    try:
        data = await structured(
            router,
            AgentCall(
                kind=TaskKind.ELIGIBILITY_SCORE,
                system=SYSTEM,
                # Reasoning helps here: the trade-off between fit dimensions is
                # exactly the kind of judgement thinking mode improves.
                thinking=True,
                # Award rows are built from crawled scholarship pages, so the
                # award block is untrusted text and gets the same fence the
                # retrieval path uses.
                user=(
                    frame_untrusted(profile_summary, label="STUDENT", max_chars=2_000)
                    + "\n\n"
                    + frame_untrusted(award_lines, label="AWARDS")
                ),
                schema=SCORE_SCHEMA,
                # Profile text is student PII; keep the call on the local path.
                contains_user_documents=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        # Degrade to eligible-with-no-score rather than hiding awards the
        # student qualifies for. Missing an award is the worse failure.
        log.warning("khoji scoring failed, returning unscored eligible set: %s", exc)
        results.extend(_unscored_but_eligible(award) for award in eligible)
        return results

    scored = {r["scholarship_id"]: r for r in data.get("results", [])}
    for award in eligible:
        entry = scored.get(award["public_id"])
        if entry is None:
            continue
        results.append(
            {
                "scholarship_id": award["public_id"],
                "score": clamp01(entry.get("score"), 0.5),
                "eligible": True,
                "reasons": entry.get("reasons", []),
            }
        )
    return results


def _hard_reason_en(key: str, profile: dict[str, Any], award: dict[str, Any]) -> str:
    threshold = _criterion_threshold(award, key)
    return {
        "cgpa_min": f"This award requires a minimum CGPA of {threshold} "
                    f"on a 4.0 scale. Your recorded CGPA is {profile.get('cgpa')} "
                    f"on a {profile.get('cgpa_scale')} scale.",
        "degree_level": f"This award is for {threshold} applicants. "
                        f"Your profile records {profile.get('degree_level')}.",
        "nationality": "This award is not open to applicants with your nationality "
                       "as recorded (or the nationality requirement could not be met).",
        "english_overall": f"This award requires an English score of at least "
                           f"{threshold}. Your recorded score is "
                           f"{profile.get('english_overall')}.",
        "english_min": f"This award requires an English score of at least "
                       f"{threshold}. Your recorded score is "
                       f"{profile.get('english_overall')}.",
    }.get(key, f"You do not meet the stated eligibility rule '{key}' for this award.")


def _hard_reason_bn(key: str, profile: dict[str, Any], award: dict[str, Any]) -> str:
    threshold = _criterion_threshold(award, key)
    return {
        "cgpa_min": f"এই বৃত্তির জন্য ৪.০ স্কেলে ন্যূনতম {threshold} সিজিপিএ দরকার। "
                    f"আপনার সিজিপিএ {profile.get('cgpa')} ({profile.get('cgpa_scale')} স্কেলে)।",
        "degree_level": "আপনার বর্তমান ডিগ্রি স্তর এই বৃত্তির জন্য প্রযোজ্য নয়।",
        "nationality": "এই বৃত্তি আপনার জাতীয়তার জন্য উন্মুক্ত নয়।",
        "english_overall": f"এই বৃত্তির জন্য ইংরেজিতে অন্তত {threshold} স্কোর দরকার। "
                           f"আপনার স্কোর {profile.get('english_overall')}।",
        "english_min": f"এই বৃত্তির জন্য ইংরেজিতে অন্তত {threshold} স্কোর দরকার। "
                       f"আপনার স্কোর {profile.get('english_overall')}।",
    }.get(key, "আপনি এই বৃত্তির একটি ঘোষিত শর্ত পূরণ করছেন না।")
