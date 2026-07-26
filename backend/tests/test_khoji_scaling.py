"""Khoji's behaviour as the funding index grows.

Two things were sized for the six seeded awards rather than for a real index:
the criteria fetch ran one query per award, and the fenced award block passed to
the model had no explicit bound, so it would have been cut mid-line by
`frame_untrusted`'s 12,000-character default once the catalogue grew — leaving
the tail of the list unscored with nothing to say why.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from app.agents import khoji
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.repositories.scholarship_repo import ScholarshipRepo


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


class CountingRouter:
    """Stands in for the model. Records the prompt it was asked to send."""

    def __init__(self) -> None:
        self.calls: list[str] = []


async def test_criteria_batch_matches_per_award_lookup(dbs) -> None:
    repo = ScholarshipRepo(dbs.app)
    awards = await repo.list_active()
    assert awards, "migration 007 seeds the funding index"

    ids = [a["id"] for a in awards]
    batched = await repo.criteria_by_scholarship(ids)

    assert set(batched) == set(ids), "every award must appear, even with no criteria"
    for award_id in ids:
        one_by_one = await repo.list_criteria(award_id)
        assert len(batched[award_id]) == len(one_by_one)
        assert {c["criterion_key"] for c in batched[award_id]} == {
            c["criterion_key"] for c in one_by_one
        }


async def test_criteria_batch_handles_an_empty_id_list(dbs) -> None:
    repo = ScholarshipRepo(dbs.app)
    assert await repo.criteria_by_scholarship([]) == {}


async def test_award_block_is_capped_and_the_overflow_is_still_returned(monkeypatch) -> None:
    """A large index must not silently drop awards or overrun the fence."""
    sent: dict[str, str] = {}

    async def fake_structured(_router, call):
        sent["user"] = call.user
        # Score only what the model was actually shown.
        ids = [
            line.split("id=")[1].split(" ")[0]
            for line in call.user.splitlines()
            if line.startswith("- id=")
        ]
        return {
            "results": [
                {
                    "scholarship_id": i,
                    "score": 0.9,
                    "eligible": True,
                    "reasons": [
                        {"criterion_key": "fit", "met": True,
                         "reason_en": "ok", "reason_bn": "ঠিক আছে"},
                    ],
                }
                for i in ids
            ]
        }

    monkeypatch.setattr(khoji, "structured", fake_structured)

    total = khoji._MAX_SCORED_AWARDS + 17
    awards = [
        {
            "public_id": f"AWARD{n:04d}",
            "name": f"Award number {n} with a reasonably long descriptive name",
            "provider": "A provider with a long institutional name",
            "country_code": "uk",
            "coverage_type": "full",
            "fields": None,
            "criteria": [],
        }
        for n in range(total)
    ]
    profile = {
        "degree_level": "master", "field_of_study": "Computer Science",
        "cgpa": 3.6, "cgpa_scale": 4.0, "english_test": "ielts",
        "english_overall": 7.0, "graduation_year": 2024, "study_gap_years": 0,
        "nationality": "Bangladesh",
    }

    results = await khoji.score_eligibility(
        profile=profile, scholarships=awards, router=CountingRouter()
    )

    # Nothing is lost: every award comes back, scored or explicitly unscored.
    assert len(results) == total
    assert {r["scholarship_id"] for r in results} == {a["public_id"] for a in awards}

    # The prompt carried at most the cap, and stayed inside the fence budget.
    assert sent["user"].count("- id=") == khoji._MAX_SCORED_AWARDS
    assert len(sent["user"]) < 12_000

    # The overflow is presented as eligible, not as a failure or a zero.
    unscored = [r for r in results if r["score"] == 0.5]
    assert len(unscored) == 17
    assert all(r["eligible"] for r in unscored)
