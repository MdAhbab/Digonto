"""Re-registration blocking, and the per-student report's identity rule.

Two features that touch the same promise from opposite directions. The tombstone keeps
something after deletion; the report holds something about a living account. Both are
allowed only because of exactly what they do not contain, so that is what is tested.
"""

from __future__ import annotations

import json
import pathlib
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.errors import Conflict
from app.repositories._util import new_ulid, utc_now_iso
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password
from app.security.tombstone import normalise_email
from app.services.auth_service import AuthService
from app.workers import retention, student_reports

KEY = "b" * 64
PASSWORD = "a long enough passphrase"


class _FakeBus:
    async def publish(self, *a, **k):  # noqa: ANN002, ANN003
        return None


@pytest.fixture
async def env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        settings = Settings(vault_master_key=KEY, private_dir=base / "private")
        users = UserRepo(dbs.app)
        auth = AuthService(users, _FakeBus(), settings)
        try:
            yield dbs, users, auth, settings
        finally:
            await dbs.close_all()


# --- matching one address to one row ------------------------------------------


def test_normalisation_is_stable_under_case_and_whitespace():
    """The lookup at signup and the write at deletion must agree on one spelling."""
    assert normalise_email("  Rina@Example.com ") == "rina@example.com"


def test_normalisation_does_not_merge_addresses_belonging_to_different_people():
    """Stripping dots or +tags is true at Gmail and false elsewhere.

    Under-matching lets someone cycle addresses; over-matching locks out a stranger, and
    only one of those two mistakes has a victim.
    """
    assert normalise_email("a.b@example.com") != normalise_email("ab@example.com")
    assert normalise_email("x+tag@example.com") != normalise_email("x@example.com")


# --- blocking re-registration ------------------------------------------------


async def _purge_now(dbs, users, auth, settings, email: str) -> None:
    row = await users.create(
        email=email, password_hash=hash_password(PASSWORD), display_name="Student"
    )
    past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await dbs.app.execute(
        "UPDATE users SET deletion_requested_at = ?, deletion_scheduled_for = ? WHERE id = ?",
        (past, past, row["id"]),
    )
    assert await retention.purge_due_accounts(dbs, _FakeBus(), settings) == 1


@pytest.mark.asyncio
async def test_a_purge_records_a_tombstone(env):
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "gone@example.com")

    row = await users.tombstone_for_email("gone@example.com")
    assert row is not None
    assert row["cycle_count"] == 1
    assert row["reason"] == "self"


@pytest.mark.asyncio
async def test_the_tombstone_keeps_the_address_and_the_name(env):
    """Both are retained in plain text, which is what makes a support question about a
    deleted account answerable. The cost of that decision is what the next test bounds."""
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "Rina.Akter@Example.com")

    row = await dbs.app.fetch_one("SELECT * FROM deleted_accounts")
    assert row["email"] == "rina.akter@example.com", "stored normalised, as users.email was"
    assert row["display_name"] == "Student"


@pytest.mark.asyncio
async def test_the_tombstone_holds_nothing_beyond_identity_and_the_abuse_counter(env):
    """The guard that matters now that the table is readable.

    A row here is the one record a student cannot remove, so what may sit next to their
    name is a fixed list. Age, district, gender, budget, shortlisted countries, question
    counts and anything model-written are all absent, and a column added later fails this
    test rather than shipping quietly.
    """
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "rina@example.com")

    cols = {r["name"] for r in await dbs.app.fetch_all("PRAGMA table_info(deleted_accounts)")}
    assert cols == {
        "public_id",
        "email",
        "display_name",
        "deleted_at",
        "reason",
        "cycle_count",
    }


@pytest.mark.asyncio
async def test_no_other_table_retains_the_address(env):
    """The tombstone is the single stated exception, so it must also be the only one.

    Sweeps every table in `app.db` for the deleted address. Written this way rather than
    naming tables so that a table added later is covered without anyone remembering to
    update this test.
    """
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "rina.akter@example.com")

    tables = [
        r["name"]
        for r in await dbs.app.fetch_all(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    ]
    for table in tables:
        if table == "deleted_accounts":
            continue
        dumped = json.dumps(
            [dict(r) for r in await dbs.app.fetch_all(f"SELECT * FROM {table}")], default=str
        )
        assert "rina.akter" not in dumped, f"{table} still holds the deleted address"


@pytest.mark.asyncio
async def test_signup_refuses_a_deleted_address(env):
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "gone@example.com")

    with pytest.raises(Conflict) as caught:
        await auth.signup(
            email="gone@example.com", password=PASSWORD, display_name="Someone Else",
            user_agent=None, ip_hash=None,
        )
    # The message says what actually happened. A student coming back deserves the truth
    # rather than "an account already exists", which is not true.
    assert "deleted" in caught.value.detail_en.lower()
    assert caught.value.detail_bn


@pytest.mark.asyncio
async def test_the_refusal_is_case_insensitive(env):
    """Otherwise the block is bypassed by capitalising one letter."""
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "gone@example.com")

    with pytest.raises(Conflict):
        await auth.signup(
            email="GONE@Example.COM", password=PASSWORD, display_name="X",
            user_agent=None, ip_hash=None,
        )


