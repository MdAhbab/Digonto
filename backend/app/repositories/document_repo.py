"""Vault documents, and the three new agents that operate on documents and
statements: Bicharok (rejection autopsy), Lekhok (statement forensics), and
Dalil (contract auditor).

Tables: `documents`, `document_fields` (section 3.6); `rejection_cases`,
`rejection_grounds`, `statements`, `statement_findings`, `contracts`,
`contract_clauses` (section 3.9) — all in `app.db`.

`document_fields.value_enc` is never selected by name here in a way that
leaves this file; the one method that reads it (`get_field_values_for_hash_compare`)
returns only `value_hash`, which is the whole point of that column (compare
without decrypting). No method in this repository returns `value_enc`.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import Database
from app.repositories._util import new_ulid, utc_now_iso


class DocumentRepo:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- documents -----------------------------------------------------

    async def create(
        self,
        *,
        user_id: int,
        kind: str,
        original_name: str,
        storage_path: str,
        mime_type: str,
        byte_size: int,
        sha256: str,
        wrapped_dek: bytes,
        nonce: bytes,
        expires_on: str | None,
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO documents
               (public_id, user_id, kind, original_name, storage_path, mime_type,
                byte_size, sha256, wrapped_dek, nonce, expires_on, status, uploaded_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'scanning', ?)""",
            (public_id, user_id, kind, original_name, storage_path, mime_type,
             byte_size, sha256, wrapped_dek, nonce, expires_on, now),
        )
        row = await self._db.fetch_one("SELECT * FROM documents WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def list_for_user(self, user_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT * FROM documents WHERE user_id = ? AND deleted_at IS NULL
               ORDER BY uploaded_at DESC""",
            (user_id,),
        )
        return [dict(r) for r in rows]

    async def get_by_public_id(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            """SELECT * FROM documents WHERE user_id = ? AND public_id = ?
               AND deleted_at IS NULL""",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def get_any_by_public_id(self, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM documents WHERE public_id = ? AND deleted_at IS NULL", (public_id,)
        )
        return dict(row) if row else None

    async def set_status(self, document_id: int, status: str, error: str | None = None) -> None:
        await self._db.execute(
            "UPDATE documents SET status = ? WHERE id = ?", (status, document_id)
        )

    async def soft_delete(self, document_id: int) -> None:
        await self._db.execute(
            "UPDATE documents SET deleted_at = ? WHERE id = ?", (utc_now_iso(), document_id)
        )

    async def count_expiring_before(self, user_id: int, before_date: str) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            """SELECT * FROM documents WHERE user_id = ? AND deleted_at IS NULL
               AND expires_on IS NOT NULL AND expires_on <= ?""",
            (user_id, before_date),
        )
        return [dict(r) for r in rows]

    async def count_for_user(self, user_id: int) -> int:
        val = await self._db.fetch_val(
            "SELECT COUNT(*) FROM documents WHERE user_id = ? AND deleted_at IS NULL",
            (user_id,),
        )
        return int(val or 0)

    # -- document fields (never expose value_enc outside this module) ------

    async def upsert_field(
        self,
        *,
        document_id: int,
        field_key: str,
        value_enc: bytes,
        value_hash: str,
        confidence: float | None,
        page_no: int | None,
    ) -> None:
        now = utc_now_iso()
        await self._db.execute(
            """INSERT INTO document_fields
               (document_id, field_key, value_enc, value_hash, confidence, page_no, extracted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (document_id, field_key) DO UPDATE SET
                 value_enc = excluded.value_enc, value_hash = excluded.value_hash,
                 confidence = excluded.confidence, page_no = excluded.page_no,
                 extracted_at = excluded.extracted_at""",
            (document_id, field_key, value_enc, value_hash, confidence, page_no, now),
        )

    async def get_field_hashes(self, document_id: int) -> dict[str, str]:
        """Field key to `value_hash` only, for cross-document comparison
        without decrypting. Never returns `value_enc`.
        """

        rows = await self._db.fetch_all(
            "SELECT field_key, value_hash FROM document_fields WHERE document_id = ?",
            (document_id,),
        )
        return {r["field_key"]: r["value_hash"] for r in rows}

    async def get_field_encrypted(self, document_id: int, field_key: str) -> bytes | None:
        """The one path that returns `value_enc`. Callers must hold the
        user's own vault key; nothing in the moderator surface calls this.
        """

        val = await self._db.fetch_val(
            "SELECT value_enc FROM document_fields WHERE document_id = ? AND field_key = ?",
            (document_id, field_key),
        )
        return val

    # -- rejection cases (Bicharok) ------------------------------------------

    async def create_rejection_case(self, user_id: int, document_id: int) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO rejection_cases (public_id, user_id, document_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (public_id, user_id, document_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM rejection_cases WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_rejection_case(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM rejection_cases WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def set_rejection_summary(
        self, case_id: int, *, summary_en: str, summary_bn: str,
        country_code: str | None, visa_type: str | None, reapply_ready_at: str | None,
    ) -> None:
        await self._db.execute(
            """UPDATE rejection_cases SET summary_en = ?, summary_bn = ?, country_code = ?,
               visa_type = ?, reapply_ready_at = ? WHERE id = ?""",
            (summary_en, summary_bn, country_code, visa_type, reapply_ready_at, case_id),
        )

    async def add_rejection_ground(
        self,
        case_id: int,
        *,
        code: str | None,
        quoted_text: str,
        meaning_en: str,
        meaning_bn: str,
        remedy_en: str,
        remedy_bn: str,
        remediable: str,
        snapshot_id: int | None,
        linked_step_key: str | None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO rejection_grounds
               (case_id, code, quoted_text, meaning_en, meaning_bn, remedy_en, remedy_bn,
                remediable, snapshot_id, linked_step_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (case_id, code, quoted_text, meaning_en, meaning_bn, remedy_en, remedy_bn,
             remediable, snapshot_id, linked_step_key),
        )

    async def list_rejection_grounds(self, case_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM rejection_grounds WHERE case_id = ?", (case_id,)
        )
        return [dict(r) for r in rows]

    # -- statements (Lekhok) --------------------------------------------------

    async def create_statement(
        self, user_id: int, target_id: int | None, kind: str, body: str
    ) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO statements (public_id, user_id, target_id, kind, body,
               version, word_count, created_at)
               VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
            (public_id, user_id, target_id, kind, body, len(body.split()), now),
        )
        row = await self._db.fetch_one("SELECT * FROM statements WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_statement(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM statements WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def add_statement_finding(
        self,
        statement_id: int,
        *,
        severity: str,
        kind: str,
        excerpt: str,
        detail_en: str,
        detail_bn: str,
        conflicts_document_id: int | None,
        suggestion_en: str | None,
        suggestion_bn: str | None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO statement_findings
               (statement_id, severity, kind, excerpt, detail_en, detail_bn,
                conflicts_document_id, suggestion_en, suggestion_bn)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (statement_id, severity, kind, excerpt, detail_en, detail_bn,
             conflicts_document_id, suggestion_en, suggestion_bn),
        )

    async def list_statement_findings(self, statement_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM statement_findings WHERE statement_id = ?", (statement_id,)
        )
        return [dict(r) for r in rows]

    # -- contracts (Dalil) -----------------------------------------------------

    async def create_contract(self, user_id: int, document_id: int) -> dict[str, Any]:
        public_id = new_ulid()
        now = utc_now_iso()
        row_id = await self._db.execute(
            """INSERT INTO contracts (public_id, user_id, document_id, analysed_at)
               VALUES (?, ?, ?, ?)""",
            (public_id, user_id, document_id, now),
        )
        row = await self._db.fetch_one("SELECT * FROM contracts WHERE id = ?", (row_id,))
        assert row is not None
        return dict(row)

    async def get_contract(self, user_id: int, public_id: str) -> dict[str, Any] | None:
        row = await self._db.fetch_one(
            "SELECT * FROM contracts WHERE user_id = ? AND public_id = ?",
            (user_id, public_id),
        )
        return dict(row) if row else None

    async def set_contract_risk(self, contract_id: int, risk_overall: str) -> None:
        await self._db.execute(
            "UPDATE contracts SET risk_overall = ? WHERE id = ?", (risk_overall, contract_id)
        )

    async def add_contract_clause(
        self,
        contract_id: int,
        *,
        quoted_text: str,
        category: str,
        risk: str,
        why_en: str,
        why_bn: str,
        fair_alternative_en: str | None,
        fair_alternative_bn: str | None,
    ) -> None:
        await self._db.execute(
            """INSERT INTO contract_clauses
               (contract_id, quoted_text, category, risk, why_en, why_bn,
                fair_alternative_en, fair_alternative_bn)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (contract_id, quoted_text, category, risk, why_en, why_bn,
             fair_alternative_en, fair_alternative_bn),
        )

    async def list_contract_clauses(self, contract_id: int) -> list[dict[str, Any]]:
        rows = await self._db.fetch_all(
            "SELECT * FROM contract_clauses WHERE contract_id = ?", (contract_id,)
        )
        return [dict(r) for r in rows]
