"""Keyed digests of email addresses, for the deleted-account tombstone.

One job: answer "have we seen this address before" after the account holding it has been
erased, without keeping the address. See
`app/db/migrations/app/023_deleted_account_tombstones.sql` for why that is the shape.

The key is derived from the application's existing vault master key rather than adding a
new secret to the deployment. A separate `info` string means this digest cannot be
confused with, or used to attack, the per-user vault keys derived from the same root
(`app/security/vault_crypto.py`), which is the whole point of domain separation in HKDF.
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import Settings, get_settings

_HKDF_SALT = b"digonto-tombstone-hkdf-v1"
_HKDF_INFO = b"tombstone:email-hmac:v1"


def _key(settings: Settings | None = None) -> bytes:
    s = settings or get_settings()
    root = (s.vault_master_key or "").encode()
    if not root:
        # A deployment with no master key would otherwise HMAC under an empty key, which
        # is a fixed unkeyed digest and therefore reversible for email addresses. Failing
        # is correct: the alternative is silently storing recoverable addresses.
        raise RuntimeError(
            "VAULT_MASTER_KEY is not set, so a tombstone digest would be unkeyed and "
            "reversible. Refusing to compute one."
        )
    return HKDF(
        algorithm=hashes.SHA256(), length=32, salt=_HKDF_SALT, info=_HKDF_INFO
    ).derive(root)


def normalise_email(email: str) -> str:
    """Lowercase and trim, matching what `users.email` stores (COLLATE NOCASE).

    Deliberately no further canonicalisation. Stripping dots or `+tags` would make
    `a.b@gmail.com` and `ab@gmail.com` the same person, which is true at Gmail and false
    at most other hosts, so it would block addresses that belong to different people.
    Under-matching lets a determined person cycle addresses; over-matching locks out
    strangers, and only one of those two mistakes has a victim.
    """
    return (email or "").strip().lower()


def email_digest(email: str, settings: Settings | None = None) -> str:
    """A stable keyed digest of an email address. Hex, 64 characters."""
    return hmac.new(_key(settings), normalise_email(email).encode(), hashlib.sha256).hexdigest()
