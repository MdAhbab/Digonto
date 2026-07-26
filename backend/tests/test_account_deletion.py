"""The 30-day deletion window, and what survives the purge.

These tests exist because the interface makes a promise. It tells a student their
data is erased within 30 days, and that only two things are kept: events with the
user id removed, and aggregate counts that name nobody. A test suite is the only
thing that stops that from drifting into a claim nobody checks.

Run against a real SQLite file with every migration applied, not against mocks,
because most of what needs proving is what the foreign-key cascades do.
"""

from __future__ import annotations

import pathlib
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.repositories._util import new_ulid, utc_now_iso
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password
from app.services.auth_service import DELETION_WINDOW_DAYS, AuthService
from app.workers import insights, retention


class _FakeBus:
    """Records publishes instead of needing Redis."""

    def __init__(self) -> None:
        self.published: list[tuple] = []

    async def publish(self, event_type, **kwargs):  # noqa: ANN001, ANN003
        self.published.append((event_type, kwargs))

    def types(self) -> list[str]:
        return [getattr(t, "value", str(t)) for t, _ in self.published]


@pytest.fixture
async def env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        settings = Settings(vault_master_key="0" * 64, private_dir=base / "private")
        bus = _FakeBus()
        users = UserRepo(dbs.app)
        auth = AuthService(users, bus, settings)
        try:
            yield dbs, users, auth, bus, settings, base
        finally:
            await dbs.close_all()


async def _make_student(users: UserRepo, dbs: Databases, *, email: str = "s@example.com") -> dict:
    row = await users.create(
        email=email, password_hash=hash_password("correct horse battery"), display_name="Student"
    )
    return row


