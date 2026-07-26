"""Identity, refresh tokens, and consents. `users`, `refresh_tokens`,
`consents` in `app.db` (docs/database.md section 3.1).
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class UserRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- reads ---------------------------------------------------------

    async def get_by_id(self, user_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,)
        )
        return dict(row) if row else None

    async def get_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE public_id = ? AND deleted_at IS NULL", (public_id,)
        )
        return dict(row) if row else None

    async def get_by_email(self, email: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM users WHERE email = ? AND deleted_at IS NULL", (email,)
        )
        return dict(row) if row else None

    async def email_exists(self, email: str) -> bool:
        val = await self._db.fetch_val(
            "SELECT 1 FROM users WHERE email = ? AND deleted_at IS NULL", (email,)
        )
        return val is not None

    # -- writes ----------------------------------------------------------

    async def create(
        self, *, email: str, password_hash: str, display_name: str, is_demo: bool = False
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO users
               (public_id, email, password_hash, display_name, role, status,
                email_verified, lang_pref, theme_pref, is_demo, failed_logins,
                created_at)
               VALUES (?, ?, ?, ?, 'student', 'active', 0, 'bn', 'system', ?, 0, ?)""",
            (public_id, email, password_hash, display_name, int(is_demo), now),
        )
        created = await self.get_by_id(row_id)
        assert created is not None
        return created

    async def update_password(self, user_id: int, password_hash: str) -> None:
        await self._db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id)
        )

    async def update_prefs(
        self, user_id: int, *, lang_pref: str | None = None, theme_pref: str | None = None
    ) -> None:
        if lang_pref is not None:
            await self._db.execute(
                "UPDATE users SET lang_pref = ? WHERE id = ?", (lang_pref, user_id)
            )
        if theme_pref is not None:
            await self._db.execute(
                "UPDATE users SET theme_pref = ? WHERE id = ?", (theme_pref, user_id)
            )

    async def touch_last_seen(self, user_id: int) -> None:
        await self._db.execute(
            "UPDATE users SET last_seen_at = ? WHERE id = ?", (utc_now_iso(), user_id)
        )

    async def record_failed_login(self, user_id: int) -> None:
        await self._db.execute(
            "UPDATE users SET failed_logins = failed_logins + 1 WHERE id = ?", (user_id,)
        )

    async def reset_failed_logins(self, user_id: int) -> None:
        await self._db.execute(
            "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = ?", (user_id,)
        )

    async def set_status(
        self,
        user_id: int,
        *,
        status: str,
        reason_en: str | None = None,
        reason_bn: str | None = None,
        suspended_until: str | None = None,
    ) -> None:
        await self._db.execute(
            """UPDATE users SET status = ?, status_reason_en = ?, status_reason_bn = ?,
               suspended_until = ? WHERE id = ?""",
            (status, reason_en, reason_bn, suspended_until, user_id),
        )

    async def hard_delete(self, user_id: int) -> None:
        """Deletes the `users` row. FK cascades handle the rest of `app.db`.

        Callers (the auth service) are responsible for the cross-database
        cleanup in `events.db` and `learn.db`, which are not foreign-key
        related and are not this repository's concern.
        """

        await self._db.execute("DELETE FROM users WHERE id = ?", (user_id,))

    # -- consents ----------------------------------------------------------

    async def get_consents(self, user_id: int) -> dict[str, bool]:
        rows = await self._db.fetch_all(
            "SELECT kind, granted FROM consents WHERE user_id = ?", (user_id,)
        )
        out = {"improve_model": False, "usage_analytics": False, "email_alerts": False}
        for row in rows:
            out[row["kind"]] = bool(row["granted"])
        return out

    async def set_consent(self, user_id: int, kind: str, granted: bool) -> None:
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO consents (user_id, kind, granted, changed_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT (user_id, kind) DO UPDATE SET granted = excluded.granted,
               changed_at = excluded.changed_at""",
            (user_id, kind, int(granted), now),
        )

    # -- refresh tokens ------------------------------------------------------

    async def create_refresh_token(
        self,
        *,
        user_id: int,
        token_hash: str,
        family_id: str,
        expires_at: str,
        user_agent: str | None,
        ip_hash: str | None,
    ) -> int:
        return await self._db.execute(
            """INSERT INTO refresh_tokens
               (user_id, token_hash, family_id, issued_at, expires_at, user_agent, ip_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, token_hash, family_id, utc_now_iso(), expires_at, user_agent, ip_hash),
        )

    async def get_refresh_token(self, token_hash: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM refresh_tokens WHERE token_hash = ?", (token_hash,)
        )
        return dict(row) if row else None

    async def mark_replaced(self, old_id: int, new_id: int) -> None:
        await self._db.execute(
            "UPDATE refresh_tokens SET revoked_at = ?, replaced_by_id = ? WHERE id = ?",
            (utc_now_iso(), new_id, old_id),
        )

    async def revoke_family(self, family_id: str) -> None:
        await self._db.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE family_id = ? AND revoked_at IS NULL",
            (utc_now_iso(), family_id),
        )

    async def revoke_all_refresh_tokens(self, user_id: int) -> None:
        """Sign this account out of every device.

        Used when deletion is scheduled. The account stays recoverable, but getting
        back in has to be a deliberate act by whoever knows the password, which is
        exactly the case where the request came from a session that should not have
        had access in the first place.
        """
        await self._db.execute(
            "UPDATE refresh_tokens SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
            (utc_now_iso(), user_id),
        )

    # -- scheduled deletion (019_account_deletion_window.sql) --------------

    async def schedule_deletion(
        self, user_id: int, *, requested_at: str, scheduled_for: str
    ) -> None:
        # `deletion_requested_at IS NULL` in the WHERE clause makes this idempotent
        # at the storage layer as well as in the service, so two concurrent requests
        # cannot push the date out twice.
        await self._db.execute(
            """UPDATE users
                  SET deletion_requested_at = ?, deletion_scheduled_for = ?
                WHERE id = ? AND deletion_requested_at IS NULL""",
            (requested_at, scheduled_for, user_id),
        )

    async def cancel_deletion(self, user_id: int) -> None:
        await self._db.execute(
            """UPDATE users
                  SET deletion_requested_at = NULL, deletion_scheduled_for = NULL
                WHERE id = ?""",
            (user_id,),
        )

    async def list_deletions_due(self, *, now: str, limit: int = 200) -> list[dict[str, Any]]:
        """Accounts whose window has expired, oldest request first.

        Bounded because the purge does per-account file deletion and cross-database
        writes; a backlog is worked through over consecutive nights rather than in
        one sweep that could run for an unbounded time.
        """
        rows = await self._db.fetch_all(
            """SELECT id, public_id, deletion_requested_at, deletion_scheduled_for
                 FROM users
                WHERE deletion_scheduled_for IS NOT NULL
                  AND deletion_scheduled_for <= ?
                ORDER BY deletion_requested_at
                LIMIT ?""",
            (now, limit),
        )
        return [dict(r) for r in rows]