@pytest.mark.asyncio
async def test_an_unrelated_address_still_works(env):
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "gone@example.com")

    user, token, _refresh, _ttl = await auth.signup(
        email="new@example.com", password=PASSWORD, display_name="New",
        user_agent=None, ip_hash=None,
    )
    assert user["email"] == "new@example.com" and token


@pytest.mark.asyncio
async def test_repeat_cycles_are_counted_rather_than_duplicated(env):
    """One row with a rising count is the signal; a dozen rows is noise."""
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "cycler@example.com")
    # A second account on the same address can only exist if something re-created it, so
    # insert directly to model the sequence the counter exists to reveal.
    await users.record_tombstone(
        public_id=new_ulid(),
        email="cycler@example.com",
        display_name="Second Try",
        deleted_at=utc_now_iso(),
    )
    rows = await dbs.app.fetch_all("SELECT * FROM deleted_accounts")
    assert len(rows) == 1
    assert rows[0]["cycle_count"] == 2
    # The current name replaces the old one. A list of every name a person has used is a
    # profile, and this table is an abuse control.
    assert rows[0]["display_name"] == "Second Try"


def test_the_reporting_jobs_never_read_the_tombstone_table():
    """The access rule stated in migration 025, asserted rather than trusted.

    `deleted_accounts` is the one place a name survives deletion. If a nightly report ever
    joined against it, every report would carry the names of people who had left, which is
    the exact outcome the rest of this file exists to prevent.
    """
    import inspect

    from app.workers import insights, student_reports as sr

    for module in (insights, sr):
        assert "deleted_accounts" not in inspect.getsource(module), module.__name__


# --- the per-student report --------------------------------------------------


@pytest.mark.asyncio
async def test_a_student_report_is_keyed_by_account_and_holds_no_personal_detail(env):
    dbs, users, auth, settings = env
    row = await users.create(
        email="rina.akter@example.com",
        password_hash=hash_password(PASSWORD),
        display_name="Rina Akter",
    )
    await dbs.app.execute(
        "UPDATE users SET last_seen_at = ? WHERE id = ?", (utc_now_iso(), row["id"])
    )

    day = datetime.now(UTC).strftime("%Y-%m-%d")
    result = await student_reports.run_nightly(dbs, settings, day=day)
    assert result["students_reported"] == 1

    written = (student_reports.report_dir(settings) / "students" / f"{day}.json").read_text()
    # The account id is present: a figure nobody can tie to a record proves nothing.
    assert row["public_id"] in written
    # Nothing about the person is.
    for forbidden in ("Rina", "Akter", "rina.akter", "@example.com"):
        assert forbidden not in written, f"report leaked {forbidden!r}"
    for key in ('"email"', '"display_name"', '"home_district"', '"cgpa"', '"name"'):
        assert key not in written, f"report carries {key}"


@pytest.mark.asyncio
async def test_reports_are_deleted_with_the_account(env):
    """Enforced by a foreign key rather than by the purge remembering."""
    dbs, users, auth, settings = env
    row = await users.create(
        email="gone2@example.com", password_hash=hash_password(PASSWORD), display_name="S"
    )
    await dbs.app.execute(
        "INSERT INTO student_reports (user_id, day, payload, generated_at) VALUES (?,?,?,?)",
        (row["id"], "2026-07-26", "{}", utc_now_iso()),
    )
    assert await dbs.app.fetch_val("SELECT COUNT(*) FROM student_reports") == 1

    past = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    await dbs.app.execute(
        "UPDATE users SET deletion_requested_at = ?, deletion_scheduled_for = ? WHERE id = ?",
        (past, past, row["id"]),
    )
    await retention.purge_due_accounts(dbs, _FakeBus(), settings)

    assert await dbs.app.fetch_val("SELECT COUNT(*) FROM student_reports") == 0


@pytest.mark.asyncio
async def test_rerunning_a_day_replaces_the_row(env):
    dbs, users, auth, settings = env
    row = await users.create(
        email="s@example.com", password_hash=hash_password(PASSWORD), display_name="S"
    )
    await dbs.app.execute(
        "UPDATE users SET last_seen_at = ? WHERE id = ?", (utc_now_iso(), row["id"])
    )
    await student_reports.run_nightly(dbs, settings, day="2026-07-26")
    await student_reports.run_nightly(dbs, settings, day="2026-07-26")
    assert await dbs.app.fetch_val("SELECT COUNT(*) FROM student_reports") == 1


@pytest.mark.asyncio
async def test_a_dormant_account_gets_no_report(env):
    """A row of zeroes every night buries the students who are mid-application."""
    dbs, users, auth, settings = env
    await users.create(
        email="quiet@example.com", password_hash=hash_password(PASSWORD), display_name="Q"
    )
    result = await student_reports.run_nightly(dbs, settings, day="2026-07-26")
    assert result["students_reported"] == 0
