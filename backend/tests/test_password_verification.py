"""Password verification, and the tuple that made it stop verifying.

`app.security.passwords.verify_password` returns `(ok, needs_rehash)`. Three call
sites treated the return value as a boolean:

    if not verify_password(password, row["password_hash"]):

A two-tuple is always truthy, so `not (False, False)` is `False` and the branch never
ran. `login` therefore accepted **any** password for any existing email, and
`change_password` and the account-deletion confirmation accepted any password too.

The bug is invisible in review because the line reads exactly like the correct
version, and no test asserted that a wrong password is rejected: the suite checked
that the right password works. These tests assert the negative, which is the half
that carries the security property.
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest

from app.config import Settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.errors import Unauthorized
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password, verify_password
from app.services.auth_service import AuthService

PASSWORD = "a genuinely long passphrase"


class _FakeBus:
    async def publish(self, *a, **k):  # noqa: ANN002, ANN003
        return None


@pytest.fixture
async def auth_env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        users = UserRepo(dbs.app)
        service = AuthService(users, _FakeBus(), Settings(vault_master_key="0" * 64))
        await users.create(
            email="student@example.com",
            password_hash=hash_password(PASSWORD),
            display_name="Student",
        )
        try:
            yield service, users, dbs
        finally:
            await dbs.close_all()


# --- the primitive -----------------------------------------------------------


def test_verify_password_returns_a_pair_not_a_boolean():
    """Pinning the shape, because the shape is what the callers got wrong.

    If this function is ever changed to return a bare bool, this test fails and
    whoever changes it is pointed at the call sites that unpack it.
    """
    result = verify_password(PASSWORD, hash_password(PASSWORD))
    assert isinstance(result, tuple) and len(result) == 2
    assert result[0] is True


def test_a_wrong_password_still_returns_a_truthy_tuple():
    """The exact trap, stated once so nobody re-introduces it."""
    result = verify_password("wrong", hash_password(PASSWORD))
    assert result[0] is False
    assert bool(result) is True, "this is why `if not verify_password(...)` never fired"


def test_a_malformed_stored_hash_is_a_failure_not_an_exception():
    ok, _ = verify_password(PASSWORD, "not a hash at all")
    assert ok is False


# --- login -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_login_rejects_a_wrong_password(auth_env):
    """The regression test for an authentication bypass.

    Before the fix this call returned a valid access token for an arbitrary password
    against any registered email address.
    """
    service, _users, _dbs = auth_env
    with pytest.raises(Unauthorized):
        await service.login(
            email="student@example.com", password="not the password",
            user_agent=None, ip_hash=None,
        )


@pytest.mark.asyncio
async def test_login_accepts_the_right_password(auth_env):
    service, _users, _dbs = auth_env
    user, access_token, refresh, _ttl = await service.login(
        email="student@example.com", password=PASSWORD, user_agent=None, ip_hash=None
    )
    assert user["email"] == "student@example.com"
    assert access_token and refresh


@pytest.mark.asyncio
async def test_a_failed_login_is_counted(auth_env):
    """`failed_logins` drives the lockout, and it only increments on the path the
    bypass skipped, so the lockout was unreachable too."""
    service, users, _dbs = auth_env
    with pytest.raises(Unauthorized):
        await service.login(
            email="student@example.com", password="wrong", user_agent=None, ip_hash=None
        )
    row = await users.get_by_email("student@example.com")
    assert row["failed_logins"] == 1


@pytest.mark.asyncio
async def test_a_successful_login_resets_the_counter(auth_env):
    service, users, _dbs = auth_env
    with pytest.raises(Unauthorized):
        await service.login(
            email="student@example.com", password="wrong", user_agent=None, ip_hash=None
        )
    await service.login(
        email="student@example.com", password=PASSWORD, user_agent=None, ip_hash=None
    )
    row = await users.get_by_email("student@example.com")
    assert row["failed_logins"] == 0


@pytest.mark.asyncio
async def test_an_unknown_email_is_rejected_with_the_same_message(auth_env):
    """Identical wording for "no such user" and "wrong password", so the endpoint
    cannot be used to find out which addresses have accounts."""
    service, _users, _dbs = auth_env
    with pytest.raises(Unauthorized) as unknown:
        await service.login(
            email="nobody@example.com", password=PASSWORD, user_agent=None, ip_hash=None
        )
    with pytest.raises(Unauthorized) as wrong:
        await service.login(
            email="student@example.com", password="wrong", user_agent=None, ip_hash=None
        )
    assert unknown.value.detail_en == wrong.value.detail_en
    assert unknown.value.detail_bn == wrong.value.detail_bn


# --- change_password ---------------------------------------------------------


@pytest.mark.asyncio
async def test_change_password_rejects_a_wrong_current_password(auth_env):
    """Otherwise anyone holding a stolen access token could take the account over
    permanently by setting a password of their own."""
    service, users, _dbs = auth_env
    row = await users.get_by_email("student@example.com")
    with pytest.raises(Unauthorized):
        await service.change_password(row["id"], "not the password", "a brand new passphrase")


@pytest.mark.asyncio
async def test_change_password_works_with_the_right_current_password(auth_env):
    service, users, _dbs = auth_env
    row = await users.get_by_email("student@example.com")
    await service.change_password(row["id"], PASSWORD, "a brand new passphrase")

    updated = await users.get_by_email("student@example.com")
    assert verify_password("a brand new passphrase", updated["password_hash"])[0] is True
    assert verify_password(PASSWORD, updated["password_hash"])[0] is False
