"""Interview Room and Shonchari models: session bootstrap, WS message
envelopes, and the post-session report.

Section 10 of the contract. Snake_case throughout.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["text", "voice"]
SessionStatus = Literal["active", "complete", "abandoned"]


class SessionCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    target_id: str | None = None
    country: str | None = None
    visa_type: str | None = None
    mode: Mode = "text"


class QuestionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ordinal: int
    text_en: str
    text_bn: str
    probes: str | None = None
    audio_url: str | None = None


class SessionCreateResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    session_id: str
    mode: Mode
    first_question: QuestionOut


class SessionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    mode: Mode
    status: SessionStatus
    country_code: str | None = None
    visa_type: str | None = None
    started_at: str
    ended_at: str | None = None


# --- WebSocket message envelopes ---------------------------------------------
# Client -> server


class ClientAnswerText(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["answer_text"] = "answer_text"
    text: str


class ClientAudioStart(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["audio_start"] = "audio_start"


class ClientAudioEnd(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["audio_end"] = "audio_end"


# Server -> client


class TranscriptPartial(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["transcript.partial"] = "transcript.partial"
    text: str


class TranscriptFinal(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["transcript.final"] = "transcript.final"
    text: str
    confidence: float


class PhaseMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["phase"] = "phase"
    phase: Literal["idle", "listening", "thinking", "speaking"]


class ContradictionOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    document_id: str
    field: str
    said: str
    document_says: str


class ScoreMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["score"] = "score"
    relevance: float
    consistency: float
    credibility: float
    contradicts: list[ContradictionOut] = Field(default_factory=list)


class QuestionMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["question"] = "question"
    ordinal: int
    text_en: str
    text_bn: str
    probes: str | None = None
    audio_url: str | None = None


class SessionCompleteMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["session.complete"] = "session.complete"
    report_id: str


class WsErrorMessage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: Literal["error"] = "error"
    detail_en: str
    detail_bn: str


# --- Report -------------------------------------------------------------


class TurnGrade(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    ordinal: int
    question_en: str
    question_bn: str
    relevance: float | None = None
    consistency: float | None = None
    credibility: float | None = None
    feedback_en: str | None = None
    feedback_bn: str | None = None
    contradicts: list[ContradictionOut] = Field(default_factory=list)


class InterviewReportOut(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    session_id: str
    overall: float
    summary_en: str
    summary_bn: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    turns: list[TurnGrade] = Field(default_factory=list)
    created_at: str
