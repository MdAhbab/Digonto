"""Prohori (প্রহরী), the Document Guardian.

Replaces the one service a consultancy genuinely performs, document checking,
with an auditable free equivalent.

Most of this agent is deliberately not the model. Expiry arithmetic, missing-item
detection, and cross-document field comparison are deterministic checks, and a
deterministic check that a reviewer can reproduce is worth more than a fluent
paragraph. The model is used for the part it is actually good at: explaining a
finding in plain Bangla and drafting the letter that fixes it.

Field comparison never decrypts anything. Every extracted field carries a
normalised hash, so "does the surname on the passport match the transcript" is a
hash comparison, and this agent can run in a worker that holds no user key.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from app.agents.runtime import REFUSAL_NOTE, AgentCall, structured
from app.llm.router import ModelRouter, TaskKind
from app.security.framing import frame_untrusted

log = logging.getLogger(__name__)

# Most student visa regimes require the passport to outlast arrival by six
# months. Kept as a named constant because it appears in findings text.
PASSPORT_VALIDITY_MARGIN_DAYS = 180

# Documents a student needs for essentially any destination. Destination
# specific requirements come from the crawled checklist, not from this list.
UNIVERSAL_KINDS = {
    "passport": ("Passport", "পাসপোর্ট"),
    "transcript": ("Academic transcripts", "একাডেমিক ট্রান্সক্রিপ্ট"),
    "english_test": ("English test result", "ইংরেজি পরীক্ষার ফল"),
    "bank_statement": ("Bank statement", "ব্যাংক স্টেটমেন্ট"),
}

# Fields that must agree across documents. A mismatch here is a common and
# entirely avoidable refusal ground.
CROSS_CHECK_FIELDS = {
    "surname": ("Surname", "পদবি"),
    "given_name": ("Given name", "নাম"),
    "date_of_birth": ("Date of birth", "জন্ম তারিখ"),
    "passport_no": ("Passport number", "পাসপোর্ট নম্বর"),
}

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "detail_en": {"type": "string"},
                    "detail_bn": {"type": "string"},
                    "action_en": {"type": "string"},
                    "action_bn": {"type": "string"},
                },
                "required": ["code", "detail_en", "detail_bn", "action_en", "action_bn"],
            },
        }
    },
    "required": ["findings"],
}

SYSTEM = (
    "You are Prohori, a document checker for Bangladeshi students applying to "
    "study abroad. You are given a list of mechanical findings already "
    "determined by exact checks. Do not re-judge them and do not invent new "
    "ones. For each finding, write a plain explanation and one concrete next "
    "action. Write for someone applying for the first time who has never seen "
    "these forms. Bangla must be natural, not translated word by word. Never "
    "state a deadline or an amount that was not given to you. " + REFUSAL_NOTE
)


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    if isinstance(value, date):
        return value
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(str(value)[:10], fmt).date()
        except ValueError:
            continue
    return None


def _mechanical_findings(
    documents: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    target: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Everything decidable without a model. Deterministic and reproducible."""
    findings: list[dict[str, Any]] = []
    today = date.today()

    present = {d["kind"] for d in documents if not d.get("deleted_at")}

    # 1. Missing universal documents.
    for kind, (label_en, label_bn) in UNIVERSAL_KINDS.items():
        if kind not in present:
            findings.append(
                {
                    "code": "MISSING",
                    "severity": "critical",
                    "document_id": None,
                    "title_en": f"{label_en} not uploaded",
                    "title_bn": f"{label_bn} আপলোড করা হয়নি",
                    "evidence": {"kind": kind},
                }
            )

    # 1b. Document content / type verification
    for doc in documents:
        if doc.get("deleted_at") or doc.get("status") == "failed":
            continue
        kind = doc.get("kind")
        fields = {f.get("field_key"): f.get("value") for f in (doc.get("fields") or []) if f.get("value")}
        if kind == "passport" and not ("passport_no" in fields or "surname" in fields):
            findings.append(
                {
                    "code": "INVALID_DOCUMENT_TYPE",
                    "severity": "critical",
                    "document_id": doc["id"],
                    "title_en": "This document does not appear to be a valid passport",
                    "title_bn": "এই নথিটি বৈধ পাসপোর্ট বলে মনে হচ্ছে না",
                    "evidence": {"kind": kind, "reason": "No passport number or biographical names found on page"},
                }
            )
        elif kind == "bank_statement" and not ("balance" in fields or "currency" in fields):
            findings.append(
                {
                    "code": "INVALID_DOCUMENT_TYPE",
                    "severity": "critical",
                    "document_id": doc["id"],
                    "title_en": "This document does not appear to be a valid bank statement",
                    "title_bn": "এই নথিটি বৈধ ব্যাংক স্টেটমেন্ট বলে মনে হচ্ছে না",
                    "evidence": {"kind": kind, "reason": "No balance or currency figures found on page"},
                }
            )
        elif kind == "transcript" and not ("institution" in fields or "cgpa" in fields):
            findings.append(
                {
                    "code": "INVALID_DOCUMENT_TYPE",
                    "severity": "critical",
                    "document_id": doc["id"],
                    "title_en": "This document does not appear to be a valid academic transcript",
                    "title_bn": "এই নথিটি বৈধ একাডেমিক ট্রান্সক্রিপ্ট বলে মনে হচ্ছে না",
                    "evidence": {"kind": kind, "reason": "No institution or GPA/CGPA found on page"},
                }
            )

    # 2. Expiry, including the passport validity margin.
    travel = _parse_date((target or {}).get("intake_start")) or (today + timedelta(days=270))
    for doc in documents:
        expires = _parse_date(doc.get("expires_on"))
        if not expires:
            continue
        days_left = (expires - today).days

        if doc["kind"] == "passport":
            required_until = travel + timedelta(days=PASSPORT_VALIDITY_MARGIN_DAYS)
            if expires < required_until:
                findings.append(
                    {
                        "code": "PASSPORT_MARGIN",
                        "severity": "critical",
                        "document_id": doc["id"],
                        "title_en": "Passport expires too close to your travel date",
                        "title_bn": "ভ্রমণের তারিখের খুব কাছে পাসপোর্টের মেয়াদ শেষ",
                        "evidence": {
                            "expires_on": expires.isoformat(),
                            "required_until": required_until.isoformat(),
                            "margin_days": PASSPORT_VALIDITY_MARGIN_DAYS,
                        },
                    }
                )
        elif days_left < 0:
            findings.append(
                {
                    "code": "EXPIRED",
                    "severity": "critical",
                    "document_id": doc["id"],
                    "title_en": "Document has expired",
                    "title_bn": "নথির মেয়াদ শেষ হয়ে গেছে",
                    "evidence": {"expires_on": expires.isoformat()},
                }
            )
        elif days_left < 90:
            findings.append(
                {
                    "code": "EXPIRING",
                    "severity": "warning",
                    "document_id": doc["id"],
                    "title_en": "Document expires soon",
                    "title_bn": "নথির মেয়াদ শীঘ্রই শেষ হবে",
                    "evidence": {"expires_on": expires.isoformat(), "days_left": days_left},
                }
            )

    # 3. Cross-document field agreement, by hash. Nothing is decrypted here.
    by_field: dict[str, dict[str, list[int]]] = {}
    for doc in documents:
        for field in doc.get("fields", []) or []:
            key = field.get("field_key")
            if key not in CROSS_CHECK_FIELDS:
                continue
            digest = field.get("value_hash")
            if not digest:
                continue
            by_field.setdefault(key, {}).setdefault(digest, []).append(doc["id"])

    for field_key, groups in by_field.items():
        if len(groups) > 1:
            label_en, label_bn = CROSS_CHECK_FIELDS[field_key]
            findings.append(
                {
                    "code": "FIELD_MISMATCH",
                    "severity": "critical",
                    "document_id": next(iter(groups.values()))[0],
                    "title_en": f"{label_en} does not match across your documents",
                    "title_bn": f"আপনার নথিগুলোর মধ্যে {label_bn} মিলছে না",
                    "evidence": {
                        "field": field_key,
                        "distinct_values": len(groups),
                        "document_ids": [i for ids in groups.values() for i in ids],
                    },
                }
            )

    # 4. Solvency shortfall, when both numbers are known.
    required = (target or {}).get("solvency_required_bdt")
    shown = (profile or {}).get("declared_funds_bdt")
    if required and shown and int(shown) < int(required):
        findings.append(
            {
                "code": "AMOUNT_SHORT",
                "severity": "critical",
                "document_id": None,
                "title_en": "Bank balance is below the required amount",
                "title_bn": "ব্যাংক ব্যালেন্স প্রয়োজনীয় পরিমাণের চেয়ে কম",
                "evidence": {
                    "required_bdt": int(required),
                    "shown_bdt": int(shown),
                    "shortfall_bdt": int(required) - int(shown),
                },
            }
        )

    return findings


