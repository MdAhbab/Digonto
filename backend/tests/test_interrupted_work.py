"""Recovery for work whose "in progress" marker outlived the work.

Six tables carry a status meaning something is happening. Each is written before the work
starts and rewritten when it ends, and nothing ran if the end never came, so a process that
stopped in between left a row lying about the present.

Two were found lying in the live database, and the second is the reason this file exists at
all rather than being a tidiness exercise:

  * a document had been "reading now" for seven hours;
  * an interview had been active for nine hours, and because `start_session` refuses while
    one is active, the Interview Room answered every attempt with "you already have a session
    in progress" and offered no way to see, finish or discard it. Only editing the database
    could clear it.

The tests are written per table because the windows differ and each one has a reason.
"""

from __future__ import annotations

import pathlib
import tempfile
from datetime import UTC, datetime, timedelta

import pytest

from app.config import Settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.errors import Conflict
from app.repositories._util import new_ulid
from app.repositories.interview_repo import InterviewRepo
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password
from app.workers import recovery

PASSWORD = "a long enough passphrase"


def ago(**kw) -> str:
    return (datetime.now(UTC) - timedelta(**kw)).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
async def env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        settings = Settings(vault_master_key="b" * 64, private_dir=base / "private")
        users = UserRepo(dbs.app)
        user = await users.create(
            email="stuck@example.com", password_hash=hash_password(PASSWORD), display_name="Stuck"
        )
        try:
            yield dbs, settings, user
        finally:
            await dbs.close_all()


async def _insert_document(dbs, user_id: int, *, status: str, uploaded_at: str) -> str:
    public_id = new_ulid()
    await dbs.app.execute(
        """INSERT INTO documents
               (public_id, user_id, kind, original_name, storage_path, mime_type, byte_size,
                sha256, wrapped_dek, nonce, status, uploaded_at)
           VALUES (?, ?, 'passport', 'p.jpg', '/tmp/p.enc', 'image/jpeg', 10,
                   'abc', X'00', X'00', ?, ?)""",
        (public_id, user_id, status, uploaded_at),
    )
    return public_id


# --- documents ----------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_document_stuck_scanning_is_marked_failed(env):
    dbs, settings, user = env
    await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(hours=7))

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("documents_failed") == 1
    row = await dbs.app.fetch_one("SELECT status, failure_reason_en FROM documents")
    assert row["status"] == "failed"
    assert row["failure_reason_en"], "a failed document with no reason blames the file"


@pytest.mark.asyncio
async def test_the_reason_does_not_blame_the_document(env):
    """The card's default for a failed document is "This document could not be read", which
    would tell a student their passport scan is bad when the truth is a restart."""
    dbs, settings, user = env
    await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(hours=7))

    await recovery.recover_interrupted_work(dbs, settings)

    reason = await dbs.app.fetch_val("SELECT failure_reason_en FROM documents")
    assert "interrupted" in reason.lower()
    assert "encrypted" in reason.lower(), "say the file is still safe"
    assert await dbs.app.fetch_val("SELECT failure_reason_bn FROM documents"), "Bangla too"


@pytest.mark.asyncio
async def test_a_scan_that_only_just_started_is_left_alone(env):
    """The window has to be longer than the work. Cancelling a live scan would turn a
    successful read into a failure a few seconds before it finished."""
    dbs, settings, user = env
    await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(minutes=2))

    await recovery.recover_interrupted_work(dbs, settings)

    assert await dbs.app.fetch_val("SELECT status FROM documents") == "scanning"


@pytest.mark.asyncio
async def test_a_finished_document_is_untouched(env):
    dbs, settings, user = env
    await _insert_document(dbs, user["id"], status="extracted", uploaded_at=ago(days=3))

    await recovery.recover_interrupted_work(dbs, settings)

    assert await dbs.app.fetch_val("SELECT status FROM documents") == "extracted"


@pytest.mark.asyncio
async def test_a_recent_failure_is_offered_to_the_caller_for_a_second_attempt(env):
    """The overwhelming cause is the restart rather than the document, so a recent one is
    worth reading again. Older than a day and the restart is no longer a plausible
    explanation, and retrying every boot would be a loop rather than a retry."""
    dbs, settings, user = env
    fresh = await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(hours=2))
    await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(days=4))

    requeue = await recovery.documents_to_rescan(dbs)

    assert [pid for _uid, pid in requeue] == [fresh]


# --- interviews ---------------------------------------------------------------


async def _start_session(dbs, user_id: int, *, started_at: str) -> int:
    session_id = await dbs.app.execute(
        """INSERT INTO interview_sessions (public_id, user_id, mode, status, started_at)
           VALUES (?, ?, 'text', 'active', ?)""",
        (new_ulid(), user_id, started_at),
    )
    return session_id


