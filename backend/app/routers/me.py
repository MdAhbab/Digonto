"""Everything scoped to the current user that isn't Ask/Ledger/Planner/Vault/
Funding/Interview: profile, consents, export, deletion, targets, country
shortlist, notifications, and the multiplexed live stream.

docs/api_contract.md sections 4, 12, and 13.

Notifications and `/stream` have no dedicated service: the given service
list (Ask/Auth/Funding/Interview/Ledger/Moderation/Planner/Profile/Stats/
Vault) has no NotificationService, only `app.repositories.notification_repo.
NotificationRepo`, which already does exactly what these two endpoints need
(list, mark-read, and a durable-store replay keyed by event_id). Rather than
invent a service class that would just forward every call unchanged, this
router constructs that repository directly, the same way it constructs a
repository to hand to every other service below. Everything else here is a
plain call into ProfileService or AuthService.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs
from app.errors import NotFound
from app.events.bus import EventBus
from app.models.auth import ConsentsUpdate, DeleteAccountRequest, DeleteReceipt, ExportReceipt
from app.models.common import Page
from app.models.destination import DestinationOut
from app.models.profile import ProfileOut, ProfilePatch, TargetCreate, TargetOut
from app.models.user import User
from app.repositories.notification_repo import NotificationRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.routers._sse import SSE_HEADERS, format_sse, sse_comment
from app.routers.auth import get_auth_service
from app.routers.destinations import destination_from_row
from app.services.auth_service import AuthService
from app.services.profile_service import ProfileService

router = APIRouter(
    prefix="/me",
    tags=["me"],
    dependencies=[Depends(RateLimit("me_default", limit=120, window_s=60))],
)


def get_profile_service(dbs: Databases = Depends(get_dbs), bus: EventBus = Depends(get_bus)) -> ProfileService:
    return ProfileService(ProfileRepo(dbs.app, dbs.events), TargetRepo(dbs.app), bus)


# --- profile ------------------------------------------------------------


@router.get("/profile", response_model=ProfileOut)
async def get_profile(
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> ProfileOut:
    profile = await profiles.get_profile(user["id"])
    if profile is None:
        raise NotFound(
            detail_en="You have not set up a profile yet.",
            detail_bn="আপনি এখনও প্রোফাইল তৈরি করেননি।",
        )
    return ProfileOut(**profile)


@router.patch("/profile", response_model=ProfileOut)
async def patch_profile(
    body: ProfilePatch,
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> ProfileOut:
    fields = body.model_dump(exclude_unset=True)
    if "study_gap_years" not in fields and await profiles.get_profile(user["id"]) is None:
        # `profiles.study_gap_years` is `NOT NULL DEFAULT 0`
        # (docs/database.md section 3.2), but `ProfileRepo.upsert`'s INSERT
        # branch always names this column explicitly with whatever
        # `fields.get(...)` returns, including `None`, which overrides the
        # column's own SQL-level DEFAULT and raises an IntegrityError on the
        # very first PATCH for a new user unless something supplies 0.
        # Never injected for an *existing* profile: PATCH must only ever
        # touch fields the caller actually sent, and this would otherwise
        # silently reset a real value back to 0.
        fields["study_gap_years"] = 0
    updated = await profiles.update_profile(user["id"], user["public_id"], fields)
    return ProfileOut(**updated)


# --- consents, export, deletion (AuthService) ----------------------------


@router.put("/consents", response_model=User)
async def put_consents(
    body: ConsentsUpdate,
    user: Mapping = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    updated = await auth_service.update_consents(
        user["id"], improve_model=body.improve_model, usage_analytics=body.usage_analytics
    )
    return User(**updated)


@router.post("/consents/withdraw", status_code=status.HTTP_202_ACCEPTED, response_model=WithdrawReceipt)
async def withdraw_consent(
    user: Mapping = Depends(get_current_user),
    dbs: Databases = Depends(get_dbs),
    auth_service: AuthService = Depends(get_auth_service),
) -> WithdrawReceipt:
    """docs/api_contract.md section 13: withdrawing `improve_model` deletes
    the student's replay samples and flags every adapter that was trained on
    them, rather than only flipping a boolean. "You can withdraw consent" is
    meaningless if the data has already trained a model and stays there.

    202 rather than 200 because the flagged adapters still need a human to
    decide whether to retrain or roll back. The deletion itself is complete
    when this returns; the review is what is outstanding.
    """
    receipt = await auth_service.withdraw_learning_consent(
        user["id"], app_db=dbs.app, learn_db=dbs.learn
    )
    return WithdrawReceipt(**receipt)


@router.get("/export", response_model=ExportReceipt)
async def get_export(
    user: Mapping = Depends(get_current_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> ExportReceipt:
    receipt = await auth_service.request_export(user["id"])
    return ExportReceipt(**receipt)


@router.delete("", response_model=DeleteReceipt, status_code=status.HTTP_202_ACCEPTED)
async def delete_account(
    body: DeleteAccountRequest,
    user: Mapping = Depends(get_current_user),
    dbs: Databases = Depends(get_dbs),
    auth_service: AuthService = Depends(get_auth_service),
) -> DeleteReceipt:
    receipt = await auth_service.delete_account(
        user["id"], body.current_password, app_db=dbs.app, events_db=dbs.events, learn_db=dbs.learn
    )
    return DeleteReceipt(**receipt)


# --- destinations shortlist ------------------------------------------------
#
# GET /destinations (the country catalogue) lives in destinations.py; this is
# only the "which of those countries has this student starred" surface.


@router.get("/shortlist", response_model=Page[DestinationOut])
async def get_shortlist(
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> Page[DestinationOut]:
    # Same row shape as GET /destinations, filtered to the starred ones, so
    # both surfaces share destinations.destination_from_row rather than
    # keeping two mappings that can drift apart.
    rows = await profiles.list_destinations(user["id"])
    items = [destination_from_row(r) for r in rows if r.get("shortlisted")]
    return Page(items=items, next_cursor=None, total=len(items))


@router.put("/shortlist/{country_code}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def add_shortlist(
    country_code: str,
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> None:
    await profiles.add_shortlist(user["id"], user["public_id"], country_code)


@router.delete("/shortlist/{country_code}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_shortlist(
    country_code: str,
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> None:
    await profiles.remove_shortlist(user["id"], user["public_id"], country_code)


# --- targets --------------------------------------------------------------


def _target_out(row: dict[str, Any]) -> TargetOut:
    return TargetOut(
        id=row["public_id"],
        programme_id=row["programme_public_id"],
        programme_name=row["programme_name"],
        institution_name=row["institution_name"],
        country_code=row["country_code"],
        visa_type=row.get("visa_type"),
        rank=row["rank"],
        status=row["status"],
        created_at=row["created_at"],
    )


@router.get("/targets", response_model=Page[TargetOut])
async def list_targets(
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> Page[TargetOut]:
    rows = await profiles.list_targets(user["id"])
    items = [_target_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.post("/targets", response_model=TargetOut, status_code=status.HTTP_201_CREATED)
async def create_target(
    body: TargetCreate,
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> TargetOut:
    result = await profiles.create_target(user["id"], user["public_id"], body.programme_id, body.visa_type)
    targets = await profiles.list_targets(user["id"])
    match = next(t for t in targets if t["public_id"] == result["public_id"])
    return _target_out(match)


@router.delete("/targets/{target_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_target(
    target_id: str,
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> None:
    await profiles.delete_target(user["id"], target_id)


# --- notifications ----------------------------------------------------


class NotificationOut(BaseModel):
    """No dedicated model module exists for notifications (the twelve named
    model modules in the build brief do not include one); this is the
    smallest shape that matches `notifications` (docs/database.md section
    3.10) and section 12 of the contract."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    severity: str
    title_en: str
    title_bn: str
    body_en: str
    body_bn: str
    link_path: str | None = None
    read: bool
    created_at: str


