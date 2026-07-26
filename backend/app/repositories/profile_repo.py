"""Student profile, the country catalogue, and the country shortlist.

`profiles` and `countries` in `app.db` (docs/database.md section 3.2).

Deliberate deviation: `docs/database.md` has no table for a student's
shortlisted *countries* (as opposed to `student_targets`, which is a
shortlist of *programmes* and does have a table). Building one would mean a
migration, which is out of scope here. Country shortlisting is a low-volume
preference toggle, and `events.db.events` already exists precisely for
"things that happened to a user"; this repo treats
`country.shortlisted` / `country.unshortlisted` as first-class events and
reduces them to current membership on read. That is why this repository,
unlike the others, is constructed with both database handles instead of one.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class ProfileRepo:
    def __init__(self, db: Database, events_db: Database) -> None:
        self._db = db
        self._events_db = events_db

    # -- profile -------------------------------------------------------

    async def get(self, user_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM profiles WHERE user_id = ?", (user_id,))
        return dict(row) if row else None

    async def upsert(self, user_id: int, fields: dict[str, Any]) -> dict[str, Any]:
        existing = await self.get(user_id)
        now = utc_now_iso()
        english_sub = fields.get("english_sub")
        if isinstance(english_sub, dict):
            fields = {**fields, "english_sub": json.dumps(english_sub)}

        if existing is None:
            columns = [
                "display_name", "home_district", "degree_level", "field_of_study",
                "cgpa", "cgpa_scale", "graduation_year", "english_test", "english_overall",
                "english_sub", "budget_bdt", "intake_target", "study_gap_years",
            ]
            values = [fields.get(c) for c in columns]
            placeholders = ", ".join("?" for _ in columns)
            await self._db.execute(
                f"""INSERT INTO profiles (user_id, {", ".join(columns)}, updated_at)
                    VALUES (?, {placeholders}, ?)""",
                (user_id, *values, now),
            )
        else:
            sets = ", ".join(f"{k} = ?" for k in fields.keys())
            await self._db.execute(
                f"UPDATE profiles SET {sets}, updated_at = ? WHERE user_id = ?",
                (*fields.values(), now, user_id),
            )
        result = await self.get(user_id)
        assert result is not None
        return result

    async def is_complete(self, user_id: int) -> bool:
        row = await self.get(user_id)
        if row is None:
            return False
        required = ("degree_level", "field_of_study", "cgpa", "graduation_year", "intake_target")
        return all(row.get(k) is not None for k in required)

    # -- countries -------------------------------------------------------

    async def list_countries(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM countries WHERE active = 1 ORDER BY sort_order, name_en"
        )
        return [dict(r) for r in rows]

    async def get_country(self, code: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM countries WHERE code = ? AND active = 1", (code,)
        )
        return dict(row) if row else None

    # -- country shortlist (event-sourced; see module docstring) -------------

    async def get_shortlist(self, user_id: int) -> set[str]:
        rows = await self._events_db.fetch_all(
            """SELECT subject_id, type, created_at FROM events
               WHERE user_id = ? AND type IN ('country.shortlisted', 'country.unshortlisted')
               ORDER BY created_at ASC""",
            (user_id,),
        )
        state: dict[str, bool] = {}
        for row in rows:
            state[row["subject_id"]] = row["type"] == "country.shortlisted"
        return {code for code, on in state.items() if on}

    async def set_shortlist(self, user_id: int, actor_public_id: str, country_code: str, on: bool) -> None:
        event_type = "country.shortlisted" if on else "country.unshortlisted"
        await self._events_db.execute(
            """INSERT INTO events
               (event_id, stream, type, actor, subject_type, subject_id, user_id, payload,
                schema_version, created_at)
               VALUES (?, 'user', ?, ?, 'country', ?, ?, ?, 1, ?)""",
            (
                new_ulid(),
                event_type,
                f"user:{actor_public_id}",
                country_code,
                user_id,
                json.dumps({"country_code": country_code}),
                utc_now_iso(),
            ),
        )
