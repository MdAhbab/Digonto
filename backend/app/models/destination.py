"""`GET /destinations` and the shortlist.

Serves `Destinations.tsx`. The mock `Country` interface is
`{id, name, lat, lng, note}`; per api_contract.md section 4, `name` and `note`
become bilingual pairs and the note becomes citable. Snake_case throughout,
matching the JSON example in the contract.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.models.common import SnapshotCitation


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
