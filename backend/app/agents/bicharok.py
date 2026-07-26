"""Bicharok (বিচারক), the Rejection Autopsy agent.

In 2024, Schengen states refused 20,957 of 39,345 applications from Bangladesh.
The refusal letter states the grounds, in administrative English, referencing
paragraph numbers the applicant has never seen. A student who cannot read the
refusal cannot correct it, so they pay an agent again or they stop. This agent
exists for that moment.

It reads the letter with the model's own vision capability rather than a separate
OCR service, because the same served model does both and a second runtime would
be a second thing to keep alive on one machine.

Two rules make this honest. A ground that cannot be remedied is reported as
not remediable, because false hope costs a second application fee. And it never
suggests concealing a prior refusal: most forms ask directly, and advising
otherwise would be advising fraud.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, structured
from app.llm.router import ModelRouter, TaskKind

log = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "properties": {
        "country_code": {"type": "string"},
        "visa_type": {"type": "string"},
        "refused_on": {"type": "string"},
        "summary_en": {"type": "string"},
        "summary_bn": {"type": "string"},
        "grounds": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "quoted_text": {"type": "string"},
                    "meaning_en": {"type": "string"},
                    "meaning_bn": {"type": "string"},
                    "remedy_en": {"type": "string"},
                    "remedy_bn": {"type": "string"},
                    "remediable": {"type": "string", "enum": ["yes", "partly", "no"]},
                    "linked_step_key": {"type": "string"},
                },
                "required": [
                    "code", "quoted_text", "meaning_en", "meaning_bn",
                    "remedy_en", "remedy_bn", "remediable",
                ],
            },
        },
    },
    "required": ["summary_en", "summary_bn", "grounds"],
}

SYSTEM = (
    "You are Bicharok. You read visa refusal letters for Bangladeshi students "
    "and explain them. Quote each stated ground exactly as written. For each "
    "ground: say in plain language what the officer actually meant, whether it "
    "can be fixed before applying again (yes, partly, or no), and the concrete "
    "remedy. Where a ground cannot be fixed, say so; false hope costs another "
    "application fee. Use the step keys ielts, transcripts, funding, solvency, "
    "sop, interview, documents when a remedy maps to one. Bangla must be "
    "natural and must not use English legal wording untranslated. "
    "Never suggest hiding or omitting a previous refusal: application forms ask "
    "about refusal history directly, and concealing it is fraud. " + REFUSAL_NOTE
)


async def analyse_rejection(
    *,
    document_bytes: bytes,
    mime_type: str,
    router: ModelRouter,
) -> dict[str, Any]:
    """Read a refusal letter and produce a remediation plan."""
    is_image = mime_type.startswith("image/")

    call = AgentCall(
        kind=TaskKind.VISION_EXTRACT,
        system=SYSTEM,
        user=(
            "Read this visa refusal letter. Identify every distinct ground for "
            "refusal, quote each one exactly, and explain and remedy each. If "
            "the letter states a country, visa type, or decision date, report "
            "them."
        ),
        schema=SCHEMA,
        images=[document_bytes] if is_image else None,
        # Vault content. The router refuses to send this off the machine.
        contains_user_documents=True,
        thinking=True,
        max_tokens=3072,
    )

    if not is_image:
        # PDFs are converted to text upstream by the vault service; if that has
        # not happened we cannot proceed rather than guessing at the contents.
        raise ValueError(
            "analyse_rejection expects an image; PDFs must be rasterised or "
            "text-extracted by the vault service first"
        )

    data = await structured(router, call)

    grounds = []
    for g in data.get("grounds", []):
        remediable = g.get("remediable")
        if remediable not in ("yes", "partly", "no"):
            remediable = "partly"
        grounds.append({**g, "remediable": remediable})

    return {
        "country_code": data.get("country_code"),
        "visa_type": data.get("visa_type"),
        "refused_on": data.get("refused_on"),
        "summary_en": data.get("summary_en", ""),
        "summary_bn": data.get("summary_bn", ""),
        "grounds": grounds,
    }
