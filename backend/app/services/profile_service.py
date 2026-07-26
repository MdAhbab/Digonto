"""Profile, destinations, shortlist, programme search, and targets.

api_contract.md section 4.
"""

from __future__ import annotations

from app.errors import Conflict, NotFound
from app.events.bus import EventBus, EventType
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo


class ProfileService:
    def __init__(self, profiles: ProfileRepo, targets: TargetRepo, bus: EventBus) -> None:
        self._profiles = profiles
        self._targets = targets
        self._bus = bus

    # -- profile -----------------------------------------------------------

    async def get_profile(self, user_id: int) -> dict | None:
        return await self._profiles.get(user_id)

    async def update_profile(self, user_id: int, user_public_id: str, patch: dict) -> dict:
        fields = {k: v for k, v in patch.items() if v is not None}
        result = await self._profiles.upsert(user_id, fields)
        await self._bus.publish(
            EventType.PROFILE_UPDATED,
            user_id=user_id,
            subject_type="user",
            subject_id=user_public_id,
            payload={"fields": list(fields.keys())},
        )
        return result

    # -- destinations and shortlist -----------------------------------------

    async def list_destinations(self, user_id: int) -> list[dict]:
        countries = await self._profiles.list_countries()
        shortlist = await self._profiles.get_shortlist(user_id)
        out = []
        for c in countries:
            row = dict(c)
            row["shortlisted"] = row["code"] in shortlist
            out.append(row)
        return out

    async def add_shortlist(self, user_id: int, user_public_id: str, country_code: str) -> None:
        country = await self._profiles.get_country(country_code)
        if country is None:
            raise NotFound(
                detail_en=f"No destination with code '{country_code}'.",
                detail_bn=f"'{country_code}' কোডের কোনো গন্তব্য নেই।",
            )
        await self._profiles.set_shortlist(user_id, user_public_id, country_code, True)

    async def remove_shortlist(self, user_id: int, user_public_id: str, country_code: str) -> None:
        await self._profiles.set_shortlist(user_id, user_public_id, country_code, False)

    # -- programme search -----------------------------------------------

    async def search_programmes(
        self, *, country: str | None, level: str | None, field: str | None, q: str | None,
        cursor: str | None,
    ) -> tuple[list[dict], str | None]:
        return await self._targets.search_programmes(
            country=country, level=level, field=field, q=q, cursor=cursor
        )

    # -- targets -------------------------------------------------------

    async def list_targets(self, user_id: int) -> list[dict]:
        return await self._targets.list_targets(user_id)

    async def create_target(self, user_id: int, user_public_id: str, programme_public_id: str, visa_type: str | None) -> dict:
        programme = await self._targets.get_programme_by_public_id(programme_public_id)
        if programme is None:
            raise NotFound(
                detail_en="That programme could not be found.",
                detail_bn="প্রোগ্রামটি খুঁজে পাওয়া যায়নি।",
            )
        try:
            result = await self._targets.create_target(user_id, programme["id"], visa_type)
        except Exception as exc:  # noqa: BLE001 - surfaces the UNIQUE constraint as a 409
            raise Conflict(
                detail_en="That programme is already on your shortlist.",
                detail_bn="প্রোগ্রামটি ইতিমধ্যে আপনার তালিকায় আছে।",
            ) from exc
        await self._bus.publish(
            EventType.PROFILE_UPDATED,
            user_id=user_id,
            subject_type="target",
            subject_id=result["public_id"],
            payload={"action": "target_added", "programme_id": programme_public_id},
        )
        return result

    async def delete_target(self, user_id: int, public_id: str) -> None:
        ok = await self._targets.delete_target(user_id, public_id)
        if not ok:
            raise NotFound(
                detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।"
            )
