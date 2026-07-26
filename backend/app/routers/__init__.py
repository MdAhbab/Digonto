"""Aggregates every router module into the API surface app/main.py mounts.

app/main.py's `_register_routers` imports `router` from this package and
mounts it once at `settings.api_base_path` ("/api/v1"). This module builds
that combined router out of `all_routers`, which is exported separately
because the build brief for this work asks for it explicitly (a stable,
inspectable list is easier to test and to reason about than only a single
merged router).
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers import (
    ask,
    auth,
    destinations,
    funding,
    interview,
    ledger,
    me,
    meta,
    moderation,
    planner,
    vault,
)

# Stable order: auth first (nothing else works without it), then the
# student-facing surfaces in roughly the order docs/api_contract.md
# introduces them, then the moderator console, then meta last.
all_routers: list[APIRouter] = [
    auth.router,
    me.router,
    me.live_router,
    destinations.router,
    ask.router,
    ledger.router,
    planner.router,
    vault.router,
    funding.router,
    interview.router,
    moderation.router,
    meta.router,
]

router = APIRouter()
for _sub_router in all_routers:
    router.include_router(_sub_router)

__all__ = ["all_routers", "router"]
