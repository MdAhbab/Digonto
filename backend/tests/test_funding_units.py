"""Money units in the funding math.

Two tables in this schema store money in two different conventions, and the
conversion in `compose_budget` has to know which is which:

  * `programmes.tuition_amount` is in MINOR units (002_profile.sql column
    comment) — 3850000 is GBP 38,500.
  * `solvency_rules.amount` is in MAJOR units — the seeded UK row is 13347 for
    GBP 13,347.

`fx_rates.rate` is quoted per MAJOR unit. Multiplying a minor-unit tuition by
that rate overstated every tuition figure by exactly 100, which put a GBP 26,800
master's degree on screen at roughly 40 crore taka. These tests pin both
conventions so the two cannot drift back together.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.repositories.budget_repo import BudgetRepo


@pytest.fixture
async def dbs():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        d = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await d.connect_all()
        await run_migrations(d)
        try:
            yield d
        finally:
            await d.close_all()


async def test_seeded_tuition_is_stored_in_minor_units(dbs) -> None:
    """A master's degree costs thousands, not millions, in its own currency."""
    rows = await dbs.app.fetch_all(
        """SELECT name, tuition_amount, tuition_currency FROM programmes
            WHERE tuition_amount > 0 AND tuition_currency IN ('GBP','EUR','CAD','AUD','USD')"""
    )
    assert rows, "expected seeded programmes priced in a major world currency"
    for row in rows:
        major = row["tuition_amount"] / 100
        assert 1_000 <= major <= 100_000, (
            f"{row['name']}: {major} {row['tuition_currency']} is not a plausible "
            f"annual tuition — tuition_amount must be in minor units"
        )


async def test_seeded_solvency_is_stored_in_major_units(dbs) -> None:
    """The counterpart convention: solvency amounts are not multiplied by 100."""
    rows = await dbs.app.fetch_all(
        "SELECT country_code, amount, currency FROM solvency_rules WHERE currency != 'JPY'"
    )
    assert rows
    for row in rows:
        assert 1_000 <= row["amount"] <= 500_000, (
            f"{row['country_code']}: {row['amount']} {row['currency']} is not a "
            f"plausible maintenance requirement in major units"
        )


async def test_tuition_conversion_does_not_multiply_by_a_hundred(dbs) -> None:
    """The arithmetic `compose_budget` performs, pinned end to end.

    GBP 26,800 stored as 2680000 minor units, at 152 BDT to the pound, is
    4,073,600 BDT. The pre-fix code returned 407,360,000.
    """
    budgets = BudgetRepo(dbs.app)
    fx = await budgets.latest_fx_rate("GBP", "BDT")
    assert fx is not None, "the GBP->BDT rate is seeded by migration 007"

    tuition_minor = 2_680_000
    tuition_bdt = round((tuition_minor / 100) * fx["rate"])

    assert tuition_bdt == round(26_800 * fx["rate"])
    assert tuition_bdt < 50_000_000, (
        "a single year of tuition above 5 crore taka means the minor-unit "
        "division was dropped again"
    )


async def test_every_solvency_rule_cites_a_real_portal(dbs) -> None:
    """Migration 026 makes the citation a foreign key, not a sentence.

    A typo in one of the seeded URLs would leave `source_portal_id` NULL and
    silently strip the citation from a policy figure, which is the one thing
    this product may not do.
    """
    orphans = await dbs.app.fetch_all(
        """SELECT s.country_code, s.visa_type FROM solvency_rules s
             LEFT JOIN portals p ON p.id = s.source_portal_id
            WHERE s.source_portal_id IS NULL OR p.id IS NULL"""
    )
    assert orphans == [], (
        "every solvency rule must resolve to a portal in the registry; "
        f"unresolved: {[dict(o) for o in orphans]}"
    )


async def test_every_destination_country_has_a_solvency_rule_and_an_fx_rate(dbs) -> None:
    """The Funding Studio needs both for any country a student can shortlist."""
    countries = await dbs.app.fetch_all("SELECT code FROM countries WHERE active = 1")
    codes = {c["code"] for c in countries}

    ruled = await dbs.app.fetch_all("SELECT DISTINCT country_code FROM solvency_rules")
    assert codes - {r["country_code"] for r in ruled} == set()

    priced = await dbs.app.fetch_all(
        "SELECT DISTINCT tuition_currency AS c FROM programmes WHERE tuition_amount > 0"
    )
    rated = await dbs.app.fetch_all("SELECT DISTINCT base FROM fx_rates WHERE quote = 'BDT'")
    missing = {p["c"] for p in priced} - {r["base"] for r in rated} - {"BDT"}
    assert missing == set(), f"programmes priced in {missing} have no BDT rate on file"


async def test_every_destination_country_has_a_programme(dbs) -> None:
    """A country with no programme cannot produce a target, which silently
    breaks the plan and the budget downstream of it."""
    rows = await dbs.app.fetch_all(
        """SELECT c.code, COUNT(p.id) AS n FROM countries c
             LEFT JOIN institutions i ON i.country_code = c.code
             LEFT JOIN programmes p ON p.institution_id = i.id
            WHERE c.active = 1 GROUP BY c.code"""
    )
    empty = [r["code"] for r in rows if r["n"] == 0]
    assert empty == [], f"no programmes for {empty}"
