"""Khoji's funding index. `scholarships`, `scholarship_criteria`,
`funding_matches`, `match_reasons` in `app.db` (docs/database.md section 3.7).
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso

_SORT_COLUMNS = {
    "name": "sc.name",
    "country": "sc.country_code",
    "coverage": "sc.amount",
    "deadline": "sc.deadline_at",
}

# Row keys used when encoding/decoding the keyset cursor for each sort.
_SORT_ROW_KEYS = {
    "name": "name",
    "country": "country_code",
    "coverage": "amount",
    "deadline": "deadline_at",
}


class ScholarshipRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- catalogue -------------------------------------------------------

    async def list_active(self, *, country: str | None = None) -> list[dict[str, Any]]:
        clauses = ["active = 1"]
        params: list[Any] = []
        if country:
            clauses.append("country_code = ?")
            params.append(country)
        rows = await self._db.fetch_all(
            f"SELECT * FROM scholarships WHERE {' AND '.join(clauses)}", params
        )
        return [dict(r) for r in rows]

    async def get(self, scholarship_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM scholarships WHERE id = ?", (scholarship_id,))
        return dict(row) if row else None

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM scholarships WHERE public_id = ?", (public_id,)
        )
        return dict(row) if row else None

    async def list_criteria(self, scholarship_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM scholarship_criteria WHERE scholarship_id = ?", (scholarship_id,)
        )
        return [dict(r) for r in rows]

    # -- ranked matches (student-facing) --------------------------------

    async def list_matches_for_user(
        self,
        user_id: int,
        *,
        sort: str,
        order: str,
        country: str | None,
        cursor: str | None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], str | None]:
        sort_col = _SORT_COLUMNS.get(sort, "fm.rank")
        sort_row_key = _SORT_ROW_KEYS.get(sort, "rank")
        direction = "ASC" if order == "asc" else "DESC"
        clauses = ["fm.user_id = ?"]
        params: list[Any] = [user_id]
        if country:
            clauses.append("sc.country_code = ?")
            params.append(country)
        decoded = decode_cursor(cursor)
        if decoded:
            sort_raw, row_id = decoded
            # Keyset must match ORDER BY (sort_col, fm.id). Secondary key is
            # always ascending so ties on the sort column page forward by id.
            sort_val: Any = None if sort_raw == "" else sort_raw
            if sort_val is not None and sort_row_key in ("amount", "rank"):
                try:
                    sort_val = int(sort_raw)
                except ValueError:
                    pass
            if direction == "ASC":
                clauses.append(f"({sort_col} > ? OR ({sort_col} = ? AND fm.id > ?))")
            else:
                clauses.append(f"({sort_col} < ? OR ({sort_col} = ? AND fm.id > ?))")
            params.extend([sort_val, sort_val, row_id])
        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT fm.id, fm.public_id, fm.score, fm.rank, fm.eligible, fm.computed_at,
                       sc.public_id AS scholarship_public_id, sc.name, sc.country_code,
                       sc.coverage_type, sc.amount, sc.deadline_at, sc.verified, sc.url,
                       sc.provider, sc.currency, sc.snapshot_id,
                       snap.public_id AS snapshot_public_id
                FROM funding_matches fm
                JOIN scholarships sc ON sc.id = fm.scholarship_id
                LEFT JOIN snapshots snap ON snap.id = sc.snapshot_id
                {where}
                ORDER BY {sort_col} {direction}, fm.id ASC
                LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            sort_part = last.get(sort_row_key)
            next_cursor = f"{'' if sort_part is None else sort_part}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def get_match(self, user_id: int, scholarship_public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT fm.*, sc.public_id AS scholarship_public_id, sc.name, sc.country_code,
                      sc.coverage_type, sc.amount, sc.deadline_at, sc.verified, sc.url,
                      sc.provider, sc.currency, sc.snapshot_id,
                      snap.public_id AS snapshot_public_id
               FROM funding_matches fm
               JOIN scholarships sc ON sc.id = fm.scholarship_id
               LEFT JOIN snapshots snap ON snap.id = sc.snapshot_id
               WHERE fm.user_id = ? AND sc.public_id = ?""",
            (user_id, scholarship_public_id),
        )
        return dict(row) if row else None

    async def list_reasons(self, match_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM match_reasons WHERE match_id = ?", (match_id,)
        )
        return [dict(r) for r in rows]

    async def clear_matches_for_user(self, user_id: int) -> None:
        await self._db.execute("DELETE FROM funding_matches WHERE user_id = ?", (user_id,))

    async def create_match(
        self, *, user_id: int, scholarship_id: int, score: float, rank: int, eligible: bool,
        kb_version_id: int | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO funding_matches
               (public_id, user_id, scholarship_id, score, rank, eligible, kb_version_id, computed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, user_id, scholarship_id, score, rank, int(eligible), kb_version_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM funding_matches WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def add_reason(
        self, match_id: int, *, criterion_key: str, met: bool, reason_en: str, reason_bn: str,
        weight: float = 1.0,
    ) -> None:
        await self._db.execute(
            """INSERT INTO match_reasons (match_id, criterion_key, met, reason_en, reason_bn, weight)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (match_id, criterion_key, int(met), reason_en, reason_bn, weight),
        )

    # -- moderator: verification queue --------------------------------------

    async def list_unverified(
        self, *, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["verified = 0"]
        params: list[Any] = []
        decoded = decode_cursor(cursor)
        if decoded:
            _, row_id = decoded
            clauses.append("id > ?")
            params.append(row_id)
        rows = await self._db.fetch_all(
            f"""SELECT * FROM scholarships WHERE {' AND '.join(clauses)}
                ORDER BY id ASC LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = f"|{rows[limit - 1]['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def set_verified(self, scholarship_id: int, verified: bool) -> None:
        await self._db.execute(
            "UPDATE scholarships SET verified = ?, updated_at = ? WHERE id = ?",
            (int(verified), utc_now_iso(), scholarship_id),
        )
