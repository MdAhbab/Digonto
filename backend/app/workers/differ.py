"""Diff worker: consumes `portal.changed`, the recurrent loop's second stage.

Aligns the previous and new snapshot's passages by `SequenceMatcher` over
their `text_hash`es (cheap, exact-match alignment), classifies every real
change with Porter, and fans out three ways: `kb.chunk.updated` for the
embedding worker, a notification plus a `plan_changes` row for every
affected student, and a moderator review queue entry when Porter is not
confident enough to alert on its own (`passage_diffs.needs_review`).

Idempotency here does not lean on the event bus's `applied_events` ledger
alone: `_find_existing_diff` makes re-processing the same `portal.changed`
event (a redelivery, or a retried handler after a partial failure) a
no-op, because passage_diffs has no natural uniqueness constraint of its
own to fall back on.
"""

from __future__ import annotations

import difflib
import logging
import os
from typing import Any

from app.agents import porter
from app.db.connection import Databases
from app.events.bus import EventBus, EventStream, EventType
from app.llm.router import ModelRouter
from app.repositories._util import utc_now_iso
from app.repositories.notification_repo import NotificationRepo
from app.repositories.plan_repo import PlanRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo

log = logging.getLogger(__name__)

CONSUMER_GROUP = "differ"


def _align(
    old_passages: list[dict[str, Any]], new_passages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Pair up passages by content hash; `equal` runs need no diff row at all."""
    old_hashes = [p["text_hash"] for p in old_passages]
    new_hashes = [p["text_hash"] for p in new_passages]
    matcher = difflib.SequenceMatcher(a=old_hashes, b=new_hashes, autojunk=False)

    diffs: list[dict[str, Any]] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        if tag == "delete":
            for old in old_passages[i1:i2]:
                diffs.append({"change_type": "removed", "old": old, "new": None, "similarity": 0.0})
        elif tag == "insert":
            for new in new_passages[j1:j2]:
                diffs.append({"change_type": "added", "old": None, "new": new, "similarity": None})
        elif tag == "replace":
            old_slice = old_passages[i1:i2]
            new_slice = new_passages[j1:j2]
            paired = min(len(old_slice), len(new_slice))
            for k in range(paired):
                old, new = old_slice[k], new_slice[k]
                ratio = difflib.SequenceMatcher(a=old["text"], b=new["text"], autojunk=False).ratio()
                diffs.append({"change_type": "modified", "old": old, "new": new, "similarity": ratio})
            for old in old_slice[paired:]:
                diffs.append({"change_type": "removed", "old": old, "new": None, "similarity": 0.0})
            for new in new_slice[paired:]:
                diffs.append({"change_type": "added", "old": None, "new": new, "similarity": None})
    return diffs


async def _find_existing_diff(
    dbs: Databases,
    *,
    portal_id: int,
    from_snapshot_id: int,
    to_snapshot_id: int,
    change_type: str,
    old_id: int | None,
    new_id: int | None,
) -> int | None:
    row = await dbs.app.fetch_one(
        """SELECT id FROM passage_diffs
           WHERE portal_id = ? AND from_snapshot_id = ? AND to_snapshot_id = ?
             AND change_type = ? AND old_passage_id IS ? AND new_passage_id IS ?""",
        (portal_id, from_snapshot_id, to_snapshot_id, change_type, old_id, new_id),
    )
    return row["id"] if row else None


async def _handle_portal_changed(
    message: dict[str, Any], *, dbs: Databases, router: ModelRouter, bus: EventBus
) -> None:
    if message.get("type") != EventType.PORTAL_CHANGED.value:
        # This handler's consumer group is on the whole `ev:crawl` stream,
        # which also carries portal.fetched and portal.unreachable; there is
        # nothing for the diff worker to do with those, and returning
        # normally (rather than raising) is what marks them applied.
        return

    payload = message.get("payload") or {}
    portal_id = payload.get("portal_id")
    to_snapshot_id = payload.get("snapshot_id")
    previous_snapshot_id = payload.get("previous_snapshot_id")
    if portal_id is None or to_snapshot_id is None:
        log.warning("portal.changed event missing portal_id/snapshot_id: %s", payload)
        return

    snapshots = SnapshotRepo(dbs.app)
    portal = await PortalRepo(dbs.app).get(portal_id)
    to_snapshot = await snapshots.get(to_snapshot_id)
    if portal is None or to_snapshot is None:
        return

    new_passages = await snapshots.list_passages(to_snapshot_id)

    if previous_snapshot_id is None:
        # First-ever snapshot for this portal: there is nothing to diff
        # against, and passage_diffs.from_snapshot_id is NOT NULL, so there
        # is nowhere to record a "diff" even conceptually. Get the content
        # into the knowledge base; there is nothing to classify or alert on.
        for new in new_passages:
            await bus.publish(
                EventType.KB_CHUNK_UPDATED,
                payload={
                    "passage_id": new["id"],
                    "portal_id": portal_id,
                    "snapshot_id": to_snapshot_id,
                    "diff_id": None,
                    "change_type": "added",
                },
                actor="worker:differ",
                subject_type="passage",
                subject_id=str(new["id"]),
            )
        return

    old_passages = await snapshots.list_passages(previous_snapshot_id)
    diffs = _align(old_passages, new_passages)

    for d in diffs:
        await _process_one_diff(
            dbs=dbs,
            router=router,
            bus=bus,
            portal=portal,
            from_snapshot_id=previous_snapshot_id,
            to_snapshot=to_snapshot,
            diff=d,
        )


async def _process_one_diff(
    *,
    dbs: Databases,
    router: ModelRouter,
    bus: EventBus,
    portal: dict[str, Any],
    from_snapshot_id: int,
    to_snapshot: dict[str, Any],
    diff: dict[str, Any],
) -> None:
    old, new = diff["old"], diff["new"]
    old_id = old["id"] if old else None
    new_id = new["id"] if new else None
    portal_id = portal["id"]
    to_snapshot_id = to_snapshot["id"]

    existing_id = await _find_existing_diff(
        dbs,
        portal_id=portal_id,
        from_snapshot_id=from_snapshot_id,
        to_snapshot_id=to_snapshot_id,
        change_type=diff["change_type"],
        old_id=old_id,
        new_id=new_id,
    )
    if existing_id is not None:
        return  # a redelivered event already produced this row; do not re-notify

    # The model call happens before any write, and the write below is a
    # single statement, not a held transaction, so nothing here holds a DB
    # write transaction across the model call.
    result = await porter.classify_change(
        old_text=old["text"] if old else "",
        new_text=new["text"] if new else "",
        portal_label=portal["label"],
        router=router,
    )

    now = utc_now_iso()
    diff_id = await dbs.app.execute(
        """INSERT INTO passage_diffs
           (portal_id, from_snapshot_id, to_snapshot_id, change_type, old_passage_id,
            new_passage_id, similarity, category, category_confidence, classified_at,
            needs_review, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            portal_id,
            from_snapshot_id,
            to_snapshot_id,
            diff["change_type"],
            old_id,
            new_id,
            diff["similarity"],
            result["category"],
            result["confidence"],
            now,
            int(result["needs_review"]),
            now,
        ),
    )

    if new_id is not None:
        await bus.publish(
            EventType.KB_CHUNK_UPDATED,
            payload={
                "passage_id": new_id,
                "portal_id": portal_id,
                "snapshot_id": to_snapshot_id,
                "diff_id": diff_id,
                "change_type": diff["change_type"],
            },
            actor="worker:differ",
            subject_type="passage",
            subject_id=str(new_id),
        )

    if not result["notify"]:
        return

    alert = await porter.compose_alert(
        category=result["category"],
        old_text=old["text"] if old else "",
        new_text=new["text"] if new else "",
        portal_label=portal["label"],
        snapshot_public_id=to_snapshot["public_id"],
        student_context=None,
        router=router,
    )
    await _notify_affected_students(
        dbs=dbs, bus=bus, portal=portal, to_snapshot=to_snapshot, alert=alert,
        diff_id=diff_id, category=result["category"],
    )


