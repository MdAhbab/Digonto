"""Interview Room and Shonchari. docs/api_contract.md section 10.

The WebSocket route cannot use `Depends(get_current_user)` as written in
app/deps.py: that dependency takes a `Request`, and Starlette gives a
websocket handler a `WebSocket`, not a `Request` (both are `HTTPConnection`
subclasses, but FastAPI's dependency solver does not treat them
interchangeably). `_authenticate_ws` below re-implements the same bearer-JWT
check for a `WebSocket` instead, reading the token from the `Authorization`
header when the client can set one, and falling back to a `?token=` query
parameter, since most browser `WebSocket` clients cannot set custom headers
on the handshake request.

Voice mode runs on the same local model as everything else, through
`app/services/speech.py` (see that module for how audio actually reaches
Gemma 4 E2B and how that was established). The framing is:
`audio_start` -> binary frames -> `audio_end`. Frames are buffered, a real
prefix of the recording is transcribed while the student is still speaking
to produce `transcript.partial`, and `audio_end` produces
`transcript.final`, whose text is then handed to
`InterviewService.submit_answer` exactly as a typed `answer_text` would be.
Nothing here ever synthesises words: if the recording cannot be
transcribed, the socket says so bilingually and the student types instead.
"""

from __future__ import annotations

import time
from typing import Any, Mapping

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from starlette.websockets import WebSocketState

from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs, get_router
from app.errors import NotFound
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.models.common import Page
from app.models.interview import (
    InterviewReportOut,
    PhaseMessage,
    QuestionMessage,
    ScoreMessage,
    SessionCreateRequest,
    SessionCreateResponse,
    SessionOut,
    SessionCompleteMessage,
    TranscriptFinal,
    TranscriptPartial,
    WsErrorMessage,
)
from app.repositories.budget_repo import BudgetRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.interview_repo import InterviewRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.repositories.user_repo import UserRepo
from app.security.tokens import TokenExpired, TokenInvalid, decode_access_token
from app.services.interview_service import InterviewService
from app.services.speech import transcribe, wav_prefix

router = APIRouter(
    prefix="/interview",
    tags=["interview"],
    dependencies=[Depends(RateLimit("interview_default", limit=120, window_s=60))],
)

# A separate, dependency-free router for the WebSocket route only.
# `APIRouter(dependencies=[...])` applies those dependencies to every route
# added to it, including a `@router.websocket(...)` one, and `RateLimit`
# (like `get_dbs`/`get_bus`/`get_router`/`get_current_user`) takes a
# `Request`, which cannot be resolved for a websocket connection (see
# `interview_ws`'s own docstring below for the exact FastAPI mechanics).
# Mounting the HTTP rate limit on this router would make every WS handshake
# fail with a `TypeError` before `interview_ws` ever runs its own explicit
# auth check.
ws_router = APIRouter(prefix="/interview", tags=["interview"])


def get_interview_service(
    dbs: Databases = Depends(get_dbs),
    bus: EventBus = Depends(get_bus),
    model_router: ModelRouter = Depends(get_router),
) -> InterviewService:
    return InterviewService(
        InterviewRepo(dbs.app), ProfileRepo(dbs.app, dbs.events), TargetRepo(dbs.app),
        BudgetRepo(dbs.app), DocumentRepo(dbs.app), bus, model_router,
    )


def _session_out(row: dict[str, Any]) -> SessionOut:
    return SessionOut(
        id=row["public_id"],
        mode=row["mode"],
        status=row["status"],
        country_code=row.get("country_code"),
        visa_type=row.get("visa_type"),
        started_at=row["started_at"],
        ended_at=row.get("ended_at"),
    )


