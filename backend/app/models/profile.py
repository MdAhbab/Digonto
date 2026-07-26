"""Profile, targets, and programme search models.

Field names follow `profiles`, `student_targets`, and `programmes` in
`docs/database.md` section 3.2 verbatim; this surface is not one of the
camelCase exceptions, so everything stays snake_case.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

DegreeLevel = Literal["bachelor", "master", "phd", "diploma"]
EnglishTest = Literal["ielts", "toefl", "duolingo", "pte", "none"]
TargetStatus = Literal[
    "considering", "applying", "submitted", "offer", "rejected", "accepted", "withdrawn"
]


class EnglishSub(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    listening: float | None = None
    reading: float | None = None
    writing: float | None = None
    speaking: float | None = None


class ProfileOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    display_name: str | None = None
    home_district: str | None = None
    degree_level: DegreeLevel | None = None
    field_of_study: str | None = None
    cgpa: float | None = None
    cgpa_scale: float | None = None
    graduation_year: int | None = None
    english_test: EnglishTest | None = None
    english_overall: float | None = None
    english_sub: EnglishSub | None = None
    budget_bdt: int | None = None
    intake_target: str | None = None
    study_gap_years: int = 0
    updated_at: str


class ProfilePatch(BaseModel):
    """All fields optional: this is a PATCH, only supplied fields change."""

    model_config = ConfigDict(populate_by_name=True)

    display_name: str | None = None
    home_district: str | None = None
    degree_level: DegreeLevel | None = None
    field_of_study: str | None = None
    cgpa: float | None = None
    cgpa_scale: float | None = None
    graduation_year: int | None = None
    english_test: EnglishTest | None = None
    english_overall: float | None = None
    english_sub: EnglishSub | None = None
    budget_bdt: int | None = None
    intake_target: str | None = None
    study_gap_years: int | None = None


class ProgrammeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    institution_id: str
    institution_name: str
    country_code: str
    name: str
    degree_level: DegreeLevel
    field_of_study: str | None = None
    duration_months: int | None = None
    tuition_amount: int | None = None
    tuition_currency: str | None = None
    intake_months: list[str] | None = None
    min_cgpa: float | None = None
    min_english: float | None = None
    deadline_at: str | None = None
    updated_at: str


class TargetCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    programme_id: str
    visa_type: str | None = None


class TargetOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    programme_id: str
    programme_name: str
    institution_name: str
    country_code: str
    visa_type: str | None = None
    rank: int
    status: TargetStatus
    created_at: str
