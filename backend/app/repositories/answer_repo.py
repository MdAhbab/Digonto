"""Questions, answers, citations, and feedback.

`questions`, `answers`, `answer_citations`, `answer_feedback` in `app.db`
(docs/database.md section 3.4). The refusal contract lives in a `CHECK`
constraint on `answers` itself: a non-refusal row must carry answer text, a
refusal must carry a reason. This repository never tries to write around
that; `ask_service` builds rows that already satisfy it.
"""

from __future__ import annotations

from typing import Any

from app.db.connection import Database
from app.repositories._util import decode_cursor, new_ulid, utc_now_iso


class AnswerRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- questions -------------------------------------------------------

    async def create_question(
        self,
        *,
        conversation_id: int,
        user_id: int,
        text_raw: str,
        text_normalised: str,
        lang_detected: str,
        country_filter: str | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO questions
               (public_id, conversation_id, user_id, text_raw, text_normalised,
                lang_detected, country_filter, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, conversation_id, user_id, text_raw, text_normalised,
             lang_detected, country_filter, now),
        )
        row = await self._db.fetch_one("SELECT * FROM questions WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_question(self, question_id: int) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM questions WHERE id = ?", (question_id,))
        return dict(row) if row else None

    # -- answers -----------------------------------------------------------

    async def create_answer(
        self,
        *,
        question_id: int,
        answer_bn: str | None,
        answer_en: str | None,
        confidence: float | None,
        is_refusal: bool,
        refusal_reason: str | None,
        kb_version_id: int | None,
        model_tag: str,
        served_by: str,
        cache_hit: bool,
        latency_ms: int | None,
        first_token_ms: int | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO answers
               (public_id, question_id, answer_bn, answer_en, confidence, is_refusal,
                refusal_reason, kb_version_id, model_tag, served_by, cache_hit,
                latency_ms, first_token_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (public_id, question_id, answer_bn, answer_en, confidence, int(is_refusal),
             refusal_reason, kb_version_id, model_tag, served_by, int(cache_hit),
             latency_ms, first_token_ms, now),
        )
        row = await self._db.fetch_one("SELECT * FROM answers WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def update_final(
        self,
        answer_id: int,
        *,
        answer_bn: str | None,
        answer_en: str | None,
        confidence: float | None,
        is_refusal: bool,
        refusal_reason: str | None,
        latency_ms: int,
        first_token_ms: int,
    ) -> None:
        await self._db.execute(
            """UPDATE answers SET answer_bn = ?, answer_en = ?, confidence = ?, is_refusal = ?,
               refusal_reason = ?, latency_ms = ?, first_token_ms = ? WHERE id = ?""",
            (answer_bn, answer_en, confidence, int(is_refusal), refusal_reason,
             latency_ms, first_token_ms, answer_id),
        )

    async def add_citation(
        self, *, answer_id: int, ordinal: int, snapshot_id: int, passage_id: int | None,
        quoted_span: str,
    ) -> None:
        await self._db.execute(
            """INSERT INTO answer_citations
               (answer_id, ordinal, snapshot_id, passage_id, quoted_span)
               VALUES (?, ?, ?, ?, ?)""",
            (answer_id, ordinal, snapshot_id, passage_id, quoted_span),
        )

    async def get_answer_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one("SELECT * FROM answers WHERE public_id = ?", (public_id,))
        return dict(row) if row else None

    async def get_owned_answer_by_public_id(
        self, public_id: str, user_id: int
    ) -> dict[str, Any] | None:
        """Load an answer only when the owning question belongs to `user_id`."""
        row = await self._db.fetch_one(
            """SELECT a.* FROM answers a
               JOIN questions q ON q.id = a.question_id
               WHERE a.public_id = ? AND q.user_id = ?""",
            (public_id, user_id),
        )
        return dict(row) if row else None

    async def list_citations(self, answer_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT ac.ordinal, ac.quoted_span, s.public_id AS snapshot_public_id,
                      s.fetched_at, p.label AS portal_label
               FROM answer_citations ac
               JOIN snapshots s ON s.id = ac.snapshot_id
               JOIN portals p ON p.id = s.portal_id
               WHERE ac.answer_id = ? ORDER BY ac.ordinal""",
            (answer_id,),
        )
        return [dict(r) for r in rows]

    # -- history ---------------------------------------------------------

    async def list_history(
        self, *, user_id: int, conversation_id: int | None, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses = ["q.user_id = ?"]
        params: list[Any] = [user_id]
        if conversation_id is not None:
            clauses.append("q.conversation_id = ?")
            params.append(conversation_id)
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(a.created_at, a.id) < (?, ?)")
            params.extend([created_at, row_id])

        where = f"WHERE {' AND '.join(clauses)}"
        rows = await self._db.fetch_all(
            f"""SELECT a.id, a.public_id, a.answer_bn, a.answer_en, a.is_refusal,
                       a.created_at, q.text_raw
                FROM answers a
                JOIN questions q ON q.id = a.question_id
                {where}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['created_at']}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    # -- feedback ----------------------------------------------------------

    async def upsert_feedback(
        self, *, answer_id: int, user_id: int, rating: str, correction_text: str | None
    ) -> None:
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO answer_feedback (answer_id, user_id, rating, correction_text, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (answer_id, user_id) DO UPDATE SET
                 rating = excluded.rating, correction_text = excluded.correction_text""",
            (answer_id, user_id, rating, correction_text, now),
        )

    # -- moderator: answer review and refusal triage ------------------------

    async def list_for_review(
        self, *, filter_: str, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        clauses: list[str] = []
        params: list[Any] = []
        joins = "LEFT JOIN answer_feedback f ON f.answer_id = a.id"
        if filter_ == "downvoted":
            clauses.append("f.rating = 'down' AND f.reviewer_verified = 0")
        elif filter_ == "escalated":
            clauses.append("f.rating IN ('down', 'unclear') AND f.reviewer_verified = 0")
        elif filter_ == "low_confidence":
            clauses.append("a.confidence IS NOT NULL AND a.confidence < 0.5")
        decoded = decode_cursor(cursor)
        if decoded:
            created_at, row_id = decoded
            clauses.append("(a.created_at, a.id) < (?, ?)")
            params.extend([created_at, row_id])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = await self._db.fetch_all(
            f"""SELECT DISTINCT a.id, a.public_id, a.answer_en, a.answer_bn, a.confidence,
                       a.is_refusal, a.created_at, q.text_raw,
                       f.rating, f.reviewer_verified
                FROM answers a
                JOIN questions q ON q.id = a.question_id
                {joins}
                {where}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = f"{last['created_at']}|{last['id']}"
            rows = rows[:limit]
        return rows, next_cursor

    async def mark_verified(self, answer_id: int, note: str | None) -> None:
        await self._db.execute(
            """UPDATE answer_feedback SET reviewer_verified = 1, reviewer_note = ?
               WHERE answer_id = ?""",
            (note, answer_id),
        )

    async def write_correction(
        self, answer_id: int, *, correction_en: str, correction_bn: str, note: str | None
    ) -> None:
        await self._db.execute(
            """UPDATE answer_feedback SET reviewer_verified = 1,
               correction_text = ?, reviewer_note = ? WHERE answer_id = ?""",
            (f"{correction_en}\n---\n{correction_bn}", note, answer_id),
        )

    async def list_refusal_clusters(
        self, *, cursor: str | None, limit: int = 20
    ) -> tuple[list[dict[str, Any]], str | None]:
        # Clustered by normalised question text prefix: a cheap, real proxy
        # for topic clustering without a dedicated embedding pass here.
        decoded = decode_cursor(cursor)
        having = ""
        params: list[Any] = []
        if decoded:
            _, row_id = decoded
            having = "HAVING MIN(a.id) > ?"
            params.append(row_id)
        rows = await self._db.fetch_all(
            f"""SELECT q.text_normalised AS cluster_key, COUNT(*) AS cnt,
                       MIN(q.text_raw) AS sample_question, MAX(q.country_filter) AS country_filter,
                       MAX(a.created_at) AS last_asked_at, MIN(a.id) AS cluster_ordinal
                FROM answers a JOIN questions q ON q.id = a.question_id
                WHERE a.is_refusal = 1
                GROUP BY q.text_normalised
                {having}
                ORDER BY cnt DESC
                LIMIT ?""",
            (*params, limit + 1),
        )
        rows = [dict(r) for r in rows]
        next_cursor = None
        if len(rows) > limit:
            next_cursor = str(rows[limit - 1]["cluster_ordinal"])
            rows = rows[:limit]
        return rows, next_cursor

    async def count_answered(self) -> int:
        val = await self._db.fetch_val("SELECT COUNT(*) FROM answers WHERE is_refusal = 0")
        return int(val or 0)

    async def citation_rate(self) -> float:
        total = await self._db.fetch_val("SELECT COUNT(*) FROM answers WHERE is_refusal = 0")
        cited = await self._db.fetch_val(
            """SELECT COUNT(DISTINCT a.id) FROM answers a
               JOIN answer_citations ac ON ac.answer_id = a.id
               WHERE a.is_refusal = 0"""
        )
        total = int(total or 0)
        if total == 0:
            return 1.0
        return round(int(cited or 0) / total, 4)

    async def count_escalated(self) -> int:
        val = await self._db.fetch_val(
            """SELECT COUNT(DISTINCT a.id) FROM answers a
               JOIN answer_feedback f ON f.answer_id = a.id
               WHERE f.rating IN ('down', 'unclear') AND f.reviewer_verified = 0"""
        )
        return int(val or 0)
