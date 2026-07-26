"""`conversations` in `app.db` (docs/database.md section 3.4)."""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class ConversationRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC",
            (user_id,),
        )
        return [dict(r) for r in rows]

    async def get_by_public_id(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM conversations WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def create(self, user_id: int, title: str | None) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO conversations (public_id, user_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (public_id, user_id, title, now, now),
        )
        result = await self.get_by_public_id(user_id, public_id)
        assert result is not None
        return result

    async def touch(self, conversation_id: int) -> None:
        await self._db.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (utc_now_iso(), conversation_id),
        )

    async def set_title_if_blank(self, conversation_id: int, title: str) -> None:
        await self._db.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND (title IS NULL OR title = '')",
            (title, conversation_id),
        )

    async def delete(self, user_id: int, public_id: str) -> bool:
        conv = await self.get_by_public_id(user_id, public_id)
        if conv is None:
            return False
        await self._db.execute(
            "DELETE FROM conversations WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return True
