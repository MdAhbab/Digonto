"""`digonto-vault-mcp`: Prohori's document tools, over stdio.

Backs Prohori (agents.md, Agent 2) and the vision-extraction step Bicharok and
Dalil also reuse. Every tool calls into `app.services.vault_service.VaultService`
for anything already scoped to a user's own documents, `app.repositories.document_repo`
for the field-level reads/writes that service does not expose (all of which
are already designed, in that repository, to never return `value_enc`), and
`app.repositories.audit_repo` for the one annotation write. Nothing here
issues its own SQL, and nothing here decrypts a field value and then hands it
back to the caller.

SECURITY, non-negotiable (see agents.md, Agent 2's "Safety" note and
docs/database.md section 3.6 on `document_fields.value_hash`): this server
must never return decrypted document bytes or a decrypted field value to an
MCP caller.

  - `read_doc_metadata` returns exactly the fields of
    `app.models.vault.DocumentDetail` (kind, name, mime type, size, dates,
    status) and nothing from `documents.storage_path`, `.wrapped_dek`, or
    `.nonce`.
  - `extract_fields` decrypts the document *internally*, in this process, to
    run the vision pass and to persist each field encrypted under the
    document's own key (exactly as `app.security.vault_crypto` is designed
    for), but the tool's return value carries only `field_key`, `confidence`,
    `page_no`, and `value_hash` per field, in that order of trust: enough for
    a caller to say "the surname on this passport does not match the
    surname on that bank statement" without ever seeing either surname.
  - There is deliberately no `delete_document` tool here (agents.md: "no
    delete tool exists, by design"). `flag_document` only adds an
    `audit_findings` annotation; it never touches `documents.storage_path`,
    `.wrapped_dek`, `.nonce`, or the row's `deleted_at`.

Tools:
  - list_documents(user_id)
  - read_doc_metadata(user_id, document_id)
  - extract_fields(user_id, document_id)
  - flag_document(user_id, document_id, code, severity, title_en, title_bn,
                  detail_en, detail_bn, evidence=None, action_en=None, action_bn=None)

Run standalone: `python -m app.mcp.vault_server` (from `backend/`). See
`app/mcp/README.md` for MCP client registration.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from app.agents.runtime import AgentCall, structured
from app.errors import NotFound
from app.events.bus import EventType
from app.llm.router import TaskKind
from app.mcp._common import AppContext, app_context, build_dispatcher, configure_stdio_logging
from app.security.vault_crypto import (
    decrypt_bytes,
    encrypt_field,
    normalised_value_hash,
    unwrap_dek,
)

log = logging.getLogger(__name__)

SERVER_NAME = "digonto-vault-mcp"

# Native image types the served model's vision pass can read directly. A PDF
# is accepted into the vault (app/services/vault_service.py's _ACCEPTED_MIME)
# but there is no page-rasterisation step anywhere in this codebase to turn a
# PDF page into an image first, so extraction over a PDF degrades honestly
# instead of guessing.
_VISION_MIME_TYPES = {"image/jpeg", "image/png", "image/heic"}

_EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field_key": {
                        "type": "string",
                        "description": "snake_case field name, e.g. 'surname', 'passport_no', 'balance'.",
                    },
                    "value": {"type": "string", "description": "The field's value, exactly as printed."},
                    "confidence": {"type": "number", "description": "0 to 1."},
                    "page_no": {"type": ["integer", "null"]},
                },
                "required": ["field_key", "value", "confidence"],
            },
        }
    },
    "required": ["fields"],
}

_EXTRACT_SYSTEM = (
    "You read one page image of a student's own document (passport, "
    "transcript, bank statement, solvency letter, English test result, "
    "visa refusal letter, or consultancy contract) and extract the salient "
    "fields as key/value pairs: identity fields (surname, given_name, "
    "date_of_birth, passport_no, nationality), financial fields (balance, "
    "currency, statement_date), or document-specific fields (issue_date, "
    "expiry_date, score, clause_text). Only report a field you can actually "
    "read; give it a lower confidence rather than guessing, and never invent "
    "a value that is not visible in the image."
)


# --- tool handlers ------------------------------------------------------


async def _require_user(ctx: AppContext, user_public_id: str) -> dict[str, Any]:
    user = await ctx.users.get_by_public_id(user_public_id)
    if user is None:
        raise NotFound(detail_en="No user with that user_id.", detail_bn="এই আইডির কোনো ব্যবহারকারী নেই।")
    return user


async def _list_documents(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    documents = await ctx.vault.list_documents(user["id"])
    return {"documents": documents}


def _metadata_only(doc: dict[str, Any]) -> dict[str, Any]:
    """Project a `documents` row onto exactly `app.models.vault.DocumentDetail`.

    Deliberately built as an explicit allow-list, not `dict(doc)` minus some
    keys: an allow-list stays correct if a future migration adds a new
    sensitive column to `documents`, where a deny-list would silently start
    leaking it.
    """
    return {
        "id": doc["public_id"],
        "kind": doc["kind"],
        "original_name": doc["original_name"],
        "mime_type": doc["mime_type"],
        "byte_size": doc["byte_size"],
        "page_count": doc.get("page_count"),
        "issued_on": doc.get("issued_on"),
        "expires_on": doc.get("expires_on"),
        "status": doc["status"],
        "uploaded_at": doc["uploaded_at"],
    }


async def _read_doc_metadata(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    doc = await ctx.vault.get_document(user["id"], args["document_id"])
    return _metadata_only(doc)


async def _extract_fields(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    doc = await ctx.vault.get_document(user["id"], args["document_id"])

    if doc["mime_type"] not in _VISION_MIME_TYPES:
        hashes = await ctx.documents.get_field_hashes(doc["id"])
        return {
            "document_id": doc["public_id"],
            "fields": [{"field_key": k, "value_hash": v} for k, v in hashes.items()],
            "note": (
                f"Automatic vision extraction only runs over {sorted(_VISION_MIME_TYPES)} "
                f"today; this document is {doc['mime_type']}. Returning previously "
                "extracted fields, if any."
            ),
        }

    dek = unwrap_dek(doc["wrapped_dek"], user_id=doc["user_id"], settings=ctx.settings)
    ciphertext = Path(doc["storage_path"]).read_bytes()
    plaintext = decrypt_bytes(ciphertext, dek, doc["nonce"])

    try:
        data = await structured(
            ctx.router,
            AgentCall(
                kind=TaskKind.VISION_EXTRACT,
                system=_EXTRACT_SYSTEM,
                user=f"Document kind: {doc['kind']}. Extract every field you can read.",
                schema=_EXTRACT_SCHEMA,
                images=[plaintext],
                # This prompt IS the document. It must never be eligible for a
                # remote provider; app/llm/router.py raises rather than route
                # a request with either flag set off-machine.
                contains_user_documents=True,
            ),
        )
    except Exception as exc:  # noqa: BLE001 - degrade, never crash the tool call
        log.warning("vault extract_fields: vision pass failed doc=%s err=%s", doc["public_id"], exc)
        hashes = await ctx.documents.get_field_hashes(doc["id"])
        return {
            "document_id": doc["public_id"],
            "fields": [{"field_key": k, "value_hash": v} for k, v in hashes.items()],
            "note": f"Extraction unavailable right now ({exc}); returning previously stored fields, if any.",
        }

    out_fields: list[dict[str, Any]] = []
    for item in data.get("fields", []):
        field_key = item.get("field_key")
        value = item.get("value")
        if not field_key or value is None:
            continue
        value_hash = normalised_value_hash(str(value))
        value_enc = encrypt_field(str(value), dek)
        confidence = item.get("confidence")
        page_no = item.get("page_no")
        await ctx.documents.upsert_field(
            document_id=doc["id"],
            field_key=field_key,
            value_enc=value_enc,
            value_hash=value_hash,
            confidence=confidence,
            page_no=page_no,
        )
        # Never add "value" here. This is the one place in the process that
        # ever holds the plaintext, and the boundary of this function is the
        # boundary of that fact.
        out_fields.append(
            {"field_key": field_key, "confidence": confidence, "page_no": page_no, "value_hash": value_hash}
        )

    return {"document_id": doc["public_id"], "fields": out_fields}


async def _flag_document(ctx: AppContext, args: dict[str, Any]) -> dict[str, Any]:
    user = await _require_user(ctx, args["user_id"])
    doc = await ctx.vault.get_document(user["id"], args["document_id"])

    audit = await ctx.audits.create(user["id"], None)
    await ctx.audits.set_status(audit["id"], "complete")
    await ctx.audits.add_finding(
        audit["id"],
        document_id=doc["id"],
        code=args["code"],
        severity=args["severity"],
        title_en=args["title_en"],
        title_bn=args["title_bn"],
        detail_en=args["detail_en"],
        detail_bn=args["detail_bn"],
        evidence=args.get("evidence"),
        action_en=args.get("action_en"),
        action_bn=args.get("action_bn"),
        snapshot_id=None,
    )
    findings = await ctx.audits.list_findings(audit["id"])
    await ctx.bus.publish(
        EventType.AUDIT_UPDATED,
        user_id=user["id"],
        subject_type="audit",
        subject_id=audit["public_id"],
        payload={"document_id": doc["public_id"], "code": args["code"]},
        actor="mcp:digonto-vault-mcp",
    )
    return {"audit_id": audit["public_id"], "finding": findings[0] if findings else None}


_HANDLERS = {
    "list_documents": _list_documents,
    "read_doc_metadata": _read_doc_metadata,
    "extract_fields": _extract_fields,
    "flag_document": _flag_document,
}


# --- tool schemas ---------------------------------------------------------

_TOOLS = [
    types.Tool(
        name="list_documents",
        description=(
            "List a user's vault documents with their latest audit finding "
            "summary (kind, expiry countdown, severity). Never includes file "
            "content or extracted field values."
        ),
        inputSchema={
            "type": "object",
            "properties": {"user_id": {"type": "string", "description": "User public id."}},
            "required": ["user_id"],
        },
    ),
    types.Tool(
        name="read_doc_metadata",
        description=(
            "Read one document's metadata only: kind, original filename, mime "
            "type, byte size, page count, issue/expiry dates, status, upload "
            "time. Never returns file content, the encrypted key material, or "
            "any extracted field value."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User public id."},
                "document_id": {"type": "string", "description": "Document public id."},
            },
            "required": ["user_id", "document_id"],
        },
    ),
    types.Tool(
        name="extract_fields",
        description=(
            "Run (or re-run) the vision extraction pass over one document's "
            "image page(s) and persist each field encrypted under the "
            "document's own key. Returns field KEYS, confidences, page "
            "numbers, and a normalised comparison hash for each field, never "
            "the plaintext value. Use the returned value_hash to compare a "
            "field across two documents (e.g. surname on a passport vs. a "
            "bank statement) without ever decrypting either one."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User public id."},
                "document_id": {"type": "string", "description": "Document public id."},
            },
            "required": ["user_id", "document_id"],
        },
    ),
    types.Tool(
        name="flag_document",
        description=(
            "Annotate a document with a finding (code, severity, bilingual "
            "title/detail, optional evidence and suggested action). This is "
            "additive only: it writes an audit_findings row and never "
            "changes, re-encrypts, or deletes the document itself. There is "
            "no delete tool in this server, by design."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string", "description": "User public id."},
                "document_id": {"type": "string", "description": "Document public id."},
                "code": {"type": "string", "description": "Short machine code, e.g. 'NAME_MISMATCH'."},
                "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                "title_en": {"type": "string"},
                "title_bn": {"type": "string"},
                "detail_en": {"type": "string"},
                "detail_bn": {"type": "string"},
                "evidence": {"type": "object", "description": "Small JSON-serialisable evidence object."},
                "action_en": {"type": "string"},
                "action_bn": {"type": "string"},
            },
            "required": [
                "user_id", "document_id", "code", "severity",
                "title_en", "title_bn", "detail_en", "detail_bn",
            ],
        },
    ),
]


def build_server(ctx: AppContext) -> Server:
    server = Server(
        SERVER_NAME,
        version="1.0.0",
        instructions=(
            "Read-only over vault document metadata, plus one annotation "
            "write. Never returns decrypted file bytes or a decrypted field "
            "value under any tool; extract_fields returns field keys, "
            "confidences, and comparison hashes only. There is no delete tool."
        ),
    )

    @server.list_tools()
    async def _list_tools() -> list[types.Tool]:
        return _TOOLS

    dispatch = build_dispatcher(_HANDLERS, ctx)

    @server.call_tool()
    async def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return await dispatch(name, arguments)

    return server


async def main() -> None:
    configure_stdio_logging(SERVER_NAME)
    async with app_context() as ctx:
        server = build_server(ctx)
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
