"""Prohori's vault audits. `audits`, `audit_findings` in `app.db`
(docs/database.md section 3.6).
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class AuditRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(self, user_id: int, target_id: int | None) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO audits (public_id, user_id, target_id, agent, status, started_at)
               VALUES (?, ?, ?, 'prohori', 'queued', ?)""",
            (public_id, user_id, target_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM audits WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_by_public_id(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM audits WHERE user_id = ? AND public_id = ?", (user_id, public_id)
        )
        return dict(row) if row else None

    async def latest_for_user(self, user_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM audits WHERE user_id = ? ORDER BY started_at DESC LIMIT 1",
            (user_id,),
        )
        return dict(row) if row else None

    async def set_status(self, audit_id: int, status: str, error: str | None = None) -> None:
        finished = utc_now_iso() if status in ("complete", "failed") else None
        await self._db.execute(
            "UPDATE audits SET status = ?, finished_at = ?, error = ? WHERE id = ?",
            (status, finished, error, audit_id),
        )

    async def add_finding(
        self,
        audit_id: int,
        *,
        document_id: int | None,
        code: str,
        severity: str,
        title_en: str,
        title_bn: str,
        detail_en: str,
        detail_bn: str,
        evidence: dict | None,
        action_en: str | None,
        action_bn: str | None,
        snapshot_id: int | None,
    ) -> None:
        public_id = new_ulid()
        await self._db.execute(
            """INSERT INTO audit_findings
               (public_id, audit_id, document_id, code, severity, title_en, title_bn,
                detail_en, detail_bn, evidence, action_en, action_bn, snapshot_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, audit_id, document_id, code, severity, title_en, title_bn,
             detail_en, detail_bn, json.dumps(evidence) if evidence else None,
             action_en, action_bn, snapshot_id),
        )

    async def list_findings(self, audit_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT * FROM audit_findings WHERE audit_id = ? AND resolved_at IS NULL
               ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END""",
            (audit_id,),
        )
        return [dict(r) for r in rows]

    async def latest_findings_for_document(self, document_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT af.* FROM audit_findings af
               JOIN audits a ON a.id = af.audit_id
               WHERE af.document_id = ? AND af.resolved_at IS NULL
               AND a.id = (SELECT id FROM audits WHERE user_id = a.user_id
                           ORDER BY started_at DESC LIMIT 1)
               ORDER BY CASE af.severity WHEN 'critical' THEN 0 WHEN 'warning' THEN 1 ELSE 2 END
               LIMIT 1""",
            (document_id,),
        )
        return [dict(r) for r in rows]
