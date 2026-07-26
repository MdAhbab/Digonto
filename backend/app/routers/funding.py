"""Funding Studio and Khoji. docs/api_contract.md section 9."""

from __future__ import annotations

from typing import Mapping

from fastapi import APIRouter, Depends, Query, status

from app.config import Settings, get_settings
from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs, get_router
from app.errors import ValidationProblem
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.models.common import Page
from app.models.funding import (
    BudgetOut,
    FeeCheckOut,
    FeeCheckRequest,
    FundingSourceCreate,
    FundingSourceOut,
    ScholarshipDetail,
    ScholarshipOut,
    SortKey,
    SortOrder,
)
from app.repositories.budget_repo import BudgetRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.target_repo import TargetRepo
from app.services.funding_service import FundingService

router = APIRouter(
    prefix="/funding",
    tags=["funding"],
    dependencies=[Depends(RateLimit("funding_default", limit=120, window_s=60))],
)


def get_funding_service(
    dbs: Databases = Depends(get_dbs),
    bus: EventBus = Depends(get_bus),
    model_router: ModelRouter = Depends(get_router),
    settings: Settings = Depends(get_settings),
) -> FundingService:
    return FundingService(
        ScholarshipRepo(dbs.app), BudgetRepo(dbs.app), ProfileRepo(dbs.app, dbs.events),
        TargetRepo(dbs.app), bus, model_router,
        documents=DocumentRepo(dbs.app), settings=settings,
    )


@router.get("/scholarships", response_model=Page[ScholarshipOut])
async def list_scholarships(
    sort: SortKey = Query(default="deadline"),
    order: SortOrder = Query(default="asc"),
    country: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> Page[ScholarshipOut]:
    rows, next_cursor = await funding.list_scholarships(
        user["id"], sort=sort, order=order, country=country, cursor=cursor
    )
    items = [ScholarshipOut(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.get("/scholarships/{scholarship_id}", response_model=ScholarshipDetail)
async def get_scholarship(
    scholarship_id: str,
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> ScholarshipDetail:
    result = await funding.get_scholarship(user["id"], scholarship_id)
    return ScholarshipDetail(**result)


@router.post("/rematch", response_model=Page[ScholarshipOut])
async def rematch(
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> Page[ScholarshipOut]:
    await funding.rematch(user["id"], user["public_id"])
    # `rematch` returns bare `funding_matches` rows (score/rank/eligible),
    # not the name/country/coverage/citation shape `ScholarshipOut` needs;
    # `list_scholarships` is where that join lives, so re-fetch through it
    # rather than duplicate the shaping here.
    rows, next_cursor = await funding.list_scholarships(
        user["id"], sort="deadline", order="asc", country=None, cursor=None
    )
    items = [ScholarshipOut(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.get("/sources", response_model=Page[FundingSourceOut])
async def list_sources(
    target_id: str = Query(...),
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> Page[FundingSourceOut]:
    rows = await funding.list_sources(user["id"], target_id)
    items = [FundingSourceOut(**r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.post("/sources", status_code=status.HTTP_201_CREATED, response_model=None)
async def add_source(
    body: FundingSourceCreate,
    target_id: str = Query(...),
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> None:
    await funding.add_source(user["id"], target_id, body.kind, body.amount_bdt)


@router.delete("/sources/{kind}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def remove_source(
    kind: str,
    target_id: str = Query(...),
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> None:
    await funding.remove_source(user["id"], target_id, kind)


@router.get("/budget", response_model=BudgetOut)
async def get_budget(
    target_id: str = Query(...),
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> BudgetOut:
    result = await funding.get_budget(user["id"], target_id)
    return BudgetOut(**result)


@router.post("/fee-check", response_model=FeeCheckOut)
async def fee_check(
    body: FeeCheckRequest,
    user: Mapping = Depends(get_current_user),
    funding: FundingService = Depends(get_funding_service),
) -> FeeCheckOut:
    if body.quoted_bdt is None and body.document_id is None:
        raise ValidationProblem(
            detail_en="Provide a quoted amount, or upload the invoice as a document first.",
            detail_bn="একটি কোটেড পরিমাণ দিন, অথবা প্রথমে চালানটি নথি হিসেবে আপলোড করুন।",
        )
    result = await funding.fee_check(
        user["id"],
        consultancy=body.consultancy,
        quoted_bdt=body.quoted_bdt,
        country=body.country,
        document_id=body.document_id,
    )
    return FeeCheckOut(**result)
