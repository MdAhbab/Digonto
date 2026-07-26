"""The RAG surface: `POST /ask` (SSE), history, feedback, conversations.

docs/api_contract.md section 5. `AskService.stream_answer` is an async
generator yielding `(event_name, payload)` tuples for exactly the event
names the contract specifies: meta, token, citation, alt, refusal, done,
error. This router's only job is to format each as an SSE frame and hold
the connection open; the event sequencing, persistence, and the refusal
being a terminal *success* rather than an error are all owned by the
service.
"""

from __future__ import annotations

from typing import Any, Mapping

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.db.connection import Databases
from app.deps import (
    RateLimit,
    get_bus,
    get_current_user,
    get_dbs,
    get_model_router,
    get_retriever,
    get_semantic_cache,
)
from app.errors import AppError
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.rag.cache import SemanticCache
from app.rag.retrieval import Retriever
from app.models.ask import AskRequest, ConversationCreate, ConversationOut, FeedbackRequest, QAItem
from app.models.common import Page
from app.repositories.answer_repo import AnswerRepo
from app.repositories.conversation_repo import ConversationRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.routers._sse import SSE_HEADERS, format_sse
from app.services.ask_service import AskService

router = APIRouter(tags=["ask"])


def get_ask_service(
    dbs: Databases = Depends(get_dbs),
    bus: EventBus = Depends(get_bus),
    router_: ModelRouter = Depends(get_model_router),
    retriever: Retriever = Depends(get_retriever),
    cache: SemanticCache = Depends(get_semantic_cache),
) -> AskService:
    return AskService(
        ConversationRepo(dbs.app),
        AnswerRepo(dbs.app),
        SnapshotRepo(dbs.app),
        bus,
        router_,
        retriever,
        cache,
    )


@router.post(
    "/ask",
    dependencies=[
        Depends(RateLimit("ask_hourly", limit=30, window_s=3600)),
        Depends(RateLimit("ask_minute", limit=6, window_s=60)),
    ],
)
async def ask(
    body: AskRequest,
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> StreamingResponse:
    async def gen():
        try:
            async for event_name, payload in ask_service.stream_answer(
                user_id=user["id"],
                user_public_id=user["public_id"],
                question=body.question,
                conversation_public_id=body.conversation_id,
                country=body.country,
                lang=body.lang,
            ):
                yield format_sse(event_name, payload)
        except AppError as exc:
            # A failure before the service's own pipeline try/except takes
            # over (e.g. an unknown conversation_id, raised by
            # AskService.stream_answer before its first `yield`). Once a
            # StreamingResponse has been returned, FastAPI's registered
            # exception handlers no longer see exceptions raised while the
            # body is being iterated, so this converts it into the same
            # terminal SSE `error` event the service uses for a pipeline
            # failure, rather than dropping the connection silently.
            problem = exc.to_problem(instance="/api/v1/ask")
            yield format_sse("error", problem.model_dump(exclude_none=True))

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


@router.get("/ask/history", response_model=Page[QAItem])
async def get_history(
    conversation_id: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> Page[QAItem]:
    items_raw, next_cursor = await ask_service.get_history(
        user_id=user["id"], conversation_public_id=conversation_id, cursor=cursor
    )
    items = [QAItem(**item) for item in items_raw]
    return Page(items=items, next_cursor=next_cursor, total=len(items))


@router.post("/ask/{answer_id}/feedback", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def submit_feedback(
    answer_id: str,
    body: FeedbackRequest,
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> None:
    await ask_service.submit_feedback(
        user_id=user["id"], answer_public_id=answer_id, rating=body.rating, correction=body.correction
    )


def _conversation_out(row: dict[str, Any]) -> ConversationOut:
    return ConversationOut(
        id=row["public_id"], title=row.get("title"), created_at=row["created_at"], updated_at=row["updated_at"]
    )


@router.get("/ask/conversations", response_model=Page[ConversationOut])
async def list_conversations(
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> Page[ConversationOut]:
    rows = await ask_service.list_conversations(user["id"])
    items = [_conversation_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.post("/ask/conversations", response_model=ConversationOut, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    body: ConversationCreate,
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> ConversationOut:
    row = await ask_service.create_conversation(user["id"], body.title)
    return _conversation_out(row)


@router.delete("/ask/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_conversation(
    conversation_id: str,
    user: Mapping = Depends(get_current_user),
    ask_service: AskService = Depends(get_ask_service),
) -> None:
    await ask_service.delete_conversation(user["id"], conversation_id)
