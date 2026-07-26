"""`digonto-funding-mcp`: Khoji's funding tools, over stdio.

Backs Khoji (agents.md, Agent 3) and Dalil's fee-clause benchmarking (Agent
7). Every tool calls into `app.repositories.scholarship_repo` /
`app.repositories.budget_repo` / `app.repositories.target_repo` for reference
data that already has a repository method, or
`app.services.funding_service.FundingService.fee_check` for the one piece of
business logic ("what does an honest fee benchmark look like given we have no
certified official fee schedule") that already lives in a service. Nothing
here issues its own SQL.

Tools:
  - search_scholarships(country=None, profile=None, cursor=None, limit=20)
  - get_fx_rate(base, quote)
  - get_solvency_rules(country_code, visa_type)
  - compose_budget(user_id, target_id, living_bdt=0, travel_bdt=0,
                    visa_fee_bdt=0, tuition_bdt=None, awards_bdt=None,
                    own_funds_bdt=None)
  - get_fee_benchmarks(user_id, consultancy=None, quoted_bdt=None, country=None)

Run standalone: `python -m app.mcp.funding_server` (from `backend/`). See
`app/mcp/README.md` for MCP client registration.
"""

from __future__ import annotations

import asyncio
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from app.errors import NotFound
from app.mcp._common import AppContext, app_context, build_dispatcher, configure_stdio_logging

SERVER_NAME = "digonto-funding-mcp"


# --- generic, transparent hard-criteria evaluation ------------------------
#
# app/agents/khoji.py has its own hard-criteria check, but it reads flattened
# keys (`award["min_cgpa"]`, `award["degree_levels"]`, ...) that nothing in
# app/services/funding_service.py actually populates onto the scholarship
# dict it builds (that dict carries a `criteria` list instead); Khoji's own
# filter is therefore effectively a no-op today. That is existing,
# authoritative code and out of scope to fix here. This search tool is a
# separate, lower-level "browse the index" surface (agents.md: Khoji "filters
# the funding index by hard criteria" *before* the model ever scores
# anything), so it evaluates the real `scholarship_criteria` rows directly,
# transparently, and reports exactly what it could and could not check.


def _criterion_met(operator: str, value: str, actual: Any) -> bool | None:
    """Evaluate one `scholarship_criteria` row against a known value.

    Returns True/False, or None when the criterion cannot be judged (the
    caller's profile did not supply this field, or the row's stored value
    does not parse for the given operator). None is surfaced to the caller
    as "unverified", never silently treated as a pass or a fail.
    """
    if actual is None:
        return None
    try:
        if operator == "gte":
            return float(actual) >= float(value)
        if operator == "lte":
            return float(actual) <= float(value)
        if operator == "eq":
            return str(actual).strip().casefold() == str(value).strip().casefold()
        if operator == "in":
            options = {v.strip().casefold() for v in value.split(",")}
            return str(actual).strip().casefold() in options
        if operator == "exists":
            return bool(actual)
    except (TypeError, ValueError):
        return None
    return None


def _profile_value(profile: dict[str, Any], criterion_key: str) -> Any:
    """`cgpa_min` special-cases scale normalisation (Bangladeshi institutions
    use both a 4.0 and a 5.0 scale, same as app/agents/khoji.py); every other
    criterion key is looked up on the profile dict verbatim, so a caller that
    names its fields the same as `scholarship_criteria.criterion_key`
    (`degree_level`, `field_of_study`, `nationality`, ...) gets a real answer,
    and one that does not gets an honest "unverified" rather than a guess.
    """
    if criterion_key == "cgpa_min":
        cgpa = profile.get("cgpa")
        if cgpa is None:
            return None
        scale = profile.get("cgpa_scale") or 4.0
        return float(cgpa) * (4.0 / float(scale))
    return profile.get(criterion_key)


# --- tool handlers ------------------------------------------------------


async def _require_user(ctx: AppContext, user_public_id: str) -> dict[str, Any]:
    user = await ctx.users.get_by_public_id(user_public_id)
    if user is None:
        raise NotFound(detail_en="No user with that user_id.", detail_bn="এই আইডির কোনো ব্যবহারকারী নেই।")
    return user


