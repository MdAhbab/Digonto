"""The RAG surface: `POST /ask` (SSE), history, feedback, conversations.

api_contract.md section 5. This service owns persistence (`questions`,
`answers`, `answer_citations`), event emission, and the exact SSE event
sequence the frontend's `TypesetAnswer` component depends on. It does not
own retrieval or generation.

**Boundary with the RAG pipeline.** Hybrid retrieval (Qdrant dense + BM25,
reciprocal rank fusion, rerank), the semantic cache, and grounded generation
live in `app/rag/`, behind the single async generator
`app.rag.pipeline.stream_grounded_answer`. This service consumes that event
sequence and owns everything around it; it never retrieves or generates.
The pipeline's clients (model router, embedder, Qdrant) are constructed once
at startup and passed in, so a question does not build its own connections.

Event kinds this service handles, in the order they can arrive: `meta`
(always first), then either `refusal`, or `token`* followed by `citation`*,
`alt`, and `final`. `incomplete` may replace the citation group when
generation was cut off after tokens were already shown.
"""

from __future__ import annotations

import re
import time
from collections.abc import AsyncIterator
from typing import Any

from app.errors import NotFound
from app.events.bus import EventBus, EventType
from app.rag.pipeline import stream_grounded_answer
from app.repositories._util import utc_now_iso
from app.repositories.answer_repo import AnswerRepo
from app.repositories.conversation_repo import ConversationRepo
from app.repositories.snapshot_repo import SnapshotRepo

_BANGLA_RANGE = re.compile(r"[ঀ-৿]")


def _detect_lang(text: str) -> str:
    has_bangla = bool(_BANGLA_RANGE.search(text))
    has_latin = bool(re.search(r"[A-Za-z]", text))
    if has_bangla and has_latin:
        return "mixed"
    if has_bangla:
        return "bn"
    if has_latin:
        # No Bangla script but Latin letters: either English or Banglish.
        # Real Banglish detection needs the model pass in the RAG pipeline;
        # this is the honest, cheap default until that call classifies it.
        return "banglish" if _looks_banglish(text) else "en"
    return "en"


_BANGLISH_MARKERS = (
    "ki", "kemon", "koto", "ache", "lagbe", "hobe", "korte", "bhai", "apni", "tumi",
)


def _looks_banglish(text: str) -> bool:
    lowered = text.lower()
    return any(f" {m} " in f" {lowered} " for m in _BANGLISH_MARKERS)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


