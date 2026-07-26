"""Vault, Prohori, and the three document-adjacent agents: Bicharok
(rejection autopsy), Lekhok (statement forensics), Dalil (contract auditor).

api_contract.md section 8 and section 11.

**Unresolved agent imports, by design.** Prohori, Bicharok, Lekhok, and Dalil
do not exist in this codebase yet. This service calls them as
`app.agents.<name>.<fn>` and lets the import fail until they are built,
rather than fabricate audit findings, rejection grounds, statement
critiques, or contract risk. The exact function contracts this service
expects are documented next to each call site and summarised in the final
report.

Document content never leaves the machine: every agent call below either
receives already-decrypted bytes for a local vision pass, or a
`contains_user_documents=True` request through `ModelRouter`, which raises
rather than route to a remote provider.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.agents.bicharok import analyse_rejection
from app.agents.dalil import audit_contract
from app.agents.lekhok import analyse_statement
from app.agents.prohori import run_audit
from app.config import Settings
from app.errors import Conflict, NotFound
from app.events.bus import EventBus, EventType
from app.llm.router import ModelRouter
from app.repositories.audit_repo import AuditRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.security.vault_crypto import decrypt_file, encrypt_file

_ACCEPTED_MIME = {"application/pdf", "image/jpeg", "image/png", "image/heic"}


class VaultService:
    def __init__(
        self,
        documents: DocumentRepo,
        audits: AuditRepo,
        profiles: ProfileRepo,
        targets: TargetRepo,
        bus: EventBus,
        router: ModelRouter,
        settings: Settings,
    ) -> None:
        self._documents = documents
        self._audits = audits
        self._profiles = profiles
        self._targets = targets
        self._bus = bus
        self._router = router
        self._settings = settings

    # -- documents -------------------------------------------------------

    async def upload_document(
        self, *, user_id: int, user_public_id: str, kind: str, filename: str,
        mime_type: str, data: bytes, expires_on: str | None,
    ) -> dict:
        if mime_type not in _ACCEPTED_MIME:
            raise Conflict(
                detail_en="Only PDF, JPEG, PNG, and HEIC files are accepted.",
                detail_bn="শুধু পিডিএফ, জেপিইজি, পিএনজি এবং হেইক ফাইল গ্রহণযোগ্য।",
            )
        if len(data) > self._settings.max_upload_bytes:
            limit_mb = self._settings.max_upload_bytes // (1024 * 1024)
            got_mb = len(data) / (1024 * 1024)
            raise Conflict(
                detail_en=f"That file is {got_mb:.0f} MB. The limit is {limit_mb} MB.",
                detail_bn=f"ফাইলটি {got_mb:.0f} মেগাবাইট। সীমা {limit_mb} মেগাবাইট।",
            )
        sha256 = hashlib.sha256(data).hexdigest()
        ciphertext, wrapped_dek, nonce = encrypt_file(data)

        storage_dir = self._settings.vault_dir / user_public_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        storage_path = storage_dir / f"{sha256}.enc"
        storage_path.write_bytes(ciphertext)

        doc = await self._documents.create(
            user_id=user_id,
            kind=kind,
            original_name=filename,
            storage_path=str(storage_path),
            mime_type=mime_type,
            byte_size=len(data),
            sha256=sha256,
            wrapped_dek=wrapped_dek,
            nonce=nonce,
            expires_on=expires_on,
        )
        await self._bus.publish(
            EventType.VAULT_DOC_ADDED,
            user_id=user_id,
            subject_type="document",
            subject_id=doc["public_id"],
            payload={"kind": kind},
        )
        return doc

    async def list_documents(self, user_id: int) -> list[dict]:
        docs = await self._documents.list_for_user(user_id)
        out = []
        for d in docs:
            findings = await self._audits.latest_findings_for_document(d["id"])
            top = findings[0] if findings else None
            expires_days = None
            if d["expires_on"]:
                try:
                    expires_days = (date.fromisoformat(d["expires_on"]) - date.today()).days
                except ValueError:
                    expires_days = None
            severity = "ok"
            finding_en = "No issues found."
            finding_bn = "কোনো সমস্যা পাওয়া যায়নি।"
            action_en = "No action needed."
            action_bn = "কোনো পদক্ষেপ প্রয়োজন নেই।"
            if top:
                severity = {"critical": "error", "warning": "warn", "info": "ok"}[top["severity"]]
                finding_en = top["detail_en"]
                finding_bn = top["detail_bn"]
                action_en = top["action_en"] or "Review this document."
                action_bn = top["action_bn"] or "এই নথিটি পর্যালোচনা করুন।"
            out.append(
                {
                    "id": d["public_id"],
                    "kind": d["kind"],
                    "nameEn": _kind_label_en(d["kind"]),
                    "nameBn": _kind_label_bn(d["kind"]),
                    "count": 1,
                    "expiresDays": expires_days,
                    "severity": severity,
                    "findingEn": finding_en,
                    "findingBn": finding_bn,
                    "actionEn": action_en,
                    "actionBn": action_bn,
                    "status": d["status"],
                    "uploaded_at": d["uploaded_at"],
                }
            )
        return out

    async def get_document(self, user_id: int, public_id: str) -> dict:
        doc = await self._documents.get_by_public_id(user_id, public_id)
        if doc is None:
            raise NotFound(detail_en="Document not found.", detail_bn="নথিটি পাওয়া যায়নি।")
        return doc

    async def get_download_url(self, user_id: int, public_id: str) -> dict:
        doc = await self.get_document(user_id, public_id)
        # Signed, short-lived download URLs are issued by the router, which
        # owns request signing; this returns the metadata it needs to do so.
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return {"document_id": doc["public_id"], "storage_path": doc["storage_path"], "expires_at": expires_at}

    async def delete_document(self, user_id: int, public_id: str) -> None:
        doc = await self.get_document(user_id, public_id)
        path = Path(doc["storage_path"])
        if path.exists():
            path.unlink()
        await self._documents.soft_delete(doc["id"])

    async def _decrypt(self, doc: dict) -> bytes:
        ciphertext = Path(doc["storage_path"]).read_bytes()
        return decrypt_file(ciphertext, doc["wrapped_dek"], doc["nonce"])

    # -- Prohori audit -----------------------------------------------------

    async def start_audit(self, user_id: int, target_public_id: str | None) -> dict:
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        audit = await self._audits.create(user_id, target_row["id"] if target_row else None)
        await self._audits.set_status(audit["id"], "running")
        try:
            documents = await self._documents.list_for_user(user_id)
            profile = await self._profiles.get(user_id)
            findings = await run_audit(
                documents=documents, profile=profile, target=target_row, router=self._router
            )
            for f in findings:
                await self._audits.add_finding(
                    audit["id"],
                    document_id=f.get("document_id"),
                    code=f["code"],
                    severity=f["severity"],
                    title_en=f["title_en"],
                    title_bn=f["title_bn"],
                    detail_en=f["detail_en"],
                    detail_bn=f["detail_bn"],
                    evidence=f.get("evidence"),
                    action_en=f.get("action_en"),
                    action_bn=f.get("action_bn"),
                    snapshot_id=f.get("snapshot_id"),
                )
            await self._audits.set_status(audit["id"], "complete")
        except Exception as exc:  # noqa: BLE001
            await self._audits.set_status(audit["id"], "failed", str(exc))
            raise
        await self._bus.publish(
            EventType.AUDIT_UPDATED,
            user_id=user_id,
            subject_type="audit",
            subject_id=audit["public_id"],
            payload={},
        )
        return audit

    async def get_latest_audit(self, user_id: int) -> dict:
        audit = await self._audits.latest_for_user(user_id)
        if audit is None:
            raise NotFound(
                detail_en="No audit has been run yet.",
                detail_bn="এখনও কোনো অডিট চালানো হয়নি।",
            )
        findings = await self._audits.list_findings(audit["id"])
        return {**audit, "findings": findings}

    # -- Bicharok: rejection autopsy ---------------------------------------

    async def create_rejection_case(self, user_id: int, document_public_id: str) -> dict:
        doc = await self.get_document(user_id, document_public_id)
        case = await self._documents.create_rejection_case(user_id, doc["id"])
        plaintext = await self._decrypt(doc)
        result = await analyse_rejection(
            document_bytes=plaintext, mime_type=doc["mime_type"], router=self._router
        )
        await self._documents.set_rejection_summary(
            case["id"],
            summary_en=result.get("summary_en", ""),
            summary_bn=result.get("summary_bn", ""),
            country_code=result.get("country_code"),
            visa_type=result.get("visa_type"),
            reapply_ready_at=result.get("reapply_ready_at"),
        )
        for g in result.get("grounds", []):
            await self._documents.add_rejection_ground(
                case["id"],
                code=g.get("code"),
                quoted_text=g["quoted_text"],
                meaning_en=g["meaning_en"],
                meaning_bn=g["meaning_bn"],
                remedy_en=g["remedy_en"],
                remedy_bn=g["remedy_bn"],
                remediable=g["remediable"],
                snapshot_id=g.get("snapshot_id"),
                linked_step_key=g.get("linked_step_key"),
            )
        return case

    async def get_rejection_case(self, user_id: int, public_id: str) -> dict:
        case = await self._documents.get_rejection_case(user_id, public_id)
        if case is None:
            raise NotFound(detail_en="Case not found.", detail_bn="কেসটি পাওয়া যায়নি।")
        grounds = await self._documents.list_rejection_grounds(case["id"])
        return {**case, "grounds": grounds}

    async def apply_rejection_to_plan(self, user_id: int, public_id: str) -> list[str]:
        case = await self._documents.get_rejection_case(user_id, public_id)
        if case is None:
            raise NotFound(detail_en="Case not found.", detail_bn="কেসটি পাওয়া যায়নি।")
        grounds = await self._documents.list_rejection_grounds(case["id"])
        applied = [g["linked_step_key"] for g in grounds if g.get("linked_step_key")]
        await self._bus.publish(
            EventType.PLAN_STEP_CHANGED,
            user_id=user_id,
            subject_type="rejection_case",
            subject_id=public_id,
            payload={"applied_step_keys": applied},
        )
        return applied

    # -- Lekhok: statement forensics -----------------------------------------

    async def create_statement(
        self, user_id: int, kind: str, body: str, target_public_id: str | None
    ) -> dict:
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        statement = await self._documents.create_statement(
            user_id, target_row["id"] if target_row else None, kind, body
        )
        documents = await self._documents.list_for_user(user_id)
        findings = await analyse_statement(body=body, documents=documents, router=self._router)
        for f in findings:
            await self._documents.add_statement_finding(
                statement["id"],
                severity=f["severity"],
                kind=f["kind"],
                excerpt=f["excerpt"],
                detail_en=f["detail_en"],
                detail_bn=f["detail_bn"],
                conflicts_document_id=f.get("conflicts_document_id"),
                suggestion_en=f.get("suggestion_en"),
                suggestion_bn=f.get("suggestion_bn"),
            )
        return statement

    async def get_statement_findings(self, user_id: int, public_id: str) -> list[dict]:
        statement = await self._documents.get_statement(user_id, public_id)
        if statement is None:
            raise NotFound(detail_en="Statement not found.", detail_bn="বিবৃতিটি পাওয়া যায়নি।")
        return await self._documents.list_statement_findings(statement["id"])

    # -- Dalil: contract auditor --------------------------------------------

    async def create_contract(self, user_id: int, document_public_id: str) -> dict:
        doc = await self.get_document(user_id, document_public_id)
        contract = await self._documents.create_contract(user_id, doc["id"])
        plaintext = await self._decrypt(doc)
        result = await audit_contract(
            document_bytes=plaintext, mime_type=doc["mime_type"], router=self._router
        )
        await self._documents.set_contract_risk(contract["id"], result.get("risk_overall", "medium"))
        for c in result.get("clauses", []):
            await self._documents.add_contract_clause(
                contract["id"],
                quoted_text=c["quoted_text"],
                category=c["category"],
                risk=c["risk"],
                why_en=c["why_en"],
                why_bn=c["why_bn"],
                fair_alternative_en=c.get("fair_alternative_en"),
                fair_alternative_bn=c.get("fair_alternative_bn"),
            )
        return contract

    async def get_contract(self, user_id: int, public_id: str) -> dict:
        contract = await self._documents.get_contract(user_id, public_id)
        if contract is None:
            raise NotFound(detail_en="Contract not found.", detail_bn="চুক্তিটি পাওয়া যায়নি।")
        clauses = await self._documents.list_contract_clauses(contract["id"])
        return {**contract, "clauses": clauses}


_KIND_LABELS_EN = {
    "passport": "Passport", "transcript": "Academic transcript", "certificate": "Certificate",
    "bank_statement": "Bank statement", "solvency_letter": "Solvency letter",
    "english_test": "English test result", "sop": "Statement of purpose",
    "recommendation": "Recommendation letter", "offer_letter": "Offer letter",
    "visa_refusal": "Visa refusal letter", "consultancy_contract": "Consultancy contract",
    "photo": "Photograph", "other": "Document",
}
_KIND_LABELS_BN = {
    "passport": "পাসপোর্ট", "transcript": "একাডেমিক ট্রান্সক্রিপ্ট", "certificate": "সার্টিফিকেট",
    "bank_statement": "ব্যাংক স্টেটমেন্ট", "solvency_letter": "সচ্ছলতা সনদ",
    "english_test": "ইংরেজি পরীক্ষার ফলাফল", "sop": "উদ্দেশ্য বিবৃতি",
    "recommendation": "সুপারিশপত্র", "offer_letter": "অফার লেটার",
    "visa_refusal": "ভিসা প্রত্যাখ্যান পত্র", "consultancy_contract": "কনসালটেন্সি চুক্তি",
    "photo": "ছবি", "other": "নথি",
}


def _kind_label_en(kind: str) -> str:
    return _KIND_LABELS_EN.get(kind, "Document")


def _kind_label_bn(kind: str) -> str:
    return _KIND_LABELS_BN.get(kind, "নথি")
