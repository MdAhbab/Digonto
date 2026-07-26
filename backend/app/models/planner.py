"""Visa Timeline Reactor models.

Serves `Planner.tsx`. `titleEn`/`titleBn`/`descEn`/`descBn` and
`textEn`/`textBn` are camelCase on the wire, matching the existing `Step` and
`ChangeEntry` TypeScript interfaces exactly; everything else on this surface
is snake_case.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import SnapshotCitation

StepStatus = Literal["done", "active", "upcoming", "blocked"]
ChangeTrigger = Literal[
    "portal_change", "profile_update", "document_change", "manual", "schedule"
]


class PlanStepOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    step_key: str
    month: str
    title_en: str = Field(alias="titleEn")
    title_bn: str = Field(alias="titleBn")
    desc_en: str = Field(alias="descEn")
    desc_bn: str = Field(alias="descBn")
    status: StepStatus
    due_at: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    citation: SnapshotCitation | None = None


class PlanTimelineOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    plan_id: str
    intake_label: str | None = None
    steps: list[PlanStepOut]
    unseen_changes: int


class PlanChangeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    text_en: str = Field(alias="textEn")
    text_bn: str = Field(alias="textBn")
    source: str
    trigger: ChangeTrigger
    step_key: str | None = None
    created_at: str
    seen: bool


class SimulateResponse(BaseModel):
    """`POST /planner/simulate` — always carries `simulated: true`.

    Demonstration only: it injects a synthetic `portal.changed` event scoped
    to the caller's own plan, never writes to the knowledge store, and never
    notifies another user.
    """

    model_config = ConfigDict(populate_by_name=True)

    simulated: Literal[True] = True
    change: PlanChangeOut
    plan: PlanTimelineOut