@pytest.mark.asyncio
async def test_an_abandoned_interview_is_closed_so_a_new_one_can_start(env):
    dbs, settings, user = env
    await _start_session(dbs, user["id"], started_at=ago(hours=9))
    repo = InterviewRepo(dbs.app)
    assert await repo.has_active_session(user["id"]) is True

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("interviews_abandoned") == 1
    assert await repo.has_active_session(user["id"]) is False
    row = await dbs.app.fetch_one("SELECT status, ended_at FROM interview_sessions")
    assert row["status"] == "abandoned"
    assert row["ended_at"], "an ended session needs an end time"


@pytest.mark.asyncio
async def test_staleness_is_measured_from_the_last_answer_not_the_start(env):
    """A long interview in progress must not be taken away from someone still answering.
    Measured from the session start, an hour of good answers would look like abandonment."""
    dbs, settings, user = env
    session_id = await _start_session(dbs, user["id"], started_at=ago(hours=9))
    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, question_text, answered_at)
           VALUES (?, 1, 'Why this university?', ?)""",
        (session_id, ago(minutes=3)),
    )

    await recovery.recover_interrupted_work(dbs, settings)

    assert await dbs.app.fetch_val("SELECT status FROM interview_sessions") == "active"


@pytest.mark.asyncio
async def test_a_pause_for_thought_does_not_end_the_interview(env):
    """Someone reading the question and typing a careful answer is not gone."""
    dbs, settings, user = env
    await _start_session(dbs, user["id"], started_at=ago(minutes=20))

    await recovery.recover_interrupted_work(dbs, settings)

    assert await dbs.app.fetch_val("SELECT status FROM interview_sessions") == "active"


@pytest.mark.asyncio
async def test_answers_already_given_survive_abandonment(env):
    """Abandoning is a status change, not a delete. Somebody may have answered five
    questions before their connection dropped, and that is their work."""
    dbs, settings, user = env
    session_id = await _start_session(dbs, user["id"], started_at=ago(hours=9))
    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, question_text, answer_text, answered_at)
           VALUES (?, 1, 'Why this university?', 'Because of the research group.', ?)""",
        (session_id, ago(hours=8)),
    )

    await recovery.recover_interrupted_work(dbs, settings)

    assert await dbs.app.fetch_val("SELECT count(*) FROM interview_turns") == 1
    assert await dbs.app.fetch_val("SELECT answer_text FROM interview_turns")


# --- the refusal that made this unrecoverable --------------------------------


@pytest.mark.asyncio
async def test_the_refusal_names_the_session_it_is_refusing_for(env):
    """Without the id there is nothing the client can offer to do about it, which is what
    turned a dropped connection into a permanently broken feature."""
    dbs, settings, user = env
    from app.services.interview_service import InterviewService

    session_id = await _start_session(dbs, user["id"], started_at=ago(minutes=5))
    public_id = await dbs.app.fetch_val(
        "SELECT public_id FROM interview_sessions WHERE id = ?", (session_id,)
    )

    repo = InterviewRepo(dbs.app)
    service = InterviewService.__new__(InterviewService)
    service._interviews = repo  # type: ignore[attr-defined]

    with pytest.raises(Conflict) as caught:
        await service.start_session(
            user["id"], target_public_id=None, country=None, visa_type=None, mode="text"
        )

    assert caught.value.extra == {"active_session_id": public_id}
    # And the message tells the student what they can do, rather than only what they cannot.
    assert "resume" in caught.value.detail_en.lower()
    assert "discard" in caught.value.detail_en.lower()


@pytest.mark.asyncio
async def test_abandoning_is_idempotent(env):
    """The client calls this exactly when its view of the state is stale, so a second call
    must not be an error."""
    dbs, settings, user = env
    from app.services.interview_service import InterviewService

    session_id = await _start_session(dbs, user["id"], started_at=ago(minutes=5))
    public_id = await dbs.app.fetch_val(
        "SELECT public_id FROM interview_sessions WHERE id = ?", (session_id,)
    )
    service = InterviewService.__new__(InterviewService)
    service._interviews = InterviewRepo(dbs.app)  # type: ignore[attr-defined]

    first = await service.abandon_session(user["id"], public_id)
    second = await service.abandon_session(user["id"], public_id)

    assert first["status"] == "abandoned"
    assert second["status"] == "abandoned"
    assert second["ended_at"] == first["ended_at"], "the second call must not move the end time"


