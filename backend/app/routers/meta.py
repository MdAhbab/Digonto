"""`GET /meta/stats`. docs/api_contract.md section 2.

The other section-2 routes (`/healthz`, `/readyz`, `/metrics`) are already
registered directly on the `FastAPI` app in app/main.py (not modified here);
this only adds the one meta route that belongs to the versioned API surface
and needs `StatsService`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.db.connection import Databases
from app.deps import RateLimit, get_dbs
from app.repositories.answer_repo import AnswerRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.services.stats_service import StatsService

router = APIRouter(
    prefix="/meta",
    tags=["meta"],
    dependencies=[Depends(RateLimit("meta_default", limit=120, window_s=60))],
)


class MetaStatsOut(BaseModel):
    """No dedicated model module exists for this single endpoint; matches
    the exact shape in docs/api_contract.md section 2."""

    model_config = ConfigDict(populate_by_name=True)

    portals_watched: int
    snapshots_archived: int
    questions_answered: int
    citation_rate: float
    commission_taken_pct: int
    sdg_aligned: int
    as_of: str


def get_stats_service(dbs: Databases = Depends(get_dbs)) -> StatsService:
    return StatsService(PortalRepo(dbs.app), SnapshotRepo(dbs.app), AnswerRepo(dbs.app))


@router.get("/stats", response_model=MetaStatsOut)
async def get_stats(stats: StatsService = Depends(get_stats_service)) -> MetaStatsOut:
    result = await stats.get_public_stats()
    return MetaStatsOut(**result)
