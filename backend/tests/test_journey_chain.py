"""The chain from a destination to a plan, end to end.

Destination -> programme -> target -> plan -> budget is the spine of this
product, and every link of it was reachable from the API and unreachable from
the UI: `GET /programmes` and `POST /me/targets` existed and no page called
them. With no way to create a target, `/planner/timeline` anchored every plan on
`now + 270 days` instead of a real deadline and `/funding/budget` had nothing to
price. These tests exercise the chain at the service layer so the links stay
connected whichever surface calls them.
"""
from __future__ import annotations

import pathlib
import tempfile
from datetime import datetime

import pytest

from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.events.bus import EventBus
from app.repositories.budget_repo import BudgetRepo
from app.repositories.plan_repo import PlanRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password
from app.services.planner_service import PlannerService
from app.services.profile_service import ProfileService


class StubRedis:
    """Enough of the Redis surface for `EventBus.publish` to complete.

    These tests are about the journey chain, not delivery; events.db is the
    durable write and it goes through the real `Database`, so the assertions
    below still see everything that matters.
    """

    def __init__(self) -> None:
        self.published: list[tuple[str, dict]] = []

    async def xadd(self, stream: str, fields: dict, **_: object) -> str:
        self.published.append((stream, fields))
        return "0-1"


@pytest.fixture
async def env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        users = UserRepo(dbs.app)
        user = await users.create(
            email="journey@example.com",
            password_hash=hash_password("a long enough passphrase"),
            display_name="Journey",
        )
        bus = EventBus(StubRedis(), dbs.events)  # type: ignore[arg-type]
        profiles = ProfileService(
            ProfileRepo(dbs.app, dbs.events), TargetRepo(dbs.app), bus
        )
        planner = PlannerService(
            PlanRepo(dbs.app), TargetRepo(dbs.app), ProfileRepo(dbs.app, dbs.events),
            BudgetRepo(dbs.app), bus,
        )
        try:
            yield dbs, user, profiles, planner
        finally:
            await dbs.close_all()


async def test_every_destination_can_produce_a_target(env) -> None:
    """The gap that broke the journey: a country you can shortlist but not act on.

    Before the catalogue expansion, six of eight destinations had no programme,
    so a student who chose Germany could go no further.
    """
    dbs, user, profiles, _ = env
    countries = await profiles.list_destinations(user["id"])
    assert len(countries) == 8

    for country in countries:
        rows, _ = await profiles.search_programmes(
            country=country["code"], level=None, field=None, q=None, cursor=None
        )
        assert rows, f"no programmes to choose from for {country['code']}"

        target = await profiles.create_target(
            user["id"], user["public_id"], rows[0]["public_id"], country["code"]
        )
        assert target["public_id"]


async def test_timeline_anchors_on_the_programme_deadline(env) -> None:
    """A plan built against a target uses that programme's real deadline.

    With no target the anchor is `now + 270 days`, which is a generic plan
    wearing a real one's clothes.
    """
    dbs, user, profiles, planner = env
    rows, _ = await profiles.search_programmes(
        country="uk", level=None, field=None, q=None, cursor=None
    )
    programme = next(r for r in rows if r["deadline_at"])
    target = await profiles.create_target(
        user["id"], user["public_id"], programme["public_id"], "student"
    )

    timeline = await planner.regenerate(user["id"], target["public_id"])
    apply_step = next(s for s in timeline["steps"] if s["step_key"] == "apply")

    # `apply` has lead_days 0, so it lands exactly on the anchor.
    assert apply_step["due_at"] == programme["deadline_at"][:10]


async def test_solvency_step_uses_the_country_hold_period_not_a_constant(env) -> None:
    """The drift this module's docstring claimed was already fixed.

    `BudgetRepo` was injected into PlannerService and never called; every
    country got a flat 45-day solvency lead. The UK requires 28 consecutive
    days and Germany's blocked account requires none, so one constant cannot
    serve both.
    """
    dbs, user, profiles, planner = env

    uk_rows, _ = await profiles.search_programmes(
        country="uk", level=None, field=None, q=None, cursor=None
    )
    uk_target = await profiles.create_target(
        user["id"], user["public_id"], uk_rows[0]["public_id"], "student"
    )
    de_rows, _ = await profiles.search_programmes(
        country="de", level=None, field=None, q=None, cursor=None
    )
    de_target = await profiles.create_target(
        user["id"], user["public_id"], de_rows[0]["public_id"], "national_visa"
    )

    def gap_days(timeline: dict) -> int:
        steps = {s["step_key"]: s for s in timeline["steps"]}
        apply_at = datetime.strptime(steps["apply"]["due_at"], "%Y-%m-%d")
        solvency_at = datetime.strptime(steps["solvency"]["due_at"], "%Y-%m-%d")
        return (apply_at - solvency_at).days

    uk = await planner.regenerate(user["id"], uk_target["public_id"])
    de = await planner.regenerate(user["id"], de_target["public_id"])

    # 28-day hold plus the statement margin, against no hold plus the margin.
    assert gap_days(uk) == 28 + 14
    assert gap_days(de) == 0 + 14
    assert gap_days(uk) > gap_days(de)


async def test_solvency_step_quotes_the_country_figure_in_both_languages(env) -> None:
    dbs, user, profiles, planner = env
    rows, _ = await profiles.search_programmes(
        country="uk", level=None, field=None, q=None, cursor=None
    )
    target = await profiles.create_target(
        user["id"], user["public_id"], rows[0]["public_id"], "student"
    )
    timeline = await planner.regenerate(user["id"], target["public_id"])
    step = next(s for s in timeline["steps"] if s["step_key"] == "solvency")

    assert "13,347 GBP" in step["descEn"]
    assert "13,347 GBP" in step["descBn"]
    # The Bangla description must actually be Bangla, not an English fallback.
    assert any("ঀ" <= ch <= "৿" for ch in step["descBn"])
    assert step["descEn"] != step["descBn"]


async def test_each_target_gets_its_own_plan(env) -> None:
    """Two targets must not share one timeline.

    `get_timeline(user, None)` returns the most recently updated plan, so a
    student with several targets who never passes one sees an arbitrary plan.
    """
    dbs, user, profiles, planner = env
    uk_rows, _ = await profiles.search_programmes(
        country="uk", level=None, field=None, q=None, cursor=None
    )
    a = await profiles.create_target(
        user["id"], user["public_id"], uk_rows[0]["public_id"], "student"
    )
    b = await profiles.create_target(
        user["id"], user["public_id"], uk_rows[1]["public_id"], "student"
    )

    plan_a = await planner.get_timeline(user["id"], a["public_id"])
    plan_b = await planner.get_timeline(user["id"], b["public_id"])
    assert plan_a["plan_id"] != plan_b["plan_id"]


async def test_completing_a_step_survives_a_regenerate(env) -> None:
    """Regenerating must recompute dates without discarding progress."""
    dbs, user, profiles, planner = env
    rows, _ = await profiles.search_programmes(
        country="uk", level=None, field=None, q=None, cursor=None
    )
    target = await profiles.create_target(
        user["id"], user["public_id"], rows[0]["public_id"], "student"
    )
    timeline = await planner.regenerate(user["id"], target["public_id"])
    step = next(s for s in timeline["steps"] if s["step_key"] == "english_test")

    after = await planner.complete_step(user["id"], step["id"])
    assert next(s for s in after["steps"] if s["step_key"] == "english_test")["status"] == "done"

    again = await planner.regenerate(user["id"], target["public_id"])
    assert next(s for s in again["steps"] if s["step_key"] == "english_test")["status"] == "done"
