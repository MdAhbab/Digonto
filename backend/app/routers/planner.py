"""Visa Timeline Reactor. docs/api_contract.md section 7."""

from __future__ import annotations

from typing import Mapping

from fastapi import APIRouter, Depends, Query, status

from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs
from app.events.bus import EventBus
from app.models.common import Page
from app.models.planner import PlanChangeOut, PlanTimelineOut, SimulateResponse
from app.repositories.budget_repo import BudgetRepo
from app.repositories.plan_repo import PlanRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.services.planner_service import PlannerService

router = APIRouter(
    prefix="/planner",
    tags=["planner"],
    dependencies=[Depends(RateLimit("planner_default", limit=120, window_s=60))],
)


def get_planner_service(dbs: Databases = Depends(get_dbs), bus: EventBus = Depends(get_bus)) -> PlannerService:
    return PlannerService(
        PlanRepo(dbs.app), TargetRepo(dbs.app), ProfileRepo(dbs.app, dbs.events), BudgetRepo(dbs.app), bus
    )


@router.get("/timeline", response_model=PlanTimelineOut)
async def get_timeline(
    target_id: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> PlanTimelineOut:
    result = await planner.get_timeline(user["id"], target_id)
    return PlanTimelineOut(**result)


@router.get("/changes", response_model=Page[PlanChangeOut])
async def list_changes(
    since: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> Page[PlanChangeOut]:
    rows, next_cursor = await planner.list_changes(user["id"], since=since, cursor=cursor)
    items = [PlanChangeOut(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/steps/{step_id}/complete", response_model=PlanTimelineOut)
async def complete_step(
    step_id: str,
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> PlanTimelineOut:
    result = await planner.complete_step(user["id"], step_id)
    return PlanTimelineOut(**result)


@router.post("/steps/{step_id}/reopen", response_model=PlanTimelineOut)
async def reopen_step(
    step_id: str,
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> PlanTimelineOut:
    result = await planner.reopen_step(user["id"], step_id)
    return PlanTimelineOut(**result)


@router.post("/regenerate", response_model=PlanTimelineOut)
async def regenerate(
    target_id: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> PlanTimelineOut:
    result = await planner.regenerate(user["id"], target_id)
    return PlanTimelineOut(**result)


@router.post("/simulate", response_model=SimulateResponse)
async def simulate(
    user: Mapping = Depends(get_current_user),
    planner: PlannerService = Depends(get_planner_service),
) -> SimulateResponse:
    result = await planner.simulate(user["id"], user["public_id"])
    return SimulateResponse(**result)