@pytest.mark.asyncio
async def test_the_pending_question_is_recoverable(env):
    """What makes reconnecting a resume rather than a blank screen. The socket used to accept
    a connection and wait silently for an answer to a question it had never sent."""
    dbs, settings, user = env
    from app.services.interview_service import InterviewService

    session_id = await _start_session(dbs, user["id"], started_at=ago(minutes=5))
    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, question_text, answered_at)
           VALUES (?, 1, 'Answered already', ?)""",
        (session_id, ago(minutes=4)),
    )
    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, question_text)
           VALUES (?, 2, 'Who is paying for your studies?')""",
        (session_id,),
    )

    service = InterviewService.__new__(InterviewService)
    service._interviews = InterviewRepo(dbs.app)  # type: ignore[attr-defined]
    pending = await service.current_question({"id": session_id})

    assert pending is not None
    assert pending["ordinal"] == 2
    assert pending["text_en"] == "Who is paying for your studies?"
    # No bank row is joined here, and an empty string would render as a blank question for
    # anyone reading in Bangla.
    assert pending["text_bn"] == pending["text_en"]


# --- the four that had not been hit yet --------------------------------------


@pytest.mark.asyncio
async def test_a_half_built_knowledge_base_version_is_retired_never_published(env):
    """A version left building is a partial index: some portals crawled, some not.
    Publishing it would answer from an incomplete knowledge base under a version number
    implying a complete one."""
    dbs, settings, user = env
    await dbs.app.execute(
        """INSERT INTO kb_versions (version_no, qdrant_collection, status, built_at)
           VALUES (99, 'kb_v99', 'building', ?)""",
        (ago(hours=20),),
    )

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("kb_builds_retired") == 1
    row = await dbs.app.fetch_one("SELECT status, retired_at FROM kb_versions")
    assert row["status"] == "retired"
    assert row["retired_at"]


@pytest.mark.asyncio
async def test_a_stale_audit_is_failed(env):
    dbs, settings, user = env
    await dbs.app.execute(
        "INSERT INTO audits (public_id, user_id, status, started_at) VALUES (?, ?, 'running', ?)",
        (new_ulid(), user["id"], ago(hours=3)),
    )

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("audits_failed") == 1
    assert await dbs.app.fetch_val("SELECT status FROM audits") == "failed"


@pytest.mark.asyncio
async def test_a_stale_agent_run_is_failed(env):
    """One agent run is a bounded tool loop, so half an hour is already far past it."""
    dbs, settings, user = env
    await dbs.events.execute(
        """INSERT INTO agent_runs (public_id, agent, status, started_at)
           VALUES (?, 'porter', 'running', ?)""",
        (new_ulid(), ago(hours=2)),
    )

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("agent_runs_failed") == 1
    assert await dbs.events.fetch_val("SELECT status FROM agent_runs") == "failed"


@pytest.mark.asyncio
async def test_a_stale_training_job_is_failed(env):
    dbs, settings, user = env
    await dbs.learn.execute(
        """INSERT INTO adapters
               (tag, base_model, rank, sample_count, rehearsal_ratio, status, trained_at)
           VALUES ('v1', 'gemma4:e2b', 16, 400, 0.3, 'training', ?)""",
        (ago(hours=30),),
    )

    changed = await recovery.recover_interrupted_work(dbs, settings)

    assert changed.get("adapters_failed") == 1
    assert await dbs.learn.fetch_val("SELECT status FROM adapters") == "failed"


# --- the sweep itself --------------------------------------------------------


@pytest.mark.asyncio
async def test_a_clean_database_reports_no_changes(env):
    """It runs on every startup, so the quiet case has to be genuinely quiet."""
    dbs, settings, user = env
    assert await recovery.recover_interrupted_work(dbs, settings) == {}


@pytest.mark.asyncio
async def test_one_failing_step_does_not_stop_the_others(env):
    """The reason this runs at all is that something already went wrong, so it cannot be the
    kind of code that gives up on the first problem."""
    dbs, settings, user = env
    await _start_session(dbs, user["id"], started_at=ago(hours=9))

    async def boom(_dbs):
        raise RuntimeError("table is gone")

    original = recovery._fail_stale_scans
    recovery._fail_stale_scans = boom  # type: ignore[assignment]
    try:
        changed = await recovery.recover_interrupted_work(dbs, settings)
    finally:
        recovery._fail_stale_scans = original  # type: ignore[assignment]

    assert changed.get("interviews_abandoned") == 1, "the interview sweep must still have run"


@pytest.mark.asyncio
async def test_the_sweep_is_idempotent(env):
    """It runs on a timer as well as at startup, so a second pass must find nothing to do
    rather than rewriting rows it already handled."""
    dbs, settings, user = env
    await _insert_document(dbs, user["id"], status="scanning", uploaded_at=ago(hours=7))
    await _start_session(dbs, user["id"], started_at=ago(hours=9))

    first = await recovery.recover_interrupted_work(dbs, settings)
    second = await recovery.recover_interrupted_work(dbs, settings)

    assert first == {"documents_failed": 1, "interviews_abandoned": 1}
    assert second == {}
