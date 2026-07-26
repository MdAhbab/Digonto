"""Vault and Prohori, plus the three document-adjacent agents (Bicharok,
Lekhok, Dalil).

docs/api_contract.md sections 8 and 11. One router module because
`VaultService` owns all six feature areas (see its own module docstring);
paths are given explicitly per route rather than via a single prefix
because the contract puts them at `/vault/*`, `/rejection/*`, `/statements`,
and `/contracts`, four different namespaces with nothing in common to
prefix.

Two things this router adds beyond a literal reading of the contract, both
noted in the final report:

1. `GET /vault/documents/{id}/download` returns a signed URL (matching
   `DocumentDownloadOut`), per the contract's "(signed, 15 min)" and
   `VaultService`'s own docstring ("Signed, short-lived download URLs are
   issued by the router, which owns request signing"). That signed URL has
   to point somewhere: `GET /vault/documents/{id}/download/file` is the
   companion route this router adds to make the signature and expiry
   actually mean something, since `VaultService` exposes no other way to
   fetch decrypted bytes.
2. Several fields the contract's response models expect are only internal
   integer foreign keys on the raw rows `VaultService` returns (a rejection
   case's `document_id`, a statement finding's `conflicts_document_id`, an
   audit finding's `document_id` and `snapshot_id`). Every ID crossing the
   wire must be a `public_id` (docs/api_contract.md section 1), so this
   router resolves each one via the already-loaded `DocumentRepo`/
   `SnapshotRepo` rather than leak the internal integer.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile, status
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.db.connection import Databases
from app.deps import RateLimit, get_bus, get_current_user, get_dbs, get_router
from app.errors import Unauthorized
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.models.common import Page, SnapshotCitation
from app.models.vault import (
    AgentAcceptedResponse,
    ApplyToPlanResponse,
    AuditFindingOut,
    AuditOut,
    AuditStartResponse,
    ContractClauseOut,
    ContractCreate,
    ContractOut,
    DocumentDetail,
    DocumentDownloadOut,
    DocumentOut,
    RejectionCaseCreate,
    RejectionCaseOut,
    RejectionGroundOut,
    StatementCreate,
    StatementCreateResponse,
    StatementFindingOut,
)
from app.repositories.audit_repo import AuditRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.notification_repo import NotificationRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.repositories.target_repo import TargetRepo
from app.routers._sse import SSE_HEADERS, format_sse, sse_comment
from app.security.vault_crypto import decrypt_file
from app.services.vault_service import VaultService

router = APIRouter(
    tags=["vault"],
    dependencies=[Depends(RateLimit("vault_default", limit=120, window_s=60))],
)


def get_vault_service(
    dbs: Databases = Depends(get_dbs),
    bus: EventBus = Depends(get_bus),
    model_router: ModelRouter = Depends(get_router),
) -> VaultService:
    return VaultService(
        DocumentRepo(dbs.app),
        AuditRepo(dbs.app),
        ProfileRepo(dbs.app, dbs.events),
        TargetRepo(dbs.app),
        bus,
        model_router,
        get_settings(),
    )


def get_document_repo(dbs: Databases = Depends(get_dbs)) -> DocumentRepo:
    return DocumentRepo(dbs.app)


def get_snapshot_repo(dbs: Databases = Depends(get_dbs)) -> SnapshotRepo:
    return SnapshotRepo(dbs.app)


async def _resolve_document_public_id(
    documents: DocumentRepo, user_id: int, internal_id: int | None
) -> str | None:
    """Every id on the wire is a public_id, never the integer primary key
    (docs/api_contract.md section 1). `VaultService` hands back rows with a
    raw `document_id` foreign key for rejection cases, contracts, and
    statement findings; this resolves it via the small set of documents the
    student owns rather than exposing the internal id."""
    if internal_id is None:
        return None
    for doc in await documents.list_for_user(user_id):
        if doc["id"] == internal_id:
            return doc["public_id"]
    return None


def _parse_json_object(value: Any) -> dict[str, Any] | None:
    """`audit_findings.evidence` (docs/database.md section 3.6) is stored as
    a JSON TEXT column; the repo hands back the raw string, but
    `AuditFindingOut.evidence` is typed `dict | None`."""
    import json

    if value is None or isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


async def _citation_from_snapshot_id(
    snapshots: SnapshotRepo, snapshot_id: int | None
) -> SnapshotCitation | None:
    if snapshot_id is None:
        return None
    snap = await snapshots.get(snapshot_id)
    if snap is None:
        return None
    return SnapshotCitation(
        snapshot_id=snap["public_id"], portal=snap.get("portal_label"), captured=snap.get("fetched_at")
    )


# --- documents --------------------------------------------------------


@router.post(
    "/vault/documents",
    response_model=DocumentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(RateLimit("vault_upload_daily", limit=20, window_s=86400))],
)
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form(...),
    expires_on: str | None = Form(default=None),
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> DocumentOut:
    data = await file.read()
    doc = await vault.upload_document(
        user_id=user["id"],
        user_public_id=user["public_id"],
        kind=kind,
        filename=file.filename or "upload",
        mime_type=file.content_type or "application/octet-stream",
        data=data,
        expires_on=expires_on,
    )
    # upload_document returns the bare inserted row (status: "scanning"), not
    # the card-shaped output; list_documents is where VaultService derives
    # nameEn/nameBn/severity/finding/action, so re-fetch and pick the new row
    # rather than duplicate that shaping logic here.
    cards = await vault.list_documents(user["id"])
    shaped = next(c for c in cards if c["id"] == doc["public_id"])
    return DocumentOut(**shaped)


@router.get("/vault/documents", response_model=Page[DocumentOut])
async def list_documents(
    user: Mapping = Depends(get_current_user), vault: VaultService = Depends(get_vault_service)
) -> Page[DocumentOut]:
    cards = await vault.list_documents(user["id"])
    items = [DocumentOut(**c) for c in cards]
    return Page(items=items, next_cursor=None, total=len(items))


@router.get("/vault/documents/{document_id}", response_model=DocumentDetail)
async def get_document(
    document_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> DocumentDetail:
    doc = await vault.get_document(user["id"], document_id)
    return DocumentDetail(
        id=doc["public_id"],
        kind=doc["kind"],
        original_name=doc["original_name"],
        mime_type=doc["mime_type"],
        byte_size=doc["byte_size"],
        page_count=doc.get("page_count"),
        issued_on=doc.get("issued_on"),
        expires_on=doc.get("expires_on"),
        status=doc["status"],
        uploaded_at=doc["uploaded_at"],
    )


def _sign_download(document_id: str, expires_at: int) -> str:
    settings = get_settings()
    message = f"{document_id}:{expires_at}".encode("utf-8")
    return hmac.new(settings.jwt_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


@router.get("/vault/documents/{document_id}/download", response_model=DocumentDownloadOut)
async def get_download_url(
    document_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> DocumentDownloadOut:
    # Confirms ownership (raises NotFound otherwise) before minting a token.
    await vault.get_document(user["id"], document_id)
    expires_at = int(time.time()) + 15 * 60
    sig = _sign_download(document_id, expires_at)
    base = get_settings().api_base_path
    url = f"{base}/vault/documents/{document_id}/download/file?exp={expires_at}&sig={sig}"
    expires_at_iso = datetime.fromtimestamp(expires_at, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return DocumentDownloadOut(url=url, expires_at=expires_at_iso)


@router.get(
    "/vault/documents/{document_id}/download/file",
    response_model=None,
    include_in_schema=True,
)
async def download_file(
    document_id: str,
    exp: int = Query(...),
    sig: str = Query(...),
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> Response:
    """Companion route to `GET /vault/documents/{id}/download`'s signed URL.
    See the module docstring: not a separate contract path, added because a
    signed URL has to resolve to something."""
    if time.time() > exp:
        raise Unauthorized(
            detail_en="This download link has expired. Request a new one.",
            detail_bn="ডাউনলোড লিংকটির মেয়াদ শেষ। নতুন একটি লিংক নিন।",
        )
    if not hmac.compare_digest(_sign_download(document_id, exp), sig):
        raise Unauthorized(
            detail_en="This download link is not valid.",
            detail_bn="এই ডাউনলোড লিংকটি সঠিক নয়।",
        )
    doc = await vault.get_document(user["id"], document_id)
    ciphertext = Path(doc["storage_path"]).read_bytes()
    plaintext = decrypt_file(ciphertext, doc["wrapped_dek"], doc["nonce"])
    return Response(
        content=plaintext,
        media_type=doc["mime_type"],
        headers={"Content-Disposition": f'attachment; filename="{doc["original_name"]}"'},
    )


@router.delete("/vault/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_document(
    document_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> None:
    await vault.delete_document(user["id"], document_id)


# --- Prohori audit ------------------------------------------------------


@router.post("/vault/audit", response_model=AuditStartResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_audit(
    target_id: str | None = Query(default=None),
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> AuditStartResponse:
    audit = await vault.start_audit(user["id"], target_id)
    return AuditStartResponse(audit_id=audit["public_id"])


@router.get("/vault/audit/latest", response_model=AuditOut)
async def get_latest_audit(
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
    documents: DocumentRepo = Depends(get_document_repo),
    snapshots: SnapshotRepo = Depends(get_snapshot_repo),
) -> AuditOut:
    audit = await vault.get_latest_audit(user["id"])
    findings = []
    for f in audit["findings"]:
        findings.append(
            AuditFindingOut(
                id=f["public_id"],
                document_id=await _resolve_document_public_id(documents, user["id"], f.get("document_id")),
                code=f["code"],
                severity=f["severity"],
                title_en=f["title_en"],
                title_bn=f["title_bn"],
                detail_en=f["detail_en"],
                detail_bn=f["detail_bn"],
                evidence=_parse_json_object(f.get("evidence")),
                action_en=f.get("action_en"),
                action_bn=f.get("action_bn"),
                citation=await _citation_from_snapshot_id(snapshots, f.get("snapshot_id")),
            )
        )
    return AuditOut(
        id=audit["public_id"],
        status=audit["status"],
        started_at=audit["started_at"],
        finished_at=audit.get("finished_at"),
        findings=findings,
    )


# --- GET /vault/events (SSE) --------------------------------------------

_VAULT_EVENT_MAP = {"vault.doc.added": "document.status", "audit.updated": "audit.finding"}
_HEARTBEAT_SECONDS = 15.0
_POLL_SECONDS = 1.5
_ULID_FLOOR = "0" * 26


@router.get("/vault/events")
async def vault_events(
    request: Request,
    user: Mapping = Depends(get_current_user),
    dbs: Databases = Depends(get_dbs),
) -> StreamingResponse:
    import asyncio

    notifications = NotificationRepo(dbs.app, dbs.events)
    user_id = user["id"]

    async def gen():
        last_id: str | None = None
        last_heartbeat = time.monotonic()
        while True:
            if await request.is_disconnected():
                break
            rows = await notifications.events_since(user_id, last_id)
            relevant = [r for r in rows if r["type"] in _VAULT_EVENT_MAP]
            if last_id is None:
                # First pass: only carry forward the high-water mark, don't
                # replay a batch of possibly-unrelated history on connect.
                last_id = rows[-1]["event_id"] if rows else _ULID_FLOOR
            elif rows:
                last_id = rows[-1]["event_id"]
            for row in relevant:
                yield format_sse(
                    _VAULT_EVENT_MAP[row["type"]],
                    {"subject_type": row.get("subject_type"), "subject_id": row.get("subject_id")},
                    event_id=row["event_id"],
                )
                last_heartbeat = time.monotonic()
            if not relevant:
                await asyncio.sleep(_POLL_SECONDS)
                if time.monotonic() - last_heartbeat >= _HEARTBEAT_SECONDS:
                    yield sse_comment()
                    last_heartbeat = time.monotonic()

    return StreamingResponse(gen(), media_type="text/event-stream", headers=SSE_HEADERS)


# --- Bicharok: rejection autopsy -----------------------------------------


@router.post("/rejection/cases", response_model=AgentAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_rejection_case(
    body: RejectionCaseCreate,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> AgentAcceptedResponse:
    case = await vault.create_rejection_case(user["id"], body.document_id)
    return AgentAcceptedResponse(id=case["public_id"])


@router.get("/rejection/cases/{case_id}", response_model=RejectionCaseOut)
async def get_rejection_case(
    case_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
    documents: DocumentRepo = Depends(get_document_repo),
    snapshots: SnapshotRepo = Depends(get_snapshot_repo),
) -> RejectionCaseOut:
    case = await vault.get_rejection_case(user["id"], case_id)
    grounds = []
    for g in case["grounds"]:
        grounds.append(
            RejectionGroundOut(
                code=g.get("code"),
                quoted_text=g["quoted_text"],
                meaning_en=g["meaning_en"],
                meaning_bn=g["meaning_bn"],
                remedy_en=g["remedy_en"],
                remedy_bn=g["remedy_bn"],
                remediable=g["remediable"],
                citation=await _citation_from_snapshot_id(snapshots, g.get("snapshot_id")),
                linked_step_key=g.get("linked_step_key"),
            )
        )
    return RejectionCaseOut(
        id=case["public_id"],
        document_id=await _resolve_document_public_id(documents, user["id"], case.get("document_id")),
        country_code=case.get("country_code"),
        visa_type=case.get("visa_type"),
        refused_on=case.get("refused_on"),
        summary_en=case.get("summary_en"),
        summary_bn=case.get("summary_bn"),
        reapply_ready_at=case.get("reapply_ready_at"),
        grounds=grounds,
        created_at=case["created_at"],
    )


@router.post("/rejection/cases/{case_id}/apply-to-plan", response_model=ApplyToPlanResponse)
async def apply_rejection_to_plan(
    case_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> ApplyToPlanResponse:
    applied = await vault.apply_rejection_to_plan(user["id"], case_id)
    return ApplyToPlanResponse(applied_step_keys=applied)


# --- Lekhok: statement forensics -----------------------------------------


@router.post("/statements", response_model=StatementCreateResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_statement(
    body: StatementCreate,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> StatementCreateResponse:
    statement = await vault.create_statement(user["id"], body.kind, body.body, body.target_id)
    return StatementCreateResponse(statement_id=statement["public_id"])


@router.get("/statements/{statement_id}/findings", response_model=Page[StatementFindingOut])
async def get_statement_findings(
    statement_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
    documents: DocumentRepo = Depends(get_document_repo),
) -> Page[StatementFindingOut]:
    findings = await vault.get_statement_findings(user["id"], statement_id)
    items = []
    for f in findings:
        items.append(
            StatementFindingOut(
                severity=f["severity"],
                kind=f["kind"],
                excerpt=f["excerpt"],
                detail_en=f["detail_en"],
                detail_bn=f["detail_bn"],
                conflicts_document_id=await _resolve_document_public_id(
                    documents, user["id"], f.get("conflicts_document_id")
                ),
                suggestion_en=f.get("suggestion_en"),
                suggestion_bn=f.get("suggestion_bn"),
            )
        )
    return Page(items=items, next_cursor=None, total=len(items))


# --- Dalil: contract auditor ----------------------------------------------


@router.post("/contracts", response_model=AgentAcceptedResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_contract(
    body: ContractCreate,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
) -> AgentAcceptedResponse:
    contract = await vault.create_contract(user["id"], body.document_id)
    return AgentAcceptedResponse(id=contract["public_id"])


@router.get("/contracts/{contract_id}", response_model=ContractOut)
async def get_contract(
    contract_id: str,
    user: Mapping = Depends(get_current_user),
    vault: VaultService = Depends(get_vault_service),
    documents: DocumentRepo = Depends(get_document_repo),
) -> ContractOut:
    contract = await vault.get_contract(user["id"], contract_id)
    clauses = [ContractClauseOut(**c) for c in contract["clauses"]]
    return ContractOut(
        id=contract["public_id"],
        document_id=await _resolve_document_public_id(documents, user["id"], contract.get("document_id"))
        or "",
        consultancy=contract.get("consultancy"),
        risk_overall=contract.get("risk_overall"),
        clauses=clauses,
        analysed_at=contract["analysed_at"],
    )