async def _ask_a_question(dbs: Databases, user_id: int, text: str = "কত টাকা দেখাতে হবে?") -> None:
    """A question needs a conversation, and `questions` stores raw plus normalised text."""
    convo_pid = f"CONV-{new_ulid()}"
    await dbs.app.execute(
        """INSERT INTO conversations (public_id, user_id, created_at, updated_at)
           VALUES (?,?,?,?)""",
        (convo_pid, user_id, utc_now_iso(), utc_now_iso()),
    )
    convo_id = await dbs.app.fetch_val(
        "SELECT id FROM conversations WHERE public_id = ?", (convo_pid,)
    )
    await dbs.app.execute(
        """INSERT INTO questions
             (public_id, conversation_id, user_id, text_raw, text_normalised,
              lang_detected, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (f"Q-{new_ulid()}", convo_id, user_id, text, text, "bn", utc_now_iso()),
    )


# --- scheduling --------------------------------------------------------------


@pytest.mark.asyncio
async def test_deletion_is_scheduled_not_performed(env):
    dbs, users, auth, bus, _s, _b = env
    user = await _make_student(users, dbs)

    receipt = await auth.request_account_deletion(user["id"], "correct horse battery")

    assert receipt["status"] == "scheduled"
    assert receipt["window_days"] == DELETION_WINDOW_DAYS
    # The row is still there. This is the whole point: the previous behaviour
    # destroyed it inline, with the vault keys, and nothing could bring it back.
    assert await users.get_by_id(user["id"]) is not None

    scheduled = datetime.strptime(receipt["scheduled_for"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    days = (scheduled - datetime.now(UTC)).days
    assert days in (DELETION_WINDOW_DAYS - 1, DELETION_WINDOW_DAYS)


@pytest.mark.asyncio
async def test_the_wrong_password_does_not_schedule_anything(env):
    from app.errors import Unauthorized

    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)

    with pytest.raises(Unauthorized):
        await auth.request_account_deletion(user["id"], "not the password")

    row = await users.get_by_id(user["id"])
    assert row["deletion_requested_at"] is None


@pytest.mark.asyncio
async def test_asking_twice_does_not_extend_the_window(env):
    """A student who re-confirms on day 29 must not buy 30 more days of retention."""
    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)

    first = await auth.request_account_deletion(user["id"], "correct horse battery")
    second = await auth.request_account_deletion(user["id"], "correct horse battery")

    assert second["status"] == "already_scheduled"
    assert second["scheduled_for"] == first["scheduled_for"]


@pytest.mark.asyncio
async def test_scheduling_revokes_every_session(env):
    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)
    await users.create_refresh_token(
        user_id=user["id"], token_hash="h1", family_id=new_ulid(),
        expires_at="2099-01-01T00:00:00Z", user_agent=None, ip_hash=None,
    )

    await auth.request_account_deletion(user["id"], "correct horse battery")

    live = await dbs.app.fetch_val(
        "SELECT COUNT(*) FROM refresh_tokens WHERE user_id = ? AND revoked_at IS NULL",
        (user["id"],),
    )
    assert live == 0, "a session that could still act on a scheduled-for-deletion account"


@pytest.mark.asyncio
async def test_cancelling_clears_the_schedule_and_needs_no_password(env):
    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)
    await auth.request_account_deletion(user["id"], "correct horse battery")

    receipt = await auth.cancel_account_deletion(user["id"])

    assert receipt["status"] == "cancelled"
    row = await users.get_by_id(user["id"])
    assert row["deletion_requested_at"] is None
    assert row["deletion_scheduled_for"] is None


@pytest.mark.asyncio
async def test_cancelling_when_nothing_is_scheduled_is_not_an_error(env):
    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)
    assert (await auth.cancel_account_deletion(user["id"]))["status"] == "not_scheduled"


@pytest.mark.asyncio
async def test_the_scheduled_date_is_visible_on_the_account(env):
    """The interface can only warn the student if the API tells it."""
    dbs, users, auth, _bus, _s, _b = env
    user = await _make_student(users, dbs)
    await auth.request_account_deletion(user["id"], "correct horse battery")

    model = await auth._to_user_model(await users.get_by_id(user["id"]))
    assert model["deletion_scheduled_for"] is not None


# --- the purge ---------------------------------------------------------------


async def _schedule_in_the_past(dbs: Databases, user_id: int, *, days_ago: int = 1) -> None:
    past = (datetime.now(UTC) - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await dbs.app.execute(
        "UPDATE users SET deletion_requested_at = ?, deletion_scheduled_for = ? WHERE id = ?",
        (past, past, user_id),
    )


@pytest.mark.asyncio
async def test_an_account_inside_its_window_is_not_purged(env):
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    await auth.request_account_deletion(user["id"], "correct horse battery")

    assert await retention.purge_due_accounts(dbs, bus, settings) == 0
    assert await users.get_by_id(user["id"]) is not None


@pytest.mark.asyncio
async def test_an_account_past_its_window_is_purged(env):
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    await _schedule_in_the_past(dbs, user["id"])

    assert await retention.purge_due_accounts(dbs, bus, settings) == 1
    assert await users.get_by_id(user["id"]) is None
    assert "user.deleted" in bus.types()


@pytest.mark.asyncio
async def test_the_purge_is_idempotent(env):
    """The sweep runs nightly and may be run by hand; twice must equal once."""
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    await _schedule_in_the_past(dbs, user["id"])

    assert await retention.purge_due_accounts(dbs, bus, settings) == 1
    assert await retention.purge_due_accounts(dbs, bus, settings) == 0


@pytest.mark.asyncio
async def test_one_failing_account_does_not_block_the_others(env):
    """A backlog must not be held up by a single bad row."""
    dbs, users, auth, bus, settings, _b = env
    good = await _make_student(users, dbs, email="a@example.com")
    other = await _make_student(users, dbs, email="b@example.com")
    await _schedule_in_the_past(dbs, good["id"], days_ago=2)
    await _schedule_in_the_past(dbs, other["id"], days_ago=1)

    real_purge = AuthService.purge_account
    calls = {"n": 0}

    async def flaky(self, user_id, **kwargs):  # noqa: ANN001, ANN003
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("disk on fire")
        return await real_purge(self, user_id, **kwargs)

    AuthService.purge_account = flaky
    try:
        purged = await retention.purge_due_accounts(dbs, bus, settings)
    finally:
        AuthService.purge_account = real_purge

    assert purged == 1, "the second account must still be deleted"
    # The failed one is still scheduled, so tonight's failure is retried tomorrow
    # rather than being silently treated as done.
    assert await users.get_by_id(good["id"]) is not None
    assert (await users.get_by_id(good["id"]))["deletion_scheduled_for"] is not None


@pytest.mark.asyncio
async def test_the_purge_deletes_the_student_data_the_promise_covers(env):
    """Profile, questions, answers, documents and targets all go.

    Written against the cascade rather than trusting it, because "ON DELETE CASCADE"
    in a migration is a claim about behaviour that only a test verifies.
    """
    dbs, users, auth, bus, settings, base = env
    user = await _make_student(users, dbs)
    uid = user["id"]

    vault_file = base / "doc.enc"
    vault_file.write_bytes(b"ciphertext")
    await dbs.app.execute(
        """INSERT INTO documents
             (public_id, user_id, kind, original_name, storage_path, mime_type,
              byte_size, sha256, wrapped_dek, nonce, uploaded_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (f"DOC-{new_ulid()}", uid, "passport", "p.pdf", str(vault_file),
         "application/pdf", 9, "x" * 64, b"k", b"n", utc_now_iso()),
    )
    await _ask_a_question(dbs, uid)

    await _schedule_in_the_past(dbs, uid)
    receipt = await retention.purge_due_accounts(dbs, bus, settings)
    assert receipt == 1

    for table in ("questions", "documents", "profiles", "student_targets", "consents"):
        left = await dbs.app.fetch_val(f"SELECT COUNT(*) FROM {table} WHERE user_id = ?", (uid,))
        assert left == 0, f"{table} still holds rows for a purged account"
    # The encrypted body on disk is gone too. The cascade cannot reach a file.
    assert not vault_file.exists(), "an encrypted document survived the purge"


@pytest.mark.asyncio
async def test_events_are_anonymised_rather_than_deleted(env):
    """The audit trail is what lets anyone verify the system did what it claims.

    It survives with the user id removed, which is stated in the interface before the
    student confirms. This test pins both halves: the row stays, the link goes.
    """
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    await dbs.events.execute(
        """INSERT INTO events (event_id, stream, type, actor, subject_type, subject_id,
                               user_id, payload, created_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (new_ulid(), "chat", "question.asked", "test", "user",
         user["public_id"], user["id"], "{}", utc_now_iso()),
    )
    await _schedule_in_the_past(dbs, user["id"])
    await retention.purge_due_accounts(dbs, bus, settings)

    rows = await dbs.events.fetch_all(
        "SELECT user_id FROM events WHERE type = 'question.asked'"
    )
    assert len(rows) == 1, "the audit trail must survive"
    assert rows[0]["user_id"] is None, "and must no longer name anybody"


@pytest.mark.asyncio
async def test_feedback_survives_the_purge_but_stops_being_attributable(env):
    """A defect report is about the product, not the person who sent it.

    It stays readable so a maintainer can still work from it, and the same statement
    that keeps it also strips the two fields that identify its author.
    """
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    await dbs.app.execute(
        """INSERT INTO feedback (public_id, user_id, kind, message, lang, contact_email, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (f"FB-{new_ulid()}", user["id"], "bug", "The funding page shows a blank bar.",
         "en", "s@example.com", utc_now_iso()),
    )
    await _schedule_in_the_past(dbs, user["id"])
    await retention.purge_due_accounts(dbs, bus, settings)

    rows = await dbs.app.fetch_all("SELECT * FROM feedback")
    assert len(rows) == 1
    assert rows[0]["message"] == "The funding page shows a blank bar."
    assert rows[0]["user_id"] is None
    assert rows[0]["contact_email"] is None


@pytest.mark.asyncio
async def test_nothing_identifiable_is_left_anywhere_in_app_db(env):
    """The strong version of the promise, checked against the schema itself.

    Rather than listing tables by hand, this walks every table in app.db that has a
    `user_id` column and asserts none of them still references the purged account. A
    table added later is covered automatically, which is the point: the failure mode
    this guards against is somebody adding a table and forgetting the cascade.
    """
    dbs, users, auth, bus, settings, _b = env
    user = await _make_student(users, dbs)
    uid = user["id"]
    await _ask_a_question(dbs, uid, "প্রশ্ন")
    await _schedule_in_the_past(dbs, uid)
    await retention.purge_due_accounts(dbs, bus, settings)

    tables = [
        r["name"]
        for r in await dbs.app.fetch_all(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    offenders: list[str] = []
    for table in tables:
        cols = {r["name"] for r in await dbs.app.fetch_all(f"PRAGMA table_info({table})")}
        for col in ("user_id", "reporter_id", "reviewed_by", "resolved_by"):
            if col not in cols:
                continue
            left = await dbs.app.fetch_val(
                f"SELECT COUNT(*) FROM {table} WHERE {col} = ?", (uid,)
            )
            if left:
                offenders.append(f"{table}.{col} ({left} rows)")
    assert not offenders, f"purged account still referenced by: {offenders}"

    assert await dbs.app.fetch_val("SELECT COUNT(*) FROM users WHERE id = ?", (uid,)) == 0


# --- the aggregate report ----------------------------------------------------


@pytest.mark.asyncio
async def test_the_report_holds_no_identifier_of_any_kind(env):
    """The report is the business artefact, so this is the test that matters most.

    It asserts on the serialised output rather than on the code that builds it,
    because what leaks is the file, not the function.
    """
    dbs, users, auth, bus, settings, base = env
    user = await _make_student(users, dbs, email="rina.akter@example.com")
    await _ask_a_question(dbs, user["id"], "আমার কত টাকা লাগবে?")

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    await insights.run_nightly(dbs, settings, day=day)
    written = (insights.report_dir(settings) / f"{day}.json").read_text()

    for forbidden in ("rina", "akter", "example.com", user["public_id"], "আমার কত টাকা"):
        assert forbidden.lower() not in written.lower(), f"report leaked {forbidden!r}"
    # And no key that could hold one.
    for key in ("user_id", "email", "display_name", "address", "name", "age", "sex"):
        assert f'"{key}"' not in written, f"report has a {key} field"


def test_small_buckets_are_suppressed_not_published():
    """A count of one in a narrow bucket is a description of one person."""
    floored = insights.apply_floor({"gb": 40, "de": 12, "se": 1, "jp": 2})

    assert floored["gb"] == 40
    assert floored["de"] == 12
    assert "se" not in floored
    assert "jp" not in floored
    # Suppressed, not dropped: the column still adds up, so a reader sees that
    # suppression happened instead of concluding those students do not exist.
    assert floored[insights.FLOOR_KEY] == 3
    assert sum(floored.values()) == 55


def test_no_floor_key_appears_when_nothing_was_suppressed():
    assert insights.FLOOR_KEY not in insights.apply_floor({"gb": 40, "de": 12})


def test_the_floor_is_a_real_threshold():
    assert insights.MIN_BUCKET_SIZE >= 5, "a floor below 5 does not protect a small group"


@pytest.mark.asyncio
async def test_the_report_for_one_day_is_reproducible(env):
    """Bounded by date rather than by "the last 24 hours", so a re-run matches."""
    dbs, users, auth, _bus, settings, _b = env
    await _make_student(users, dbs)

    first = await insights.collect(dbs, day="2026-07-20")
    second = await insights.collect(dbs, day="2026-07-20")

    del first["generated_at"], second["generated_at"]
    assert first == second


@pytest.mark.asyncio
async def test_rerunning_a_day_replaces_its_row_rather_than_adding_one(env):
    dbs, users, auth, _bus, settings, _b = env
    await insights.run_nightly(dbs, settings, day="2026-07-20")
    await insights.run_nightly(dbs, settings, day="2026-07-20")

    rows = await dbs.events.fetch_val("SELECT COUNT(*) FROM daily_insights WHERE day = ?", ("2026-07-20",))
    assert rows == 1


@pytest.mark.asyncio
async def test_daily_insights_has_no_column_that_could_name_a_student(env):
    """Enforced in the schema, so a later query cannot start filling one in."""
    dbs, *_ = env
    cols = {r["name"] for r in await dbs.events.fetch_all("PRAGMA table_info(daily_insights)")}
    for forbidden in ("user_id", "email", "display_name", "user_public_id", "address"):
        assert forbidden not in cols
