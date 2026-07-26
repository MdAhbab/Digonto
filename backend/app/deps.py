"""FastAPI dependencies: database/bus/router access, auth, and rate limiting.

Everything here reads shared state off `request.app.state`, which
app/main.py's lifespan populates once at startup (`dbs`, `redis`, `bus`,
`model_router`). No dependency here constructs its own connections.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import Depends, Request, Response

from app.db.connection import Databases
from app.errors import AccountBanned, Forbidden, RateLimited, Unauthorized
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.security.tokens import TokenExpired, TokenInvalid, decode_access_token


def get_dbs(request: Request) -> Databases:
    return request.app.state.dbs


def get_bus(request: Request) -> EventBus:
    return request.app.state.bus


def get_router(request: Request) -> ModelRouter:
    return request.app.state.model_router


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("Authorization")
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    return token or None


async def get_current_user(
    request: Request,
    dbs: Databases = Depends(get_dbs),
) -> Mapping[str, Any]:
    """Bearer JWT -> the `users` row. 401 if missing/invalid, 423 if the
    account is banned or suspended, per docs/api_contract.md section 3."""
    token = _bearer_token(request)
    if token is None:
        raise Unauthorized()

    try:
        claims = decode_access_token(token)
    except TokenExpired:
        raise Unauthorized(
            detail_en="Your session has expired. Please sign in again.",
            detail_bn="আপনার সেশনের মেয়াদ শেষ হয়ে গেছে। আবার সাইন ইন করুন।",
        )
    except TokenInvalid:
        raise Unauthorized()

    row = await dbs.app.fetch_one(
        "SELECT * FROM users WHERE public_id = ? AND deleted_at IS NULL",
        (claims.get("sub"),),
    )
    if row is None:
        raise Unauthorized()
    user = dict(row)

    if user["status"] in ("banned", "suspended"):
        raise AccountBanned(
            detail_en=user.get("status_reason_en") or None,
            detail_bn=user.get("status_reason_bn") or None,
        )

    # Stashed for dependencies later in the same request's chain, chiefly
    # RateLimit, which prefers a per-user bucket over a per-IP one.
    request.state.user_id = user["id"]
    request.state.user_public_id = user["public_id"]
    return user


async def get_optional_user(
    request: Request,
    dbs: Databases = Depends(get_dbs),
) -> Mapping[str, Any] | None:
    """Like get_current_user, but returns None for an anonymous caller.

    A *present but invalid* token still raises 401 rather than silently
    degrading to anonymous: a client sending a garbled token has a bug worth
    surfacing, not a reason to pretend it sent nothing.
    """
    if _bearer_token(request) is None:
        return None
    return await get_current_user(request, dbs)


_ROLE_RANK = {"student": 0, "moderator": 1, "admin": 2}


def require_role(minimum_role: str) -> Callable[..., Awaitable[Mapping[str, Any]]]:
    """Dependency factory: 403s unless the caller's role meets `minimum_role`.

    Roles are hierarchical (student < moderator < admin). This matches
    docs/api_contract.md section 11a, which grants the moderator console to
    "role in (moderator, admin)" rather than moderator alone, so
    `require_role("moderator")` is satisfied by an admin too.
    """

    async def _dependency(
        user: Mapping[str, Any] = Depends(get_current_user),
    ) -> Mapping[str, Any]:
        if _ROLE_RANK.get(user["role"], -1) < _ROLE_RANK.get(minimum_role, 99):
            raise Forbidden(
                detail_en="Your account does not have permission for this action.",
                detail_bn="এই কাজের জন্য আপনার অ্যাকাউন্টের প্রয়োজনীয় অনুমতি নেই।",
            )
        return user

    return _dependency


# --- Rate limiting -----------------------------------------------------------
#
# A Redis token bucket per docs/api_contract.md section 14. The Lua script
# makes the read-refill-check-write cycle atomic on the Redis side, so
# concurrent requests against the same key cannot race each other into
# over-admitting.

_TOKEN_BUCKET_LUA = """
local tokens_key = KEYS[1]
local capacity = tonumber(ARGV[1])
local window_s = tonumber(ARGV[2])
local now = tonumber(ARGV[3])

