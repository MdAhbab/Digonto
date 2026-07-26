"""Small helpers shared by every repository.

Not a repository itself: just the two things every insert needs and that
have no business being copy-pasted forty times. `new_id` mints the
`PREFIX-ULID` public identifiers the contract describes (`SNAP-01J8...`,
`PLAN-01J8...`); callers pass the prefix that matches their table.
"""

from __future__ import annotations

from datetime import datetime, timezone

from ulid import ULID


def new_ulid() -> str:
    return str(ULID())


def new_id(prefix: str) -> str:
    return f"{prefix}-{ULID()}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def encode_cursor(created_at: str, row_id: int) -> str:
    """Opaque keyset cursor over `(created_at, id)`, newest first.

    Not meant to be decoded by the client, only replayed verbatim as the
    `cursor` query parameter, so a plain delimited string is enough.
    """

    return f"{created_at}|{row_id}"


def decode_cursor(cursor: str | None) -> tuple[str, int] | None:
    if not cursor:
        return None
    try:
        created_at, row_id = cursor.rsplit("|", 1)
        return created_at, int(row_id)
    except (ValueError, TypeError):
        return None
