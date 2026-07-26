"""Shonchari's interview room. `interview_bank`, `interview_sessions`,
`interview_turns`, `interview_reports` in `app.db` (docs/database.md
section 3.8).
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class InterviewRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- question bank ---------------------------------------------------

    # How one session's questions are split across the three tiers. A session has to
    # escalate to be practice: ordering the whole bank by difficulty and taking the
    # first N meant the limit was exhausted by openings and standards, so the pressure
    # questions, which are the ones a student actually needs to rehearse, were never
    # asked. Fractions of the limit rather than fixed counts, so a shorter session
    # still contains a hard question.
    _TIER_SHARE = (("opening", 0.25), ("standard", 0.5), ("pressure", 0.25))

    async def pick_questions(
        self, country_code: str | None, visa_type: str | None, limit: int = 8
    ) -> list[dict[str, Any]]:
        """One session's questions: stratified by difficulty, varied between sessions.

        Two things this deliberately does that the previous single query did not.

        It guarantees a hard question. See `_TIER_SHARE`.

        It varies between sessions. The old query was fully deterministic, so a student
        practising three times was asked the same eight questions in the same order and
        was rehearsing a script rather than preparing for an interview. Selection is now
        random within each tier.

        Country-specific questions are preferred over general ones inside a tier,
        because a question about the applicant's own destination is worth more than a
        generic one, but general questions still fill the tier when a destination has
        few or none of its own.
        """
        clauses = []
        params: list[Any] = []
        if country_code:
            clauses.append("(country_code = ? OR country_code IS NULL)")
            params.append(country_code)
        if visa_type:
            clauses.append("(visa_type = ? OR visa_type IS NULL)")
            params.append(visa_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        picked: list[dict[str, Any]] = []
        for tier, share in self._TIER_SHARE:
            # At least one from every tier, whatever the limit and the rounding.
            want = max(1, round(limit * share))
            tier_clause = f"{where} AND difficulty = ?" if where else "WHERE difficulty = ?"
            rows = await self._db.fetch_all(
                f"""SELECT * FROM interview_bank {tier_clause}
                     ORDER BY (country_code IS NULL), RANDOM()
                     LIMIT ?""",
                (*params, tier, want),
            )
            picked.extend(dict(r) for r in rows)

        # A thin tier (a destination with no pressure questions of its own and a small
        # general pool) would leave the session short, so the remainder is topped up
        # from anything not already chosen, still hardest-last.
        if len(picked) < limit:
            have = {r["id"] for r in picked}
            rows = await self._db.fetch_all(
                f"""SELECT * FROM interview_bank {where}
                     ORDER BY RANDOM() LIMIT ?""",
                (*params, limit * 2),
            )
            for r in rows:
                if r["id"] not in have:
                    picked.append(dict(r))
                    have.add(r["id"])
                if len(picked) >= limit:
                    break

        order = {"opening": 0, "standard": 1, "pressure": 2}
        picked.sort(key=lambda r: order.get(r["difficulty"], 1))
        return picked[:limit]

    # -- sessions -------------------------------------------------------

    async def create_session(
        self, *, user_id: int, target_id: int | None, country_code: str | None,
        visa_type: str | None, mode: str,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO interview_sessions
               (public_id, user_id, target_id, country_code, visa_type, mode, status, started_at)
               VALUES (?, ?, ?, ?, ?, ?, 'active', ?)""",
            (public_id, user_id, target_id, country_code, visa_type, mode, now),
        )
        row = await self._db.fetch_one("SELECT * FROM interview_sessions WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_by_public_id(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM interview_sessions WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def get(self, session_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM interview_sessions WHERE id = ?", (session_id,)
        )
        return dict(row) if row else None

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM interview_sessions WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,),
        )
        return [dict(r) for r in rows]

    async def end_session(self, session_id: int, status: str) -> None:
        await self._db.execute(
            "UPDATE interview_sessions SET status = ?, ended_at = ? WHERE id = ?",
            (status, utc_now_iso(), session_id),
        )

    async def has_active_session(self, user_id: int) -> bool:
        val = await self._db.fetch_val(
            "SELECT 1 FROM interview_sessions WHERE user_id = ? AND status = 'active'",
            (user_id,),
        )
        return val is not None

    # -- turns -------------------------------------------------------------

    async def add_turn(
        self, session_id: int, *, ordinal: int, bank_id: int | None, question_text: str,
    ) -> int:
        return await self._db.execute(
            """INSERT INTO interview_turns (session_id, ordinal, bank_id, question_text)
               VALUES (?, ?, ?, ?)""",
            (session_id, ordinal, bank_id, question_text),
        )

    async def record_answer(
        self,
        turn_id: int,
        *,
        answer_text: str,
        audio_path: str | None,
        relevance: float | None,
        consistency: float | None,
        credibility: float | None,
        contradicts: list[dict[str, Any]],
        feedback_en: str | None,
        feedback_bn: str | None,
    ) -> None:
        await self._db.execute(
            """UPDATE interview_turns SET answer_text = ?, audio_path = ?, relevance = ?,
               consistency = ?, credibility = ?, contradicts = ?, feedback_en = ?,
               feedback_bn = ?, answered_at = ? WHERE id = ?""",
            (answer_text, audio_path, relevance, consistency, credibility,
             json.dumps(contradicts), feedback_en, feedback_bn, utc_now_iso(), turn_id),
        )

    async def list_turns(self, session_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM interview_turns WHERE session_id = ? ORDER BY ordinal",
            (session_id,),
        )
        return [dict(r) for r in rows]

    async def count_turns(self, session_id: int) -> int:
        val = await self._db.fetch_val(
            "SELECT COUNT(*) FROM interview_turns WHERE session_id = ?", (session_id,)
        )
        return int(val or 0)

    # -- reports -----------------------------------------------------------

    async def create_report(
        self,
        session_id: int,
        *,
        overall: float,
        summary_en: str,
        summary_bn: str,
        strengths: list[str],
        weaknesses: list[str],
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO interview_reports
               (public_id, session_id, overall, summary_en, summary_bn, strengths,
                weaknesses, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, session_id, overall, summary_en, summary_bn,
             json.dumps(strengths), json.dumps(weaknesses), now),
        )
        row = await self._db.fetch_one("SELECT * FROM interview_reports WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_report_for_session(self, session_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM interview_reports WHERE session_id = ?", (session_id,)
        )
        return dict(row) if row else None