local data = redis.call('HMGET', tokens_key, 'tokens', 'ts')
local tokens = tonumber(data[1])
local ts = tonumber(data[2])
if tokens == nil then
  tokens = capacity
  ts = now
end

local refill_rate = capacity / window_s
local elapsed = now - ts
if elapsed > 0 then
  tokens = math.min(capacity, tokens + elapsed * refill_rate)
end

local allowed = 0
if tokens >= 1 then
  allowed = 1
  tokens = tokens - 1
end

redis.call('HMSET', tokens_key, 'tokens', tokens, 'ts', now)
redis.call('EXPIRE', tokens_key, math.ceil(window_s * 2))

return {allowed, tostring(tokens)}
"""


class RateLimit:
    """Redis token-bucket rate limit dependency, per api_contract.md section 14.

    Usage: `Depends(RateLimit("ask_hourly", limit=30, window_s=3600))`. The
    bucket key is scoped by user id when the caller is authenticated (set by
    get_current_user earlier in the same request's dependency chain) and
    falls back to the client IP for public routes such as the Truth Ledger.
    """

    def __init__(self, scope: str, limit: int, window_s: int) -> None:
        self.scope = scope
        self.limit = limit
        self.window_s = window_s

    def _identity(self, request: Request) -> str:
        user_id = getattr(request.state, "user_id", None)
        if user_id is not None:
            return f"u:{user_id}"
        client_host = request.client.host if request.client else "unknown"
        return f"ip:{client_host}"

    async def __call__(self, request: Request, response: Response) -> None:
        redis_client = request.app.state.redis
        key = f"rl:{self.scope}:{self._identity(request)}"
        now = time.time()

        allowed_raw, tokens_raw = await redis_client.eval(
            _TOKEN_BUCKET_LUA, 1, key, self.limit, self.window_s, now
        )
        allowed = int(allowed_raw) == 1
        tokens_left = float(tokens_raw)
        reset_s = 0 if allowed else max(1, int((1 - tokens_left) * self.window_s / self.limit))

        response.headers["X-RateLimit-Limit"] = str(self.limit)
        response.headers["X-RateLimit-Remaining"] = str(max(int(tokens_left), 0))
        response.headers["X-RateLimit-Reset"] = str(reset_s)

        if not allowed:
            raise RateLimited(
                detail_en=(
                    f"You're sending requests too quickly for {self.scope}. The model is "
                    f"shared across every student on Digonto, so please wait about "
                    f"{reset_s} seconds and try again."
                ),
                detail_bn=(
                    f"আপনি {self.scope}-এর জন্য অনেক দ্রুত অনুরোধ পাঠাচ্ছেন। মডেলটি Digonto-র "
                    f"সব শিক্ষার্থীর মধ্যে ভাগ করা, তাই প্রায় {reset_s} সেকেন্ড অপেক্ষা করে "
                    "আবার চেষ্টা করুন।"
                ),
                retry_after=reset_s,
            )


# FastAPI resolves the string annotations that `from __future__ import
# annotations` produces (module-wide, in this file) by looking up
# `getattr(dependency_callable, "__globals__", {})`. That works for a plain
# function or a bound method, but `Depends(RateLimit(...))` hands FastAPI a
# class *instance*, which has no `__globals__` of its own, only its `__call__`
# method does. Without this, "request: Request" and "response: Response"
# above silently fail to resolve to the special injectable types and FastAPI
# instead treats them as required query parameters, breaking every route that
# uses RateLimit with a 422. Exposing the module's globals as a class
# attribute is what makes instance-based dependencies with deferred
# annotations resolve correctly.
RateLimit.__globals__ = globals()
