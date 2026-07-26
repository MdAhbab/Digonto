"""Watched portals. `portals` in `app.db` (docs/database.md section 3.3).

Serves both the public Truth Ledger watch list (`GET /ledger/portals`) and
the moderator's portal management (`GET/POST/PATCH /mod/portals`); it is the
same table read and written from two different trust levels, not two tables.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class PortalRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def list_all(self) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM portals ORDER BY last_fetch_at DESC NULLS LAST, label"
        )
        return [dict(r) for r in rows]

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM portals WHERE public_id = ?", (public_id,))
        return dict(row) if row else None

    async def get(self, portal_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM portals WHERE id = ?", (portal_id,))
        return dict(row) if row else None

    async def silent_since(self, hours: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT * FROM portals WHERE enabled = 1 AND
               (last_fetch_at IS NULL OR
                julianday('now') - julianday(last_fetch_at) > ? / 24.0)""",
            (hours,),
        )
        return [dict(r) for r in rows]

    async def create(
        self,
        *,
        url: str,
        kind: str,
        country_code: str | None,
        label: str,
        parser_key: str,
        crawl_cron: str,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO portals
               (public_id, url, kind, country_code, label, parser_key, crawl_cron,
                enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)""",
            (public_id, url, kind, country_code, label, parser_key, crawl_cron, now),
        )
        result = await self.get_by_public_id(public_id)
        assert result is not None
        return result

    async def register_discovered(
        self,
        *,
        url: str,
        parent: dict[str, Any],
        crawl_cron: str = "0 4 */2 * *",
    ) -> int | None:
        """Register a page the crawler found under `parent`. Returns its id.

        Idempotent by URL: `INSERT OR IGNORE` then read back, so a page linked
        from several parents is registered once and re-running a crawl adds
        nothing. Returns None only if the row can neither be inserted nor found,
        which would mean the URL was deleted concurrently.

        Kind and country are inherited: a page one click inside
        `immi.homeaffairs.gov.au/.../student-500` is the same kind of source about
        the same country as its parent, and guessing otherwise from the URL would
        be worse than inheriting.

        The default cron is deliberately slower than a root's. Child pages are
        numerous and change less often than the index that links them, so they
        should not multiply the crawl budget by MAX_CHILD_PAGES.
        """
        label = self._child_label(url)
        await self._db.execute(
            """INSERT OR IGNORE INTO portals
               (public_id, url, kind, country_code, label, parser_key, crawl_cron,
                enabled, created_at, discovered_from_portal_id, discovered_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)""",
            (
                new_ulid(), url, parent["kind"], parent["country_code"], label,
                parent["parser_key"], crawl_cron, utc_now_iso(), parent["id"],
                utc_now_iso(),
            ),
        )
        row = await self._db.fetch_one("SELECT id FROM portals WHERE url = ?", (url,))
        return int(row[0]) if row else None

    @staticmethod
    def _child_label(url: str) -> str:
        """A short, human label for the UI, e.g. 'gov.uk/student-visa/money'."""
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.netloc.removeprefix("www.")
        path = parsed.path.rstrip("/")
        label = f"{host}{path}"
        # `portals.label` is shown inline in citations and the watch list, so it
        # is trimmed from the left, keeping the end of the path that identifies
        # the page rather than the site prefix that repeats.
        return label if len(label) <= 60 else f"{host}/…{label[-48:]}"

    async def roots_for_expansion(self) -> list[dict[str, Any]]:
        """Enabled registry portals, i.e. those the crawler may expand from."""
        rows = await self._db.fetch_all(
            "SELECT * FROM portals WHERE enabled = 1 AND discovered_at IS NULL"
        )
        return [dict(r) for r in rows]

    async def patch(self, portal_id: int, fields: dict[str, Any]) -> None:
        if not fields:
            return
        sets = ", ".join(f"{k} = ?" for k in fields.keys())
        await self._db.execute(
            f"UPDATE portals SET {sets} WHERE id = ?", (*fields.values(), portal_id)
        )

    async def count_enabled(self) -> int:
        val = await self._db.fetch_val("SELECT COUNT(*) FROM portals WHERE enabled = 1")
        return int(val or 0)

    async def count_silent(self, hours: int = 48) -> int:
        val = await self._db.fetch_val(
            """SELECT COUNT(*) FROM portals WHERE enabled = 1 AND
               (last_fetch_at IS NULL OR
                julianday('now') - julianday(last_fetch_at) > ? / 24.0)""",
            (hours,),
        )
        return int(val or 0)
