"""Access and refresh tokens.

Access tokens are stateless JWTs (HS256, 15 minutes) and are never stored.
Refresh tokens are opaque random strings; only their sha256 hash is stored, in
`refresh_tokens.token_hash`, so a stolen database dump cannot be replayed as a
live session. See docs/database.md section 3.1 for the table and the rotation
family it uses for stolen-token detection.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

import jwt

from app.config import Settings, get_settings

_ALGORITHM = "HS256"
_REFRESH_TOKEN_BYTES = 48  # secrets.token_urlsafe input length, per spec


class TokenError(Exception):
    """Base for access-token problems. Callers typically map this to 401."""


class TokenExpired(TokenError):
    pass


class TokenInvalid(TokenError):
    pass


def create_access_token(
    user_public_id: str,
    role: str,
    *,
    settings: Settings | None = None,
    ttl_seconds: int | None = None,
) -> str:
    """Mint a 15-minute access JWT. Claims: sub, role, jti, iat, exp."""
    s = settings or get_settings()
    now = int(time.time())
    ttl = ttl_seconds if ttl_seconds is not None else s.jwt_access_ttl_seconds
    claims = {
        "sub": user_public_id,
        "role": role,
        "jti": secrets.token_urlsafe(16),
        "iat": now,
        "exp": now + ttl,
    }
    return jwt.encode(claims, s.jwt_secret, algorithm=_ALGORITHM)


def decode_access_token(token: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Decode and verify an access JWT.

    Raises TokenExpired or TokenInvalid rather than pyjwt's own exceptions, so
    callers (notably app/deps.py) do not need to import pyjwt to handle this.
    """
    s = settings or get_settings()
    try:
        return jwt.decode(token, s.jwt_secret, algorithms=[_ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpired("access token has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalid("access token is malformed or has a bad signature") from exc


def new_refresh_token() -> str:
    """Return a fresh raw refresh token. Only its sha256 hash (via
    `hash_refresh_token`) is ever persisted.

    Signature note: this used to return `(raw, hash)` as a tuple, but
    `app/services/auth_service.py` (authoritative, not modified as part of
    the router work that found this) calls it expecting a single raw string
    and separately calls `hash_refresh_token(refresh_plain)` itself at both
    call sites (`_issue_tokens` and `refresh`). That module's own docstring
    flags exactly this risk ("signatures used here are the most
    conventional shape for each function ... in case the real signatures
    differ"). Changed to match the caller rather than the other way around,
    since app/services/*.py is the file this build must not modify.
    """
    return secrets.token_urlsafe(_REFRESH_TOKEN_BYTES)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_refresh_family() -> str:
    """A new rotation-family id, assigned once at login and carried across
    every rotation of that login session's refresh token."""
    return secrets.token_urlsafe(16)


# --- Refresh-token rotation-reuse detection ---------------------------------
#
# `refresh_tokens.revoked_at` (docs/database.md section 3.1) is set the moment
# a token is rotated to its replacement. If a token that already carries a
# `revoked_at` is presented again, that is not an expired session: it is a
# stolen token being replayed after the legitimate client already moved on to
# the replacement, and the whole `family_id` must be revoked. These helpers
# make that decision from data the caller already has in hand; they do not
# touch the database themselves, since that is a repository-layer concern.


class RefreshOutcome(str, Enum):
    VALID = "valid"
    REUSE_DETECTED = "reuse_detected"
    EXPIRED = "expired"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class RefreshTokenState:
    """The subset of a `refresh_tokens` row needed to evaluate a presented token."""

    family_id: str
    revoked_at: str | None
    expires_at: str


def _parse_iso(ts: str) -> datetime:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def evaluate_refresh_token(
    state: RefreshTokenState | None, *, now: datetime | None = None
) -> RefreshOutcome:
    """Decide what a presented refresh token means, given its stored row.

    `state` is None when no row matches the presented token's hash at all,
    which is treated the same as an unrecognised/forged token. Callers should
    revoke every token in `state.family_id` on REUSE_DETECTED before
    returning 401, per docs/api_contract.md section 3 ("stolen-token
    detection, not a bug").
    """
    if state is None:
        return RefreshOutcome.UNKNOWN
    if state.revoked_at is not None:
        return RefreshOutcome.REUSE_DETECTED
    if _parse_iso(state.expires_at) <= (now or datetime.now(timezone.utc)):
        return RefreshOutcome.EXPIRED
    return RefreshOutcome.VALID
