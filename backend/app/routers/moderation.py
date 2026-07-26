"""The moderator console. docs/api_contract.md section 11a.

`require_role("moderator")` is applied exactly once, at the `APIRouter`
level, per the contract's own instruction ("enforced by a dependency on the
router, not by a check inside each handler") and requirement 5 of this
build. `require_role` is hierarchical (student < moderator < admin, see
app/deps.py), so an admin passes this gate too, matching "role in
(moderator, admin)".

Never selects or returns document contents or `document_fields` values:
every model here (app/models/moderation.py) is already shaped to omit them,
and this router only ever forwards what `ModerationService` returns, which
in turn only ever calls `ModerationRepo`, which the module itself documents
as never selecting those columns. Nothing in this file reaches into the
vault decryption path.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query, status

from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs, require_role
from app.events.bus import EventBus
from app.models.common import Page
from app.models.moderation import (
    AddPortalFromRefusalRequest,
    AdapterOut,
    AdapterRollbackRequest,
    ApproveChangeRequest,
    BanRequest,
    ChangeReviewItem,
    CorrectAnswerRequest,
    DiscardChangeRequest,
    ModHealthOut,
    ModOverviewOut,
    ModPortalOut,
    ModScholarshipOut,
    ModUserDetail,
    ModUserListItem,
    ModAnswerItem,
    ModerationActionOut,
    PortalCreateRequest,
    PortalPatchRequest,
    ReclassifyChangeRequest,
    ReinstateRequest,
    RefusalClusterOut,
    SuspendRequest,
    UserReportOut,
    VerifyScholarshipRequest,
)
from app.repositories.answer_repo import AnswerRepo
from app.repositories.moderation_repo import ModerationRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.repositories.user_repo import UserRepo
from app.services.moderation_service import ModerationService

router = APIRouter(
    prefix="/mod",
    tags=["moderation"],
    dependencies=[
        Depends(require_role("moderator")),
        Depends(RateLimit("mod_default", limit=120, window_s=60)),
    ],
)


def get_moderation_service(dbs: Databases = Depends(get_dbs), bus: EventBus = Depends(get_bus)) -> ModerationService:
    return ModerationService(
        ModerationRepo(dbs.app, dbs.events, dbs.learn), SnapshotRepo(dbs.app), AnswerRepo(dbs.app),
        PortalRepo(dbs.app), ScholarshipRepo(dbs.app), UserRepo(dbs.app), bus,
    )


# --- change review queue --------------------------------------------------


@router.get("/changes", response_model=Page[ChangeReviewItem])
async def list_pending_changes(
    status_: str = Query(default="pending", alias="status"),
    cursor: str | None = Query(default=None),
    mod: ModerationService = Depends(get_moderation_service),
) -> Page[ChangeReviewItem]:
    # `status` is accepted for contract completeness; `ModerationService.
    # list_pending_changes` takes no such parameter because
    # `SnapshotRepo.list_pending_review` (its one data source) only ever
    # queries the pending queue, so there is no other status to switch on
    # yet.
    rows, next_cursor = await mod.list_pending_changes(cursor)
    items = [ChangeReviewItem(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/changes/{change_id}/approve", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def approve_change(
    change_id: str,
    body: ApproveChangeRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.approve_change(user["id"], change_id, body.category, body.notify)


@router.post("/changes/{change_id}/reclassify", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def reclassify_change(
    change_id: str,
    body: ReclassifyChangeRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.reclassify_change(user["id"], change_id, body.category, body.reason)


@router.post("/changes/{change_id}/discard", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def discard_change(
    change_id: str,
    body: DiscardChangeRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.discard_change(user["id"], change_id, body.reason)


# --- answer review and refusal triage ------------------------------------


@router.get("/answers", response_model=Page[ModAnswerItem])
async def list_answers_for_review(
    filter: str = Query(...),  # noqa: A002 - matches the contract's own query name
    cursor: str | None = Query(default=None),
    mod: ModerationService = Depends(get_moderation_service),
) -> Page[ModAnswerItem]:
    rows, next_cursor = await mod.list_answers_for_review(filter, cursor)
    items = [
        ModAnswerItem(
            id=r["id"], question_text=r["question_text"], answer_en=r.get("answer_en"),
            answer_bn=r.get("answer_bn"), confidence=r.get("confidence"), is_refusal=r["is_refusal"],
            rating=r.get("rating"), reviewer_verified=r["reviewer_verified"], created_at=r["created_at"],
        )
        for r in rows
    ]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/answers/{answer_id}/verify", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def verify_answer(
    answer_id: str,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.verify_answer(user["id"], answer_id)


@router.post("/answers/{answer_id}/correct", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def correct_answer(
    answer_id: str,
    body: CorrectAnswerRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.correct_answer(user["id"], answer_id, body.correction_bn, body.correction_en, body.note)


@router.get("/refusals", response_model=Page[RefusalClusterOut])
async def list_refusal_clusters(
    cursor: str | None = Query(default=None),
    mod: ModerationService = Depends(get_moderation_service),
) -> Page[RefusalClusterOut]:
    rows, next_cursor = await mod.list_refusal_clusters(cursor)
    items = [RefusalClusterOut(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/refusals/{cluster_id}/add-portal", response_model=ModPortalOut, status_code=status.HTTP_201_CREATED)
async def add_portal_from_refusal(
    cluster_id: str,
    body: AddPortalFromRefusalRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> ModPortalOut:
    portal = await mod.add_portal_from_refusal(user["id"], cluster_id, body.url, body.kind, body.country)
    return _mod_portal_out(portal)


# --- source and funding verification --------------------------------------


def _mod_portal_out(row: dict[str, Any]) -> ModPortalOut:
    return ModPortalOut(
        id=row["public_id"], url=row["url"], kind=row["kind"], country_code=row.get("country_code"),
        label=row["label"], parser_key=row["parser_key"], crawl_cron=row["crawl_cron"],
        enabled=bool(row["enabled"]), last_fetch_at=row.get("last_fetch_at"),
        last_status=row.get("last_status"), consecutive_failures=row["consecutive_failures"],
    )


@router.get("/portals", response_model=Page[ModPortalOut])
async def list_portals(mod: ModerationService = Depends(get_moderation_service)) -> Page[ModPortalOut]:
    rows = await mod.list_portals()
    items = [_mod_portal_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.post("/portals", response_model=ModPortalOut, status_code=status.HTTP_201_CREATED)
async def create_portal(
    body: PortalCreateRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> ModPortalOut:
    portal = await mod.create_portal(
        user["id"], url=body.url, kind=body.kind, country_code=body.country_code,
        label=body.label, parser_key=body.parser_key, crawl_cron=body.crawl_cron,
    )
    return _mod_portal_out(portal)


@router.patch("/portals/{portal_id}", response_model=ModPortalOut)
async def patch_portal(
    portal_id: str,
    body: PortalPatchRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> ModPortalOut:
    portal = await mod.patch_portal(user["id"], portal_id, body.model_dump(exclude_unset=True))
    return _mod_portal_out(portal)


@router.get("/scholarships", response_model=Page[ModScholarshipOut])
async def list_unverified_scholarships(
    verified: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    mod: ModerationService = Depends(get_moderation_service),
) -> Page[ModScholarshipOut]:
    rows, next_cursor = await mod.list_unverified_scholarships(cursor)
    items = [
        ModScholarshipOut(
            id=r["public_id"], name=r["name"], provider=r["provider"], country_code=r.get("country_code"),
            verified=bool(r["verified"]), active=bool(r["active"]), url=r["url"], updated_at=r["updated_at"],
        )
        for r in rows
    ]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/scholarships/{scholarship_id}/verify", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def verify_scholarship(
    scholarship_id: str,
    body: VerifyScholarshipRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.verify_scholarship(user["id"], scholarship_id, body.verified, body.note)


# --- people ---------------------------------------------------------------


@router.get("/users", response_model=Page[ModUserListItem])
async def list_users(
    status_: str | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    mod: ModerationService = Depends(get_moderation_service),
) -> Page[ModUserListItem]:
    rows, next_cursor = await mod.list_users(status=status_, q=q, cursor=cursor)
    items = [
        ModUserListItem(
            id=r["public_id"], email=r["email"], display_name=r["display_name"], role=r["role"],
            status=r["status"], created_at=r["created_at"], last_seen_at=r.get("last_seen_at"),
            question_count=r["question_count"], document_count=r["document_count"],
            flagged=bool(r["flagged"]),
        )
        for r in rows
    ]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.get("/users/{user_id}", response_model=ModUserDetail)
async def get_user(
    user_id: str,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> ModUserDetail:
    detail = await mod.get_user(user["id"], user_id)
    history = [
        ModerationActionOut(
            id=h["public_id"], action=h["action"], subject_type=h["subject_type"],
            subject_id=h["subject_id"], reason_en=h.get("reason_en"), reason_bn=h.get("reason_bn"),
            created_at=h["created_at"],
        )
        for h in detail["moderation_history"]
    ]
    return ModUserDetail(
        id=detail["public_id"], email=detail["email"], display_name=detail["display_name"],
        role=detail["role"], status=detail["status"], status_reason_en=detail.get("status_reason_en"),
        status_reason_bn=detail.get("status_reason_bn"), created_at=detail["created_at"],
        last_seen_at=detail.get("last_seen_at"), question_count=detail["question_count"],
        document_count=detail["document_count"], plan_step_count=detail["plan_step_count"],
        report_count=detail["report_count"], moderation_history=history,
    )


@router.post("/users/{user_id}/suspend", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def suspend_user(
    user_id: str,
    body: SuspendRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.suspend_user(user["id"], user_id, body.reason_en, body.reason_bn, body.until)


@router.post("/users/{user_id}/ban", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def ban_user(
    user_id: str,
    body: BanRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.ban_user(user["id"], user_id, body.reason_en, body.reason_bn)


@router.post("/users/{user_id}/reinstate", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def reinstate_user(
    user_id: str,
    body: ReinstateRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.reinstate_user(user["id"], user_id, body.note)


@router.get("/reports", response_model=Page[UserReportOut])
async def list_reports(mod: ModerationService = Depends(get_moderation_service)) -> Page[UserReportOut]:
    rows = await mod.list_reports()
    items = [
        UserReportOut(
            id=r["public_id"], subject_type=r["subject_type"], subject_id=r["subject_id"],
            category=r["category"], detail=r.get("detail"), status=r["status"], created_at=r["created_at"],
        )
        for r in rows
    ]
    return Page(items=items, next_cursor=None, total=len(items))


# --- model oversight -------------------------------------------------------


def _adapter_out(row: dict[str, Any]) -> AdapterOut:
    before = row.get("_before") or {}
    after = row.get("_after") or {}
    return AdapterOut(
        id=row["tag"], tag=row["tag"], base_model=row["base_model"], rank=row["rank"],
        sample_count=row["sample_count"], status=row["status"], trained_at=row["trained_at"],
        groundedness_before=before.get("groundedness"), groundedness_after=after.get("groundedness"),
        refusal_correctness_before=before.get("refusal_correctness"),
        refusal_correctness_after=after.get("refusal_correctness"),
        bangla_clarity_before=before.get("bangla_clarity"), bangla_clarity_after=after.get("bangla_clarity"),
    )


@router.get("/adapters", response_model=Page[AdapterOut])
async def list_adapters(mod: ModerationService = Depends(get_moderation_service)) -> Page[AdapterOut]:
    rows = await mod.list_adapters()
    items = [_adapter_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.post("/adapters/{adapter_tag}/promote", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def promote_adapter(
    adapter_tag: str,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.promote_adapter(user["id"], adapter_tag)


@router.post("/adapters/{adapter_tag}/rollback", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def rollback_adapter(
    adapter_tag: str,
    body: AdapterRollbackRequest,
    user: Mapping = Depends(get_current_user),
    mod: ModerationService = Depends(get_moderation_service),
) -> None:
    await mod.rollback_adapter(user["id"], adapter_tag, body.reason)


@router.get("/health", response_model=ModHealthOut)
async def get_health(mod: ModerationService = Depends(get_moderation_service)) -> ModHealthOut:
    result = await mod.get_health()
    return ModHealthOut(**result)


@router.get("/overview", response_model=ModOverviewOut)
async def get_overview(mod: ModerationService = Depends(get_moderation_service)) -> ModOverviewOut:
    result = await mod.get_overview()
    return ModOverviewOut(**result)
