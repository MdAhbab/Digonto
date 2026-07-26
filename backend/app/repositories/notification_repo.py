"""Notifications and the multiplexed live stream.

`notifications` lives in `app.db` (docs/database.md section 3.10). The
`/stream` endpoint's `Last-Event-ID` replay reads the durable archive in
`events.db.events` directly (docs/database.md section 4), which is why this
repository, like `ProfileRepo`, is constructed with both database handles.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso


class NotificationRepo:
    def __init__(self, db: Database, events_db: Database) -> None:
        self._db = db
        self._events_db = events_db

    # -- notifications -------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        kind: str,
        severity: str,
        title_en: str,
        title_bn: str,
        body_en: str,
        body_bn: str,
        link_path: str | None,
        snapshot_id: int | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO notifications
               (public_id, user_id, kind, severity, title_en, title_bn, body_en, body_bn,
                link_path, snapshot_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, user_id, kind, severity, title_en, title_bn, body_en, body_bn,
             link_path, snapshot_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM notifications WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def list_for_user(
        self, user_id: int, *, unread_only: bool, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["user_id = ?"]
        params: list[Any] = [user_id]
        if unread_only:
            clauses.append("read_at IS NULL")
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(created_at, id) < (?, ?)")
            params.extend([created_at, row_id])
        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT * FROM notifications {where}
                ORDER BY created_at DESC, id DESC LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['created_at']}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def mark_read(self, user_id: int, public_id: str) -> bool:
        row = await self._db.fetch_one(
            "SELECT id FROM notifications WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        if row is None:
            return False
        await self._db.execute(
            "UPDATE notifications SET read_at = ? WHERE id = ?", (utc_now_iso(), row["id"])
        )
        return True

    # -- live stream replay ------------------------------------------------

    async def events_since(self, user_id: int, last_event_id: str | None) -> list[dict[str, Any]]:
        """Replay events for this user newer than `last_event_id` (a ULID,
        which sorts lexicographically by time, so string comparison is
        enough) for the `Last-Event-ID` reconnection path.
        """

        if last_event_id:
            rows = await self._events_db.fetch_all(
                """SELECT * FROM events WHERE user_id = ? AND event_id > ?
                   ORDER BY event_id ASC""",
                (user_id, last_event_id),
            )
        else:
            rows = await self._events_db.fetch_all(
                """SELECT * FROM events WHERE user_id = ?
                   ORDER BY event_id DESC LIMIT 50""",
                (user_id,),
            )
            rows = list(reversed(rows))
        return [dict(r) for r in rows]
