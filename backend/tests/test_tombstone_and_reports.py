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
from app.security.tombstone import email_digest, normalise_email
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


# --- the digest --------------------------------------------------------------


def test_the_digest_is_stable_under_case_and_whitespace():
    s = Settings(vault_master_key=KEY)
    assert email_digest("Rina@Example.com", s) == email_digest("  rina@example.com  ", s)


def test_the_digest_does_not_contain_the_address():
    """The whole reason for storing a digest instead of the address."""
    s = Settings(vault_master_key=KEY)
    d = email_digest("rina.akter@example.com", s)
    for fragment in ("rina", "akter", "example", "@"):
        assert fragment not in d
    assert len(d) == 64


def test_the_digest_is_keyed_so_a_stolen_database_does_not_yield_addresses():
    """An unkeyed SHA-256 of an email is the email: the search space is enumerable."""
    a = email_digest("rina@example.com", Settings(vault_master_key="c" * 64))
    b = email_digest("rina@example.com", Settings(vault_master_key="d" * 64))
    assert a != b


def test_an_unkeyed_deployment_refuses_rather_than_storing_a_reversible_digest():
    """An empty key would make this a bare SHA-256, which for an email is reversible.

    A stub rather than `Settings(vault_master_key="")`: this repository has a real key in
    its `.env`, and pydantic-settings fills the field from there, so constructing the
    empty case through `Settings` tests the environment instead of the guard.
    """

    class _NoKey:
        vault_master_key = ""

    with pytest.raises(RuntimeError, match="unkeyed"):
        email_digest("rina@example.com", _NoKey())  # type: ignore[arg-type]


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

    row = await users.tombstone_for_email(email_digest("gone@example.com", settings))
    assert row is not None
    assert row["cycle_count"] == 1
    assert row["reason"] == "self"


@pytest.mark.asyncio
async def test_the_tombstone_holds_no_address_and_no_name(env):
    """It answers "have we seen this address" and nothing else."""
    dbs, users, auth, settings = env
    await _purge_now(dbs, users, auth, settings, "rina.akter@example.com")

    cols = {r["name"] for r in await dbs.app.fetch_all("PRAGMA table_info(deleted_accounts)")}
    assert "email" not in cols
    assert "display_name" not in cols

    dumped = json.dumps(
        [dict(r) for r in await dbs.app.fetch_all("SELECT * FROM deleted_accounts")]
    )
    for fragment in ("rina", "akter", "Student", "@example.com"):
        assert fragment not in dumped


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
        email_hmac=email_digest("cycler@example.com", settings),
        deleted_at=utc_now_iso(),
    )
    rows = await dbs.app.fetch_all("SELECT * FROM deleted_accounts")
    assert len(rows) == 1
    assert rows[0]["cycle_count"] == 2


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
