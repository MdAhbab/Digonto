"""Funding Studio and Khoji models.

Matches api_contract.md section 9. Snake_case throughout; the scholarship
broadsheet has no camelCase requirement (unlike Ask/Planner/Vault).

Note on `/funding/sources`: `docs/database.md` has no table for an itemised,
freely add/removable list of funding sources; the closest real columns are
`budgets.own_funds_bdt` and `budgets.awards_bdt`. Migrations are out of
scope for this build, so `FundingSourceOut` models a small closed set of
source kinds backed by those two aggregate columns rather than an arbitrary
user-defined list. See the final report for the full explanation.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.models.common import SnapshotCitation

CoverageType = Literal["full", "partial", "tuition_only", "stipend_only", "travel"]
SortKey = Literal["name", "country", "coverage", "deadline"]
SortOrder = Literal["asc", "desc"]
FeeCategory = Literal["free", "official_fee", "fair_service", "unjustified"]
SourceKind = Literal["own_funds", "awards", "sponsorship", "loan", "other"]


class MatchReasonOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    criterion: str
    met: bool
    reason_en: str
    reason_bn: str


class ScholarshipOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    country: str | None = None
    # What the award is worth, and what kind of award it is. These used to be a single
    # `coverage: int` populated from `scholarships.amount`, which is a money value; the
    # funding table rendered it with a percent sign and reported a 1,500,000 BDT award
    # as "1500000%". A number whose unit is not carried alongside it will eventually be
    # printed with the wrong unit, so the unit travels with it now.
    amount: int | None = None
    currency: str | None = None
    coverage_type: CoverageType | None = None
    deadline: str | None = None
    score: float
    rank: int
    eligible: bool
    verified: bool
    reasons: list[MatchReasonOut]
    citation: SnapshotCitation | None = None


class ScholarshipDetail(ScholarshipOut):
    model_config = ConfigDict(populate_by_name=True)

    provider: str
    url: str


class BudgetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tuition_bdt: int
    living_bdt: int
    travel_bdt: int
    visa_fee_bdt: int
    awards_bdt: int
    own_funds_bdt: int
    gap_bdt: int
    solvency_required_bdt: int | None = None
    fx_rate_used: float | None = None
    computed_at: str


class FundingSourceCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: SourceKind
    amount_bdt: int


class FundingSourceOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    kind: SourceKind
    label_en: str
    label_bn: str
    amount_bdt: int


class FeeCheckRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    consultancy: str | None = None
    quoted_bdt: int | None = None
    country: str | None = None
    document_id: str | None = None


class FeeLineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    label_en: str
    label_bn: str
    category: FeeCategory
    amount_bdt: int
    note_en: str | None = None
    note_bn: str | None = None
    citation: SnapshotCitation | None = None


class FeeCheckOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    quoted_bdt: int
    fair_bdt: int | None = None
    lines: list[FeeLineOut]
