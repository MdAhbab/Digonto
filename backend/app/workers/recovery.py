"""Recovery for work that was interrupted rather than finished.

Six tables in this product carry a status meaning "in progress": a document being read,
an interview being conducted, an audit, a knowledge base version being built, an agent
run, an adapter being trained. Every one of them is written before the work starts and
rewritten when it ends, and none of them had anything that ran if the end never came.

A process that stops between those two writes therefore leaves a row claiming work is
happening when nothing is. That is not a rare event: a deploy, a crash, an out of memory
kill and a development reload all do it. Two were found in the live database, and both
were user visible in the worst way:

  * A passport had been reading for seven hours. The document card said "Reading this
    document now" and "Nothing to do; this takes a few seconds", which was false, and no
    amount of waiting or reloading would change it.
  * An interview session had been active for nine hours. `start_session` refuses while one
    is active, so the Interview Room answered every attempt with "You already have an
    interview session in progress" and offered no way to see, finish or discard it. The
    feature was permanently unusable for that account, and only a manual database edit
    could clear it.

The other four had no stuck rows yet. They are swept too, because "has not happened yet"
is not a property worth relying on, and the sweep for one is the sweep for all.

Run at startup, which is exactly when the interruption has just happened, and nightly, for
a process that stays up while something inside it dies.

The rule is the same everywhere: a row is stale when its start is older than a window
comfortably longer than the work could legitimately take. Nothing here cancels live work,
because a window is a poor way to identify it, so every window is set well past the real
duration and the cost of being wrong is one repeated unit of work rather than one lost.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db.connection import Databases

log = logging.getLogger(__name__)

# A document is read by one vision pass. Minutes on a CPU-only machine, never an hour.
STALE_SCAN_MINUTES = 30

# An interview is a person typing answers. Long pauses are normal and a stale window has to
# respect that, so this is generous: someone who steps away for lunch mid-session and comes
# back must find it still there, and only a session nobody could still be sitting at is
# taken away.
STALE_INTERVIEW_MINUTES = 180

# An audit is a few model calls over one document.
STALE_AUDIT_MINUTES = 30

# A knowledge base build crawls every registered portal. Hours is normal.
STALE_BUILD_HOURS = 12

# One agent run is a bounded tool loop (`agent_max_steps`).
STALE_AGENT_RUN_MINUTES = 30

# Adapter training is the longest job in the product and the least urgent to recover.
STALE_TRAINING_HOURS = 24

# A document that failed to read is offered one more attempt when the process comes back,
# because the overwhelming cause is the restart itself rather than the document. Past this
# age the restart is no longer a plausible explanation, and repeating it every boot would be
# a loop rather than a retry.
REQUEUE_WITHIN_HOURS = 24


def _before(*, minutes: int = 0, hours: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes, hours=hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


async def recover_interrupted_work(
    dbs: Databases, settings: Settings | None = None
) -> dict[str, int]:
    """Sweep every in-progress marker. Returns what was changed, per table.

    Each table is handled in its own try block. A failure recovering one must not stop the
    others, because the reason this runs at all is that something already went wrong.
    """
    changed: dict[str, int] = {}

    async def _step(name: str, coro) -> None:  # noqa: ANN001
        try:
            n = await coro
        except Exception:  # noqa: BLE001
            log.exception("recovery step %s failed", name)
            return
        if n:
            changed[name] = n

    await _step("documents_failed", _fail_stale_scans(dbs))
    await _step("interviews_abandoned", _abandon_stale_interviews(dbs))
    await _step("audits_failed", _fail_stale_audits(dbs))
    await _step("kb_builds_retired", _retire_stale_builds(dbs))
    await _step("agent_runs_failed", _fail_stale_agent_runs(dbs))
    await _step("adapters_failed", _fail_stale_training(dbs))

    if changed:
        log.warning("recovered interrupted work: %s", changed)
    return changed


async def documents_to_rescan(dbs: Databases) -> list[tuple[int, str]]:
    """`(user_id, public_id)` for documents worth reading again after a restart.

    Read before `recover_interrupted_work` marks them failed, so the caller can requeue the
    recent ones. Kept separate from the sweep because requeueing needs the vault service and
    its encryption keys, which this module deliberately does not touch.
    """
    rows = await dbs.app.fetch_all(
        """SELECT user_id, public_id FROM documents
           WHERE status = 'scanning' AND deleted_at IS NULL
             AND uploaded_at < ? AND uploaded_at >= ?
           ORDER BY uploaded_at""",
        (_before(minutes=STALE_SCAN_MINUTES), _before(hours=REQUEUE_WITHIN_HOURS)),
    )
    return [(r["user_id"], r["public_id"]) for r in rows]


async def _fail_stale_scans(dbs: Databases) -> int:
    """A half-read document is marked failed, with a reason that says what happened.

    The status alone would be enough to stop the card claiming the document is being read,
    but not enough to be honest about it. `VaultService.list_documents` shows
    `failure_reason_en` for a failed document, and its default is "This document could not be
    read", which would blame the file for a restart. The file is fine. Setting the reason here
    is what makes the card tell the truth.
    """
    return await _mark(
        dbs.app,
        """UPDATE documents
              SET status = 'failed',
                  failure_reason_en = ?,
                  failure_reason_bn = ?
            WHERE status = 'scanning' AND deleted_at IS NULL AND uploaded_at < ?""",
        (
            "The automatic check was interrupted before it finished. Your file is stored and "
            "encrypted; only the reading step did not complete.",
            "স্বয়ংক্রিয় পরীক্ষাটি শেষ হওয়ার আগেই থেমে গেছে। আপনার ফাইলটি সংরক্ষিত ও এনক্রিপ্ট "
            "করা আছে, শুধু পড়ার ধাপটি সম্পূর্ণ হয়নি।",
            _before(minutes=STALE_SCAN_MINUTES),
        ),
    )


async def _abandon_stale_interviews(dbs: Databases) -> int:
    """An interview nobody is sitting at is abandoned, which unblocks starting a new one.

    Staleness is measured from the last answered turn, not from the session start, so a long
    session in progress is not taken away from someone who is still answering.
    """
    return await _mark(
        dbs.app,
        """UPDATE interview_sessions
              SET status = 'abandoned', ended_at = ?
            WHERE status = 'active'
              AND COALESCE(
                    (SELECT MAX(answered_at) FROM interview_turns
                      WHERE interview_turns.session_id = interview_sessions.id),
                    started_at
                  ) < ?""",
        (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), _before(minutes=STALE_INTERVIEW_MINUTES)),
    )


async def _fail_stale_audits(dbs: Databases) -> int:
    return await _mark(
        dbs.app,
        """UPDATE audits SET status = 'failed', finished_at = ?
            WHERE status IN ('queued', 'running') AND started_at < ?""",
        (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), _before(minutes=STALE_AUDIT_MINUTES)),
    )


async def _retire_stale_builds(dbs: Databases) -> int:
    """Retired, never live.

    A version left building is a partial index: some portals crawled, some not. Publishing it
    would answer questions from an incomplete knowledge base while reporting a version number
    that implies a complete one, so the only safe direction is out.
    """
    return await _mark(
        dbs.app,
        """UPDATE kb_versions SET status = 'retired', retired_at = ?
            WHERE status = 'building' AND built_at < ?""",
        (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), _before(hours=STALE_BUILD_HOURS)),
    )


async def _fail_stale_agent_runs(dbs: Databases) -> int:
    return await _mark(
        dbs.events,
        """UPDATE agent_runs SET status = 'failed', finished_at = ?
            WHERE status IN ('queued', 'running') AND started_at < ?""",
        (datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), _before(minutes=STALE_AGENT_RUN_MINUTES)),
    )


async def _fail_stale_training(dbs: Databases) -> int:
    stale = await dbs.learn.fetch_all(
        "SELECT id FROM adapters WHERE status = 'training' AND trained_at < ?",
        (_before(hours=STALE_TRAINING_HOURS),),
    )
    if not stale:
        return 0
    adapter_ids = [r["id"] for r in stale]
    count = await _mark(
        dbs.learn,
        "UPDATE adapters SET status = 'failed' WHERE status = 'training' AND trained_at < ?",
        (_before(hours=STALE_TRAINING_HOURS),),
    )
    await dbs.learn.execute_many(
        "UPDATE replay_samples SET exported_in = NULL WHERE exported_in = ?",
        [(aid,) for aid in adapter_ids],
    )
    return count


async def _mark(db, sql: str, params: tuple) -> int:  # noqa: ANN001
    """Run the statement and report how many rows it changed.

    The count is the whole point of the return value: in a log, a sweep that repaired nothing
    and one that repaired forty rows are indistinguishable without it.
    """
    return await db.execute_count(sql, params)
