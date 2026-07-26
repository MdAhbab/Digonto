"""Tests for the three report bugs fixed in this session.

1. list_turns must expose question_bn from the bank join so the report is
   bilingual, not English-only.
2. compose_report must exclude unanswered turns (answer_text = NULL) from the
   transcript sent to the model.
3. The overall score is the arithmetic mean of relevance/consistency/credibility
   across answered turns, and the model cannot change it.
"""
from __future__ import annotations

import pathlib
import tempfile

import pytest

from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.repositories._util import new_ulid
from app.repositories.interview_repo import InterviewRepo
from app.repositories.user_repo import UserRepo
from app.security.passwords import hash_password


PASSWORD = "a long enough passphrase"


@pytest.fixture
async def env():
    with tempfile.TemporaryDirectory() as tmp:
        base = pathlib.Path(tmp)
        dbs = Databases(base / "app.db", base / "events.db", base / "learn.db")
        await dbs.connect_all()
        await run_migrations(dbs)
        users = UserRepo(dbs.app)
        user = await users.create(
            email="report-test@example.com",
            password_hash=hash_password(PASSWORD),
            display_name="Tester",
        )
        interviews = InterviewRepo(dbs.app)
        try:
            yield dbs, user, interviews
        finally:
            await dbs.close_all()


async def _seed_bank_question(dbs: Databases, *, text_en: str, text_bn: str) -> int:
    row_id = await dbs.app.execute(
        """INSERT INTO interview_bank (category, text_en, text_bn, probes, difficulty, country_code)
           VALUES ('intent', ?, ?, '[]', 'opening', NULL)""",
        (text_en, text_bn),
    )
    return row_id


@pytest.mark.asyncio
async def test_list_turns_returns_question_bn(env):
    """list_turns must join interview_bank.text_bn so the report is bilingual."""
    dbs, user, interviews = env

    bank_id = await _seed_bank_question(
        dbs,
        text_en="Why do you want to study abroad?",
        text_bn="আপনি কেন বিদেশে পড়তে চান?",
    )

    session_public_id = new_ulid()
    session_id = await dbs.app.execute(
        """INSERT INTO interview_sessions
               (public_id, user_id, mode, status, started_at)
           VALUES (?, ?, 'text', 'active', '2026-01-01T00:00:00Z')""",
        (session_public_id, user["id"]),
    )

    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, bank_id, question_text)
           VALUES (?, 1, ?, ?)""",
        (session_id, bank_id, "Why do you want to study abroad?"),
    )

    turns = await interviews.list_turns(session_id)
    assert len(turns) == 1
    assert turns[0]["question_text"] == "Why do you want to study abroad?"
    assert turns[0]["question_bn"] == "আপনি কেন বিদেশে পড়তে চান?"


@pytest.mark.asyncio
async def test_list_turns_falls_back_when_no_bank_id(env):
    """Turns without a bank_id must not crash; question_bn is NULL."""
    dbs, user, interviews = env

    session_public_id = new_ulid()
    session_id = await dbs.app.execute(
        """INSERT INTO interview_sessions
               (public_id, user_id, mode, status, started_at)
           VALUES (?, ?, 'text', 'active', '2026-01-01T00:00:00Z')""",
        (session_public_id, user["id"]),
    )

    await dbs.app.execute(
        """INSERT INTO interview_turns (session_id, ordinal, bank_id, question_text)
           VALUES (?, 1, NULL, 'Tell me about yourself.')""",
        (session_id,),
    )

    turns = await interviews.list_turns(session_id)
    assert len(turns) == 1
    assert turns[0]["question_bn"] is None


@pytest.mark.asyncio
async def test_compose_report_overall_cannot_be_overridden_by_model():
    """The overall score must be the arithmetic mean; the model cannot change it."""
    from app.agents.shonchari import compose_report
    from unittest.mock import AsyncMock, patch

    turns = [
        {
            "ordinal": 1, "question_text": "Q1", "question_bn": "Q1-BN",
            "answer_text": "A1", "answered_at": "2026-01-01T00:01:00Z",
            "relevance": 0.8, "consistency": 0.6, "credibility": 0.7,
        },
        {
            "ordinal": 2, "question_text": "Q2", "question_bn": "Q2-BN",
            "answer_text": "A2", "answered_at": "2026-01-01T00:02:00Z",
            "relevance": 1.0, "consistency": 1.0, "credibility": 1.0,
        },
    ]
    expected_overall = round(
        ((0.8 + 0.6 + 0.7) / 3 + (1.0 + 1.0 + 1.0) / 3) / 2, 3
    )

    mock_answer = {
        "overall": 0.5,  # model tries to override — must be ignored
        "summary_en": "Good.", "summary_bn": "ভালো।",
        "strengths": ["clarity"], "weaknesses": ["depth"],
    }
    with patch("app.agents.shonchari.structured", AsyncMock(return_value=mock_answer)):
        result = await compose_report(turns=turns, router=AsyncMock())

    assert result["overall"] == expected_overall


@pytest.mark.asyncio
async def test_compose_report_excludes_unanswered_turns():
    """Unanswered turns (answered_at=None) must not appear in the model transcript."""
    from app.agents.shonchari import compose_report
    from unittest.mock import AsyncMock, patch

    turns = [
        {
            "ordinal": 1, "question_text": "Q1", "question_bn": "Q1-BN",
            "answer_text": "MyAnswer", "answered_at": "2026-01-01T00:01:00Z",
            "relevance": 0.8, "consistency": 0.8, "credibility": 0.8,
        },
        {
            "ordinal": 2, "question_text": "Q2-never-answered", "question_bn": None,
            "answer_text": None, "answered_at": None,  # interrupted
            "relevance": None, "consistency": None, "credibility": None,
        },
    ]

    captured: list[str] = []

    async def capture(router, call_obj):
        captured.append(call_obj.user)
        return {"overall": 0.5, "summary_en": "x", "summary_bn": "x",
                "strengths": [], "weaknesses": []}

    with patch("app.agents.shonchari.structured", side_effect=capture):
        await compose_report(turns=turns, router=AsyncMock())

    assert captured, "structured was never called"
    sent = captured[0]
    assert "Q2-never-answered" not in sent, (
        "Unanswered turn must not appear in the transcript"
    )
    assert "MyAnswer" in sent
