"""The moderator console's data access, and the audit trail of every
moderator action.

This repository is the one deliberately given all three database handles,
because the console is a cross-cutting read surface by design: `users`,
`moderation_actions`, `moderation_views`, `user_reports` live in `app.db`;
dead letters, agent runs, and request metrics live in `events.db`; adapters
and benchmark runs live in `learn.db` (docs/database.md sections 3.1, 4, 5).

The privacy promise in api_contract.md section 11a is enforced here by
omission: no query in this file selects `documents.storage_path`,
`document_fields.value_enc`, or `questions.text_raw` for a non-escalated
item. Escalated answer text is read from `AnswerRepo` by the service layer,
never from here, which keeps "a student's full question history" structurally
unreachable from this class.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso


class ModerationRepo:
    def __init__(self, db: Database, events_db: Database, learn_db: Database) -> None:
        self._db = db
        self._events_db = events_db
        self._learn_db = learn_db

    # -- audit trail -----------------------------------------------------

    async def record_action(
        self,
        *,
        moderator_id: int,
        action: str,
        subject_type: str,
        subject_id: str,
        reason_en: str | None,
        reason_bn: str | None,
        detail: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO moderation_actions
               (public_id, moderator_id, action, subject_type, subject_id, reason_en,
                reason_bn, detail, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, moderator_id, action, subject_type, subject_id, reason_en,
             reason_bn, json.dumps(detail) if detail is not None else None, now),
        )
        row = await self._db.fetch_one("SELECT * FROM moderation_actions WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def list_actions_for_subject(self, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT * FROM moderation_actions WHERE subject_type = ? AND subject_id = ?
               ORDER BY created_at DESC""",
            (subject_type, subject_id),
        )
        return [dict(r) for r in rows]

    async def record_view(
        self, *, moderator_id: int, user_id: int, scope: str, subject_id: str | None
    ) -> None:
        """Every moderator read of student-linked data writes this row. The
        student can see it in their own account (docs/api_contract.md
        section 11a), so this must be called on every such read path, not
        just the ones that feel sensitive.
        """

        await self._db.execute(
            """INSERT INTO moderation_views (moderator_id, user_id, scope, subject_id, viewed_at)
               VALUES (?, ?, ?, ?, ?)""",
            (moderator_id, user_id, scope, subject_id, utc_now_iso()),
        )

    async def list_views_for_user(self, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT scope, subject_id, viewed_at FROM moderation_views
               WHERE user_id = ? ORDER BY viewed_at DESC LIMIT ?""",
            (user_id, limit),
        )
        return [dict(r) for r in rows]

    # -- user reports --------------------------------------------------------

    async def create_report(
        self, *, reporter_id: int | None, subject_type: str, subject_id: str,
        category: str, detail: str | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO user_reports
               (public_id, reporter_id, subject_type, subject_id, category, detail,
                status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 'open', ?)""",
            (public_id, reporter_id, subject_type, subject_id, category, detail, now),
        )
        row = await self._db.fetch_one("SELECT * FROM user_reports WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def list_reports(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM user_reports ORDER BY created_at DESC"
        )
        return [dict(r) for r in rows]

    # -- people ----------------------------------------------------------

    async def list_users(
        self, *, status: str | None, q: str | None, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["u.deleted_at IS NULL"]
        params: list[Any] = []
        if status:
            clauses.append("u.status = ?")
            params.append(status)
        if q:
            clauses.append("(u.email LIKE ? OR u.display_name LIKE ?)")
            params.extend([f"%{q}%", f"%{q}%"])
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(u.created_at, u.id) < (?, ?)")
            params.extend([created_at, row_id])
        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT u.id, u.public_id, u.email, u.display_name, u.role, u.status,
                       u.created_at, u.last_seen_at,
                       (SELECT COUNT(*) FROM questions q WHERE q.user_id = u.id) AS question_count,
                       (SELECT COUNT(*) FROM documents d WHERE d.user_id = u.id
                        AND d.deleted_at IS NULL) AS document_count,
                       EXISTS(SELECT 1 FROM user_reports r WHERE r.subject_type = 'user'
                              AND r.subject_id = u.public_id AND r.status = 'open') AS flagged
                FROM users u
                {where}
                ORDER BY u.created_at DESC, u.id DESC
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

    async def get_user_detail(self, user_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT u.id, u.public_id, u.email, u.display_name, u.role, u.status,
                      u.status_reason_en, u.status_reason_bn, u.created_at, u.last_seen_at,
                      (SELECT COUNT(*) FROM questions q WHERE q.user_id = u.id) AS question_count,
                      (SELECT COUNT(*) FROM documents d WHERE d.user_id = u.id
                       AND d.deleted_at IS NULL) AS document_count,
                      (SELECT COUNT(*) FROM plan_steps ps JOIN plans p ON p.id = ps.plan_id
                       WHERE p.user_id = u.id) AS plan_step_count,
                      (SELECT COUNT(*) FROM user_reports r WHERE r.subject_type = 'user'
                       AND r.subject_id = u.public_id) AS report_count
               FROM users u WHERE u.id = ?""",
            (user_id,),
        )
        return dict(row) if row else None

    async def new_users_today(self) -> int:
        val = await self._db.fetch_val(
            "SELECT COUNT(*) FROM users WHERE date(created_at) = date('now')"
        )
        return int(val or 0)

    # -- model oversight (learn.db) ------------------------------------------

    async def list_adapters(self) -> list[dict[str, Any]]:
        rows = await self._learn_db.fetch_all(
            "SELECT * FROM adapters ORDER BY trained_at DESC"
        )
        adapters = [dict(r) for r in rows]
        for adapter in adapters:
            after = await self._learn_db.fetch_one(
                """SELECT * FROM benchmark_runs WHERE adapter_id = ?
                   ORDER BY run_at DESC LIMIT 1""",
                (adapter["id"],),
            )
            before = await self._learn_db.fetch_one(
                """SELECT * FROM benchmark_runs WHERE adapter_id IS NULL
                   ORDER BY run_at DESC LIMIT 1"""
            )
            adapter["_after"] = dict(after) if after else None
            adapter["_before"] = dict(before) if before else None
        return adapters

    async def get_adapter(self, adapter_id: int) -> dict[str, Any] | None:
        row = await self._learn_db.fetch_one("SELECT * FROM adapters WHERE id = ?", (adapter_id,))
        return dict(row) if row else None

    async def get_adapter_by_tag(self, tag: str) -> dict[str, Any] | None:
        row = await self._learn_db.fetch_one("SELECT * FROM adapters WHERE tag = ?", (tag,))
        return dict(row) if row else None

    async def promote_adapter(self, adapter_id: int) -> None:
        await self._learn_db.execute(
            "UPDATE adapters SET status = 'promoted', promoted_at = ? WHERE id = ?",
            (utc_now_iso(), adapter_id),
        )

    async def rollback_adapter(self, adapter_id: int, reason: str) -> None:
        await self._learn_db.execute(
            """UPDATE adapters SET status = 'rolled_back', rolled_back_at = ?, notes = ?
               WHERE id = ?""",
            (utc_now_iso(), reason, adapter_id),
        )

    async def count_adapters_awaiting_promotion(self) -> int:
        val = await self._learn_db.fetch_val(
            "SELECT COUNT(*) FROM adapters WHERE status = 'candidate'"
        )
        return int(val or 0)

    # -- health (events.db) ---------------------------------------------------

    async def count_dead_letters(self) -> int:
        val = await self._events_db.fetch_val(
            "SELECT COUNT(*) FROM dead_letters WHERE resolved_at IS NULL"
        )
        return int(val or 0)

    async def count_crawl_failures(self, hours: int = 48) -> int:
        val = await self._events_db.fetch_val(
            """SELECT COUNT(*) FROM events WHERE type = 'portal.unreachable'
               AND julianday('now') - julianday(created_at) <= ? / 24.0""",
            (hours,),
        )
        return int(val or 0)

    async def queue_depth_agent(self) -> int:
        val = await self._events_db.fetch_val(
            "SELECT COUNT(*) FROM agent_runs WHERE status IN ('queued', 'running')"
        )
        return int(val or 0)

    async def model_latency_percentiles(self) -> tuple[int | None, int | None]:
        p50 = await self._events_db.fetch_val(
            """SELECT latency_ms FROM request_metrics WHERE route LIKE '%/ask%'
               ORDER BY latency_ms LIMIT 1 OFFSET
               (SELECT COUNT(*) / 2 FROM request_metrics WHERE route LIKE '%/ask%')"""
        )
        p95 = await self._events_db.fetch_val(
            """SELECT latency_ms FROM request_metrics WHERE route LIKE '%/ask%'
               ORDER BY latency_ms LIMIT 1 OFFSET
               (SELECT CAST(COUNT(*) * 0.95 AS INTEGER) FROM request_metrics WHERE route LIKE '%/ask%')"""
        )
        return (int(p50) if p50 is not None else None, int(p95) if p95 is not None else None)
