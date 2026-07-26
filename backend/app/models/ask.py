"""Models for the RAG surface: `POST /ask` (SSE), history, feedback, and
conversations.

`QAItem` is the one place besides Planner and Vault that the wire format is
camelCase (`answerEn`, `answerBn`), because `Ask.tsx`'s existing `QA`
interface uses those names and the contract deliberately keeps the mapping
so the page needs no translation layer. Everything else on this surface
(the SSE event payloads, the request body) is snake_case.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.common import Citation

Lang = Literal["bn", "en"]
ServedBy = Literal["local", "cache", "degraded"]


class AskRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question: str = Field(min_length=1)
    conversation_id: str | None = None
    country: str | None = None
    lang: Lang | None = None


# --- SSE event payloads ------------------------------------------------------
# Each is serialised with `model_dump(by_alias=True, exclude_none=True)` and
# written as the `data:` line of its named SSE event.


class AskMetaEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question_id: str
    answer_id: str
    kb_version: int
    cache_hit: bool
    served_by: ServedBy


class AskTokenEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    t: str


class AskCitationEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ordinal: int
    snapshot_id: str
    portal: str
    captured: str
    quoted: str


class AskAltEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    lang: Lang
    text: str


class AskRefusalEvent(BaseModel):
    """Terminal SUCCESS state, not an error. No `token` events follow it."""

    model_config = ConfigDict(populate_by_name=True)

    reason_en: str
    reason_bn: str
    watching_portal_ids: list[str] = Field(default_factory=list)


class AskDoneEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    latency_ms: int
    first_token_ms: int
    confidence: float | None = None
    tokens: int


# --- History, feedback, conversations ---------------------------------------


class QAItem(BaseModel):
    """The frontend `QA` interface, verbatim."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    q: str
    answer_en: str = Field(alias="answerEn")
    answer_bn: str = Field(alias="answerBn")
    citations: list[Citation]
    refusal: bool
    created_at: str


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    rating: Literal["up", "down", "unclear"]
    correction: str | None = None


class ConversationCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None


class ConversationOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    title: str | None = None
    created_at: str
    updated_at: str
