"""Shared bootstrap for Digonto's MCP stdio servers.

Every server in this package (`portal_server.py`, `vault_server.py`,
`funding_server.py`) needs the same three things: logging that never touches
stdout, a connected `Databases` handle plus every repository/service the
tools call into, and a small dispatch helper so `@server.call_tool()` stays a
one-line switch instead of a thirty-line if/elif ladder repeated three times.
All of that lives here so the three server modules stay focused on their own
tool schemas and nothing else.

`AppContext` mirrors `app/main.py`'s `lifespan` wiring on purpose (same
`Databases`, `EventBus`, `ModelRouter` construction) rather than inventing a
second way to build the same objects, so an MCP server and the FastAPI app
agree on how a repository or service is constructed. Nothing in this module
re-implements a query: every tool handler in the three server files calls a
method that already exists on one of the repositories or services built
below.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

import httpx
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.db.connection import Databases
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.repositories.answer_repo import AnswerRepo
from app.repositories.audit_repo import AuditRepo
from app.repositories.budget_repo import BudgetRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.moderation_repo import ModerationRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.repositories.target_repo import TargetRepo
from app.repositories.user_repo import UserRepo
from app.workers.crawler import USER_AGENT
from app.services.funding_service import FundingService
from app.services.ledger_service import LedgerService
from app.services.moderation_service import ModerationService
from app.services.vault_service import VaultService

log = logging.getLogger(__name__)


def configure_stdio_logging(server_name: str) -> None:
    """Route every log record to stderr, unconditionally.

    The stdio MCP transport speaks newline-delimited JSON-RPC on stdout; one
    stray log line on stdout would corrupt the protocol stream from the
    client's side, silently, since the client just tries to JSON-decode
    whatever it reads. app/main.py's `logging.basicConfig` defaults to
    stderr already, but that call never runs in these standalone processes,
    so it is repeated here explicitly rather than assumed.
    """
    logging.basicConfig(
        level=logging.INFO,
        format=f"%(asctime)s {server_name} %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )


@dataclass(slots=True)
class AppContext:
    """Every repository and service a tool handler needs, built once per
    server process and torn down together on shutdown.
    """

    settings: Settings
    dbs: Databases
    redis: Redis
    bus: EventBus
    router: ModelRouter
    # Used by the portal server's official-source search. Shared rather than
    # per-call, so the crawling User-Agent and connection pool are set once.
    http_client: httpx.AsyncClient

    users: UserRepo
    portals: PortalRepo
    snapshots: SnapshotRepo
    documents: DocumentRepo
    audits: AuditRepo
    profiles: ProfileRepo
    targets: TargetRepo
    scholarships: ScholarshipRepo
    budgets: BudgetRepo
    moderation: ModerationRepo
    answers: AnswerRepo

    ledger: LedgerService
    vault: VaultService
    funding: FundingService
    moderation_service: ModerationService


@asynccontextmanager
async def app_context() -> AsyncIterator[AppContext]:
    """Connect the three SQLite files and build every repository/service the
    MCP tool servers call into, then close everything on exit.
    """
    settings = get_settings()
    settings.ensure_dirs()

    dbs = Databases(settings.app_db, settings.events_db, settings.learn_db)
    await dbs.connect_all()

    # decode_responses=True: app/events/bus.py assumes str fields out of this
    # client, same as app/main.py's lifespan.
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    bus = EventBus(redis_client, dbs.events)
    router = ModelRouter(settings)
    http_client = httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT}, follow_redirects=True
    )

    users = UserRepo(dbs.app)
    portals = PortalRepo(dbs.app)
    snapshots = SnapshotRepo(dbs.app)
    documents = DocumentRepo(dbs.app)
    audits = AuditRepo(dbs.app)
    profiles = ProfileRepo(dbs.app, dbs.events)
    targets = TargetRepo(dbs.app)
    scholarships = ScholarshipRepo(dbs.app)
    budgets = BudgetRepo(dbs.app)
    moderation = ModerationRepo(dbs.app, dbs.events, dbs.learn)
    answers = AnswerRepo(dbs.app)

    ledger = LedgerService(portals, snapshots)
    vault = VaultService(documents, audits, profiles, targets, bus, router, settings)
    funding = FundingService(
        scholarships, budgets, profiles, targets, bus, router,
        documents=documents, settings=settings,
    )
    moderation_service = ModerationService(
        moderation, snapshots, answers, portals, scholarships, users, bus
    )

    ctx = AppContext(
        settings=settings,
        dbs=dbs,
        redis=redis_client,
        bus=bus,
        router=router,
        http_client=http_client,
        users=users,
        portals=portals,
        snapshots=snapshots,
        documents=documents,
        audits=audits,
        profiles=profiles,
        targets=targets,
        scholarships=scholarships,
        budgets=budgets,
        moderation=moderation,
        answers=answers,
        ledger=ledger,
        vault=vault,
        funding=funding,
        moderation_service=moderation_service,
    )
    try:
        yield ctx
    finally:
        await http_client.aclose()
        await router.aclose()
        await redis_client.aclose()
        await dbs.close_all()


ToolHandler = Callable[[AppContext, dict[str, Any]], Awaitable[dict[str, Any]]]


def build_dispatcher(handlers: dict[str, ToolHandler], ctx: AppContext) -> ToolHandler:
    """Bind `ctx` into a `(name, arguments) -> result` callable for
    `@server.call_tool()`.

    A handler is free to raise (`app.errors.AppError` or anything else); the
    `mcp` package's `call_tool` wrapper (see `mcp.server.lowlevel.server`)
    already catches any exception from the registered function and turns it
    into an `isError: true` tool result carrying `str(exc)`, which for every
    `AppError` subclass is its bilingual `detail_en` message. There is
    nothing to add here beyond the lookup itself.
    """

    async def _dispatch(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        handler = handlers.get(name)
        if handler is None:
            raise ValueError(f"Unknown tool '{name}'")
        return await handler(ctx, arguments)

    return _dispatch


def resolve_user_id(ctx: AppContext, user_public_id: str) -> Awaitable[dict[str, Any] | None]:
    """Look up a user by public id. Every tool below takes a public id, never
    a raw integer primary key, matching the convention the rest of the
    product uses (docs/database.md section 1: internal ids never leave the
    server).
    """
    return ctx.users.get_by_public_id(user_public_id)


class ToolInputError(ValueError):
    """A tool was called with an argument that does not resolve to a real
    record (unknown public id, wrong role, etc). Raised in preference to a
    bare `ValueError` only so it reads clearly in a stack trace; it is
    caught the same way by `mcp`'s `call_tool` wrapper either way.
    """
