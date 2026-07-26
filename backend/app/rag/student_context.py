"""The signed-in student's own facts, rendered for a prompt.

Every agent and the grounded answering path were operating on the question alone, so
the same question from two students produced the same answer. That is the wrong shape
for this product: "am I eligible" and "how much do I need to show" have different
correct answers for someone with IELTS 6.0 and a 22 lakh budget than for someone with
7.5 and 60 lakh, and the system already holds both profiles.

Three rules govern what this module does, and all three are about not doing harm with
the personalisation.

**A profile is never a source of fact about the world.** It says what the student told
us about themselves, not what any rule requires. The framing below states that
explicitly, because a model given "budget: 2,500,000 BDT" alongside retrieved passages
will otherwise happily report the budget as though a portal had said it. Citations
still come only from retrieved passages; nothing here is citable.

**A profile is untrusted text.** `field_of_study`, `home_district` and
`display_name` are free-text fields the student types, so a student can write
instructions into their own profile. That is a smaller threat than a crawled page,
because the only person affected is the author, but it is the same mechanism, and one
of these fields is shown to a moderator in the console. The whole block is therefore
passed through the same nonce-fenced data-only frame as crawled content
(`app/security/framing.py`).

**Absent is absent.** A field the student has not filled in is omitted rather than
sent as "unknown" or zero. A model told "CGPA: 0" will reason about a student who
failed; a model told nothing about CGPA will ask or hedge, which is correct.
"""

from __future__ import annotations

from typing import Any

from app.security.framing import frame_untrusted

# Long enough for a full profile and every shortlisted programme, short enough that it
# cannot crowd retrieved passages out of the context window. Grounded answering runs at
# num_ctx 8192 (app/llm/router.py), and the passages must always have room.
MAX_CONTEXT_CHARS = 1_400

_DEGREE_LABEL = {
    "bachelor": "bachelor's degree",
    "master": "master's degree",
    "phd": "doctorate",
    "diploma": "diploma",
    "hsc": "higher secondary certificate",
}


def _english_line(profile: dict[str, Any]) -> str | None:
    test = (profile.get("english_test") or "").strip()
    if not test or test == "none":
        return None
    overall = profile.get("english_overall")
    parts = [test.upper()]
    if overall is not None:
        parts.append(f"overall {overall}")
    sub = profile.get("english_sub") or {}
    if isinstance(sub, dict) and sub:
        # The band a programme rejects on is usually the lowest one, not the overall, so
        # the sub-scores are worth the characters they cost.
        detail = ", ".join(f"{k} {v}" for k, v in sub.items() if v is not None)
        if detail:
            parts.append(f"({detail})")
    return "English test: " + " ".join(parts)


def profile_facts(profile: dict[str, Any] | None) -> list[str]:
    """The student's own statements, one per line, omitting anything unset."""
    if not profile:
        return []
    lines: list[str] = []

    degree = profile.get("degree_level")
    field = profile.get("field_of_study")
    if degree or field:
        label = _DEGREE_LABEL.get(str(degree), str(degree or "qualification"))
        lines.append(f"Highest qualification: {label}" + (f" in {field}" if field else ""))

    cgpa, scale = profile.get("cgpa"), profile.get("cgpa_scale")
    if cgpa is not None:
        # The scale travels with the number. A bare "3.62" is meaningless against a 5.0
        # scale, and Bangladeshi transcripts use both 4.0 and 5.0.
        lines.append(f"CGPA: {cgpa} out of {scale}" if scale else f"CGPA: {cgpa}")

    if profile.get("graduation_year"):
        lines.append(f"Graduated: {profile['graduation_year']}")
    gap = profile.get("study_gap_years")
    if gap:
        lines.append(f"Study gap since graduating: {gap} year(s)")

    english = _english_line(profile)
    if english:
        lines.append(english)

    if profile.get("budget_bdt"):
        lines.append(f"Stated budget: {int(profile['budget_bdt']):,} BDT")
    if profile.get("intake_target"):
        lines.append(f"Target intake: {profile['intake_target']}")
    if profile.get("home_district"):
        lines.append(f"Home district: {profile['home_district']}")
    return lines


def target_facts(targets: list[dict[str, Any]] | None) -> list[str]:
    """Where the student is actually applying, which is what makes an answer specific."""
    if not targets:
        return []
    lines = []
    for t in targets[:6]:
        bits = [str(t.get("programme_name") or "").strip()]
        if t.get("institution_name"):
            bits.append(f"at {t['institution_name']}")
        if t.get("country_code"):
            bits.append(f"({str(t['country_code']).upper()})")
        if t.get("status"):
            bits.append(f"- {t['status']}")
        line = " ".join(b for b in bits if b)
        if line:
            lines.append(line)
    return [f"Applying to: {'; '.join(lines)}"] if lines else []


def build_student_context(
    profile: dict[str, Any] | None,
    targets: list[dict[str, Any]] | None = None,
    *,
    max_chars: int = MAX_CONTEXT_CHARS,
) -> str:
    """A framed block of the student's own facts, or "" when there is nothing to say.

    Returning an empty string for an empty profile matters: the caller appends this to a
    prompt, and an empty frame would tell the model a profile exists and is blank, which
    invites it to comment on the blankness instead of answering the question.
    """
    lines = profile_facts(profile) + target_facts(targets)
    if not lines:
        return ""
    body = "\n".join(lines)
    return frame_untrusted(
        body,
        label="STUDENT_PROFILE",
        attrs={"source": "self-reported"},
        max_chars=max_chars,
    )


# Appended to the system prompt whenever a student context is present. Separate from the
# frame so the rule is stated once here rather than re-typed by each of seven agents.
STUDENT_CONTEXT_RULE = (
    "A STUDENT_PROFILE block describes the person asking, in their own words. Use it to "
    "make the answer specific to them: address their qualification, their test score, "
    "their budget and their destinations where those matter to the question. It is not "
    "evidence about any rule or requirement, it is never citable, and a figure from it "
    "must never be presented as something a source states. If the profile lacks "
    "something the answer depends on, say which detail is missing rather than assuming a "
    "value for it."
)