class AskService:
    def __init__(
        self,
        conversations: ConversationRepo,
        answers: AnswerRepo,
        snapshots: SnapshotRepo,
        bus: EventBus,
        router: ModelRouter,
        retriever: Retriever,
        cache: SemanticCache,
    ) -> None:
        self._conversations = conversations
        self._answers = answers
        self._snapshots = snapshots
        self._bus = bus
        self._router = router
        self._retriever = retriever
        self._cache = cache

    async def stream_answer(
        self, *, user_id: int, user_public_id: str, question: str,
        conversation_public_id: str | None, country: str | None, lang: str | None,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        # -- conversation ------------------------------------------------
        conv = None
        if conversation_public_id:
            conv = await self._conversations.get_by_public_id(user_id, conversation_public_id)
            if conv is None:
                raise NotFound(
                    detail_en="That conversation could not be found.",
                    detail_bn="কথোপকথনটি খুঁজে পাওয়া যায়নি।",
                )
        else:
            conv = await self._conversations.create(user_id, None)

        lang_detected = _detect_lang(question)
        text_normalised = _normalise(question)

        question_row = await self._answers.create_question(
            conversation_id=conv["id"],
            user_id=user_id,
            text_raw=question,
            text_normalised=text_normalised,
            lang_detected=lang_detected,
            country_filter=country,
        )
        await self._conversations.touch(conv["id"])

        kb_version = await self._snapshots.live_kb_version()
        kb_version_id = kb_version["id"] if kb_version else None
        kb_version_no = kb_version["version_no"] if kb_version else 0

        started = time.monotonic()
        first_token_at: float | None = None
        primary_lang = lang or ("bn" if lang_detected in ("bn", "mixed", "banglish") else "en")

        answer_bn: str | None = None
        answer_en: str | None = None
        confidence: float | None = None
        is_refusal = False
        incomplete = False
        refusal_reason: str | None = None
        served_by = "local"
        cache_hit = False
        model_tag = "unknown"
        token_count = 0
        answer_row: dict[str, Any] | None = None

        try:
            pipeline = stream_grounded_answer(
                question=text_normalised,
                lang=primary_lang,
                country=country,
                kb_version_id=kb_version_id,
                router=self._router,
                retriever=self._retriever,
                cache=self._cache,
            )
            async for event in pipeline:
                kind = event.get("kind")
                if kind == "meta":
                    served_by = event.get("served_by", "local")
                    cache_hit = bool(event.get("cache_hit", False))
                    model_tag = event.get("model_tag", model_tag)
                    # The answer row is created here, with placeholder empty
                    # text, purely so `answer_id` exists for the `meta` SSE
                    # event, which the contract requires "first, always". The
                    # real content is written once streaming finishes.
                    answer_row = await self._answers.create_answer(
                        question_id=question_row["id"],
                        answer_bn="",
                        answer_en="",
                        confidence=None,
                        is_refusal=False,
                        refusal_reason=None,
                        kb_version_id=kb_version_id,
                        model_tag=model_tag,
                        served_by=served_by,
                        cache_hit=cache_hit,
                        latency_ms=None,
                        first_token_ms=None,
                    )
                    yield "meta", {
                        "question_id": question_row["public_id"],
                        "answer_id": answer_row["public_id"],
                        "kb_version": kb_version_no,
                        "cache_hit": cache_hit,
                        "served_by": served_by,
                    }
                elif kind == "token":
                    if first_token_at is None:
                        first_token_at = time.monotonic()
                    token_count += 1
                    text = event.get("text", "")
                    if primary_lang == "bn":
                        answer_bn = (answer_bn or "") + text
                    else:
                        answer_en = (answer_en or "") + text
                    yield "token", {"t": text}
                elif kind == "citation":
                    if answer_row is not None:
                        await self._answers.add_citation(
                            answer_id=answer_row["id"],
                            ordinal=event["ordinal"],
                            snapshot_id=event["snapshot_id"],
                            passage_id=event.get("passage_id"),
                            quoted_span=event.get("quoted", ""),
                        )
                    yield "citation", {
                        "ordinal": event["ordinal"],
                        "snapshot_id": event.get("snapshot_public_id", ""),
                        "portal": event.get("portal", ""),
                        "captured": event.get("captured", ""),
                        "quoted": event.get("quoted", ""),
                    }
                elif kind == "alt":
                    alt_lang = event.get("lang")
                    if alt_lang == "bn":
                        answer_bn = event.get("text")
                    else:
                        answer_en = event.get("text")
                    yield "alt", {"lang": alt_lang, "text": event.get("text", "")}
                elif kind == "refusal":
                    is_refusal = True
                    refusal_reason = event.get("reason_en")
                    yield "refusal", {
                        "reason_en": event.get("reason_en", ""),
                        "reason_bn": event.get("reason_bn", ""),
                        "watching_portal_ids": event.get("watching_portal_ids", []),
                    }
                elif kind == "incomplete":
                    # Generation was cut off after tokens had already been shown.
                    # The text stands, but it carries no citations, so the client
                    # has to be able to label it rather than presenting it with
                    # the same authority as a fully cited answer.
                    incomplete = True
                    yield "incomplete", {
                        "reason_en": event.get("reason_en", ""),
                        "reason_bn": event.get("reason_bn", ""),
                    }
                elif kind == "final":
                    confidence = event.get("confidence")
                    if event.get("answer_primary") is not None:
                        if primary_lang == "bn":
                            answer_bn = event["answer_primary"]
                        else:
                            answer_en = event["answer_primary"]
        except Exception as exc:  # noqa: BLE001 - convert to a terminal SSE `error` event
            yield "error", {
                "type": "https://digonto.ahbab.dev/errors/ask-pipeline-failed",
                "title": "Could not generate an answer",
                "status": 500,
                "detail_en": "Something went wrong while generating the answer. Please try again.",
                "detail_bn": "উত্তর তৈরির সময় সমস্যা হয়েছে। আবার চেষ্টা করুন।",
                "instance": "/api/v1/ask",
            }
            await self._bus.publish(
                EventType.ANSWER_FAILED,
                user_id=user_id,
                subject_type="question",
                subject_id=question_row["public_id"],
                payload={"error": str(exc)},
            )
            return

        latency_ms = int((time.monotonic() - started) * 1000)
        first_token_ms = int((first_token_at - started) * 1000) if first_token_at else latency_ms

        if answer_row is None:
            # The pipeline never emitted `meta`; nothing to persist against.
            return

        await self._answers.update_final(
            answer_row["id"],
            answer_bn=answer_bn or ("" if not is_refusal else None),
            answer_en=answer_en or ("" if not is_refusal else None),
            confidence=confidence,
            is_refusal=is_refusal,
            refusal_reason=refusal_reason,
            latency_ms=latency_ms,
            first_token_ms=first_token_ms,
        )

        # On a refusal the question text and country ride along on the event. The
        # discovery consumer (app/workers/discovery.py) needs them to search for a
        # source that would have answered it, which is what turns a refusal from a
        # dead end into the trigger that grows the watch list. Carried only when
        # refusing, so an ordinary answered question adds nothing to the archive
        # that `questions` does not already hold.
        payload: dict[str, Any] = {"is_refusal": is_refusal, "confidence": confidence}
        if is_refusal:
            payload["question"] = text_normalised
            payload["country"] = country
        await self._bus.publish(
            EventType.ANSWER_GENERATED,
            user_id=user_id,
            subject_type="answer",
            subject_id=answer_row["public_id"],
            payload=payload,
        )

        yield "done", {
            "latency_ms": latency_ms,
            "first_token_ms": first_token_ms,
            "confidence": confidence,
            "tokens": token_count,
            "incomplete": incomplete,
        }

    # -- history, feedback, conversations --------------------------------

    async def get_history(
        self, *, user_id: int, conversation_public_id: str | None, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        conversation_id = None
        if conversation_public_id:
            conv = await self._conversations.get_by_public_id(user_id, conversation_public_id)
            if conv is None:
                raise NotFound(
                    detail_en="That conversation could not be found.",
                    detail_bn="কথোপকথনটি খুঁজে পাওয়া যায়নি।",
                )
            conversation_id = conv["id"]
        rows, next_cursor = await self._answers.list_history(
            user_id=user_id, conversation_id=conversation_id, cursor=cursor
        )
        items = []
        for r in rows:
            citations_raw = await self._answers.list_citations(r["id"])
            items.append(
                {
                    "id": r["public_id"],
                    "q": r["text_raw"],
                    "answerEn": r["answer_en"] or "",
                    "answerBn": r["answer_bn"] or "",
                    "citations": [
                        {
                            "id": c["snapshot_public_id"],
                            "portal": c["portal_label"],
                            "captured": c["fetched_at"],
                            "quoted": c["quoted_span"],
                        }
                        for c in citations_raw
                    ],
                    "refusal": bool(r["is_refusal"]),
                    "created_at": r["created_at"],
                }
            )
        return items, next_cursor

    async def submit_feedback(
        self, *, user_id: int, answer_public_id: str, rating: str, correction: str | None
    ) -> None:
        answer = await self._answers.get_answer_by_public_id(answer_public_id)
        if answer is None:
            raise NotFound(detail_en="Answer not found.", detail_bn="উত্তরটি পাওয়া যায়নি।")
        await self._answers.upsert_feedback(
            answer_id=answer["id"], user_id=user_id, rating=rating, correction_text=correction
        )
        await self._bus.publish(
            EventType.ANSWER_CORRECTED if correction else EventType.ANSWER_GENERATED,
            user_id=user_id,
            subject_type="answer",
            subject_id=answer_public_id,
            payload={"rating": rating},
        )

    async def list_conversations(self, user_id: int) -> list[dict]:
        return await self._conversations.list_for_user(user_id)

    async def create_conversation(self, user_id: int, title: str | None) -> dict:
        return await self._conversations.create(user_id, title)

    async def delete_conversation(self, user_id: int, public_id: str) -> None:
        ok = await self._conversations.delete(user_id, public_id)
        if not ok:
            raise NotFound(
                detail_en="That conversation could not be found.",
                detail_bn="কথোপকথনটি খুঁজে পাওয়া যায়নি।",
            )
