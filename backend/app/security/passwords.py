"""Password hashing and basic strength checks.

Argon2id via argon2-cffi's default parameters: we do not override memory cost,
time cost, or parallelism here, so a future argon2-cffi release can raise the
default work factor without a code change on our side.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

_hasher = PasswordHasher()

# docs/api_contract.md section 3 describes checking against the 10,000 most
# common passwords, which belongs in a downloaded wordlist at deploy time, not
# hardcoded in source. This list is the floor that ships even if that
# wordlist is missing: a small, embedded set of the passwords that show up at
# the top of essentially every breach corpus, plus a bare minimum length.
_MIN_LENGTH = 8

_COMMON_PASSWORDS: frozenset[str] = frozenset(
    {
        "12345678", "123456789", "1234567890", "password", "password1",
        "password123", "qwerty123", "qwertyuiop", "11111111", "123123123",
        "1q2w3e4r", "iloveyou", "admin123", "welcome1", "letmein1",
        "abc123456", "monkey123", "dragon123", "football1", "baseball1",
        "superman1", "trustno1", "sunshine1", "princess1", "12345678910",
        "1234567891", "123456780", "87654321", "00000000", "11223344",
        "qazwsxedc", "1qaz2wsx", "changeme", "passw0rd", "p@ssw0rd",
        "letmein123", "welcome123", "student123", "bangladesh1", "dhaka1234",
        "asdfghjkl", "zxcvbnm12", "qwerty12345", "michael1", "jennifer1",
        "computer1", "internet1", "whatever1", "shadow123", "master123",
        "hello1234", "freedom12", "starwars1", "batman123", "spiderman1",
    }
)


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> tuple[bool, bool]:
    """Verify a password against a stored Argon2id hash.

    Returns (ok, needs_rehash). `needs_rehash` is only meaningful when `ok` is
    True: it signals the stored hash used older parameters than the current
    hasher default and should be re-hashed and saved on this successful login.

    Verification failure and hash-format failure are both "wrong password" to
    the caller (constant-time behaviour matters here: argon2-cffi's verify
    already runs in constant time relative to the correct hash, so we must not
    add a fast-path branch on top of it, e.g. by pre-checking length).
    """
    try:
        _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        # InvalidHashError is not a subclass of VerificationError: it inherits from
        # ValueError, so it escaped this handler and reached the caller as a 500.
        # A stored hash that argon2 cannot parse at all is still "this password does
        # not open this account", which is what the docstring above promises and what
        # a row written by an older scheme, or truncated by a bad migration, produces.
        return False, False
    # check_needs_rehash can raise on a hash it parsed but does not recognise the
    # parameters of. The password has already been verified at this point, so a
    # failure here must not turn a successful login into an error: the worst outcome
    # of returning False is that a weak hash is upgraded on some later login instead.
    try:
        return True, _hasher.check_needs_rehash(password_hash)
    except Exception:  # noqa: BLE001 - never fail a correct password
        return True, False


def check_common_password(password: str) -> bool:
    """Return True if this password must be rejected at signup or change.

    Rejects anything under 8 characters and anything in the embedded common
    list, case-insensitively so 'Password1' is caught as readily as
    'password1'.
    """
    if len(password) < _MIN_LENGTH:
        return True
    return password.casefold() in _COMMON_PASSWORDS


# A precomputed hash of a password nobody will ever set. Login handlers that
# look a user up by email and find nothing should still call
# verify_password(supplied_password, DUMMY_HASH_FOR_TIMING) before returning
# 401, so "no such account" costs the same wall-clock time as "wrong
# password" and the endpoint cannot be used to enumerate accounts (the
# behaviour docs/api_contract.md section 3 requires of POST /auth/login).
DUMMY_HASH_FOR_TIMING = hash_password("no-account-has-this-password-2026")