async def _search_scholarships(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    country = args.get("country")
    profile = args.get("profile") or {}
    limit = int(args.get("limit", 20) or 20)

    scholarships = await ctx.scholarships.list_active(country=country)
    out: list[dict[str, Any]] = []
    for sc in scholarships:
        criteria = await ctx.scholarships.list_criteria(sc["id"])
        checks = []
        disqualified = False
        for c in criteria:
            met = _criterion_met(c["operator"], c["value"], _profile_value(profile, c["criterion_key"]))
            checks.append(
                {
                    "criterion_key": c["criterion_key"],
                    "operator": c["operator"],
                    "value": c["value"],
                    "is_hard": bool(c["is_hard"]),
                    "met": met,
                }
            )
            if c["is_hard"] and met is False:
                disqualified = True
        if disqualified:
            continue
        out.append(
            {
                "id": sc["public_id"],
                "name": sc["name"],
                "provider": sc["provider"],
                "country": sc["country_code"],
                "coverage_type": sc["coverage_type"],
                "amount": sc["amount"],
                "currency": sc["currency"],
                "deadline_at": sc["deadline_at"],
                "url": sc["url"],
                "verified": bool(sc["verified"]),
                "criteria_checked": checks,
            }
        )
        if len(out) >= limit:
            break
    return {"scholarships": out}


async def _get_fx_rate(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    rate = await ctx.budgets.latest_fx_rate(args["base"].upper(), args["quote"].upper())
    if rate is None:
        raise NotFound(
            detail_en=f"No fx rate on file for {args['base']}->{args['quote']}.",
            detail_bn="এই মুদ্রা জোড়ার কোনো বিনিময় হার রেকর্ডে নেই।",
        )
    return {"rate": rate}


async def _get_solvency_rules(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    rule = await ctx.budgets.solvency_rule(args["country_code"], args["visa_type"])
    if rule is None:
        raise NotFound(
            detail_en="No solvency rule on file for that country and visa type.",
            detail_bn="এই দেশ ও ভিসা ধরনের জন্য কোনো সচ্ছলতার নিয়ম রেকর্ডে নেই।",
        )
    return {"rule": rule}


async def _compose_budget(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    target = await ctx.targets.get_target(user["id"], args["target_id"])
    if target is None:
        raise NotFound(detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।")

    programme = None
    if target.get("programme_id"):
        programme = await ctx.targets.get_programme(target["programme_id"])

    living_bdt = int(args.get("living_bdt", 0) or 0)
    travel_bdt = int(args.get("travel_bdt", 0) or 0)
    visa_fee_bdt = int(args.get("visa_fee_bdt", 0) or 0)

    existing = await ctx.budgets.get_for_target(user["id"], target["id"])
    notes: list[str] = []

    fx_rate_used: float | None = None
    tuition_bdt: int | None = None
    if programme and programme.get("tuition_amount"):
        currency = (programme.get("tuition_currency") or "BDT").upper()
        amount = programme["tuition_amount"]
        if currency == "BDT":
            tuition_bdt = int(amount)
        else:
            fx = await ctx.budgets.latest_fx_rate(currency, "BDT")
            if fx:
                fx_rate_used = fx["rate"]
                tuition_bdt = round(amount * fx_rate_used)
            else:
                notes.append(f"No {currency}->BDT rate on file; tuition left at 0 pending one.")
    if tuition_bdt is None:
        tuition_bdt = int(args.get("tuition_bdt", 0) or 0)

    awards_bdt = args.get("awards_bdt")
    awards_bdt = int(awards_bdt) if awards_bdt is not None else (existing["awards_bdt"] if existing else 0)
    own_funds_bdt = args.get("own_funds_bdt")
    own_funds_bdt = (
        int(own_funds_bdt) if own_funds_bdt is not None else (existing["own_funds_bdt"] if existing else 0)
    )

    solvency_required_bdt: int | None = None
    country_code = (programme or {}).get("country_code") or args.get("country_code")
    visa_type = target.get("visa_type") or args.get("visa_type")
    if country_code and visa_type:
        rule = await ctx.budgets.solvency_rule(country_code, visa_type)
        if rule:
            if rule["currency"].upper() == "BDT":
                solvency_required_bdt = rule["amount"]
            else:
                fx2 = await ctx.budgets.latest_fx_rate(rule["currency"], "BDT")
                if fx2:
                    solvency_required_bdt = round(rule["amount"] * fx2["rate"])
                else:
                    notes.append(
                        f"Solvency rule is in {rule['currency']}; no rate on file to convert to BDT."
                    )

    gap_bdt = max(0, tuition_bdt + living_bdt + travel_bdt + visa_fee_bdt - awards_bdt - own_funds_bdt)

    budget = await ctx.budgets.upsert(
        user_id=user["id"],
        target_id=target["id"],
        tuition_bdt=tuition_bdt,
        living_bdt=living_bdt,
        travel_bdt=travel_bdt,
        visa_fee_bdt=visa_fee_bdt,
        awards_bdt=awards_bdt,
        own_funds_bdt=own_funds_bdt,
        gap_bdt=gap_bdt,
        solvency_required_bdt=solvency_required_bdt,
        fx_rate_used=fx_rate_used,
    )
    return {"budget": budget, "notes": notes}


async def _get_fee_benchmarks(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    result = await ctx.funding.fee_check(
        user["id"],
        consultancy=args.get("consultancy"),
        quoted_bdt=args.get("quoted_bdt"),
        country=args.get("country"),
        document_id=args.get("document_id"),
    )
    return result


_HANDLERS = {
    "search_scholarships": _search_scholarships,
    "get_fx_rate": _get_fx_rate,
    "get_solvency_rules": _get_solvency_rules,
    "compose_budget": _compose_budget,
    "get_fee_benchmarks": _get_fee_benchmarks,
}


# --- tool schemas ---------------------------------------------------------

_TOOLS = [
    types.Tool(
        name="search_scholarships",
        description=(
            "Filter the active scholarship index by hard criteria. Pass a "
            "profile object (any of cgpa, cgpa_scale, degree_level, "
            "field_of_study, nationality, graduation_year, english_overall) "
            "to check it against each scholarship's stored criteria rows; "
            "omit profile to just browse the index for a country. Every "
            "returned scholarship carries the specific criteria checked and "
            "whether each was met, unmet, or unverifiable, never a bare "
            "yes/no."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "country": {"type": "string", "description": "ISO-3166-1 alpha-2 filter."},
                "profile": {"type": "object", "description": "Ad hoc profile fields to check hard criteria against."},
                "limit": {"type": "integer", "default": 20},
            },
            "required": [],
        },
    ),
    types.Tool(
        name="get_fx_rate",
        description="Look up the latest on-file exchange rate between two currency codes.",
        inputSchema={
            "type": "object",
            "properties": {
                "base": {"type": "string", "description": "e.g. 'USD'."},
                "quote": {"type": "string", "description": "e.g. 'BDT'."},
            },
            "required": ["base", "quote"],
        },
    ),
    types.Tool(
        name="get_solvency_rules",
        description="Look up the bank-balance amount an embassy requires for a country and visa type.",
        inputSchema={
            "type": "object",
            "properties": {
                "country_code": {"type": "string"},
                "visa_type": {"type": "string"},
            },
            "required": ["country_code", "visa_type"],
        },
    ),
    types.Tool(
        name="compose_budget",
        description=(
            "Compose and persist a full funding plan for one of a student's "
            "targets: tuition (converted to BDT from the programme's own "
            "currency when an fx rate is on file), living/travel/visa-fee "
            "inputs, award coverage, remaining gap in BDT, and the bank "
            "solvency amount the embassy requires, all cited to the "
            "programme and solvency_rules rows used. awards_bdt/own_funds_bdt "
            "default to whatever is already on record for this target if not "
            "given."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "target_id": {"type": "string", "description": "student_targets public id."},
                "living_bdt": {"type": "integer", "default": 0},
                "travel_bdt": {"type": "integer", "default": 0},
                "visa_fee_bdt": {"type": "integer", "default": 0},
                "tuition_bdt": {
                    "type": "integer",
                    "description": "Only used if the target's programme has no tuition_amount on file.",
                },
                "awards_bdt": {"type": "integer"},
                "own_funds_bdt": {"type": "integer"},
                "country_code": {"type": "string", "description": "Only used if the programme has no institution country."},
                "visa_type": {"type": "string", "description": "Only used if the target has no visa_type set."},
            },
            "required": ["user_id", "target_id"],
        },
    ),
    types.Tool(
        name="get_fee_benchmarks",
        description=(
            "Benchmark a consultancy fee quote (app.services.funding_service."
            "FundingService.fee_check): itemises what this system can "
            "actually certify as free or official versus what remains an "
            "unverified consultancy charge, pending a real fee-schedule "
            "source. Feeds Dalil's Agent Fee Reality Check."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "consultancy": {"type": "string"},
                "quoted_bdt": {"type": "integer"},
                "country": {"type": "string"},
                "document_id": {"type": "string"},
            },
            "required": ["user_id"],
        },
    ),
]


def build_server(ctx: AppContext) -> Server:
    server = Server(
        SERVER_NAME,
        version="1.0.0",
        instructions=(
            "Funding reference data and arithmetic for Khoji and Dalil: "
            "scholarship search, fx rates, solvency rules, a composed "
            "per-target budget, and fee-quote benchmarking. Every eligibility "
            "check is returned with its criteria, never a bare score."
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
