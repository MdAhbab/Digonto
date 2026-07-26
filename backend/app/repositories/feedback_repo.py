"""Product feedback. `feedback` in `app.db` (020_feedback.sql).

Distinct from `answer_feedback` (004_qa.sql), which is a thumbs up or down on one
specific answer and is joined to that answer. This table is the general "something
about this product is wrong or confusing" channel, is not tied to any answer, and
accepts submissions from students who are not signed in.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso

# Longest message accepted. Long enough for a paragraph of detail in Bangla, where a
# conjunct costs more bytes than a Latin character, and short enough that the field
# cannot be used to push arbitrary content into the database.
MAX_MESSAGE_CHARS = 4000
MAX_PAGE_CHARS = 200
MAX_EMAIL_CHARS = 254  # RFC 5321 maximum length of a forward path


class FeedbackRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: int | None,
        kind: str,
        message: str,
        page: str | None,
        lang: str,
        contact_email: str | None,
    ) -> dict[str, Any]:
        public_id = f"FB-{new_ulid()}"
        await self._db.execute(
            """INSERT INTO feedback
                 (public_id, user_id, kind, message, page, lang, contact_email, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                public_id,
                user_id,
                kind,
                message[:MAX_MESSAGE_CHARS],
                (page or None) and page[:MAX_PAGE_CHARS],
                lang,
                (contact_email or None) and contact_email[:MAX_EMAIL_CHARS],
                utc_now_iso(),
            ),
        )
        row = await self._db.fetch_one("SELECT * FROM feedback WHERE public_id = ?", (public_id,))
        assert row is not None
        return dict(row)

    async def count_recent_for_user(self, user_id: int, *, since: str) -> int:
        value = await self._db.fetch_val(
            "SELECT COUNT(*) FROM feedback WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        )
        return int(value or 0)

    async def count_recent_anonymous(self, *, since: str) -> int:
        """Submissions with no account attached, across everyone.

        There is no per-person key to rate-limit an anonymous submitter by. An IP
        address would be one, but storing it to throttle a feedback form would mean
        collecting more about the person than the feedback does, which is the wrong
        trade for this feature. A shared ceiling is the honest alternative: it can be
        exhausted by one bad actor, and the failure mode is that a form says "try
        again later" rather than that anybody's data is retained.
        """
        value = await self._db.fetch_val(
            "SELECT COUNT(*) FROM feedback WHERE user_id IS NULL AND created_at >= ?",
            (since,),
        )
        return int(value or 0)

    async def list_for_review(
        self, *, unreviewed_only: bool = False, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        where = "WHERE f.reviewed_at IS NULL" if unreviewed_only else ""
        rows = await self._db.fetch_all(
            f"""SELECT f.*, u.public_id AS user_public_id
                  FROM feedback f
                  LEFT JOIN users u ON u.id = f.user_id
                  {where}
                 ORDER BY f.reviewed_at IS NULL DESC, f.created_at DESC
                 LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        return [dict(r) for r in rows]

    async def count_all(self, *, unreviewed_only: bool = False) -> int:
        where = "WHERE reviewed_at IS NULL" if unreviewed_only else ""
        value = await self._db.fetch_val(f"SELECT COUNT(*) FROM feedback {where}")
        return int(value or 0)

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM feedback WHERE public_id = ?", (public_id,))
        return dict(row) if row else None

    async def mark_reviewed(
        self, public_id: str, *, reviewer_id: int, disposition: str
    ) -> dict[str, Any] | None:
        await self._db.execute(
            """UPDATE feedback
                  SET reviewed_at = ?, reviewed_by = ?, disposition = ?
                WHERE public_id = ?""",
            (utc_now_iso(), reviewer_id, disposition, public_id),
        )
        return await self.get_by_public_id(public_id)
