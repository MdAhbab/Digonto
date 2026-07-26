"""The Truth Ledger: public, no-auth verification surface.

docs/api_contract.md section 6. Every route here is public by contract, so
none of them depend on `get_current_user`; the rate limiter falls back to
per-IP bucketing (see `RateLimit._identity` in app/deps.py) exactly because
no `request.state.user_id` is ever set on this router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.db.connection import Databases
from app.deps import RateLimit, get_dbs
from app.models.common import Page
from app.models.ledger import LedgerChangeOut, PortalOut, SnapshotDetail
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.services.ledger_service import LedgerService

router = APIRouter(
    prefix="/ledger",
    tags=["ledger"],
    dependencies=[Depends(RateLimit("ledger_public", limit=60, window_s=60))],
)


def get_ledger_service(dbs: Databases = Depends(get_dbs)) -> LedgerService:
    return LedgerService(PortalRepo(dbs.app), SnapshotRepo(dbs.app))


@router.get("/snapshots/{snapshot_id}", response_model=SnapshotDetail)
async def get_snapshot(
    snapshot_id: str, ledger: LedgerService = Depends(get_ledger_service)
) -> SnapshotDetail:
    result = await ledger.get_snapshot(snapshot_id)
    return SnapshotDetail(**result)


def _portal_out(row: dict[str, Any]) -> PortalOut:
    return PortalOut(
        id=row["public_id"],
        url=row["url"],
        kind=row["kind"],
        country_code=row.get("country_code"),
        label=row["label"],
        enabled=bool(row["enabled"]),
        last_fetch_at=row.get("last_fetch_at"),
        last_status=row.get("last_status"),
        consecutive_failures=row["consecutive_failures"],
    )


@router.get("/portals", response_model=Page[PortalOut])
async def list_portals(ledger: LedgerService = Depends(get_ledger_service)) -> Page[PortalOut]:
    rows = await ledger.list_portals()
    items = [_portal_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.get("/changes", response_model=Page[LedgerChangeOut])
async def list_changes(
    portal_id: str | None = Query(default=None),
    since: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    ledger: LedgerService = Depends(get_ledger_service),
) -> Page[LedgerChangeOut]:
    rows, next_cursor = await ledger.list_changes(portal_public_id=portal_id, since=since, cursor=cursor)
    items = [LedgerChangeOut(**r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))
