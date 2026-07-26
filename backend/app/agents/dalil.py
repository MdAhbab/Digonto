"""Dalil (দলিল), the Contract Auditor.

Students sign consultancy agreements they have not read, in a register they may
not read well, containing clauses that keep their original documents or forfeit
the entire fee on refusal. Two categories cause most of the harm and are always
surfaced first:

  * original document retention, which leaves a student unable to apply anywhere
    else while a dispute runs
  * any clause guaranteeing a visa outcome, which no agent can lawfully promise
    and which is a reliable marker of a firm worth avoiding

Dalil reports what a contract says and how unusual it is. It does not give legal
advice, says so, and recommends a lawyer where the amounts justify one.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, structured
from app.llm.router import ModelRouter, TaskKind

log = logging.getLogger(__name__)

HIGH_RISK_CATEGORIES = {"document_retention", "guarantee", "refund"}

SCHEMA = {
    "type": "object",
    "properties": {
        "consultancy": {"type": "string"},
        "risk_overall": {"type": "string", "enum": ["low", "medium", "high"]},
        "clauses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quoted_text": {"type": "string"},
                    "category": {
                        "type": "string",
                        "enum": [
                            "fee", "refund", "document_retention", "exclusivity",
                            "liability", "guarantee", "other",
                        ],
                    },
                    "risk": {"type": "string", "enum": ["low", "medium", "high"]},
                    "why_en": {"type": "string"},
                    "why_bn": {"type": "string"},
                    "fair_alternative_en": {"type": "string"},
                    "fair_alternative_bn": {"type": "string"},
                },
                "required": [
                    "quoted_text", "category", "risk",
                    "why_en", "why_bn", "fair_alternative_en", "fair_alternative_bn",
                ],
            },
        },
    },
    "required": ["risk_overall", "clauses"],
}

SYSTEM = (
    "You are Dalil. You read education consultancy contracts for Bangladeshi "
    "students and report what each clause actually permits the firm to do. "
    "Quote each clause exactly. Rate the risk it transfers onto the student and "
    "state a fair alternative. Treat these as high risk whenever they appear: "
    "retention of original documents, any guarantee of a visa or admission "
    "outcome, and forfeiture of the whole fee on refusal. "
    "Explain in plain Bangla what the clause means for the student in practice. "
    "You report what the contract says and how unusual it is. You do not give "
    "legal advice, and you say so. Where the amounts are large, recommend the "
    "student consult a lawyer. " + REFUSAL_NOTE
)


async def audit_contract(
    *,
    document_bytes: bytes,
    mime_type: str,
    router: ModelRouter,
) -> dict[str, Any]:
    """Read a consultancy contract clause by clause."""
    if not mime_type.startswith("image/"):
        raise ValueError(
            "audit_contract expects an image; PDFs must be rasterised by the "
            "vault service first"
        )

    data = await structured(
        router,
        AgentCall(
            kind=TaskKind.VISION_EXTRACT,
            system=SYSTEM,
            user=(
                "Read this consultancy contract. Report every clause that "
                "affects fees, refunds, document custody, exclusivity, "
                "liability, or promises about outcomes."
            ),
            schema=SCHEMA,
            images=[document_bytes],
            contains_user_documents=True,
            thinking=True,
            max_tokens=3072,
        ),
    )

    clauses: list[dict[str, Any]] = []
    escalated = False
    for c in data.get("clauses", []):
        category = c.get("category", "other")
        risk = c.get("risk", "medium")
        # The model sometimes rates a document-retention clause as medium. These
        # three categories are high risk by policy, not by judgement.
        if category in HIGH_RISK_CATEGORIES and risk != "high":
            risk = "high"
            escalated = True
        clauses.append({**c, "category": category, "risk": risk})

    overall = data.get("risk_overall", "medium")
    if escalated or any(c["risk"] == "high" for c in clauses):
        overall = "high"

    return {
        "consultancy": data.get("consultancy"),
        "risk_overall": overall,
        "clauses": clauses,
    }
