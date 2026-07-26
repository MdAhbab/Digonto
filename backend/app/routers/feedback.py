"""`POST /feedback` and the moderator's review queue.

Open to signed-out callers on purpose. The most useful feedback about a product
aimed at people who find official English hard to read comes from someone who could
not get far enough to make an account, and requiring a login would filter out exactly
that person.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.connection import Databases
from app.deps import RateLimit, get_dbs, get_optional_user, require_role
from app.errors import Conflict, NotFound
from app.models.common import Page
from app.repositories.feedback_repo import MAX_MESSAGE_CHARS, FeedbackRepo

router = APIRouter(prefix="/feedback", tags=["feedback"])

# Ceiling on submissions per identity per hour.
#
# Generous for a person: nobody has ten distinct things to report in an hour. Low
# enough that the form is not a way to write to the database at will.
MAX_PER_USER_PER_HOUR = 10

# Shared ceiling for everyone who is not signed in. See
# FeedbackRepo.count_recent_anonymous for why this is a single shared bucket rather
# than a per-person one: the per-person key would have to be an IP address, and
# storing an IP address in order to police a feedback form would collect more about
# the person than the feedback itself does.
MAX_ANONYMOUS_PER_HOUR = 60

FeedbackKind = str


class FeedbackIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: str = Field(default="other")
    message: str = Field(min_length=4, max_length=MAX_MESSAGE_CHARS)
    page: str | None = Field(default=None, max_length=200)
    lang: str = Field(default="bn")
    # Optional, and never pre-filled from the account. A signed-in student who leaves
    # this blank has chosen not to be contacted about this report.
    contact_email: str | None = Field(default=None, max_length=254)

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, v: str) -> str:
        allowed = {"bug", "confusing", "wrong_answer", "idea", "praise", "other"}
        return v if v in allowed else "other"

    @field_validator("lang")
    @classmethod
    def _known_lang(cls, v: str) -> str:
        return v if v in {"bn", "en"} else "bn"

    @field_validator("message")
    @classmethod
    def _not_only_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("message cannot be blank")
        return v.strip()


class FeedbackReceipt(BaseModel):
    """Deliberately thin. The submitter gets an acknowledgement and an id they can
    quote, not the stored row: echoing the record back would make the endpoint a way
    to confirm what was retained about a message somebody else sent."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    status: str
    created_at: str


class FeedbackOut(BaseModel):
    """Moderator view. Includes the author's public id when there is one."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: str
    message: str
    page: str | None = None
    lang: str
    contact_email: str | None = None
    user_id: str | None = None
    created_at: str
    reviewed_at: str | None = None
    disposition: str | None = None


class FeedbackReviewIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    disposition: str

    @field_validator("disposition")
    @classmethod
    def _known(cls, v: str) -> str:
        allowed = {"fixed", "planned", "declined", "duplicate", "answered"}
        if v not in allowed:
            raise ValueError(f"disposition must be one of {sorted(allowed)}")
        return v


def _out(row: Mapping[str, Any]) -> FeedbackOut:
    return FeedbackOut(
        id=row["public_id"],
        kind=row["kind"],
        message=row["message"],
        page=row["page"],
        lang=row["lang"],
        contact_email=row["contact_email"],
        user_id=row.get("user_public_id"),
        created_at=row["created_at"],
        reviewed_at=row["reviewed_at"],
        disposition=row["disposition"],
    )


@router.post(
    "",
    response_model=FeedbackReceipt,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(RateLimit("feedback", limit=30, window_s=3600))],
)
async def submit_feedback(
    body: FeedbackIn,
    user: Mapping | None = Depends(get_optional_user),
    dbs: Databases = Depends(get_dbs),
) -> FeedbackReceipt:
    """Record one piece of feedback. Works signed in or signed out.

    The Redis limiter above is the first line and covers bursts. The database count
    below is the second, and it exists because the limiter is per process lifetime of
    a Redis key while this reads what was actually stored, so a restart cannot reset
    somebody's allowance.
    """
    repo = FeedbackRepo(dbs.app)
    since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

    if user is not None:
        if await repo.count_recent_for_user(user["id"], since=since) >= MAX_PER_USER_PER_HOUR:
            raise Conflict(
                detail_en="You have sent several messages in the last hour. "
                "Please try again later.",
                detail_bn="গত এক ঘণ্টায় আপনি একাধিক বার্তা পাঠিয়েছেন। কিছুক্ষণ পরে আবার চেষ্টা করুন।",
            )
    elif await repo.count_recent_anonymous(since=since) >= MAX_ANONYMOUS_PER_HOUR:
        raise Conflict(
            detail_en="The feedback form is busy right now. Please try again later, "
            "or sign in to send it straight away.",
            detail_bn="ফিডব্যাক ফর্মটি এখন ব্যস্ত। পরে আবার চেষ্টা করুন, অথবা সাইন ইন করে পাঠান।",
        )

    row = await repo.create(
        user_id=user["id"] if user else None,
        kind=body.kind,
        message=body.message,
        page=body.page,
        lang=body.lang,
        contact_email=body.contact_email,
    )
    return FeedbackReceipt(id=row["public_id"], status="received", created_at=row["created_at"])


# --- moderator review queue -------------------------------------------------

mod_router = APIRouter(
    prefix="/mod/feedback",
    tags=["moderation"],
    dependencies=[Depends(require_role("moderator"))],
)


@mod_router.get("", response_model=Page[FeedbackOut])
async def list_feedback(
    unreviewed: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    dbs: Databases = Depends(get_dbs),
) -> Page[FeedbackOut]:
    repo = FeedbackRepo(dbs.app)
    rows = await repo.list_for_review(unreviewed_only=unreviewed, limit=limit, offset=offset)
    total = await repo.count_all(unreviewed_only=unreviewed)
    return Page[FeedbackOut](
        items=[_out(r) for r in rows],
        total=total,
        # `Page` carries a cursor, not the offset back: the caller already knows what
        # it asked for, and what it needs is whether there is more.
        next_cursor=str(offset + limit) if offset + limit < total else None,
    )


@mod_router.patch("/{feedback_id}", response_model=FeedbackOut)
async def review_feedback(
    feedback_id: str,
    body: FeedbackReviewIn,
    reviewer: Mapping = Depends(require_role("moderator")),
    dbs: Databases = Depends(get_dbs),
) -> FeedbackOut:
    repo = FeedbackRepo(dbs.app)
    row = await repo.mark_reviewed(
        feedback_id, reviewer_id=reviewer["id"], disposition=body.disposition
    )
    if row is None:
        raise NotFound(
            detail_en="No feedback with that id.",
            detail_bn="এই আইডিতে কোনো ফিডব্যাক পাওয়া যায়নি।",
        )
    return _out(row)
