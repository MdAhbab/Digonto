"""Vault and Prohori models.

`DocumentOut` matches the frontend `Doc` interface exactly, camelCase for
`nameEn`/`nameBn`/`expiresDays`/`findingEn`/`findingBn`/`actionEn`/`actionBn`.
Audit models are snake_case: they are new surface, not a mock replacement.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SnapshotCitation

DocumentKind = Literal[
    "passport", "transcript", "certificate", "bank_statement", "solvency_letter",
    "english_test", "sop", "recommendation", "offer_letter", "visa_refusal",
    "consultancy_contract", "photo", "other",
]
DocumentStatus = Literal["uploaded", "scanning", "extracted", "failed", "quarantined"]
Severity = Literal["ok", "warn", "error"]
FindingSeverity = Literal["critical", "warning", "info"]
AuditStatus = Literal["queued", "running", "complete", "failed"]


class DocumentOut(BaseModel):
    """The frontend `Doc` interface, verbatim."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: DocumentKind
    name_en: str = Field(alias="nameEn")
    name_bn: str = Field(alias="nameBn")
    count: int
    expires_days: int | None = Field(default=None, alias="expiresDays")
    severity: Severity
    finding_en: str = Field(alias="findingEn")
    finding_bn: str = Field(alias="findingBn")
    action_en: str = Field(alias="actionEn")
    action_bn: str = Field(alias="actionBn")
    status: DocumentStatus
    uploaded_at: str


class DocumentDetail(BaseModel):
    """`GET /vault/documents/{id}` — the full metadata record, never the
    file content and never a `document_fields.value_enc` value.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: DocumentKind
    original_name: str
    mime_type: str
    byte_size: int
    page_count: int | None = None
    issued_on: str | None = None
    expires_on: str | None = None
    status: DocumentStatus
    uploaded_at: str


class DocumentDownloadOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str
    expires_at: str


class AuditFindingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str | None = None
    code: str
    severity: FindingSeverity
    title_en: str
    title_bn: str
    detail_en: str
    detail_bn: str
    evidence: dict | None = None
    action_en: str | None = None
    action_bn: str | None = None
    citation: SnapshotCitation | None = None


class AuditOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: AuditStatus
    started_at: str
    finished_at: str | None = None
    findings: list[AuditFindingOut] = Field(default_factory=list)


class AuditStartResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    audit_id: str


# --- Bicharok, Lekhok, Dalil (api_contract.md section 11) -------------------
# These three agents are document-and-text adjacent, so their models live
# here rather than in a module of their own; the model package list in this
# build's brief names twelve fixed modules and none of them is "agents".


class RejectionCaseCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str


class RejectionGroundOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    code: str | None = None
    quoted_text: str
    meaning_en: str
    meaning_bn: str
    remedy_en: str
    remedy_bn: str
    remediable: Literal["yes", "partly", "no"]
    citation: SnapshotCitation | None = None
    linked_step_key: str | None = None


class RejectionCaseOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str | None = None
    country_code: str | None = None
    visa_type: str | None = None
    refused_on: str | None = None
    summary_en: str | None = None
    summary_bn: str | None = None
    reapply_ready_at: str | None = None
    grounds: list[RejectionGroundOut] = Field(default_factory=list)
    created_at: str


class ApplyToPlanResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    applied_step_keys: list[str] = Field(default_factory=list)


class StatementCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["sop", "motivation", "cover", "study_plan"]
    body: str
    target_id: str | None = None


class StatementCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    statement_id: str


class StatementFindingOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    severity: FindingSeverity
    kind: Literal["contradiction", "unsupported", "vague", "cliche", "missing"]
    excerpt: str
    detail_en: str
    detail_bn: str
    conflicts_document_id: str | None = None
    suggestion_en: str | None = None
    suggestion_bn: str | None = None


class ContractCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str


class ContractClauseOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    quoted_text: str
    category: Literal[
        "fee", "refund", "document_retention", "exclusivity", "liability", "guarantee", "other"
    ]
    risk: Literal["low", "medium", "high"]
    why_en: str
    why_bn: str
    fair_alternative_en: str | None = None
    fair_alternative_bn: str | None = None


class ContractOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    document_id: str
    consultancy: str | None = None
    risk_overall: Literal["low", "medium", "high"] | None = None
    clauses: list[ContractClauseOut] = Field(default_factory=list)
    analysed_at: str


class AgentAcceptedResponse(BaseModel):
    """`202` body shared by the three async agent-triggering POSTs."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: Literal["queued"] = "queued"