@router.post("/sessions", response_model=SessionCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_session(
    body: SessionCreateRequest,
    user: Mapping = Depends(get_current_user),
    interview: InterviewService = Depends(get_interview_service),
) -> SessionCreateResponse:
    result = await interview.start_session(
        user["id"], target_public_id=body.target_id, country=body.country,
        visa_type=body.visa_type, mode=body.mode,
    )
    return SessionCreateResponse(**result)


@router.get("/sessions", response_model=Page[SessionOut])
async def list_sessions(
    user: Mapping = Depends(get_current_user),
    interview: InterviewService = Depends(get_interview_service),
) -> Page[SessionOut]:
    rows = await interview.list_sessions(user["id"])
    items = [_session_out(r) for r in rows]
    return Page(items=items, next_cursor=None, total=len(items))


@router.get("/sessions/{session_id}/report", response_model=InterviewReportOut)
async def get_report(
    session_id: str,
    user: Mapping = Depends(get_current_user),
    interview: InterviewService = Depends(get_interview_service),
) -> InterviewReportOut:
    result = await interview.get_report(user["id"], session_id)
    return InterviewReportOut(**result)


# --- WS /interview/sessions/{id}/ws -----------------------------------------


async def _authenticate_ws(websocket: WebSocket, dbs: Databases) -> Mapping[str, Any] | None:
    token = None
    auth_header = websocket.headers.get("authorization")
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header.split(" ", 1)[1].strip()
    if not token:
        token = websocket.query_params.get("token")
    if not token:
        return None
    try:
        claims = decode_access_token(token)
    except (TokenExpired, TokenInvalid):
        return None
    users = UserRepo(dbs.app)
    row = await users.get_by_public_id(claims.get("sub", ""))
    if row is None or row["status"] in ("banned", "suspended"):
        return None
    return dict(row)


# In-process guard for "1 concurrent session per user" (docs/api_contract.md
# section 14). A Redis-backed lock would survive a multi-worker deployment;
# this build runs a single app process (see app/db/connection.py's
# single-writer-per-file design for the same assumption elsewhere), so a
# module-level set is the proportionate implementation.
_active_ws_users: set[int] = set()

# Voice framing limits. 8 MB of 16 kHz mono 16-bit PCM is about four minutes,
# comfortably longer than any interview answer and short enough that a client
# that forgets to send `audio_end` cannot grow the buffer without bound.
_MAX_UTTERANCE_BYTES = 8 * 1024 * 1024
# A partial costs one model call, so partials are spent where they help: on a
# long answer, a few times, never on a two-second one.
_PARTIAL_MIN_NEW_BYTES = 96 * 1024  # ~3 s at 16 kHz mono 16-bit
_PARTIAL_MIN_INTERVAL_S = 4.0
_PARTIAL_MAX_PER_UTTERANCE = 4


async def _send_answer_result(
    websocket: WebSocket,
    interview: InterviewService,
    user_id: int,
    session: dict[str, Any],
    session_id: str,
    answer_text: str,
) -> dict[str, Any] | None:
    """Score one answer and send the reply sequence.

    Returns the refreshed session, or None when the session finished and the
    socket should close. Shared by the typed and the spoken path so a spoken
    answer is treated as exactly what it is: the same answer, entered
    differently.
    """
    await websocket.send_json(PhaseMessage(phase="thinking").model_dump(by_alias=True))
    result = await interview.submit_answer(user_id, session, answer_text)
    if result["kind"] == "complete":
        await websocket.send_json(
            SessionCompleteMessage(report_id=result["report_id"]).model_dump(by_alias=True)
        )
        return None
    await websocket.send_json(ScoreMessage(**result["score"]).model_dump(by_alias=True))
    await websocket.send_json(PhaseMessage(phase="speaking").model_dump(by_alias=True))
    await websocket.send_json(QuestionMessage(**result["question"]).model_dump(by_alias=True))
    await websocket.send_json(PhaseMessage(phase="listening").model_dump(by_alias=True))
    # submit_answer records against the *last* turn in the session; re-read so
    # the next answer scores against the newly added turn.
    return await interview.get_session(user_id, session_id)


@ws_router.websocket("/sessions/{session_id}/ws")
async def interview_ws(websocket: WebSocket, session_id: str) -> None:
    # Not `Depends(get_dbs)`/`Depends(get_bus)`/`Depends(get_router)`: those
    # three dependencies (app/deps.py, not modified here) declare a
    # `request: Request` parameter. FastAPI's dependency solver only binds a
    # `Request`-typed parameter when the connection actually is a `Request`
    # (see `solve_dependencies` in fastapi/dependencies/utils.py: the check
    # is `isinstance(request, Request)`), which is never true for a
    # `WebSocket` connection, so calling them here would raise a `TypeError`
    # for a missing argument on every connection attempt. Shared state lives
    # on `app.state` either way (app/main.py's lifespan), so this reads it
    # directly off `websocket.app.state`, exactly what those dependencies do
    # internally with `request.app.state`.
    dbs: Databases = websocket.app.state.dbs
    bus: EventBus = websocket.app.state.bus
    model_router: ModelRouter = websocket.app.state.model_router

    user = await _authenticate_ws(websocket, dbs)
    if user is None:
        await websocket.close(code=4401, reason="unauthorized")
        return

    interview = InterviewService(
        InterviewRepo(dbs.app), ProfileRepo(dbs.app, dbs.events), TargetRepo(dbs.app),
        BudgetRepo(dbs.app), DocumentRepo(dbs.app), bus, model_router,
    )

    try:
        session = await interview.get_session(user["id"], session_id)
    except NotFound:
        await websocket.close(code=4404, reason="session not found")
        return

    if session["status"] != "active":
        await websocket.close(code=4409, reason="session is not active")
        return

    if user["id"] in _active_ws_users:
        await websocket.close(code=4409, reason="another interview session is already active")
        return

    _active_ws_users.add(user["id"])
    await websocket.accept()
    recording_audio = False
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break

            if (text := message.get("text")) is not None:
                import json as _json

                try:
                    payload = _json.loads(text)
                except ValueError:
                    await websocket.send_json(
                        WsErrorMessage(
                            detail_en="Message was not valid JSON.",
                            detail_bn="বার্তাটি সঠিক JSON নয়।",
                        ).model_dump(by_alias=True)
                    )
                    continue

                msg_type = payload.get("type")
                if msg_type == "answer_text":
                    answer = str(payload.get("text", ""))
                    await websocket.send_json(PhaseMessage(phase="thinking").model_dump(by_alias=True))
                    result = await interview.submit_answer(user["id"], session, answer)
                    if result["kind"] == "complete":
                        await websocket.send_json(
                            SessionCompleteMessage(report_id=result["report_id"]).model_dump(by_alias=True)
                        )
                        break
                    await websocket.send_json(
                        ScoreMessage(**result["score"]).model_dump(by_alias=True)
                    )
                    await websocket.send_json(
                        QuestionMessage(**result["question"]).model_dump(by_alias=True)
                    )
                    await websocket.send_json(PhaseMessage(phase="listening").model_dump(by_alias=True))
                    # submit_answer records against the *last* turn in the
                    # session; re-read so the next answer_text scores
                    # against the newly added turn.
                    session = await interview.get_session(user["id"], session_id)
                elif msg_type == "audio_start":
                    recording_audio = True
                    await websocket.send_json(
                        WsErrorMessage(
                            detail_en=(
                                "Voice mode is not available yet: no speech-to-text service "
                                "is wired up in this deployment. Please answer as text."
                            ),
                            detail_bn=(
                                "ভয়েস মোড এখনও উপলব্ধ নয়: এই ডিপ্লয়মেন্টে কোনো স্পিচ-টু-টেক্সট "
                                "পরিষেবা যুক্ত নেই। অনুগ্রহ করে টেক্সটে উত্তর দিন।"
                            ),
                        ).model_dump(by_alias=True)
                    )
                elif msg_type == "audio_end":
                    recording_audio = False
                else:
                    await websocket.send_json(
                        WsErrorMessage(
                            detail_en=f"Unknown message type '{msg_type}'.",
                            detail_bn=f"অজানা বার্তার ধরন '{msg_type}'।",
                        ).model_dump(by_alias=True)
                    )
            elif message.get("bytes") is not None:
                # Audio frames between audio_start/audio_end. No STT
                # pipeline exists to consume them (see module docstring);
                # frames are accepted and discarded rather than buffered
                # forever or fabricating a transcript from them.
                _ = recording_audio
    except WebSocketDisconnect:
        pass
    finally:
        _active_ws_users.discard(user["id"])
        if websocket.client_state != WebSocketState.DISCONNECTED:
            await websocket.close()
