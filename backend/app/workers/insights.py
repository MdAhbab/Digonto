"""Nightly aggregate usage report. Counts only, never a person.

Answers the questions a maintainer has to be able to answer: is anyone using this,
does the answering path refuse when it should, is the crawl loop finding changes,
which destinations do students actually care about. Written every night to
`backend/private/reports/` as JSON for machines and Markdown for reading, plus one
row in `events.db.daily_insights` so a trend survives a lost file.

Two rules make this a usage report rather than a record about students, and both are
enforced here rather than left to whoever writes the next query.

**Counts only.** Every value produced is a `COUNT` or a derived percentage. Nothing
in the output refers to a user, a question, a document, or a target: no identifier,
no email, no name, no address, no free text. `daily_insights` has no user column to
populate, so a later change cannot quietly begin filling one in.

**A small-group floor.** A breakdown bucket is a description of a person once it gets
small enough. "1 student targeting Sweden" plus a signup announcement is an
identification. Buckets below `MIN_BUCKET_SIZE` are therefore not published: they are
summed into one `below_reporting_floor` figure, so the column still adds up and the
suppression is visible instead of looking like the students do not exist.

What this file deliberately does not do is build a per-student profile. That would be
a different artefact with a different risk: a table of names, ages, addresses and
inferred migration intentions is the most sensitive dataset this product could hold,
it is exactly what the interface promises is erased when an account is deleted, and
a student cannot consent to something they are not told about. The aggregate answers
the operational question without holding anything that could hurt anyone if the file
leaked. If per-student reporting is ever wanted, it needs a consent checkbox, an
entry in the privacy documentation, an entry in the data export, and deletion on
account deletion, in that order.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from app.config import Settings
from app.db.connection import Databases

log = logging.getLogger(__name__)

# Smallest breakdown bucket that may be published on its own.
#
# Five is the conventional floor for released frequency tables. The exact number
# matters less than having one: with no floor, a single student in a narrow bucket is
# reported as a fact about that student.
MIN_BUCKET_SIZE = 5

# Key that carries everything the floor suppressed, so a reader can see that
# suppression happened and the total still reconciles.
FLOOR_KEY = "below_reporting_floor"

REPORT_FILENAME_FORMAT = "%Y-%m-%d"


def report_dir(settings: Settings) -> Path:
    """`backend/private/reports/`. Operational output, not source, and not public.

    Under `backend/private/` because the directory is already excluded from the
    repository: this is a public repository and a usage report is nobody's business
    but the operator's, even when it holds no personal data.
    """
    return Path(settings.private_dir) / "reports"


def apply_floor(counts: dict[str, int], *, floor: int = MIN_BUCKET_SIZE) -> dict[str, int]:
    """Suppress buckets below `floor`, preserving the total in `FLOOR_KEY`.

    Suppressed rather than dropped. Dropping would make the breakdown quietly stop
    summing to the headline count, and a reader would conclude the missing students
    do not exist rather than that they were protected.
    """
    kept: dict[str, int] = {}
    suppressed = 0
    for key, value in counts.items():
        if value >= floor:
            kept[key] = value
        else:
            suppressed += value
    if suppressed:
        kept[FLOOR_KEY] = suppressed
    return kept


async def _scalar(db: Any, sql: str, params: tuple = ()) -> int:
    value = await db.fetch_val(sql, params)
    return int(value or 0)


async def collect(dbs: Databases, *, day: str) -> dict[str, Any]:
    """Every figure for one UTC day. `day` is 'YYYY-MM-DD'.

    Bounded by `day` rather than by "the last 24 hours" so that re-running the job
    for a past date reproduces the same numbers, which is what makes a backfill
    possible and a report checkable.
    """
    start = f"{day}T00:00:00Z"
    end = f"{day}T23:59:59Z"
    window = (start, end)
    app, events = dbs.app, dbs.events

    # `student_targets` names a programme, not a country, so the destination is
    # reached through the institution that offers it. COUNT(DISTINCT user_id), not
    # COUNT(*): a student who targets four British universities is one student
    # interested in the United Kingdom, and counting rows would let one person's
    # shortlist look like demand.
    destinations = {
        row["code"]: int(row["n"])
        for row in await app.fetch_all(
            """SELECT i.country_code AS code, COUNT(DISTINCT st.user_id) AS n
                 FROM student_targets st
                 JOIN programmes p   ON p.id = st.programme_id
                 JOIN institutions i ON i.id = p.institution_id
                 JOIN users u        ON u.id = st.user_id
                WHERE u.is_demo = 0 AND u.deleted_at IS NULL
                GROUP BY i.country_code
                ORDER BY n DESC"""
        )
    }

    return {
        "day": day,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reporting_floor": MIN_BUCKET_SIZE,
        "accounts_total": await _scalar(
            app, "SELECT COUNT(*) FROM users WHERE is_demo = 0 AND deleted_at IS NULL"
        ),
        "accounts_new": await _scalar(
            app,
            "SELECT COUNT(*) FROM users WHERE is_demo = 0 AND created_at BETWEEN ? AND ?",
            window,
        ),
        "accounts_active": await _scalar(
            app,
            "SELECT COUNT(*) FROM users WHERE is_demo = 0 AND last_seen_at BETWEEN ? AND ?",
            window,
        ),
        "accounts_pending_deletion": await _scalar(
            app, "SELECT COUNT(*) FROM users WHERE deletion_requested_at IS NOT NULL"
        ),
        "accounts_purged": await _scalar(
            events,
            "SELECT COUNT(*) FROM events WHERE type = 'user.deleted' AND created_at BETWEEN ? AND ?",
            window,
        ),
        "questions_asked": await _scalar(
            app, "SELECT COUNT(*) FROM questions WHERE created_at BETWEEN ? AND ?", window
        ),
        "answers_grounded": await _scalar(
            app,
            "SELECT COUNT(*) FROM answers WHERE created_at BETWEEN ? AND ? AND is_refusal = 0",
            window,
        ),
        "answers_refused": await _scalar(
            app,
            "SELECT COUNT(*) FROM answers WHERE created_at BETWEEN ? AND ? AND is_refusal = 1",
            window,
        ),
        "answers_cached": await _scalar(
            app,
            "SELECT COUNT(*) FROM answers WHERE created_at BETWEEN ? AND ? AND cache_hit = 1",
            window,
        ),
        "portals_enabled": await _scalar(app, "SELECT COUNT(*) FROM portals WHERE enabled = 1"),
        "portals_unreachable": await _scalar(
            app, "SELECT COUNT(*) FROM portals WHERE last_status = 'unreachable'"
        ),
        "snapshots_new": await _scalar(
            app, "SELECT COUNT(*) FROM snapshots WHERE fetched_at BETWEEN ? AND ?", window
        ),
        "changes_classified": await _scalar(
            app, "SELECT COUNT(*) FROM passage_diffs WHERE created_at BETWEEN ? AND ?", window
        ),
        "alerts_sent": await _scalar(
            app, "SELECT COUNT(*) FROM notifications WHERE created_at BETWEEN ? AND ?", window
        ),
        "documents_checked": await _scalar(
            app,
            """SELECT COUNT(*) FROM documents
                WHERE uploaded_at BETWEEN ? AND ? AND deleted_at IS NULL""",
            window,
        ),
        "funding_plans": await _scalar(
            app, "SELECT COUNT(*) FROM funding_matches WHERE computed_at BETWEEN ? AND ?", window
        ),
        "interviews_scored": await _scalar(
            app, "SELECT COUNT(*) FROM interview_reports WHERE created_at BETWEEN ? AND ?", window
        ),
        "feedback_received": await _scalar(
            app, "SELECT COUNT(*) FROM feedback WHERE created_at BETWEEN ? AND ?", window
        ),
        "destinations": apply_floor(destinations),
    }


def render_markdown(report: dict[str, Any]) -> str:
    """A page a person reads. The JSON beside it is the one a script reads."""
    asked = report["questions_asked"]
    refused = report["answers_refused"]
    answered = report["answers_grounded"] + refused
    refusal_pct = f"{100 * refused / answered:.1f} percent" if answered else "no answers"

    lines = [
        f"# Digonto usage, {report['day']}",
        "",
        "Aggregate counts. No row in this report describes an individual student, and",
        f"any breakdown bucket below {report['reporting_floor']} is folded into",
        f"`{FLOOR_KEY}` rather than published.",
        "",
        "## Students",
        "",
        f"- Accounts: {report['accounts_total']} total, {report['accounts_new']} new today",
        f"- Active today: {report['accounts_active']}",
        f"- Scheduled for deletion: {report['accounts_pending_deletion']}",
        f"- Erased today: {report['accounts_purged']}",
        "",
        "## Answering",
        "",
        f"- Questions asked: {asked}",
        f"- Grounded answers: {report['answers_grounded']}",
        f"- Refusals: {refused} ({refusal_pct} of answers)",
        f"- Served from cache: {report['answers_cached']}",
        "",
        "## Sources",
        "",
        f"- Portals crawled: {report['portals_enabled']}",
        f"- Portals unreachable: {report['portals_unreachable']}",
        f"- New snapshots: {report['snapshots_new']}",
        f"- Passage changes classified: {report['changes_classified']}",
        f"- Alerts sent to students: {report['alerts_sent']}",
        "",
        "## Agents",
        "",
        f"- Documents checked: {report['documents_checked']}",
        f"- Funding plans built: {report['funding_plans']}",
        f"- Interviews scored: {report['interviews_scored']}",
        f"- Feedback received: {report['feedback_received']}",
        "",
        "## Destination interest",
        "",
    ]
    destinations = report["destinations"]
    if destinations:
        lines += [f"- {code}: {n}" for code, n in destinations.items()]
    else:
        lines.append("- No destination reached the reporting floor.")
    lines.append("")
    return "\n".join(lines)


async def persist(dbs: Databases, report: dict[str, Any]) -> None:
    """One row per day, replaced on a re-run so a backfill is not additive."""
    await dbs.events.execute(
        """INSERT INTO daily_insights
             (day, accounts_total, accounts_new, accounts_active,
              accounts_pending_deletion, accounts_purged,
              questions_asked, answers_grounded, answers_refused, answers_cached,
              portals_enabled, portals_unreachable, snapshots_new,
              changes_classified, alerts_sent,
              documents_checked, funding_plans, interviews_scored, feedback_received,
              destinations_json, generated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(day) DO UPDATE SET
              accounts_total = excluded.accounts_total,
              accounts_new = excluded.accounts_new,
              accounts_active = excluded.accounts_active,
              accounts_pending_deletion = excluded.accounts_pending_deletion,
              accounts_purged = excluded.accounts_purged,
              questions_asked = excluded.questions_asked,
              answers_grounded = excluded.answers_grounded,
              answers_refused = excluded.answers_refused,
              answers_cached = excluded.answers_cached,
              portals_enabled = excluded.portals_enabled,
              portals_unreachable = excluded.portals_unreachable,
              snapshots_new = excluded.snapshots_new,
              changes_classified = excluded.changes_classified,
              alerts_sent = excluded.alerts_sent,
              documents_checked = excluded.documents_checked,
              funding_plans = excluded.funding_plans,
              interviews_scored = excluded.interviews_scored,
              feedback_received = excluded.feedback_received,
              destinations_json = excluded.destinations_json,
              generated_at = excluded.generated_at""",
        (
            report["day"],
            report["accounts_total"], report["accounts_new"], report["accounts_active"],
            report["accounts_pending_deletion"], report["accounts_purged"],
            report["questions_asked"], report["answers_grounded"],
            report["answers_refused"], report["answers_cached"],
            report["portals_enabled"], report["portals_unreachable"],
            report["snapshots_new"], report["changes_classified"], report["alerts_sent"],
            report["documents_checked"], report["funding_plans"],
            report["interviews_scored"], report["feedback_received"],
            json.dumps(report["destinations"], ensure_ascii=False),
            report["generated_at"],
        ),
    )


async def run_nightly(dbs: Databases, settings: Settings, *, day: str | None = None) -> dict[str, Any]:
    """Build, store and write yesterday's report.

    Yesterday, not today: the job runs shortly after midnight UTC, so the complete
    day is the one that just ended. Reporting on a partial day would make every
    figure look like a decline the next morning.
    """
    if day is None:
        day = (datetime.now(UTC) - timedelta(days=1)).strftime(REPORT_FILENAME_FORMAT)

    report = await collect(dbs, day=day)
    await persist(dbs, report)

    out = report_dir(settings)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{day}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out / f"{day}.md").write_text(render_markdown(report), encoding="utf-8")

    log.info(
        "insight report for %s: %d accounts, %d questions, %d refusals, %d new snapshots",
        day, report["accounts_total"], report["questions_asked"],
        report["answers_refused"], report["snapshots_new"],
    )
    return report
