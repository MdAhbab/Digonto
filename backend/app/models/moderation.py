"""Moderator console models: api_contract.md section 11a.

Every model here is shaped to guarantee the console's core promise: a
moderator never sees document contents, extracted field values, or a
student's full question history. Where a table would otherwise expose that
(`documents`, `document_fields`, `questions`), the corresponding Out model
below simply has no field for it, and `ModerationRepo` (app/repositories)
never selects those columns in the first place.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ChangeCategory = Literal["deadline", "fee", "document_requirement", "policy", "cosmetic"]
ReportStatus = Literal["open", "reviewing", "resolved", "dismissed"]
ReportCategory = Literal["wrong_information", "dishonesty_request", "abuse", "privacy", "other"]
AdapterStatus = Literal["training", "candidate", "promoted", "rolled_back", "failed"]
UserStatus = Literal["active", "suspended", "banned"]


# --- Change review queue ------------------------------------------------


class ChangeReviewItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    portal_id: str
    portal_label: str
    change_type: Literal["added", "removed", "modified"]
    old_text: str | None = None
    new_text: str | None = None
    from_snapshot_id: str
    to_snapshot_id: str
    proposed_category: ChangeCategory | None = None
    confidence: float | None = None
    created_at: str


class ApproveChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: ChangeCategory
    notify: bool = True


class ReclassifyChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    category: ChangeCategory
    reason: str


class DiscardChangeRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason: str


# --- Answer review and refusal triage -----------------------------------


class ModAnswerItem(BaseModel):
    """Question and answer text appear here deliberately: these are
    escalated items only (downvoted, escalated, or low confidence), which is
    exactly the exception the contract carves out ("Question and answer text
    on escalated items only").
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    question_text: str
    answer_en: str | None = None
    answer_bn: str | None = None
    confidence: float | None = None
    is_refusal: bool
    rating: Literal["up", "down", "unclear"] | None = None
    reviewer_verified: bool
    created_at: str


class CorrectAnswerRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    correction_bn: str
    correction_en: str
    note: str | None = None


class RefusalClusterOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    cluster_id: str
    sample_question: str
    count: int
    country_filter: str | None = None
    last_asked_at: str


class AddPortalFromRefusalRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str
    kind: Literal["embassy", "university", "scholarship", "government", "bank"]
    country: str | None = None


# --- Source and funding verification ------------------------------------


class ModPortalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    url: str
    kind: Literal["embassy", "university", "scholarship", "government", "bank"]
    country_code: str | None = None
    label: str
    parser_key: str
    crawl_cron: str
    enabled: bool
    last_fetch_at: str | None = None
    last_status: str | None = None
    consecutive_failures: int


class PortalCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    url: str
    kind: Literal["embassy", "university", "scholarship", "government", "bank"]
    country_code: str | None = None
    label: str
    parser_key: str = "generic"
    crawl_cron: str = "0 */6 * * *"


class PortalPatchRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    enabled: bool | None = None
    crawl_cron: str | None = None
    parser_key: str | None = None
    label: str | None = None


class ModScholarshipOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    provider: str
    country_code: str | None = None
    verified: bool
    active: bool
    url: str
    updated_at: str


class VerifyScholarshipRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    verified: bool
    note: str | None = None


# --- People ---------------------------------------------------------------


class ModUserListItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    display_name: str
    role: str
    status: UserStatus
    created_at: str
    last_seen_at: str | None = None
    question_count: int
    document_count: int
    flagged: bool


class ModUserDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    email: str
    display_name: str
    role: str
    status: UserStatus
    status_reason_en: str | None = None
    status_reason_bn: str | None = None
    created_at: str
    last_seen_at: str | None = None
    question_count: int
    document_count: int
    plan_step_count: int
    report_count: int
    moderation_history: list["ModerationActionOut"] = Field(default_factory=list)


class SuspendRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason_en: str
    reason_bn: str
    until: str


class BanRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason_en: str
    reason_bn: str


class ReinstateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    note: str | None = None


class ModerationActionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    action: str
    subject_type: str
    subject_id: str
    reason_en: str | None = None
    reason_bn: str | None = None
    created_at: str


class UserReportOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    subject_type: Literal["answer", "user", "scholarship", "content"]
    subject_id: str
    category: ReportCategory
    detail: str | None = None
    status: ReportStatus
    created_at: str


# --- Model oversight --------------------------------------------------------


class AdapterOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    tag: str
    base_model: str
    rank: int
    sample_count: int
    status: AdapterStatus
    trained_at: str
    groundedness_before: float | None = None
    groundedness_after: float | None = None
    refusal_correctness_before: float | None = None
    refusal_correctness_after: float | None = None
    bangla_clarity_before: float | None = None
    bangla_clarity_after: float | None = None


class AdapterRollbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    reason: str


class ModHealthOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pending_changes: int
    crawl_failures_48h: int
    dead_letters: int
    model_latency_p50_ms: int | None = None
    model_latency_p95_ms: int | None = None
    queue_depth_agent: int


class ModOverviewOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    pending_changes: int
    escalated_answers: int
    unverified_scholarships: int
    silent_portals: int
    dead_letters: int
    adapters_awaiting_promotion: int
    new_users_today: int
