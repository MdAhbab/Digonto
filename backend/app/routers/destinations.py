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


@router.get("/destinations", response_model=Page[DestinationOut])
async def list_destinations(
    user: Mapping | None = Depends(get_optional_user),
    profiles: ProfileService = Depends(get_profile_service),
) -> Page[DestinationOut]:
    # ProfileService.list_destinations needs a user_id to compute the
    # `shortlisted` flag; an anonymous caller gets `0`, which matches no
    # real user, so every country simply comes back unshortlisted rather
    # than requiring auth for a route the contract marks public.
    user_id = user["id"] if user is not None else 0

    # `countries` (docs/database.md section 3.2) has only code/name_en/
    # name_bn/visa_types/active/sort_order: no lat, lng, note_en, note_bn,
    # or citation columns, and the seed migration
    # (app/db/migrations/app/011_seed_countries.sql) does not add any either.
    # `DestinationOut` requires lat/lng/note_en/note_bn as non-optional
    # fields, per the frontend `Country` interface. Populating them would
    # mean inventing coordinates and citable prose, which "no mock or
    # placeholder data anywhere" rules out, and adding the columns is a
    # migration, out of scope for a router-only build. Raising here (rather
    # than returning fabricated geography) is deliberate; see the final
    # report for what a real fix needs (a migration adding those columns,
    # seeded from a real source, each with its own snapshot citation).
    raise NotImplementedError(
        "GET /destinations needs DestinationOut.{lat,lng,note_en,note_bn}, which "
        "have no backing column on `countries` (docs/database.md section 3.2). "
        "ProfileService.list_destinations() only returns "
        "{code,name_en,name_bn,visa_types,active,sort_order,shortlisted}."
    )


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
