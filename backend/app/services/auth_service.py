"""Signup, login, session, password change, consents, export and deletion.

Business rules from api_contract.md section 3: identical failure message and
near-identical timing for "no such user" and "wrong password" (so the
endpoint cannot enumerate accounts), a banned account fails with `423` and
the moderator's bilingual reason, and a replayed (already-rotated) refresh
token revokes its whole family, which is the standard defence against a
stolen refresh token.

Integration note: this module calls `app.security.passwords`,
`app.security.tokens`, and `app.errors`, all owned by a concurrent build
task. Signatures used here are the most conventional shape for each
function; see the final report for the exact calls made, in case the real
signatures differ.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.errors import AccountBanned, Conflict, NotFound, Unauthorized
from app.events.bus import EventBus, EventType
from app.repositories._util import new_ulid, utc_now_iso
from app.repositories.user_repo import UserRepo
from app.security.passwords import check_common_password, hash_password, verify_password
from app.security.tokens import create_access_token, hash_refresh_token, new_refresh_token

# A fixed, valid-looking hash to run `verify_password` against when the email
# does not exist, so a lookup miss costs about the same wall-clock time as a
# wrong password on a real account. Never a valid password for any real user.
_DUMMY_HASH = "$argon2id$v=19$m=65536,t=3,p=4$ZGlnb250b3NhbHQ$Z8x1n8h3vQwq2m2s5r8z1w"


class AuthService:
    def __init__(self, users: UserRepo, bus: EventBus, settings: Settings) -> None:
        self._users = users
        self._bus = bus
        self._settings = settings

    # -- shape helpers -----------------------------------------------------

    async def _to_user_model(self, row: dict) -> dict:
        consents = await self._users.get_consents(row["id"])
        return {
            "id": row["public_id"],
            "email": row["email"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["status"],
            "lang_pref": row["lang_pref"],
            "theme_pref": row["theme_pref"],
            "created_at": row["created_at"],
            "profile_complete": False,
            "consents": {
                "improve_model": consents["improve_model"],
                "usage_analytics": consents["usage_analytics"],
            },
        }

    def _refresh_expiry(self) -> str:
        dt = datetime.now(timezone.utc) + timedelta(days=self._settings.jwt_refresh_ttl_days)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    async def _issue_tokens(self, user_row: dict, *, user_agent: str | None, ip_hash: str | None):
        access_token = create_access_token(user_row["public_id"], user_row["role"])
        refresh_plain = new_refresh_token()
        family_id = new_ulid()
        await self._users.create_refresh_token(
            user_id=user_row["id"],
            token_hash=hash_refresh_token(refresh_plain),
            family_id=family_id,
            expires_at=self._refresh_expiry(),
            user_agent=user_agent,
            ip_hash=ip_hash,
        )
        return access_token, refresh_plain

    # -- signup / login ------------------------------------------------------

    async def signup(
        self, *, email: str, password: str, display_name: str, user_agent: str | None, ip_hash: str | None
    ) -> tuple[dict, str, str, int]:
        email = email.strip().lower()
        if await self._users.email_exists(email):
            raise Conflict(
                detail_en="An account already exists for that email.",
                detail_bn="এই ইমেইলে ইতিমধ্যে একটি অ্যাকাউন্ট আছে।",
            )
        if len(password) < 8 or check_common_password(password):
            raise Conflict(
                detail_en="Choose a password with at least 8 characters that is not one of the "
                "most common passwords.",
                detail_bn="অন্তত ৮ অক্ষরের এমন পাসওয়ার্ড দিন যা সাধারণ পাসওয়ার্ডের তালিকায় নেই।",
            )
        password_hash = hash_password(password)
        user_row = await self._users.create(
            email=email, password_hash=password_hash, display_name=display_name
        )
        access_token, refresh_plain = await self._issue_tokens(
            user_row, user_agent=user_agent, ip_hash=ip_hash
        )
        await self._bus.publish(
            EventType.PROFILE_UPDATED,
            user_id=user_row["id"],
            subject_type="user",
            subject_id=user_row["public_id"],
            payload={"action": "signup"},
        )
        user_model = await self._to_user_model(user_row)
        return user_model, access_token, refresh_plain, self._settings.jwt_access_ttl_seconds

    async def login(
        self, *, email: str, password: str, user_agent: str | None, ip_hash: str | None
    ) -> tuple[dict, str, str, int]:
        email = email.strip().lower()
        row = await self._users.get_by_email(email)
        if row is None:
            verify_password(password, _DUMMY_HASH)
            raise Unauthorized(
                detail_en="Email or password is incorrect.",
                detail_bn="ইমেইল অথবা পাসওয়ার্ড সঠিক নয়।",
            )
        if row["status"] == "banned":
            raise AccountBanned(
                detail_en=row.get("status_reason_en") or "This account has been banned.",
                detail_bn=row.get("status_reason_bn") or "এই অ্যাকাউন্টটি নিষিদ্ধ করা হয়েছে।",
            )
        if not verify_password(password, row["password_hash"]):
            await self._users.record_failed_login(row["id"])
            raise Unauthorized(
                detail_en="Email or password is incorrect.",
                detail_bn="ইমেইল অথবা পাসওয়ার্ড সঠিক নয়।",
            )
        await self._users.reset_failed_logins(row["id"])
        await self._users.touch_last_seen(row["id"])
        access_token, refresh_plain = await self._issue_tokens(
            row, user_agent=user_agent, ip_hash=ip_hash
        )
        user_model = await self._to_user_model(row)
        return user_model, access_token, refresh_plain, self._settings.jwt_access_ttl_seconds

    async def refresh(
        self, *, refresh_plain: str, user_agent: str | None, ip_hash: str | None
    ) -> tuple[str, str, int]:
        token_hash = hash_refresh_token(refresh_plain)
        token_row = await self._users.get_refresh_token(token_hash)
        if token_row is None:
            raise Unauthorized(
                detail_en="Session expired. Please log in again.",
                detail_bn="সেশনের মেয়াদ শেষ। আবার লগইন করুন।",
            )
        if token_row["revoked_at"] is not None:
            # Reuse of an already-rotated token: assume theft, burn the family.
            await self._users.revoke_family(token_row["family_id"])
            raise Unauthorized(
                detail_en="Session invalidated for security. Please log in again.",
                detail_bn="নিরাপত্তার জন্য সেশন বাতিল হয়েছে। আবার লগইন করুন।",
            )
        user_row = await self._users.get_by_id(token_row["user_id"])
        if user_row is None or user_row["status"] == "banned":
            raise Unauthorized(
                detail_en="Session expired. Please log in again.",
                detail_bn="সেশনের মেয়াদ শেষ। আবার লগইন করুন।",
            )
        new_access = create_access_token(user_row["public_id"], user_row["role"])
        new_plain = new_refresh_token()
        new_id = await self._users.create_refresh_token(
            user_id=user_row["id"],
            token_hash=hash_refresh_token(new_plain),
            family_id=token_row["family_id"],
            expires_at=self._refresh_expiry(),
            user_agent=user_agent,
            ip_hash=ip_hash,
        )
        await self._users.mark_replaced(token_row["id"], new_id)
        return new_access, new_plain, self._settings.jwt_access_ttl_seconds

    async def logout(self, refresh_plain: str) -> None:
        token_row = await self._users.get_refresh_token(hash_refresh_token(refresh_plain))
        if token_row is not None:
            await self._users.revoke_family(token_row["family_id"])

    async def get_session_user(self, user_id: int) -> dict:
        row = await self._users.get_by_id(user_id)
        if row is None:
            raise Unauthorized(
                detail_en="Not signed in.", detail_bn="লগইন করা নেই।"
            )
        return await self._to_user_model(row)

    # -- account management ---------------------------------------------

    async def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        row = await self._users.get_by_id(user_id)
        if row is None or not verify_password(current_password, row["password_hash"]):
            raise Unauthorized(
                detail_en="Current password is incorrect.",
                detail_bn="বর্তমান পাসওয়ার্ড সঠিক নয়।",
            )
        if len(new_password) < 8 or check_common_password(new_password):
            raise Conflict(
                detail_en="Choose a new password with at least 8 characters that is not one of "
                "the most common passwords.",
                detail_bn="নতুন পাসওয়ার্ড অন্তত ৮ অক্ষরের এবং সাধারণ তালিকার বাইরে হতে হবে।",
            )
        await self._users.update_password(user_id, hash_password(new_password))

    async def update_consents(self, user_id: int, *, improve_model: bool, usage_analytics: bool) -> dict:
        await self._users.set_consent(user_id, "improve_model", improve_model)
        await self._users.set_consent(user_id, "usage_analytics", usage_analytics)
        row = await self._users.get_by_id(user_id)
        assert row is not None
        return await self._to_user_model(row)

    async def withdraw_learning_consent(self, user_id: int, *, app_db, learn_db) -> dict:
        """Turn off `improve_model` and actually remove what it collected.

        Three steps, in this order. First flip the consent, so nothing new is
        captured while the rest runs. Second, find which adapters already
        consumed this student's samples, because that has to be read before
        the rows are deleted. Third, delete the samples and mark those
        adapters for a reviewer.

        The adapter is flagged rather than rolled back automatically. A
        rollback removes the accumulated learning of every other consenting
        student too, so the trade is a person's to make; the moderator
        console surfaces the flag at `GET /mod/adapters`.
        """
        now = utc_now_iso()
        await self._users.set_consent(user_id, "improve_model", False)

        # replay_samples references answers only softly, by public_id across
        # database files, so the ids have to be gathered from app.db first.
        answer_public_ids = [
            r["public_id"]
            for r in await app_db.fetch_all(
                """SELECT a.public_id FROM answers a
                   JOIN questions q ON q.id = a.question_id
                   WHERE q.user_id = ?""",
                (user_id,),
            )
        ]
        if not answer_public_ids:
            return {
                "status": "withdrawn",
                "withdrawn_at": now,
                "samples_deleted": 0,
                "adapters_flagged": 0,
                "adapter_tags": [],
            }

        placeholders = ", ".join("?" for _ in answer_public_ids)
        params = tuple(answer_public_ids)

        sample_rows = await learn_db.fetch_all(
            f"""SELECT id, exported_in FROM replay_samples
                WHERE source_answer_public_id IN ({placeholders})""",
            params,
        )
        # exported_in holds the tag of the adapter a sample was trained into,
        # and is NULL for samples that were collected but never used.
        tags = sorted({r["exported_in"] for r in sample_rows if r["exported_in"]})

        await learn_db.execute(
            f"DELETE FROM replay_samples WHERE source_answer_public_id IN ({placeholders})",
            params,
        )

        for tag in tags:
            await learn_db.execute(
                """UPDATE adapters
                   SET notes = COALESCE(notes || ' | ', '') || ?
                   WHERE tag = ?""",
                (
                    f"consent withdrawn {now}: trained on samples since deleted, "
                    f"needs review for retrain or rollback",
                    tag,
                ),
            )

        await self._bus.publish(
            EventType.PROFILE_UPDATED,
            user_id=user_id,
            subject_type="user",
            subject_id=str(user_id),
            payload={
                "action": "learning_consent_withdrawn",
                "withdrawn_at": now,
                "samples_deleted": len(sample_rows),
                "adapters_flagged": tags,
            },
        )

        return {
            "status": "withdrawn",
            "withdrawn_at": now,
            "samples_deleted": len(sample_rows),
            "adapters_flagged": len(tags),
            "adapter_tags": tags,
        }

    async def request_export(self, user_id: int) -> dict:
        now = utc_now_iso()
        await self._bus.publish(
            EventType.PROFILE_UPDATED,
            user_id=user_id,
            subject_type="user",
            subject_id=str(user_id),
            payload={"action": "export_requested", "requested_at": now},
        )
        return {"status": "processing", "requested_at": now}

    async def delete_account(
        self, user_id: int, current_password: str, *, app_db, events_db, learn_db
    ) -> dict:
        """Hard delete, in the order docs/database.md section 7 specifies:
        capture the trace needed for cross-database cleanup, anonymise
        `events.db`, delete traceable `learn.db` replay samples, then delete
        the `app.db` row (FK cascades take care of the rest of `app.db`).
        """

        row = await self._users.get_by_id(user_id)
        if row is None:
            raise NotFound(detail_en="Account not found.", detail_bn="অ্যাকাউন্ট পাওয়া যায়নি।")
        if not verify_password(current_password, row["password_hash"]):
            raise Unauthorized(
                detail_en="Current password is incorrect.",
                detail_bn="বর্তমান পাসওয়ার্ড সঠিক নয়।",
            )
        now = utc_now_iso()

        # `learn.db.replay_samples` is only soft-referenced from app.db answers
        # by public_id, so the trace has to be captured before the cascade
        # delete removes those answer rows.
        answer_public_ids = [
            r["public_id"]
            for r in await app_db.fetch_all(
                """SELECT a.public_id FROM answers a
                   JOIN questions q ON q.id = a.question_id
                   WHERE q.user_id = ?""",
                (user_id,),
            )
        ]
        if answer_public_ids:
            placeholders = ", ".join("?" for _ in answer_public_ids)
            await learn_db.execute(
                f"DELETE FROM replay_samples WHERE source_answer_public_id IN ({placeholders})",
                tuple(answer_public_ids),
            )

        # events.db: anonymise rather than delete, the audit trail must survive.
        await events_db.execute("UPDATE events SET user_id = NULL WHERE user_id = ?", (user_id,))

        await self._users.hard_delete(user_id)
        await self._bus.publish(
            EventType.USER_DELETED,
            user_id=None,
            subject_type="user",
            subject_id=row["public_id"],
            payload={"deleted_at": now},
        )
        return {"status": "accepted", "requested_at": now}
