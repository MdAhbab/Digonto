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
        if await self._interviews.has_active_session(user_id):
            raise Conflict(
                detail_en="You already have an interview session in progress.",
                detail_bn="আপনার একটি ইন্টারভিউ সেশন ইতিমধ্যে চলছে।",
            )
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        session = await self._interviews.create_session(
            user_id=user_id,
            target_id=target_row["id"] if target_row else None,
            country_code=country or (target_row["country_code"] if target_row else None),
            visa_type=visa_type or (target_row["visa_type"] if target_row else None),
            mode=mode,
        )
        bank = await self._interviews.pick_questions(session["country_code"], session["visa_type"])
        if not bank:
            raise NotFound(
                detail_en="No interview questions are available for this country yet.",
                detail_bn="এই দেশের জন্য এখনও কোনো ইন্টারভিউ প্রশ্ন নেই।",
            )
        first = bank[0]
        turn_id = await self._interviews.add_turn(
            session["id"], ordinal=1, bank_id=first["id"], question_text=first["text_en"]
        )
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

    async def submit_answer(self, user_id: int, session: dict, answer_text: str) -> dict:
        """Scores the current turn and returns either the next question or
        the session completion payload. The router's WebSocket handler is
        responsible for sequencing `phase` messages around this call.
        """

        turns = await self._interviews.list_turns(session["id"])
        current = turns[-1]
        target_row = None
        if session["target_id"]:
            targets = await self._targets.list_targets(user_id)
            target_row = next((t for t in targets if t.get("id") == session["target_id"]), None)
        file_summary = await self.get_file_summary(user_id, target_row)
        field_hashes = {}
        for doc in await self._documents.list_for_user(user_id):
            field_hashes[doc["public_id"]] = await self._documents.get_field_hashes(doc["id"])

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

        bank = await self._interviews.pick_questions(
            session["country_code"], session["visa_type"], limit=8
        )
        next_ordinal = len(turns) + 1
        if next_ordinal > len(bank):
            return await self._complete_session(user_id, session)

        next_q = bank[next_ordinal - 1]
        await self._interviews.add_turn(
            session["id"], ordinal=next_ordinal, bank_id=next_q["id"],
            question_text=next_q["text_en"],
        )
        return {
            "kind": "question",
            "score": {
                "relevance": result.get("relevance"),
                "consistency": result.get("consistency"),
                "credibility": result.get("credibility"),
                "contradicts": result.get("contradicts", []),
            },
            "question": {
                "ordinal": next_ordinal,
                "text_en": next_q["text_en"],
                "text_bn": next_q["text_bn"],
                "probes": next_q.get("probes"),
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
        return {
            "id": report["public_id"],
            "session_id": session["public_id"],
            "overall": report["overall"],
            "summary_en": report["summary_en"],
            "summary_bn": report["summary_bn"],
            "strengths": json.loads(report["strengths"] or "[]"),
            "weaknesses": json.loads(report["weaknesses"] or "[]"),
            "turns": [
                {
                    "ordinal": t["ordinal"],
                    "question_en": t["question_text"],
                    "question_bn": t["question_text"],
                    "relevance": t["relevance"],
                    "consistency": t["consistency"],
                    "credibility": t["credibility"],
                    "feedback_en": t["feedback_en"],
                    "feedback_bn": t["feedback_bn"],
                    "contradicts": json.loads(t["contradicts"] or "[]"),
                }
                for t in turns
            ],
            "created_at": report["created_at"],
        }
