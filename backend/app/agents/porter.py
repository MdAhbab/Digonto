"""Porter (পোর্টার), the Portal Watch agent.

No student should learn about a deadline change after it stops being
recoverable. Porter consumes portal-change events, decides what a change is, and
turns material changes into alerts that quote the changed sentence and cite the
snapshot it came from.

The confidence threshold is the whole design. A wrong alert telling five hundred
students their deadline moved is far worse than an alert that arrives six hours
late, so anything below the threshold goes to a human queue instead of to
students. Cosmetic changes are discarded silently, because an alert about
reworded boilerplate teaches students to ignore alerts.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, clamp01, structured
from app.llm.router import ModelRouter, TaskKind
from app.security.framing import frame_untrusted

log = logging.getLogger(__name__)

# Below this, a person decides. Tuned against reviewer capacity, not set once:
# see docs/business_model.md section 5.
REVIEW_THRESHOLD = 0.70

MATERIAL_CATEGORIES = {"deadline", "fee", "document_requirement", "policy"}

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "category": {
            "type": "string",
            "enum": ["deadline", "fee", "document_requirement", "policy", "cosmetic"],
        },
        "confidence": {"type": "number"},
        "reason": {"type": "string"},
    },
    "required": ["category", "confidence", "reason"],
}

ALERT_SCHEMA = {
    "type": "object",
    "properties": {
        "title_en": {"type": "string"},
        "title_bn": {"type": "string"},
        "body_en": {"type": "string"},
        "body_bn": {"type": "string"},
        "consequence_en": {"type": "string"},
        "consequence_bn": {"type": "string"},
    },
    "required": [
        "title_en", "title_bn", "body_en", "body_bn",
        "consequence_en", "consequence_bn",
    ],
}

# The page being classified is the least trusted text in the product: a page that
# could talk its way to `cosmetic` would silence a real deadline alert for every
# affected student. Both texts are fenced by `frame_untrusted`, and
# `agents.runtime.structured` appends the matching data-only rule to this prompt
# because that fence is present.
CLASSIFY_SYSTEM = (
    "You classify changes to official immigration and university pages into "
    "exactly one category.\n"
    "Apply these rules IN ORDER and stop at the first one that matches:\n"
    "1. deadline: any date by which something must be done changed, was added, "
    "or was removed. A date change is ALWAYS 'deadline', never 'policy'.\n"
    "2. fee: an amount of money changed, was added, or was removed.\n"
    "3. document_requirement: the list of documents or evidence changed.\n"
    "4. policy: a rule changed that is not a date, an amount, or a document. "
    "Use this only when rules 1 to 3 do not match.\n"
    "5. cosmetic: the meaning is unchanged and only wording, formatting, "
    "punctuation, or navigation moved.\n"
    "Confidence is your certainty from 0 to 1. Be conservative: when the change "
    "is ambiguous, give a low confidence rather than guessing a category."
)

ALERT_SYSTEM = (
    "You are Porter, writing an alert to a Bangladeshi student about a change "
    "on an official page they depend on. Quote the changed sentence. State the "
    "concrete consequence for this student, including a date where one is "
    "given. Be brief and calm. Never state a date, amount, or requirement that "
    "is not in the change you were given. Bangla must be natural and must not "
    "leave English administrative wording untranslated. " + REFUSAL_NOTE
)


async def classify_change(
    *,
    old_text: str,
    new_text: str,
    portal_label: str,
    router: ModelRouter,
) -> dict[str, Any]:
    """Decide what a diff is. Returns category, confidence, and needs_review."""
    data = await structured(
        router,
        AgentCall(
            kind=TaskKind.CLASSIFY_CHANGE,
            system=CLASSIFY_SYSTEM,
            # Thinking off: this is a short classification and the extra tokens
            # only add latency to a job that runs on every changed passage.
            thinking=False,
            temperature=0.0,
            max_tokens=256,
            user=(
                "Classify the change between the two blocks below.\n\n"
                + frame_untrusted(
                    old_text, label="OLD_PORTAL_TEXT", attrs={"portal": portal_label}
                )
                + "\n\n"
                + frame_untrusted(
                    new_text, label="NEW_PORTAL_TEXT", attrs={"portal": portal_label}
                )
            ),
            schema=CLASSIFY_SCHEMA,
        ),
    )

    category = data.get("category", "policy")
    if category not in MATERIAL_CATEGORIES | {"cosmetic"}:
        category = "policy"
    confidence = clamp01(data.get("confidence"), 0.0)

    return {
        "category": category,
        "confidence": confidence,
        "reason": data.get("reason", ""),
        # A low-confidence cosmetic call still goes to review: discarding a real
        # change is the expensive mistake, not queueing a trivial one.
        "needs_review": confidence < REVIEW_THRESHOLD,
        "notify": category in MATERIAL_CATEGORIES and confidence >= REVIEW_THRESHOLD,
    }


async def compose_alert(
    *,
    category: str,
    old_text: str,
    new_text: str,
    portal_label: str,
    snapshot_public_id: str,
    student_context: dict[str, Any] | None,
    router: ModelRouter,
) -> dict[str, Any]:
    """Write the alert a student receives, quoting and citing the change."""
    context = ""
    if student_context:
        context = "\n".join(
            f"{k}: {v}" for k, v in student_context.items() if v is not None
        )

    data = await structured(
        router,
        AgentCall(
            kind=TaskKind.AGENT_TOOL,
            system=ALERT_SYSTEM,
            user=(
                f"CHANGE TYPE: {category}\n"
                "Write the alert for the change between these two blocks.\n\n"
                + frame_untrusted(
                    old_text, label="OLD_PORTAL_TEXT", attrs={"portal": portal_label}
                )
                + "\n\n"
                + frame_untrusted(
                    new_text, label="NEW_PORTAL_TEXT", attrs={"portal": portal_label}
                )
                + "\n\n"
                # Framed as well, and separately: profile fields are student-typed,
                # and keeping them in their own block stops the portal text from
                # reaching for them.
                + frame_untrusted(
                    context or "no additional context",
                    label="THIS_STUDENT",
                    max_chars=2_000,
                )
            ),
            schema=ALERT_SCHEMA,
            max_tokens=1024,
        ),
    )

    return {
        "kind": "portal_change",
        "severity": "critical" if category == "deadline" else "warning",
        "title_en": data.get("title_en", ""),
        "title_bn": data.get("title_bn", ""),
        "body_en": f"{data.get('body_en', '')}\n\n{data.get('consequence_en', '')}".strip(),
        "body_bn": f"{data.get('body_bn', '')}\n\n{data.get('consequence_bn', '')}".strip(),
        "snapshot_public_id": snapshot_public_id,
    }
