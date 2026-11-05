"""GET /programmes must serialise both shapes of intake_months the data holds.

Migration 027's catalogue stores month numbers and the demo seed stores month
names. Accepting only strings made one catalogue row crash the whole listing.
"""

from __future__ import annotations

import json

import pytest

from app.routers.destinations import _programme_out


def _row(intake_months: str | None) -> dict:
    return {
        "public_id": "PROG-1",
        "institution_public_id": "INST-1",
        "institution_name": "Example University",
        "country_code": "GB",
        "name": "MSc Data Science",
        "degree_level": "master",
        "intake_months": intake_months,
        "updated_at": "2026-01-01T00:00:00Z",
    }


@pytest.mark.parametrize(
    "stored",
    [[9, 1], ["September"]],
    ids=["catalogue-month-numbers", "seeded-month-names"],
)
def test_intake_months_survive_serialisation_unchanged(stored: list) -> None:
    assert _programme_out(_row(json.dumps(stored))).intake_months == stored


def test_missing_intake_months_stays_none() -> None:
    assert _programme_out(_row(None)).intake_months is None
