"""Programme search and the student's target shortlist.

`programmes`, `institutions`, `student_targets` in `app.db`
(docs/database.md section 3.2).
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso

_PROGRAMME_SELECT = """
    SELECT p.id, p.public_id, p.name, p.degree_level, p.field_of_study,
           p.duration_months, p.tuition_amount, p.tuition_currency, p.intake_months,
           p.min_cgpa, p.min_english, p.deadline_at, p.updated_at,
           i.public_id AS institution_public_id, i.name AS institution_name,
           i.country_code
    FROM programmes p
    JOIN institutions i ON i.id = p.institution_id
"""


class TargetRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- programme search --------------------------------------------------

    async def search_programmes(
        self,
        *,
        country: str | None,
        level: str | None,
        field: str | None,
        q: str | None,
        cursor: str | None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses: list[str] = []
        params: list[Any] = []
        if country:
            clauses.append("i.country_code = ?")
            params.append(country)
        if level:
            clauses.append("p.degree_level = ?")
            params.append(level)
        if field:
            clauses.append("p.field_of_study LIKE ?")
            params.append(f"%{field}%")
        if q:
            clauses.append("(p.name LIKE ? OR i.name LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])

        decoded = decode_cursor(cursor)
        if decoded:
            updated_at, row_id = decoded
            clauses.append("(p.updated_at, p.id) < (?, ?)")
            params.extend([updated_at, row_id])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"""{_PROGRAMME_SELECT}
                  {where}
                  ORDER BY p.updated_at DESC, p.id DESC
                  LIMIT ?"""
        rows = await self._db.fetch_all(sql, (*params, limit + 1))
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['updated_at']}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def get_programme_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            f"{_PROGRAMME_SELECT} WHERE p.public_id = ?", (public_id,)
        )
        return dict(row) if row else None

    async def get_programme(self, programme_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(f"{_PROGRAMME_SELECT} WHERE p.id = ?", (programme_id,))
        return dict(row) if row else None

    # -- targets -------------------------------------------------------------

    async def list_targets(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            f"""SELECT st.id, st.public_id, st.visa_type, st.rank, st.status, st.created_at,
                       p.public_id AS programme_public_id, p.name AS programme_name,
                       i.name AS institution_name, i.country_code
                FROM student_targets st
                JOIN programmes p ON p.id = st.programme_id
                JOIN institutions i ON i.id = p.institution_id
                WHERE st.user_id = ?
                ORDER BY st.rank, st.created_at""",
            (user_id,),
        )
        return [dict(r) for r in rows]

    async def get_target(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT st.id, st.public_id, st.programme_id, st.visa_type, st.rank,
                      st.status, st.created_at, st.user_id
               FROM student_targets st WHERE st.user_id = ? AND st.public_id = ?""",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def get_target_by_id(self, user_id: int, target_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT st.id, st.public_id, st.programme_id, st.visa_type, st.rank,
                      st.status, st.created_at, st.user_id
               FROM student_targets st WHERE st.user_id = ? AND st.id = ?""",
            (user_id, target_id),
        )
        return dict(row) if row else None

    async def create_target(
        self, user_id: int, programme_id: int, visa_type: str | None
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        rank_val = await self._db.fetch_val(
            "SELECT COALESCE(MAX(rank), -1) + 1 FROM student_targets WHERE user_id = ?",
            (user_id,),
        )
        await self._db.execute(
            """INSERT INTO student_targets
               (public_id, user_id, programme_id, visa_type, rank, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'considering', ?)""",
            (public_id, user_id, programme_id, visa_type, rank_val, now),
        )
        targets = await self.list_targets(user_id)
        return next(t for t in targets if t["public_id"] == public_id)

    async def delete_target(self, user_id: int, public_id: str) -> bool:
        target = await self.get_target(user_id, public_id)
        if target is None:
            return False
        await self._db.execute(
            "DELETE FROM student_targets WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return True

    async def list_target_ids_for_user(self, user_id: int) -> list[int]:
        rows = await self._db.fetch_all(
            "SELECT id FROM student_targets WHERE user_id = ?", (user_id,)
        )
        return [r["id"] for r in rows]
