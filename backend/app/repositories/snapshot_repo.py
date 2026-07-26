"""The Truth Ledger evidence layer: `snapshots`, `passages`, `passage_diffs`,
`kb_versions` in `app.db` (docs/database.md section 3.3).
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor


class SnapshotRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- snapshots -----------------------------------------------------

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT s.*, p.label AS portal_label, p.url AS portal_url
               FROM snapshots s JOIN portals p ON p.id = s.portal_id
               WHERE s.public_id = ?""",
            (public_id,),
        )
        return dict(row) if row else None

    async def get(self, snapshot_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT s.*, p.label AS portal_label, p.url AS portal_url
               FROM snapshots s JOIN portals p ON p.id = s.portal_id
               WHERE s.id = ?""",
            (snapshot_id,),
        )
        return dict(row) if row else None

    async def latest_for_portal(self, portal_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM snapshots WHERE portal_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (portal_id,),
        )
        return dict(row) if row else None

    async def list_passages(self, snapshot_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM passages WHERE snapshot_id = ? ORDER BY ordinal", (snapshot_id,)
        )
        return [dict(r) for r in rows]

    # -- change feed (public) --------------------------------------------

    async def list_changes(
        self, *, portal_id: int | None, since: str | None, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["needs_review = 0", "category != 'cosmetic' OR category IS NULL"]
        params: list[Any] = []
        if portal_id is not None:
            clauses.append("d.portal_id = ?")
            params.append(portal_id)
        if since:
            clauses.append("d.created_at >= ?")
            params.append(since)
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(d.created_at, d.id) < (?, ?)")
            params.extend([created_at, row_id])

        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT d.*, p.public_id AS portal_public_id,
                       op.text AS old_text, np.text AS new_text
                FROM passage_diffs d
                JOIN portals p ON p.id = d.portal_id
                LEFT JOIN passages op ON op.id = d.old_passage_id
                LEFT JOIN passages np ON np.id = d.new_passage_id
                {where}
                ORDER BY d.created_at DESC, d.id DESC
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

    # -- moderator change review queue --------------------------------------

    async def list_pending_review(
        self, *, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["d.needs_review = 1"]
        params: list[Any] = []
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(d.created_at, d.id) < (?, ?)")
            params.extend([created_at, row_id])

        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT d.*, p.public_id AS portal_public_id, p.label AS portal_label,
                       fs.public_id AS from_snapshot_public_id, ts.public_id AS to_snapshot_public_id,
                       op.text AS old_text, np.text AS new_text
                FROM passage_diffs d
                JOIN portals p ON p.id = d.portal_id
                JOIN snapshots fs ON fs.id = d.from_snapshot_id
                JOIN snapshots ts ON ts.id = d.to_snapshot_id
                LEFT JOIN passages op ON op.id = d.old_passage_id
                LEFT JOIN passages np ON np.id = d.new_passage_id
                {where}
                ORDER BY d.created_at ASC, d.id ASC
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

    async def get_diff(self, diff_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM passage_diffs WHERE id = ?", (diff_id,))
        return dict(row) if row else None

    async def get_diff_by_public_id_or_id(self, ident: str) -> dict[str, Any] | None:
        # passage_diffs has no public_id column; the moderator queue uses the
        # integer id directly since it is never exposed outside the console.
        if not ident.isdigit():
            return None
        return await self.get_diff(int(ident))

    async def approve_diff(self, diff_id: int, category: str) -> None:
        await self._db.execute(
            """UPDATE passage_diffs SET category = ?, needs_review = 0, classified_at =
               strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?""",
            (category, diff_id),
        )

    async def reclassify_diff(self, diff_id: int, category: str) -> None:
        await self._db.execute(
            """UPDATE passage_diffs SET category = ?, needs_review = 0, classified_at =
               strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?""",
            (category, diff_id),
        )

    async def discard_diff(self, diff_id: int) -> None:
        await self._db.execute(
            """UPDATE passage_diffs SET category = 'cosmetic', needs_review = 0,
               classified_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now') WHERE id = ?""",
            (diff_id,),
        )

    async def count_pending_review(self) -> int:
        val = await self._db.fetch_val(
            "SELECT COUNT(*) FROM passage_diffs WHERE needs_review = 1"
        )
        return int(val or 0)

    # -- knowledge base version ------------------------------------------

    async def count_all(self) -> int:
        val = await self._db.fetch_val("SELECT COUNT(*) FROM snapshots")
        return int(val or 0)

    async def live_kb_version(self) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM kb_versions WHERE status = 'live'")
        return dict(row) if row else None