def get_notification_repo(dbs: Databases = Depends(get_dbs)) -> NotificationRepo:
    return NotificationRepo(dbs.app, dbs.events)


def _notification_out(row: dict[str, Any]) -> NotificationOut:
    return NotificationOut(
        id=row["public_id"],
        kind=row["kind"],
        severity=row["severity"],
        title_en=row["title_en"],
        title_bn=row["title_bn"],
        body_en=row["body_en"],
        body_bn=row["body_bn"],
        link_path=row.get("link_path"),
        read=row.get("read_at") is not None,
        created_at=row["created_at"],
    )


# --- notifications and /stream live at the root, not under /me -------------
#
# docs/api_contract.md section 12 gives these bare paths ("/notifications",
# "/stream"), not "/me/notifications". A second, prefix-less router carries
# them; app/routers/__init__.py mounts both routers this module exports.

live_router = APIRouter(
    tags=["notifications"],
    dependencies=[Depends(RateLimit("me_default", limit=120, window_s=60))],
)


@live_router.get("/notifications", response_model=Page[NotificationOut])
async def list_notifications(
    unread: bool = Query(default=False),
    cursor: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    notifications: NotificationRepo = Depends(get_notification_repo),
) -> Page[NotificationOut]:
    rows, next_cursor = await notifications.list_for_user(
        user["id"], unread_only=unread, cursor=cursor
    )
    items = [_notification_out(r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@live_router.post(
    "/notifications/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def mark_notification_read(
    notification_id: str,
    user: Mapping = Depends(get_current_user),
    notifications: NotificationRepo = Depends(get_notification_repo),
) -> None:
    ok = await notifications.mark_read(user["id"], notification_id)
    if not ok:
        raise NotFound(
            detail_en="Notification not found.", detail_bn="বিজ্ঞপ্তিটি পাওয়া যায়নি।"
        )


# --- GET /stream ------------------------------------------------------------
#
# One authenticated SSE connection multiplexing notification/plan.changed/
# audit.updated/funding.updated/document.status events (section 12). Reads
# straight from events.db (the durable archive) via NotificationRepo, so a
# reconnect with Last-Event-ID replays exactly what was missed, and a client
# that never sends the header gets the last 50 events for context.
#
# events.db.events.type values are whatever app.events.bus.EventType members
# the services actually published (see the final report: several service
# call sites reference EventType members, e.g. FUNDING_UPDATED/AUDIT_UPDATED/
# PLAN_CHANGED/USER_SUSPENDED/USER_BANNED/USER_REINSTATED, that do not exist
# on the enum in app/events/bus.py, so those specific publishes raise before
# ever reaching Redis or events.db. This mapping is deliberately permissive:
# it maps every known-good type to a contract event name and falls back to
# the generic "notification" name for anything else, rather than silently
# dropping events once those gaps are fixed upstream.
_STREAM_EVENT_MAP: dict[str, str] = {
    "vault.doc.added": "document.status",
    "plan.step.changed": "plan.changed",
    "plan.changed": "plan.changed",
    "audit.updated": "audit.updated",
    "funding.updated": "funding.updated",
}
_HEARTBEAT_SECONDS = 15.0
_POLL_SECONDS = 1.5
# Lower than any real ULID, lexicographically: switches the replay query
# from "give me the last 50" (Last-Event-ID absent) into "give me everything
# after this id" (incremental) once the initial replay has been sent, even
# when that initial replay was empty.
_ULID_FLOOR = "0" * 26


def _stream_event_name(event_type: str) -> str:
    return _STREAM_EVENT_MAP.get(event_type, "notification")


@live_router.get("/stream")
async def stream_events(
    request: Request,
    user: Mapping = Depends(get_current_user),
    notifications: NotificationRepo = Depends(get_notification_repo),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    user_id = user["id"]

    async def gen():
        last_id = last_event_id
        last_heartbeat = time.monotonic()

        # Initial replay: everything since Last-Event-ID, or (if the header
        # is absent) the last 50 events for context, per
        # NotificationRepo.events_since's own documented dual mode.
        rows = await notifications.events_since(user_id, last_id)
        for row in rows:
            last_id = row["event_id"]
            yield format_sse(
                _stream_event_name(row["type"]),
                {
                    "type": row["type"],
                    "subject_type": row.get("subject_type"),
                    "subject_id": row.get("subject_id"),
                    **_safe_payload(row.get("payload")),
                },
                event_id=row["event_id"],
            )
            last_heartbeat = time.monotonic()

        if last_id is None:
            # Nothing ever happened for this user; switch into incremental
            # mode so the next poll asks "what's new" rather than
            # re-fetching "the last 50" (which would be an empty list
            # forever, but for the wrong reason to rely on implicitly).
            last_id = _ULID_FLOOR

        while True:
            if await request.is_disconnected():
                break
            new_rows = await notifications.events_since(user_id, last_id)
            if new_rows:
                for row in new_rows:
                    last_id = row["event_id"]
                    yield format_sse(
                        _stream_event_name(row["type"]),
                        {
                            "type": row["type"],
                            "subject_type": row.get("subject_type"),
                            "subject_id": row.get("subject_id"),
                            **_safe_payload(row.get("payload")),
                        },
                        event_id=row["event_id"],
                    )
                last_heartbeat = time.monotonic()
                continue
            await asyncio.sleep(_POLL_SECONDS)
            if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                yield sse_comment()
                last_heartbeat = time.monotonic()

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


def _safe_payload(payload: Any) -> dict[str, Any]:
    """`events.payload` is stored as a JSON string; NotificationRepo's
    `events_since` returns the raw row, so this router (not the repo) is
    responsible for decoding it for the wire."""
    import json

    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str) and payload:
        try:
            decoded = json.loads(payload)
            return decoded if isinstance(decoded, dict) else {"value": decoded}
        except ValueError:
            return {}
    return {}
