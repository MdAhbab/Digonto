"""The Truth Ledger: public, no-auth verification. api_contract.md section 6."""

from __future__ import annotations

from app.errors import NotFound
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo


class LedgerService:
    def __init__(self, portals: PortalRepo, snapshots: SnapshotRepo) -> None:
        self._portals = portals
        self._snapshots = snapshots

    async def get_snapshot(self, public_id: str) -> dict:
        snap = await self._snapshots.get_by_public_id(public_id)
        if snap is None:
            raise NotFound(
                detail_en=f"No snapshot with ID '{public_id}'. Check the ID and try again.",
                detail_bn=f"'{public_id}' আইডির কোনো স্ন্যাপশট নেই। আইডিটি যাচাই করে আবার চেষ্টা করুন।",
            )
        passages = await self._snapshots.list_passages(snap["id"])
        quoted = passages[0]["text"][:280] if passages else None
        return {
            "id": snap["public_id"],
            "portal": snap["portal_label"],
            "portal_url": snap["portal_url"],
            "captured": snap["fetched_at"],
            "content_hash": snap["content_hash"],
            "http_status": snap["http_status"],
            "quoted": quoted,
            "retired": snap["retired_at"] is not None,
            "passages": [
                {"ordinal": p["ordinal"], "section_path": p["section_path"], "text": p["text"]}
                for p in passages
            ],
        }

    async def list_portals(self) -> list[dict]:
        return await self._portals.list_all()

    async def list_changes(
        self, *, portal_public_id: str | None, since: str | None, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        portal_id = None
        if portal_public_id:
            portal = await self._portals.get_by_public_id(portal_public_id)
            if portal is None:
                raise NotFound(
                    detail_en="Unknown portal.", detail_bn="অজানা পোর্টাল।"
                )
            portal_id = portal["id"]
        rows, next_cursor = await self._snapshots.list_changes(
            portal_id=portal_id, since=since, cursor=cursor
        )
        return [
            {
                "id": str(r["id"]),
                "portal_id": r["portal_public_id"],
                "change_type": r["change_type"],
                "category": r["category"],
                "category_confidence": r["category_confidence"],
                "old_text": r["old_text"],
                "new_text": r["new_text"],
                "created_at": r["created_at"],
            }
            for r in rows
        ], next_cursor