async def run_audit(
    *,
    documents: list[dict[str, Any]],
    profile: dict[str, Any] | None,
    target: dict[str, Any] | None,
    router: ModelRouter,
) -> list[dict[str, Any]]:
    """Audit a student's vault. Returns findings ready for audit_findings rows."""
    findings = _mechanical_findings(documents, profile, target)
    if not findings:
        return []

    summary = "\n".join(
        f"- code={f['code']} severity={f['severity']} title={f['title_en']} "
        f"evidence={f['evidence']}"
        for f in findings
    )

    try:
        explained = await structured(
            router,
            AgentCall(
                kind=TaskKind.AGENT_TOOL,
                system=SYSTEM,
                user=(
                    "Explain each finding and give one concrete action. "
                    "Return the same codes, in the same order.\n\n"
                    # The findings carry evidence strings built from fields the
                    # vision pass read out of uploaded documents, so the text is
                    # attacker-influenced even though the codes are ours.
                    + frame_untrusted(summary, label="FINDINGS", max_chars=8_000)
                ),
                schema=EXPLAIN_SCHEMA,
                # Findings reference the student's own documents.
                contains_user_documents=True,
            ),
        )
        by_code: dict[str, dict[str, Any]] = {}
        for item in explained.get("findings", []):
            by_code.setdefault(item.get("code", ""), item)
    except Exception as exc:  # noqa: BLE001
        # A failed explanation must not hide a real finding. Ship the mechanical
        # result with a neutral description rather than dropping it.
        log.warning("prohori explanation failed, returning mechanical findings: %s", exc)
        by_code = {}

    out: list[dict[str, Any]] = []
    for finding in findings:
        extra = by_code.get(finding["code"], {})
        out.append(
            {
                **finding,
                "detail_en": extra.get("detail_en") or finding["title_en"],
                "detail_bn": extra.get("detail_bn") or finding["title_bn"],
                "action_en": extra.get("action_en"),
                "action_bn": extra.get("action_bn"),
            }
        )
    return out
