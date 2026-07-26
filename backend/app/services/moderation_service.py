"""The moderator console. api_contract.md section 11a.

Every method that reads student-linked data writes a `moderation_views` row
(see `ModerationRepo.record_view`) and every action that changes state
writes a `moderation_actions` row before returning, because "an immutable
event" and "the student can see this in their own account" are both
requirements from the contract, not just from a database constraint.
"""

from __future__ import annotations

from app.errors import Conflict, NotFound
from app.events.bus import EventBus, EventType
from app.repositories.moderation_repo import ModerationRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.snapshot_repo import SnapshotRepo
from app.repositories.answer_repo import AnswerRepo
from app.repositories.user_repo import UserRepo


class ModerationService:
    def __init__(
        self,
        moderation: ModerationRepo,
        snapshots: SnapshotRepo,
        answers: AnswerRepo,
        portals: PortalRepo,
        scholarships: ScholarshipRepo,
        users: UserRepo,
        bus: EventBus,
    ) -> None:
        self._mod = moderation
        self._snapshots = snapshots
        self._answers = answers
        self._portals = portals
        self._scholarships = scholarships
        self._users = users
        self._bus = bus

    # -- change review queue ----------------------------------------------

    async def list_pending_changes(self, cursor: str | None) -> tuple[list[dict], str | None]:
        rows, next_cursor = await self._snapshots.list_pending_review(cursor=cursor)
        return [
            {
                "id": str(r["id"]),
                "portal_id": r["portal_public_id"],
                "portal_label": r["portal_label"],
                "change_type": r["change_type"],
                "old_text": r["old_text"],
                "new_text": r["new_text"],
                "from_snapshot_id": r["from_snapshot_public_id"],
                "to_snapshot_id": r["to_snapshot_public_id"],
                "proposed_category": r["category"],
                "confidence": r["category_confidence"],
                "created_at": r["created_at"],
            }
            for r in rows
        ], next_cursor

    async def approve_change(self, moderator_id: int, diff_id: str, category: str, notify: bool) -> None:
        diff = await self._snapshots.get_diff_by_public_id_or_id(diff_id)
        if diff is None:
            raise NotFound(detail_en="Change not found.", detail_bn="পরিবর্তনটি পাওয়া যায়নি।")
        await self._snapshots.approve_diff(diff["id"], category)
        await self._mod.record_action(
            moderator_id=moderator_id, action="change_approve", subject_type="passage_diff",
            subject_id=diff_id, reason_en=None, reason_bn=None,
            detail={"category": category, "notify": notify},
        )
        if notify:
            await self._bus.publish(
                EventType.PORTAL_CHANGED,
                user_id=None,
                subject_type="passage_diff",
                subject_id=diff_id,
                payload={"category": category},
            )

    async def reclassify_change(self, moderator_id: int, diff_id: str, category: str, reason: str) -> None:
        diff = await self._snapshots.get_diff_by_public_id_or_id(diff_id)
        if diff is None:
            raise NotFound(detail_en="Change not found.", detail_bn="পরিবর্তনটি পাওয়া যায়নি।")
        await self._snapshots.reclassify_diff(diff["id"], category)
        await self._mod.record_action(
            moderator_id=moderator_id, action="change_reclassify", subject_type="passage_diff",
            subject_id=diff_id, reason_en=reason, reason_bn=reason,
            detail={"category": category},
        )

    async def discard_change(self, moderator_id: int, diff_id: str, reason: str) -> None:
        diff = await self._snapshots.get_diff_by_public_id_or_id(diff_id)
        if diff is None:
            raise NotFound(detail_en="Change not found.", detail_bn="পরিবর্তনটি পাওয়া যায়নি।")
        await self._snapshots.discard_diff(diff["id"])
        await self._mod.record_action(
            moderator_id=moderator_id, action="change_discard", subject_type="passage_diff",
            subject_id=diff_id, reason_en=reason, reason_bn=reason,
        )

    # -- answer review and refusal triage ------------------------------------

    async def list_answers_for_review(self, filter_: str, cursor: str | None) -> tuple[list[dict], str | None]:
        rows, next_cursor = await self._answers.list_for_review(filter_=filter_, cursor=cursor)
        return [
            {
                "id": r["public_id"],
                "question_text": r["text_raw"],
                "answer_en": r["answer_en"],
                "answer_bn": r["answer_bn"],
                "confidence": r["confidence"],
                "is_refusal": bool(r["is_refusal"]),
                "rating": r["rating"],
                "reviewer_verified": bool(r["reviewer_verified"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ], next_cursor

    async def verify_answer(self, moderator_id: int, answer_public_id: str) -> None:
        answer = await self._answers.get_answer_by_public_id(answer_public_id)
        if answer is None:
            raise NotFound(detail_en="Answer not found.", detail_bn="উত্তরটি পাওয়া যায়নি।")
        await self._answers.mark_verified(answer["id"], None)
        await self._mod.record_action(
            moderator_id=moderator_id, action="answer_verify", subject_type="answer",
            subject_id=answer_public_id, reason_en=None, reason_bn=None,
        )

    async def correct_answer(
        self, moderator_id: int, answer_public_id: str, correction_bn: str, correction_en: str,
        note: str | None,
    ) -> None:
        answer = await self._answers.get_answer_by_public_id(answer_public_id)
        if answer is None:
            raise NotFound(detail_en="Answer not found.", detail_bn="উত্তরটি পাওয়া যায়নি।")
        await self._answers.write_correction(
            answer["id"], correction_en=correction_en, correction_bn=correction_bn, note=note
        )
        await self._mod.record_action(
            moderator_id=moderator_id, action="answer_correct", subject_type="answer",
            subject_id=answer_public_id, reason_en=note, reason_bn=note,
            detail={"correction_en": correction_en, "correction_bn": correction_bn},
        )
        await self._bus.publish(
            EventType.ANSWER_CORRECTED,
            user_id=None,
            subject_type="answer",
            subject_id=answer_public_id,
            payload={},
        )

    async def list_refusal_clusters(self, cursor: str | None) -> tuple[list[dict], str | None]:
        rows, next_cursor = await self._answers.list_refusal_clusters(cursor=cursor)
        return [
            {
                "cluster_id": str(r["cluster_ordinal"]),
                "sample_question": r["sample_question"],
                "count": r["cnt"],
                "country_filter": r["country_filter"],
                "last_asked_at": r["last_asked_at"],
            }
            for r in rows
        ], next_cursor

    async def add_portal_from_refusal(
        self, moderator_id: int, cluster_id: str, url: str, kind: str, country: str | None
    ) -> dict:
        label = url.replace("https://", "").replace("http://", "").split("/")[0]
        portal = await self._portals.create(
            url=url, kind=kind, country_code=country, label=label,
            parser_key="generic", crawl_cron="0 */6 * * *",
        )
        await self._mod.record_action(
            moderator_id=moderator_id, action="portal_add", subject_type="portal",
            subject_id=portal["public_id"], reason_en=f"Added from refusal cluster {cluster_id}",
            reason_bn=f"রিফিউজাল ক্লাস্টার {cluster_id} থেকে যোগ করা হয়েছে",
        )
        return portal

    # -- source and funding verification --------------------------------------

    async def list_portals(self) -> list[dict]:
        return await self._portals.list_all()

    async def create_portal(self, moderator_id: int, **fields) -> dict:
        portal = await self._portals.create(**fields)
        await self._mod.record_action(
            moderator_id=moderator_id, action="portal_add", subject_type="portal",
            subject_id=portal["public_id"], reason_en=None, reason_bn=None,
        )
        return portal

    async def patch_portal(self, moderator_id: int, portal_public_id: str, fields: dict) -> dict:
        portal = await self._portals.get_by_public_id(portal_public_id)
        if portal is None:
            raise NotFound(detail_en="Portal not found.", detail_bn="পোর্টালটি পাওয়া যায়নি।")
        clean = {k: v for k, v in fields.items() if v is not None}
        await self._portals.patch(portal["id"], clean)
        await self._mod.record_action(
            moderator_id=moderator_id, action="portal_pause", subject_type="portal",
            subject_id=portal_public_id, reason_en=None, reason_bn=None, detail=clean,
        )
        return await self._portals.get_by_public_id(portal_public_id)

    async def list_unverified_scholarships(self, cursor: str | None) -> tuple[list[dict], str | None]:
        return await self._scholarships.list_unverified(cursor=cursor)

    async def verify_scholarship(
        self, moderator_id: int, scholarship_public_id: str, verified: bool, note: str | None
    ) -> None:
        scholarship = await self._scholarships.get_by_public_id(scholarship_public_id)
        if scholarship is None:
            raise NotFound(detail_en="Scholarship not found.", detail_bn="বৃত্তিটি পাওয়া যায়নি।")
        await self._scholarships.set_verified(scholarship["id"], verified)
        await self._mod.record_action(
            moderator_id=moderator_id, action="scholarship_verify", subject_type="scholarship",
            subject_id=scholarship_public_id, reason_en=note, reason_bn=note,
            detail={"verified": verified},
        )

    # -- people --------------------------------------------------------------

    async def list_users(self, *, status: str | None, q: str | None, cursor: str | None) -> tuple[list[dict], str | None]:
        return await self._mod.list_users(status=status, q=q, cursor=cursor)

    async def get_user(self, moderator_id: int, user_public_id: str) -> dict:
        user = await self._users.get_by_public_id(user_public_id)
        if user is None:
            raise NotFound(detail_en="User not found.", detail_bn="ব্যবহারকারী পাওয়া যায়নি।")
        detail = await self._mod.get_user_detail(user["id"])
        assert detail is not None
        await self._mod.record_view(
            moderator_id=moderator_id, user_id=user["id"], scope="profile", subject_id=None
        )
        history = await self._mod.list_actions_for_subject("user", user_public_id)
        return {**detail, "moderation_history": history}

    async def suspend_user(
        self, moderator_id: int, user_public_id: str, reason_en: str, reason_bn: str, until: str
    ) -> None:
        user = await self._users.get_by_public_id(user_public_id)
        if user is None:
            raise NotFound(detail_en="User not found.", detail_bn="ব্যবহারকারী পাওয়া যায়নি।")
        await self._users.set_status(
            user["id"], status="suspended", reason_en=reason_en, reason_bn=reason_bn,
            suspended_until=until,
        )
        await self._mod.record_action(
            moderator_id=moderator_id, action="suspend", subject_type="user",
            subject_id=user_public_id, reason_en=reason_en, reason_bn=reason_bn,
            detail={"until": until},
        )
        await self._bus.publish(
            EventType.USER_SUSPENDED, user_id=user["id"], subject_type="user",
            subject_id=user_public_id, payload={"until": until},
        )

    async def ban_user(self, moderator_id: int, user_public_id: str, reason_en: str, reason_bn: str) -> None:
        user = await self._users.get_by_public_id(user_public_id)
        if user is None:
            raise NotFound(detail_en="User not found.", detail_bn="ব্যবহারকারী পাওয়া যায়নি।")
        await self._users.set_status(user["id"], status="banned", reason_en=reason_en, reason_bn=reason_bn)
        await self._mod.record_action(
            moderator_id=moderator_id, action="ban", subject_type="user",
            subject_id=user_public_id, reason_en=reason_en, reason_bn=reason_bn,
        )
        await self._bus.publish(
            EventType.USER_BANNED, user_id=user["id"], subject_type="user",
            subject_id=user_public_id, payload={},
        )

    async def reinstate_user(self, moderator_id: int, user_public_id: str, note: str | None) -> None:
        user = await self._users.get_by_public_id(user_public_id)
        if user is None:
            raise NotFound(detail_en="User not found.", detail_bn="ব্যবহারকারী পাওয়া যায়নি।")
        await self._users.set_status(user["id"], status="active")
        await self._mod.record_action(
            moderator_id=moderator_id, action="reinstate", subject_type="user",
            subject_id=user_public_id, reason_en=note, reason_bn=note,
        )
        await self._bus.publish(
            EventType.USER_REINSTATED, user_id=user["id"], subject_type="user",
            subject_id=user_public_id, payload={},
        )

    async def list_reports(self) -> list[dict]:
        return await self._mod.list_reports()

    # -- model oversight -------------------------------------------------

    async def list_adapters(self) -> list[dict]:
        return await self._mod.list_adapters()

    async def promote_adapter(self, moderator_id: int, adapter_tag: str) -> None:
        adapter = await self._mod.get_adapter_by_tag(adapter_tag)
        if adapter is None:
            raise NotFound(detail_en="Adapter not found.", detail_bn="অ্যাডাপ্টারটি পাওয়া যায়নি।")
        if adapter["status"] != "candidate":
            raise Conflict(
                detail_en="Only a candidate adapter can be promoted.",
                detail_bn="শুধু প্রার্থী অ্যাডাপ্টার প্রমোট করা যায়।",
            )
        await self._mod.promote_adapter(adapter["id"])
        await self._mod.record_action(
            moderator_id=moderator_id, action="adapter_promote", subject_type="adapter",
            subject_id=adapter_tag, reason_en=None, reason_bn=None,
        )
        await self._bus.publish(
            EventType.ADAPTER_PROMOTED, user_id=None, subject_type="adapter",
            subject_id=adapter_tag, payload={},
        )

    async def rollback_adapter(self, moderator_id: int, adapter_tag: str, reason: str) -> None:
        adapter = await self._mod.get_adapter_by_tag(adapter_tag)
        if adapter is None:
            raise NotFound(detail_en="Adapter not found.", detail_bn="অ্যাডাপ্টারটি পাওয়া যায়নি।")
        await self._mod.rollback_adapter(adapter["id"], reason)
        await self._mod.record_action(
            moderator_id=moderator_id, action="adapter_rollback", subject_type="adapter",
            subject_id=adapter_tag, reason_en=reason, reason_bn=reason,
        )
        await self._bus.publish(
            EventType.ADAPTER_ROLLED_BACK, user_id=None, subject_type="adapter",
            subject_id=adapter_tag, payload={"reason": reason},
        )

    async def get_health(self) -> dict:
        pending_changes = await self._snapshots.count_pending_review()
        crawl_failures = await self._mod.count_crawl_failures(48)
        dead_letters = await self._mod.count_dead_letters()
        queue_depth = await self._mod.queue_depth_agent()
        p50, p95 = await self._mod.model_latency_percentiles()
        return {
            "pending_changes": pending_changes,
            "crawl_failures_48h": crawl_failures,
            "dead_letters": dead_letters,
            "model_latency_p50_ms": p50,
            "model_latency_p95_ms": p95,
            "queue_depth_agent": queue_depth,
        }

    async def get_overview(self) -> dict:
        return {
            "pending_changes": await self._snapshots.count_pending_review(),
            "escalated_answers": await self._answers.count_escalated(),
            "unverified_scholarships": len((await self._scholarships.list_unverified(cursor=None))[0]),
            "silent_portals": await self._portals.count_silent(48),
            "dead_letters": await self._mod.count_dead_letters(),
            "adapters_awaiting_promotion": await self._mod.count_adapters_awaiting_promotion(),
            "new_users_today": await self._mod.new_users_today(),
        }
