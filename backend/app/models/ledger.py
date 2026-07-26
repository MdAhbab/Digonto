"""Truth Ledger models: public, no-auth verification surface.

Matches api_contract.md section 6 verbatim, snake_case throughout.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

PortalKind = Literal["embassy", "university", "scholarship", "government", "bank"]
PortalStatus = Literal["ok", "unchanged", "unreachable", "parse_failed"]
ChangeType = Literal["added", "removed", "modified"]
ChangeCategory = Literal["deadline", "fee", "document_requirement", "policy", "cosmetic"]


class LedgerPassage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ordinal: int
    section_path: str | None = None
    text: str


class SnapshotDetail(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    portal: str
    portal_url: str
    captured: str
    content_hash: str
    http_status: int | None = None
    quoted: str | None = None
    retired: bool
    passages: list[LedgerPassage]


class PortalOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    url: str
    kind: PortalKind
    country_code: str | None = None
    label: str
    enabled: bool
    last_fetch_at: str | None = None
    last_status: PortalStatus | None = None
    consecutive_failures: int


class LedgerChangeOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    portal_id: str
    change_type: ChangeType
    category: ChangeCategory | None = None
    category_confidence: float | None = None
    old_text: str | None = None
    new_text: str | None = None
    created_at: str
