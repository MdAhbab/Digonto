"""Shared Pydantic models.

Every list endpoint in the contract returns the same envelope shape:
`{"items": [...], "next_cursor": "..."|null, "total": n}`. Defining it once as
a generic keeps every router honest about cursor pagination instead of
inventing a slightly different shape per endpoint.

`ProblemDetail` is re-exported from `app.errors` so every model module in this
package can `from app.models.common import ProblemDetail` without knowing
where the error type actually lives.
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from app.errors import ProblemDetail

__all__ = ["Page", "Citation", "SnapshotCitation", "ProblemDetail"]

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """The cursor-paginated list envelope used by every `items` endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    items: list[T]
    next_cursor: str | None = None
    total: int


class Citation(BaseModel):
    """The frontend `Citation` interface: `{id, portal, captured, quoted}`.

    Used verbatim by `GET /ask/history`, where `id` is the snapshot's public
    ID (`SNAP-...`).
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str
    portal: str
    captured: str
    quoted: str


class SnapshotCitation(BaseModel):
    """A lighter citation reference attached to a fact elsewhere in the
    product: a destination note, a plan step, a scholarship rank, a fee
    line. Different surfaces populate a different subset of these fields, so
    routers should serialise with `exclude_none` to avoid sending nulls the
    frontend never asked for.
    """

    model_config = ConfigDict(populate_by_name=True)

    snapshot_id: str
    portal: str | None = None
    captured: str | None = None
    quoted: str | None = None
