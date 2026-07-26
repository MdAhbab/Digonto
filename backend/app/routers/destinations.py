"""Public country catalogue and programme search.

docs/api_contract.md section 4. `GET /destinations` is explicitly public
("country catalogue, public" in the contract's own table); `GET /programmes`
is not marked public, so it is kept behind the same authentication as the
rest of the profile/target surface it feeds.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query

from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs, get_optional_user
from app.events.bus import EventBus
from app.models.common import Page
from app.models.destination import DestinationOut
from app.models.profile import ProgrammeOut
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.services.profile_service import ProfileService

router = APIRouter(
    tags=["destinations"],
    dependencies=[Depends(RateLimit("destinations_default", limit=120, window_s=60))],
)


def get_profile_service(dbs: Databases = Depends(get_dbs), bus: EventBus = Depends(get_bus)) -> ProfileService:
    return ProfileService(ProfileRepo(dbs.app, dbs.events), TargetRepo(dbs.app), bus)


def destination_from_row(row: Mapping[str, Any]) -> DestinationOut:
    """Map one `countries` row onto the shape the destinations globe reads.

    lat, lng, note_en and note_bn arrive from migration 014, which carries
    capital-city coordinates and a non-advisory one-line note per country.
    `citation` stays None on purpose: nothing in this row is a claim about
    policy, so there is no snapshot to point at. Anything that is such a
    claim reaches the client through the ask or ledger surfaces instead,
    where a citation is mandatory.
    """
    visa_types = row.get("visa_types")
    if isinstance(visa_types, str):
        try:
            visa_types = json.loads(visa_types)
        except ValueError:
            visa_types = None

    return DestinationOut(
        id=row["code"],
        name_en=row["name_en"],
        name_bn=row["name_bn"],
        lat=row["lat"],
        lng=row["lng"],
        note_en=row["note_en"],
        note_bn=row["note_bn"],
        visa_types=list(visa_types or []),
        shortlisted=bool(row.get("shortlisted", False)),
        citation=None,
    )


@router.get("/destinations", response_model=Page[DestinationOut])
async def list_destinations(
    user: Mapping | None = Depends(get_optional_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> Page[DestinationOut]:
    # Public endpoint. A signed-out visitor still sees the catalogue; they
    # just see every country as un-shortlisted, because a shortlist belongs
    # to an account.
    rows = await profiles.list_destinations(user["id"] if user else None)
    items = [destination_from_row(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.get("/programmes", response_model=Page[ProgrammeOut])
async def search_programmes(
    country: str | None = Query(default=None),
    level: str | None = Query(default=None),
    field: str | None = Query(default=None),
    q: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> Page[ProgrammeOut]:
    rows, next_cursor = await profiles.search_programmes(
        country=country, level=level, field=field, q=q, cursor=cursor
    )
    items = [_programme_out(r) for r in rows]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


def _programme_out(row: dict[str, Any]) -> ProgrammeOut:
    intake_months = row.get("intake_months")
    if isinstance(intake_months, str):
        try:
            intake_months = json.loads(intake_months)
        except ValueError:
            intake_months = None
    return ProgrammeOut(
        id=row["public_id"],
        institution_id=row["institution_public_id"],
        institution_name=row["institution_name"],
        country_code=row["country_code"],
        name=row["name"],
        degree_level=row["degree_level"],
        field_of_study=row.get("field_of_study"),
        duration_months=row.get("duration_months"),
        tuition_amount=row.get("tuition_amount"),
        tuition_currency=row.get("tuition_currency"),
        intake_months=intake_months,
        min_cgpa=row.get("min_cgpa"),
        min_english=row.get("min_english"),
        deadline_at=row.get("deadline_at"),
        updated_at=row["updated_at"],
    )
