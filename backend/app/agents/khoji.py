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

import logging
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, clamp01, structured
from app.llm.router import ModelRouter, TaskKind

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


def _fails_hard_criteria(profile: dict[str, Any], award: dict[str, Any]) -> str | None:
    """Return the failing criterion key, or None when the student qualifies."""
    cgpa = profile.get("cgpa")
    scale = profile.get("cgpa_scale") or 4.0
    if award.get("min_cgpa") and cgpa is not None:
        # Normalise to a 4.0 scale before comparing, since Bangladeshi
        # institutions use both 4.0 and 5.0.
        normalised = float(cgpa) * (4.0 / float(scale))
        if normalised < float(award["min_cgpa"]):
            return "cgpa_min"

    levels = award.get("degree_levels")
    if levels and profile.get("degree_level") and profile["degree_level"] not in levels:
        return "degree_level"

    if award.get("nationality_excluded") and "BD" in (award["nationality_excluded"] or []):
        return "nationality"

    english = profile.get("english_overall")
    if award.get("min_english") and english is not None:
        if float(english) < float(award["min_english"]):
            return "english_min"

    return None


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
                user=f"STUDENT:\n{profile_summary}\n\nAWARDS:\n{award_lines}",
                schema=SCORE_SCHEMA,
            ),
        )
    except Exception as exc:  # noqa: BLE001
        # Degrade to eligible-with-no-score rather than hiding awards the
        # student qualifies for. Missing an award is the worse failure.
        log.warning("khoji scoring failed, returning unscored eligible set: %s", exc)
        for award in eligible:
            results.append(
                {
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
            )
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
    return {
        "cgpa_min": f"This award requires a minimum CGPA of {award.get('min_cgpa')} "
                    f"on a 4.0 scale. Your recorded CGPA is {profile.get('cgpa')} "
                    f"on a {profile.get('cgpa_scale')} scale.",
        "degree_level": f"This award is for {award.get('degree_levels')} applicants. "
                        f"Your profile records {profile.get('degree_level')}.",
        "nationality": "This award is not open to Bangladeshi nationals.",
        "english_min": f"This award requires an English score of at least "
                       f"{award.get('min_english')}. Your recorded score is "
                       f"{profile.get('english_overall')}.",
    }.get(key, "You do not meet a stated eligibility rule for this award.")


def _hard_reason_bn(key: str, profile: dict[str, Any], award: dict[str, Any]) -> str:
    return {
        "cgpa_min": f"এই বৃত্তির জন্য ৪.০ স্কেলে ন্যূনতম {award.get('min_cgpa')} সিজিপিএ দরকার। "
                    f"আপনার সিজিপিএ {profile.get('cgpa')} ({profile.get('cgpa_scale')} স্কেলে)।",
        "degree_level": "আপনার বর্তমান ডিগ্রি স্তর এই বৃত্তির জন্য প্রযোজ্য নয়।",
        "nationality": "এই বৃত্তি বাংলাদেশি নাগরিকদের জন্য উন্মুক্ত নয়।",
        "english_min": f"এই বৃত্তির জন্য ইংরেজিতে অন্তত {award.get('min_english')} স্কোর দরকার। "
                       f"আপনার স্কোর {profile.get('english_overall')}।",
    }.get(key, "আপনি এই বৃত্তির একটি ঘোষিত শর্ত পূরণ করছেন না।")
