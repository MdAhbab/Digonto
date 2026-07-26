"""`digonto-portal-mcp`: the Truth Ledger's tools, over stdio.

Backs Porter (agents.md, Agent 1) and any other MCP client that needs to read
or extend the watched-portal list. Every tool below calls into
`app.services.ledger_service.LedgerService` (fetch/list, public/no-auth by
design), `app.services.moderation_service.ModerationService.create_portal`
(the one write, which also writes the `moderation_actions` audit row per
docs/database.md section 3.1), or the underlying `app.repositories.snapshot_repo`
for the moderator-queue-shaped read `list_pending_review` already exposes.
Nothing here issues its own SQL.

Tools:
  - fetch_snapshot(snapshot_id)
  - diff_snapshots(portal_id, cursor=None, since=None, only_pending_review=False, limit=20)
  - list_watched_portals()
  - register_portal(moderator_id, url, kind, label, country_code=None,
                     parser_key="generic", crawl_cron="0 */6 * * *")

Run standalone: `python -m app.mcp.portal_server` (from `backend/`, so the
`app` package resolves). See `app/mcp/README.md` for MCP client registration.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from app.errors import Forbidden, NotFound
from app.mcp._common import AppContext, app_context, build_dispatcher, configure_stdio_logging

SERVER_NAME = "digonto-portal-mcp"

_MODERATOR_ROLES = {"moderator", "admin"}


# --- tool handlers ------------------------------------------------------


async def _fetch_snapshot(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    snapshot_id = args["snapshot_id"]
    return await ctx.ledger.get_snapshot(snapshot_id)


async def _diff_snapshots(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    portal_id = args.get("portal_id")
    cursor = args.get("cursor")
    limit = int(args.get("limit", 20) or 20)

    if args.get("only_pending_review"):
        rows, next_cursor = await ctx.snapshots.list_pending_review(cursor=cursor, limit=limit)
        if portal_id:
            rows = [r for r in rows if r["portal_public_id"] == portal_id]
        return {
            "diffs": [
                {
                    "id": str(r["id"]),
                    "portal_id": r["portal_public_id"],
                    "portal_label": r["portal_label"],
                    "change_type": r["change_type"],
                    "old_text": r["old_text"],
                    "new_text": r["new_text"],
                    "from_snapshot_id": r["from_snapshot_public_id"],
                    "to_snapshot_id": r["to_snapshot_public_id"],
                    "proposed_category": r["category"],
                    "confidence": r["category_confidence"],
                    "needs_review": True,
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "next_cursor": next_cursor,
        }

    if not portal_id:
        raise ValueError("portal_id is required unless only_pending_review is true")
    rows, next_cursor = await ctx.ledger.list_changes(
        portal_public_id=portal_id, since=args.get("since"), cursor=cursor
    )
    return {"diffs": rows[:limit], "next_cursor": next_cursor}


async def _list_watched_portals(ctx: AppContext, _args: dict[str, Any]) -> dict[str, Any]:
    portals = await ctx.ledger.list_portals()
    return {"portals": portals}


async def _register_portal(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    moderator = await ctx.users.get_by_public_id(args["moderator_id"])
    if moderator is None:
        raise NotFound(detail_en="No user with that moderator_id.", detail_bn="এই আইডির কোনো ব্যবহারকারী নেই।")
    if moderator["role"] not in _MODERATOR_ROLES:
        raise Forbidden(
            detail_en="Only a moderator or admin account can register a portal.",
            detail_bn="শুধু মডারেটর বা অ্যাডমিন অ্যাকাউন্ট একটি পোর্টাল নিবন্ধন করতে পারে।",
        )
    portal = await ctx.moderation_service.create_portal(
        moderator["id"],
        url=args["url"],
        kind=args["kind"],
        country_code=args.get("country_code"),
        label=args["label"],
        parser_key=args.get("parser_key", "generic"),
        crawl_cron=args.get("crawl_cron", "0 */6 * * *"),
    )
    return {"portal": portal}


_HANDLERS = {
    "fetch_snapshot": _fetch_snapshot,
    "diff_snapshots": _diff_snapshots,
    "list_watched_portals": _list_watched_portals,
    "register_portal": _register_portal,
}


# --- tool schemas ---------------------------------------------------------

_TOOLS = [
    types.Tool(
        name="fetch_snapshot",
        description=(
            "Fetch one captured portal snapshot by its public id (e.g. "
            "'SNAP-01J8...'), including its passages and a short quoted "
            "excerpt. This reads an already-captured snapshot; it does not "
            "trigger a new crawl."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "snapshot_id": {"type": "string", "description": "Snapshot public id."},
            },
            "required": ["snapshot_id"],
        },
    ),
    types.Tool(
        name="diff_snapshots",
        description=(
            "Pull passage-level diffs for a watched portal: what changed "
            "between two of its snapshots, with the old and new text and any "
            "classification already recorded. Pass only_pending_review=true "
            "to pull the human review queue instead of the public change "
            "feed (optionally still scoped to portal_id)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "portal_id": {
                    "type": "string",
                    "description": "Portal public id. Required unless only_pending_review is true.",
                },
                "since": {"type": "string", "description": "ISO-8601 UTC lower bound, e.g. 2026-07-01T00:00:00Z."},
                "cursor": {"type": "string", "description": "Opaque pagination cursor from a previous call."},
                "only_pending_review": {
                    "type": "boolean",
                    "description": "Pull the moderator review queue (needs_review=1) instead of the public feed.",
                    "default": False,
                },
                "limit": {"type": "integer", "description": "Max rows to return.", "default": 20},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="list_watched_portals",
        description="List every watched portal: url, kind, country, crawl cadence, and last fetch status.",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    types.Tool(
        name="register_portal",
        description=(
            "Register a new portal to watch. Restricted to a moderator or "
            "admin account (moderator_id); records a 'portal_add' entry in "
            "the moderation audit trail, same as the moderator console."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "moderator_id": {"type": "string", "description": "Public id of the acting moderator/admin user."},
                "url": {"type": "string", "description": "Portal URL, e.g. https://ukvi.gov.uk/..."},
                "kind": {
                    "type": "string",
                    "enum": ["embassy", "university", "scholarship", "government", "bank"],
                },
                "label": {"type": "string", "description": "Short label shown in the UI, e.g. 'ukvi.gov.uk'."},
                "country_code": {"type": "string", "description": "ISO-3166-1 alpha-2, e.g. 'GB'."},
                "parser_key": {"type": "string", "default": "generic"},
                "crawl_cron": {"type": "string", "default": "0 */6 * * *"},
            },
            "required": ["moderator_id", "url", "kind", "label"],
        },
    ),
]


def build_server(ctx: AppContext) -> Server:
    server = Server(
        SERVER_NAME,
        version="1.0.0",
        instructions=(
            "Read and extend Digonto's Truth Ledger: watched portals, their "
            "captured snapshots, and the passage-level diffs between them. "
            "Every fact this tool set returns traces back to a snapshot id."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return _TOOLS

    dispatch = build_dispatcher(_HANDLERS, ctx)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await dispatch(name, arguments)

    return server


async def main() -> None:
    configure_stdio_logging(SERVER_NAME)
    async with app_context() as ctx:
        server = build_server(ctx)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
