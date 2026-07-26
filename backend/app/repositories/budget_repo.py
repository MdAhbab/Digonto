"""Funding math: `budgets`, `fx_rates`, `solvency_rules`, `fee_quotes`,
`fee_line_items` in `app.db` (docs/database.md section 3.7).

`/funding/sources` (the budget composition bar) has no dedicated table in
`docs/database.md`; see `app.models.funding` for the full explanation. The
`*_source_*` methods here model it as two named, addable/removable
contributions layered onto the existing `budgets.own_funds_bdt` and
`budgets.awards_bdt` aggregate columns, which are real, rather than inventing
storage a migration would be needed to add.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class BudgetRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_for_target(self, user_id: int, target_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT * FROM budgets WHERE user_id = ? AND target_id = ?
               ORDER BY computed_at DESC LIMIT 1""",
            (user_id, target_id),
        )
        return dict(row) if row else None

    async def upsert(
        self,
        *,
        user_id: int,
        target_id: int,
        tuition_bdt: int,
        living_bdt: int,
        travel_bdt: int,
        visa_fee_bdt: int,
        awards_bdt: int,
        own_funds_bdt: int,
        gap_bdt: int,
        solvency_required_bdt: int | None,
        fx_rate_used: float | None,
    ) -> dict[str, Any]:
        existing = await self.get_for_target(user_id, target_id)
        now = utc_now_iso()
        if existing is None:
            public_id = new_ulid()
            await self._db.execute(
                """INSERT INTO budgets
                   (public_id, user_id, target_id, tuition_bdt, living_bdt, travel_bdt,
                    visa_fee_bdt, awards_bdt, own_funds_bdt, gap_bdt,
                    solvency_required_bdt, fx_rate_used, computed_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (public_id, user_id, target_id, tuition_bdt, living_bdt, travel_bdt,
                 visa_fee_bdt, awards_bdt, own_funds_bdt, gap_bdt,
                 solvency_required_bdt, fx_rate_used, now),
            )
        else:
            await self._db.execute(
                """UPDATE budgets SET tuition_bdt = ?, living_bdt = ?, travel_bdt = ?,
                   visa_fee_bdt = ?, awards_bdt = ?, own_funds_bdt = ?, gap_bdt = ?,
                   solvency_required_bdt = ?, fx_rate_used = ?, computed_at = ?
                   WHERE id = ?""",
                (tuition_bdt, living_bdt, travel_bdt, visa_fee_bdt, awards_bdt,
                 own_funds_bdt, gap_bdt, solvency_required_bdt, fx_rate_used, now,
                 existing["id"]),
            )
        result = await self.get_for_target(user_id, target_id)
        assert result is not None
        return result

    async def adjust_own_funds(self, user_id: int, target_id: int, delta_bdt: int) -> None:
        budget = await self.get_for_target(user_id, target_id)
        current = budget["own_funds_bdt"] if budget else 0
        new_val = max(0, current + delta_bdt)
        if budget is None:
            await self.upsert(
                user_id=user_id, target_id=target_id, tuition_bdt=0, living_bdt=0,
                travel_bdt=0, visa_fee_bdt=0, awards_bdt=0, own_funds_bdt=new_val,
                gap_bdt=0, solvency_required_bdt=None, fx_rate_used=None,
            )
        else:
            await self._db.execute(
                "UPDATE budgets SET own_funds_bdt = ?, computed_at = ? WHERE id = ?",
                (new_val, utc_now_iso(), budget["id"]),
            )

    # -- fx and solvency reference data -----------------------------------

    async def latest_fx_rate(self, base: str, quote: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM fx_rates WHERE base = ? AND quote = ? ORDER BY as_of DESC LIMIT 1",
            (base, quote),
        )
        return dict(row) if row else None

    async def solvency_rule(self, country_code: str, visa_type: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT * FROM solvency_rules WHERE country_code = ? AND visa_type = ?
               ORDER BY effective_from DESC LIMIT 1""",
            (country_code, visa_type),
        )
        return dict(row) if row else None

    # -- fee reality check ---------------------------------------------------

    async def create_fee_quote(
        self, *, user_id: int, consultancy: str | None, quoted_bdt: int,
        country_code: str | None, document_id: int | None, fair_bdt: int | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO fee_quotes
               (public_id, user_id, consultancy, quoted_bdt, country_code, document_id,
                fair_bdt, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, user_id, consultancy, quoted_bdt, country_code, document_id,
             fair_bdt, now),
        )
        row = await self._db.fetch_one("SELECT * FROM fee_quotes WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def add_fee_line(
        self,
        quote_id: int,
        *,
        label_en: str,
        label_bn: str,
        category: str,
        amount_bdt: int,
        note_en: str | None,
        note_bn: str | None,
        snapshot_id: int | None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO fee_line_items
               (quote_id, label_en, label_bn, category, amount_bdt, note_en, note_bn, snapshot_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (quote_id, label_en, label_bn, category, amount_bdt, note_en, note_bn, snapshot_id),
        )

    async def list_fee_lines(self, quote_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM fee_line_items WHERE quote_id = ?", (quote_id,)
        )
        return [dict(r) for r in rows]
