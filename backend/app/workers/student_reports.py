"""Nightly per-student report, keyed by account id and holding no personal details.

The aggregate report in `app/workers/insights.py` answers "is the product working".
This answers "is it working *for this student*", which the aggregate cannot: a mean
refusal rate of 20 percent hides the one applicant whose every question was refused
because nothing in the archive covers their destination.

The identity rule, and why it is the shape it is. Each row is keyed by
`users.public_id`, the same opaque identifier the event log and the Truth Ledger already
use. That is what makes a report attributable and therefore auditable: a figure nobody
can tie back to a record is not evidence of anything. What the report does not contain is
any personal detail: no name, no email address, no home district, no age, no gender, no
free text the student wrote, and no inferred description of them as a person. It records
what the account *did* with the product, not who the account belongs to.

The distinction is worth being precise about, because "no personal information" and "no
identifier" are different claims and only the first one is made here. A `public_id` is
personal data under any sensible reading: it points at one person. The protection is that
it points at them *only through this database*, so the report is useless to anyone who
does not already hold the account row, and it disappears when the account is purged.

Which is the second rule: a report is deleted with its account. `student_reports` has a
foreign key to `users` with `ON DELETE CASCADE`, so the 30-day purge takes the reports
with it, in the same statement, without anyone having to remember. That is deliberate.
A report keyed by an id whose account no longer exists would be exactly the quiet
survival that `docs/privacy.md` promises does not happen.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.connection import Databases
from app.workers.insights import report_dir

log = logging.getLogger(__name__)

# Only accounts that did something in this window get a report. Writing a row every night
# for a dormant account would fill the table with zeroes and bury the students who are
# actually mid-application.
ACTIVITY_WINDOW_DAYS = 30


async def collect_for_user(dbs: Databases, *, user_id: int, day: str) -> dict[str, Any]:
    """One student's activity counts. Every value is a count or a date, never text."""
    app = dbs.app
    since = (datetime.now(UTC) - timedelta(days=ACTIVITY_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    async def n(sql: str, params: tuple = ()) -> int:
        return int(await app.fetch_val(sql, params) or 0)

    asked = await n("SELECT COUNT(*) FROM questions WHERE user_id = ?", (user_id,))
    refused = await n(
        """SELECT COUNT(*) FROM answers a JOIN questions q ON q.id = a.question_id
            WHERE q.user_id = ? AND a.is_refusal = 1""",
        (user_id,),
    )

    # Destination interest, as country codes only. A country code is not a personal
    # detail, and it is the single most useful field for deciding which portal to add
    # next, which is the whole operational point of a per-student report.
    destinations = [
        r["country_code"]
        for r in await app.fetch_all(
            """SELECT DISTINCT i.country_code
                 FROM student_targets st
                 JOIN programmes p   ON p.id = st.programme_id
                 JOIN institutions i ON i.id = p.institution_id
                WHERE st.user_id = ? AND i.country_code IS NOT NULL
                ORDER BY i.country_code""",
            (user_id,),
        )
    ]

    plan_total = await n(
        "SELECT COUNT(*) FROM plan_steps ps JOIN plans p ON p.id = ps.plan_id WHERE p.user_id = ?",
        (user_id,),
    )
    plan_done = await n(
        """SELECT COUNT(*) FROM plan_steps ps JOIN plans p ON p.id = ps.plan_id
            WHERE p.user_id = ? AND ps.status = 'done'""",
        (user_id,),
    )

    return {
        "day": day,
        "questions_asked": asked,
        "answers_refused": refused,
        # Rounded to whole percent. A refusal rate is the one figure that says whether
        # this student is being served or stonewalled.
        "refusal_pct": round(100 * refused / asked) if asked else 0,
        "documents_held": await n(
            "SELECT COUNT(*) FROM documents WHERE user_id = ? AND deleted_at IS NULL", (user_id,)
        ),
        "documents_flagged": await n(
            """SELECT COUNT(*) FROM audit_findings af
                 JOIN audits au ON au.id = af.audit_id
                WHERE au.user_id = ? AND af.severity IN ('critical', 'warning')""",
            (user_id,),
        ),
        "targets": await n("SELECT COUNT(*) FROM student_targets WHERE user_id = ?", (user_id,)),
        "destinations": destinations,
        "plan_steps_total": plan_total,
        "plan_steps_done": plan_done,
        "plan_pct": round(100 * plan_done / plan_total) if plan_total else 0,
        "scholarship_matches": await n(
            "SELECT COUNT(*) FROM funding_matches WHERE user_id = ?", (user_id,)
        ),
        "interviews_completed": await n(
            "SELECT COUNT(*) FROM interview_reports ir JOIN interview_sessions s "
            "ON s.id = ir.session_id WHERE s.user_id = ?",
            (user_id,),
        ),
        "active_last_30_days": await n(
            "SELECT COUNT(*) FROM questions WHERE user_id = ? AND created_at >= ?",
            (user_id, since),
        ),
    }


async def run_nightly(
    dbs: Databases, settings: Settings, *, day: str | None = None
) -> dict[str, int]:
    """Write one row per recently active account, and a single combined file.

    One file for the night rather than one per student. A directory with a file per
    account per night is a directory whose *listing* discloses how many accounts exist and
    which ones were active, before anybody opens anything.
    """
    if day is None:
        day = (datetime.now(UTC) - timedelta(days=1)).strftime("%Y-%m-%d")
    since = (datetime.now(UTC) - timedelta(days=ACTIVITY_WINDOW_DAYS)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    rows = await dbs.app.fetch_all(
        """SELECT DISTINCT u.id, u.public_id
             FROM users u
             LEFT JOIN questions q ON q.user_id = u.id
            WHERE u.is_demo = 0
              AND u.deleted_at IS NULL
              AND (u.last_seen_at >= ? OR q.created_at >= ?)""",
        (since, since),
    )

    written: list[dict[str, Any]] = []
    for row in rows:
        try:
            report = await collect_for_user(dbs, user_id=int(row["id"]), day=day)
        except Exception as exc:  # noqa: BLE001 - one student must not stop the rest
            log.error("could not build report for %s: %s", row["public_id"], exc)
            continue
        await dbs.app.execute(
            """INSERT INTO student_reports (user_id, day, payload, generated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_id, day) DO UPDATE SET
                   payload = excluded.payload,
                   generated_at = excluded.generated_at""",
            (
                int(row["id"]),
                day,
                json.dumps(report, ensure_ascii=False),
                datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            ),
        )
        written.append({"account": row["public_id"], **report})

    out: Path = report_dir(settings) / "students"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{day}.json").write_text(
        json.dumps(
            {
                "day": day,
                "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "note": (
                    "Keyed by account id. Contains no name, email address, location, age, "
                    "gender or free text. Deleted with the account it describes."
                ),
                "accounts": written,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    log.info("wrote %d per-student report(s) for %s", len(written), day)
    return {"students_reported": len(written)}
