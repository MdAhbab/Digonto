"""Email normalisation for the deleted-account tombstone.

The tombstone records the address and display name of a purged account in plain text; see
`app/db/migrations/app/025_tombstone_plaintext_identity.sql` for what that table is for and
what it costs. The only logic that has to live in code is agreeing on one spelling of an
address, so a lookup at signup matches a row written at deletion.
"""

from __future__ import annotations


def normalise_email(email: str) -> str:
    """Lowercase and trim, matching what `users.email` stores (COLLATE NOCASE).

    Deliberately no further canonicalisation. Stripping dots or `+tags` would make
    `a.b@gmail.com` and `ab@gmail.com` the same person, which is true at Gmail and false
    at most other hosts, so it would block addresses that belong to different people.
    Under-matching lets a determined person cycle addresses; over-matching locks out
    strangers, and only one of those two mistakes has a victim.
    """
    return (email or "").strip().lower()
