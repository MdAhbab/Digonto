"""Shonchari's interview room. api_contract.md section 10.

Turn scoring and the final report both require judgement this build does not
implement directly: `app.agents.shonchari.score_answer` and `.compose_report`
are called unresolved, exactly like every other agent gap in this codebase.
`get_file_summary` here is real, though — a PII-minimised read of the
student's own profile, targets, and budget, which is exactly the tool
`agents.md` describes Shonchari calling before it asks a single question.
"""

from __future__ import annotations

import json
from typing import Any

from app.agents.shonchari import compose_report, score_answer
from app.errors import Conflict, NotFound
from app.events.bus import EventBus, EventType
from app.llm.router import ModelRouter
from app.repositories.budget_repo import BudgetRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.interview_repo import InterviewRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo


class InterviewService:
    def __init__(
        self, interviews: InterviewRepo, profiles: ProfileRepo, targets: TargetRepo,
        budgets: BudgetRepo, documents: DocumentRepo, bus: EventBus, router: ModelRouter,
    ) -> None:
        self._interviews = interviews
        self._profiles = profiles
        self._targets = targets
        self._budgets = budgets
        self._documents = documents
        self._bus = bus
        self._router = router

    async def get_file_summary(self, user_id: int, target_row: dict | None) -> dict:
        profile = await self._profiles.get(user_id)
        budget = None
        if target_row is not None:
            budget = await self._budgets.get_for_target(user_id, target_row["id"])
        return {
            "degree_level": profile["degree_level"] if profile else None,
            "field_of_study": profile["field_of_study"] if profile else None,
            "cgpa": profile["cgpa"] if profile else None,
            "english_test": profile["english_test"] if profile else None,
            "budget_bdt": profile["budget_bdt"] if profile else None,
            "study_gap_years": profile["study_gap_years"] if profile else 0,
            "target_country": target_row["country_code"] if target_row else None,
            "target_visa_type": target_row["visa_type"] if target_row else None,
            "funding_gap_bdt": budget["gap_bdt"] if budget else None,
        }

    async def start_session(
        self, user_id: int, *, target_public_id: str | None, country: str | None,
        visa_type: str | None, mode: str,
    ) -> dict:
        # An active session blocks a new one, which is correct while somebody is answering
        # and was a trap when nobody was. A WebSocket that drops (a closed tab, a reload, a
        # restarted server) leaves the row active with nothing to end it, and the interface
        # only ever asked for a *new* session, so every later attempt was refused and the
        # Interview Room stayed unusable for that account until the row was edited by hand.
        #
        # The refusal now names the session it is refusing for, so the client can offer to
        # resume or discard it instead of showing a dead end. `POST /sessions/{id}/abandon`
        # is the discard, and app/workers/recovery.py clears sessions nobody came back to.
        existing = await self._interviews.active_session(user_id)
        if existing is not None:
            raise Conflict(
                detail_en=(
                    "You already have an interview session in progress. Resume it, or "
                    "discard it to start a new one."
                ),
                detail_bn=(
                    "আপনার একটি ইন্টারভিউ সেশন ইতিমধ্যে চলছে। সেটি চালিয়ে যান, অথবা নতুন "
                    "শুরু করতে বাতিল করুন।"
                ),
                extra={"active_session_id": existing["public_id"]},
            )
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        if not target_row:
            targets = await self._targets.list_targets(user_id)
            if targets:
                target_row = targets[0]
        country_code = country or (target_row["country_code"] if target_row else None)
        resolved_visa = visa_type or (target_row["visa_type"] if target_row else None)
        # Pick the sticky bank before inserting a session so an empty bank cannot leave
        # an orphan active row the student can neither finish nor replace.
        bank = await self._interviews.pick_questions(country_code, resolved_visa)
        if not bank:
            raise NotFound(
                detail_en="No interview questions are available for this country yet.",
                detail_bn="এই দেশের জন্য এখনও কোনো ইন্টারভিউ প্রশ্ন নেই।",
            )
        session = await self._interviews.create_session(
            user_id=user_id,
            target_id=target_row["id"] if target_row else None,
            country_code=country_code,
            visa_type=resolved_visa,
            mode=mode,
        )
        # Insert every turn up front. Later answers advance through pending_turn only —
        # never re-sample the bank mid-session.
        for ordinal, question in enumerate(bank, start=1):
            await self._interviews.add_turn(
                session["id"],
                ordinal=ordinal,
                bank_id=question["id"],
                question_text=question["text_en"],
            )
        first = bank[0]
        return {
            "session_id": session["public_id"],
            "mode": session["mode"],
            "first_question": {
                "ordinal": 1,
                "text_en": first["text_en"],
                "text_bn": first["text_bn"],
                "probes": first.get("probes"),
                "audio_url": None,
            },
        }

    async def get_session(self, user_id: int, public_id: str) -> dict:
        session = await self._interviews.get_by_public_id(user_id, public_id)
        if session is None:
            raise NotFound(detail_en="Session not found.", detail_bn="সেশনটি পাওয়া যায়নি।")
        return session

    async def list_sessions(self, user_id: int) -> list[dict]:
        return await self._interviews.list_for_user(user_id)

    async def active_session(self, user_id: int) -> dict | None:
        """The session in progress, if there is one. Read on entering the Interview Room."""
        return await self._interviews.active_session(user_id)

    async def current_question(self, session: dict) -> dict | None:
        """The question this session is waiting on, shaped like `first_question`.

        What makes a reconnect a resume rather than a blank screen. The socket used to accept
        a connection to an active session and then wait silently for an answer to a question
        it had never sent, so a student who reloaded the page saw an interview in progress
        with nothing in it.

        Returns None when every asked turn has been answered, which means scoring was
        interrupted between recording the answer and asking the next question.
        """
        turn = await self._interviews.pending_turn(session["id"])
        if turn is None:
            return None
        return {
            "ordinal": turn["ordinal"],
            "text_en": turn["question_text"],
            # The bank row is joined and may be absent if a question was retired since.
            # Falling back to the English text is right: an empty string would render as a
            # blank question for anyone reading in Bangla.
            "text_bn": turn.get("text_bn") or turn["question_text"],
            "probes": turn.get("probes"),
            "audio_url": None,
        }

    async def abandon_session(self, user_id: int, public_id: str) -> dict:
        """End a session without scoring it, so a new one can start.

        Deliberately not a delete. The questions asked and any answers given stay on record,
        because a student may have answered five questions before their connection dropped and
        deleting that is destroying their work to tidy up a status column. `abandoned` was
        already an allowed value in 008_interview.sql and nothing had ever set it.

        Idempotent: abandoning an already finished session returns it unchanged rather than
        failing, because the client calls this exactly when its view of the state is stale.
        """
        session = await self.get_session(user_id, public_id)
        if session["status"] != "active":
            return session
        await self._interviews.end_session(session["id"], "abandoned")
        return await self.get_session(user_id, public_id)

    async def submit_answer(self, user_id: int, session: dict, answer_text: str) -> dict:
        """Scores the current turn and returns either the next question or
        the session completion payload. The router's WebSocket handler is
        responsible for sequencing `phase` messages around this call.
        """

        current = await self._interviews.pending_turn(session["id"])
        if current is None:
            raise NotFound(
                detail_en="No active question to answer.",
                detail_bn="উত্তর দেওয়ার মতো কোনো প্রশ্ন পাওয়া যায়নি।",
            )
        target_row = None
        if session["target_id"]:
            targets = await self._targets.list_targets(user_id)
            target_row = next((t for t in targets if t.get("id") == session["target_id"]), None)
        file_summary = await self.get_file_summary(user_id, target_row)
        # Flat field_key -> hash map (last write wins across documents) so
        # Shonchari can compare spoken figures against amount/_no/_number digests.
        field_hashes: dict[str, str] = {}
        for doc in await self._documents.list_for_user(user_id):
            field_hashes.update(await self._documents.get_field_hashes(doc["id"]))

        result = await score_answer(
            question_text=current["question_text"],
            answer_text=answer_text,
            file_summary=file_summary,
            document_field_hashes=field_hashes,
            router=self._router,
        )
        await self._interviews.record_answer(
            current["id"],
            answer_text=answer_text,
            audio_path=None,
            relevance=result.get("relevance"),
            consistency=result.get("consistency"),
            credibility=result.get("credibility"),
            contradicts=result.get("contradicts", []),
            feedback_en=result.get("feedback_en"),
            feedback_bn=result.get("feedback_bn"),
        )

        next_turn = await self._interviews.pending_turn(session["id"])
        if next_turn is None:
            return await self._complete_session(user_id, session)

        return {
            "kind": "question",
            "score": {
                "relevance": result.get("relevance"),
                "consistency": result.get("consistency"),
                "credibility": result.get("credibility"),
                "contradicts": result.get("contradicts", []),
            },
            "question": {
                "ordinal": next_turn["ordinal"],
                "text_en": next_turn["question_text"],
                "text_bn": next_turn.get("text_bn") or next_turn["question_text"],
                "probes": next_turn.get("probes"),
                "audio_url": None,
            },
        }

    async def _complete_session(self, user_id: int, session: dict) -> dict:
        turns = await self._interviews.list_turns(session["id"])
        report_data = await compose_report(turns=turns, router=self._router)
        report = await self._interviews.create_report(
            session["id"],
            overall=report_data["overall"],
            summary_en=report_data["summary_en"],
            summary_bn=report_data["summary_bn"],
            strengths=report_data.get("strengths", []),
            weaknesses=report_data.get("weaknesses", []),
        )
        await self._interviews.end_session(session["id"], "complete")
        await self._bus.publish(
            EventType.AGENT_COMPLETED,
            user_id=user_id,
            subject_type="interview_session",
            subject_id=session["public_id"],
            payload={"report_id": report["public_id"]},
        )
        return {"kind": "complete", "report_id": report["public_id"]}

    async def get_report(self, user_id: int, session_public_id: str) -> dict:
        session = await self.get_session(user_id, session_public_id)
        report = await self._interviews.get_report_for_session(session["id"])
        if report is None:
            raise NotFound(
                detail_en="No report yet; finish the session first.",
                detail_bn="এখনও কোনো রিপোর্ট নেই; আগে সেশনটি শেষ করুন।",
            )
        turns = await self._interviews.list_turns(session["id"])

        def _safe_json_loads(val: Any, default: Any) -> Any:
            if isinstance(val, (list, dict)):
                return val
            if isinstance(val, str) and val.strip():
                try:
                    return json.loads(val)
                except ValueError:
                    return default
            return default

        return {
            "id": report["public_id"],
            "session_id": session["public_id"],
            "overall": report["overall"],
            "summary_en": report["summary_en"],
            "summary_bn": report["summary_bn"],
            "strengths": _safe_json_loads(report.get("strengths"), []),
            "weaknesses": _safe_json_loads(report.get("weaknesses"), []),
            "turns": [
                {
                    "ordinal": t["ordinal"],
                    "question_en": t["question_text"],
                    # list_turns now joins interview_bank.text_bn; fall back to the
                    # English text only when the bank row was deleted since this turn.
                    "question_bn": t.get("question_bn") or t["question_text"],
                    "relevance": t["relevance"],
                    "consistency": t["consistency"],
                    "credibility": t["credibility"],
                    "feedback_en": t["feedback_en"],
                    "feedback_bn": t["feedback_bn"],
                    "contradicts": _safe_json_loads(t.get("contradicts"), []),
                }
                for t in turns
                if t.get("answered_at") is not None
            ],
            "created_at": report["created_at"],
        }