async def _notify_affected_students(
    *,
    dbs: Databases,
    bus: EventBus,
    portal: dict[str, Any],
    to_snapshot: dict[str, Any],
    alert: dict[str, Any],
    diff_id: int,
    category: str,
) -> None:
    """Notify students whose shortlist references this exact institution
    (its `institution.portal_id` matches) plus anyone who has shortlisted
    the portal's country at all (an embassy/government portal is not tied
    to one institution, per docs/database.md section 3.3's `kind` values)."""
    rows = await dbs.app.fetch_all(
        """SELECT DISTINCT st.user_id
           FROM student_targets st
           JOIN programmes p ON p.id = st.programme_id
           JOIN institutions i ON i.id = p.institution_id
           WHERE i.portal_id = ?
              OR (? IS NOT NULL AND i.country_code = ?)""",
        (portal["id"], portal["country_code"], portal["country_code"]),
    )
    user_ids = [r["user_id"] for r in rows]
    if not user_ids:
        return

    notifications = NotificationRepo(dbs.app, dbs.events)
    plans = PlanRepo(dbs.app)

    for user_id in user_ids:
        user = await dbs.app.fetch_one(
            "SELECT id FROM users WHERE id = ? AND deleted_at IS NULL AND status = 'active'",
            (user_id,),
        )
        if user is None:
            continue

        await notifications.create(
            user_id=user_id,
            kind="portal_change",
            severity=alert["severity"],
            title_en=alert["title_en"],
            title_bn=alert["title_bn"],
            body_en=alert["body_en"],
            body_bn=alert["body_bn"],
            link_path=f"/ledger?snapshot={to_snapshot['public_id']}",
            snapshot_id=to_snapshot["id"],
        )

        # Only nudge a plan that already exists. Generating one from scratch
        # is the Visa Timeline Reactor's own baseline-building logic
        # (app/services/planner_service.py, not modified here); this worker
        # only appends the reactive change a real plan should show.
        plan = await plans.get_for_user_target(user_id, None)
        if plan is None:
            continue

        await plans.add_change(
            plan["id"],
            step_id=None,
            trigger="portal_change",
            text_en=f"{alert['title_en']}: {alert['body_en']}",
            text_bn=f"{alert['title_bn']}: {alert['body_bn']}",
            source_label=portal["label"],
            snapshot_id=to_snapshot["id"],
            event_id=None,
        )
        # Reuses PLAN_STEP_CHANGED (ev:user), the same event
        # app/services/planner_service.py emits for its own step/plan
        # mutations, rather than inventing a new type: it is what the
        # `/stream` SSE replay (NotificationRepo.events_since) and any
        # future timeline-reactor consumer already watch per-user for.
        await bus.publish(
            EventType.PLAN_STEP_CHANGED,
            payload={"action": "portal_change", "diff_id": diff_id, "category": category},
            actor="worker:differ",
            user_id=user_id,
            subject_type="plan",
            subject_id=plan["public_id"],
        )


async def consume(bus: EventBus, dbs: Databases, router: ModelRouter) -> None:
    consumer_name = f"{CONSUMER_GROUP}-{os.getpid()}"

    async def handler(message: dict[str, Any]) -> None:
        await _handle_portal_changed(message, dbs=dbs, router=router, bus=bus)

    await bus.consume(EventStream.CRAWL, CONSUMER_GROUP, consumer_name, handler)
