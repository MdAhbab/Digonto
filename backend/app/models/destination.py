"""`GET /destinations` and the shortlist.

Serves `Destinations.tsx`. The mock `Country` interface is
`{id, name, lat, lng, note}`; per api_contract.md section 4, `name` and `note`
become bilingual pairs and the note becomes citable. Snake_case throughout,
matching the JSON example in the contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.common import SnapshotCitation


class SolvencySummary(BaseModel):
    """The bank balance a country's student route requires, and its provenance.

    `verified` is the honest part and the reason this is not just a number.
    False means the figure was seeded from published guidance and has not yet
    been confirmed against a crawled snapshot of `source_url` (migration 026).
    The client must label an unverified figure as provisional; presenting a
    seeded amount as though a source had confirmed it is exactly the
    confidently-wrong answer this product exists to replace.
    """

    amount: int
    currency: str
    hold_days: int
    verified: bool
    note_en: str | None = None
    note_bn: str | None = None
    source_url: str | None = None
    source_label: str | None = None


class DestinationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name_en: str
    name_bn: str
    lat: float
    lng: float
    note_en: str
    note_bn: str
    visa_types: list[str]
    shortlisted: bool
    citation: SnapshotCitation | None = None

    # Journey context. Shortlisting a country used to write a flag that nothing
    # downstream read; these three carry the country forward into the parts of
    # the journey that follow from it — what you can apply to, what might pay
    # for it, and what the embassy will want to see in your account.
    programme_count: int = 0
    scholarship_count: int = 0
    solvency: SolvencySummary | None = None
