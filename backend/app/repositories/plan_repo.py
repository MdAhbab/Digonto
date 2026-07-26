"""Visa Timeline Reactor storage: `plans`, `plan_steps`, `plan_changes` in
`app.db` (docs/database.md section 3.5).

`step_key` is stable across re-plans; `month_label`, `due_at`, and `status`
are not. Every method here that mutates a step is careful to update in
place by `step_key` rather than delete-and-recreate, which is what lets the
frontend's `layout` animation move a row instead of destroying it.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso


class PlanRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- plans -----------------------------------------------------------

    async def get_for_user_target(self, user_id: int, target_id: int | None) -> dict[str, Any] | None:
        if target_id is None:
            row = await self._db.fetch_one(
                "SELECT * FROM plans WHERE user_id = ? ORDER BY updated_at DESC LIMIT 1",
                (user_id,),
            )
        else:
            row = await self._db.fetch_one(
                "SELECT * FROM plans WHERE user_id = ? AND target_id = ?", (user_id, target_id)
            )
        return dict(row) if row else None

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM plans WHERE public_id = ?", (public_id,))
        return dict(row) if row else None

    async def get(self, plan_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM plans WHERE id = ?", (plan_id,))
        return dict(row) if row else None

    async def create(
        self, user_id: int, target_id: int | None, intake_label: str | None
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO plans (public_id, user_id, target_id, intake_label, generated_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (public_id, user_id, target_id, intake_label, now, now),
        )
        result = await self.get_by_public_id(public_id)
        assert result is not None
        return result

    async def touch(self, plan_id: int) -> None:
        await self._db.execute(
            "UPDATE plans SET updated_at = ? WHERE id = ?", (utc_now_iso(), plan_id)
        )

    # -- steps -------------------------------------------------------------

    async def list_steps(self, plan_id: int) -> list[dict[str, Any]]:
        """Every step on a plan, with its citation resolved.

        The snapshot and portal are joined here rather than looked up per step
        by the service. A timeline is six rows today, but the join costs one
        statement either way and the alternative is six round trips against a
        single-writer SQLite file every time the page loads.

        Steps whose `source_snapshot_id` is NULL — every step that is a generic
        template rather than a country rule — come back with NULLs in the three
        citation columns, which the service reads as "no citation to show".
        """
        rows = await self._db.fetch_all(
            # Date order, then template order as the tiebreak for steps sharing a due
            # date or having none. Ordering by `order_idx` alone put a step due in April
            # 2027 above one due in November 2025, because `order_idx` is the position in
            # the template rather than a position in time, and a timeline that is not in
            # time order is not a timeline.
            """SELECT ps.*,
                      sn.public_id  AS snapshot_public_id,
                      sn.fetched_at AS snapshot_fetched_at,
                      po.label      AS snapshot_portal_label
                 FROM plan_steps ps
                 LEFT JOIN snapshots sn ON sn.id = ps.source_snapshot_id
                 LEFT JOIN portals   po ON po.id = sn.portal_id
                WHERE ps.plan_id = ?
                ORDER BY ps.due_at IS NULL, ps.due_at, ps.order_idx""",
            (plan_id,),
        )
        return [dict(r) for r in rows]

    async def get_step_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM plan_steps WHERE public_id = ?", (public_id,)
        )
        return dict(row) if row else None

    async def upsert_step(
        self,
        plan_id: int,
        *,
        step_key: str,
        order_idx: int,
        month_label: str,
        due_at: str | None,
        title_en: str,
        title_bn: str,
        desc_en: str,
        desc_bn: str,
        status: str,
        depends_on: list[str],
        lead_days: int,
        source_snapshot_id: int | None,
        keep_status: bool = True,
    ) -> None:
        """Create or update one step, keyed by `step_key`.

        `keep_status` defaults to True, and that is the fix for a data-loss bug rather
        than a preference. `existing` already selected `status` and then discarded it,
        so every regenerate wrote the caller's status over the stored one. The planner
        passes `status="upcoming"` for every template step, which meant pressing
        "regenerate" marked a student's completed IELTS and submitted applications as
        not yet started. Dates and wording are the plan's to recompute; what the student
        has actually finished is not.
        """
        existing = await self._db.fetch_one(
            "SELECT id, status FROM plan_steps WHERE plan_id = ? AND step_key = ?",
            (plan_id, step_key),
        )
        if existing is not None and keep_status:
            status = existing["status"]
        depends_json = json.dumps(depends_on)
        if existing is None:
            public_id = new_ulid()
            await self._db.execute(
                """INSERT INTO plan_steps
                   (public_id, plan_id, step_key, order_idx, month_label, due_at,
                    title_en, title_bn, desc_en, desc_bn, status, depends_on,
                    lead_days, source_snapshot_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (public_id, plan_id, step_key, order_idx, month_label, due_at,
                 title_en, title_bn, desc_en, desc_bn, status, depends_json,
                 lead_days, source_snapshot_id),
            )
        else:
            await self._db.execute(
                """UPDATE plan_steps SET order_idx = ?, month_label = ?, due_at = ?,
                   title_en = ?, title_bn = ?, desc_en = ?, desc_bn = ?, status = ?,
                   depends_on = ?, lead_days = ?, source_snapshot_id = ?
                   WHERE id = ?""",
                (order_idx, month_label, due_at, title_en, title_bn, desc_en, desc_bn,
                 status, depends_json, lead_days, source_snapshot_id, existing["id"]),
            )

    async def set_step_status(self, step_id: int, status: str, completed_at: str | None) -> None:
        await self._db.execute(
            "UPDATE plan_steps SET status = ?, completed_at = ? WHERE id = ?",
            (status, completed_at, step_id),
        )

    # -- changes -------------------------------------------------------------

    async def add_change(
        self,
        plan_id: int,
        *,
        step_id: int | None,
        trigger: str,
        text_en: str,
        text_bn: str,
        source_label: str,
        snapshot_id: int | None,
        event_id: str | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO plan_changes
               (public_id, plan_id, step_id, trigger, text_en, text_bn, source_label,
                snapshot_id, event_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, plan_id, step_id, trigger, text_en, text_bn, source_label,
             snapshot_id, event_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM plan_changes WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def list_changes(
        self, plan_id: int, *, since: str | None, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        # Every column here is qualified with the `pc.` alias on purpose:
        # plan_steps carries plan_id, created_at and id too, so an unqualified
        # name in the WHERE clause is ambiguous once the LEFT JOIN is applied
        # and SQLite rejects the whole statement.
        clauses = ["pc.plan_id = ?"]
        params: list[Any] = [plan_id]
        if since:
            clauses.append("pc.created_at >= ?")
            params.append(since)
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(pc.created_at, pc.id) < (?, ?)")
            params.extend([created_at, row_id])
        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT pc.*, ps.step_key FROM plan_changes pc
                LEFT JOIN plan_steps ps ON ps.id = pc.step_id
                {where}
                ORDER BY pc.created_at DESC, pc.id DESC
                LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['created_at']}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def count_unseen(self, plan_id: int) -> int:
        val = await self._db.fetch_val(
            "SELECT COUNT(*) FROM plan_changes WHERE plan_id = ? AND seen_at IS NULL",
            (plan_id,),
        )
        return int(val or 0)

    async def mark_seen(self, plan_id: int) -> None:
        await self._db.execute(
            "UPDATE plan_changes SET seen_at = ? WHERE plan_id = ? AND seen_at IS NULL",
            (utc_now_iso(), plan_id),
        )
