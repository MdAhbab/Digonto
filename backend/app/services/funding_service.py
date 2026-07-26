"""Funding Studio and Khoji. api_contract.md section 9.

`POST /funding/rematch` re-runs Khoji's eligibility scoring, which does not
exist in this codebase yet; this service calls
`app.agents.khoji.score_eligibility` and lets that import stay unresolved
rather than fabricate a score or a reason string. Every other read here
(the budget, the fee check) is real arithmetic over `budgets`, `fx_rates`,
and `solvency_rules`, none of which needs a model call.
"""

from __future__ import annotations

from app.agents.khoji import score_eligibility
from app.errors import NotFound
from app.events.bus import EventBus, EventType
from app.llm.router import ModelRouter
from app.repositories.budget_repo import BudgetRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.target_repo import TargetRepo

_SOURCE_LABELS_EN = {"own_funds": "Family / personal savings", "awards": "Scholarship awards"}
_SOURCE_LABELS_BN = {"own_funds": "পরিবার / ব্যক্তিগত সঞ্চয়", "awards": "বৃত্তির অর্থ"}


class FundingService:
    def __init__(
        self, scholarships: ScholarshipRepo, budgets: BudgetRepo, profiles: ProfileRepo,
        targets: TargetRepo, bus: EventBus, router: ModelRouter,
    ) -> None:
        self._scholarships = scholarships
        self._budgets = budgets
        self._profiles = profiles
        self._targets = targets
        self._bus = bus
        self._router = router

    # -- scholarships --------------------------------------------------

    async def list_scholarships(
        self, user_id: int, *, sort: str, order: str, country: str | None, cursor: str | None
    ) -> tuple[list[dict], str | None]:
        rows, next_cursor = await self._scholarships.list_matches_for_user(
            user_id, sort=sort, order=order, country=country, cursor=cursor
        )
        out = []
        for r in rows:
            reasons = await self._scholarships.list_reasons(r["id"])
            out.append(self._shape_match(r, reasons))
        return out, next_cursor

    def _shape_match(self, r: dict, reasons: list[dict]) -> dict:
        return {
            "id": r["scholarship_public_id"],
            "name": r["name"],
            "country": r["country_code"],
            "coverage": r["amount"],
            "deadline": r["deadline_at"],
            "score": r["score"],
            "rank": r["rank"],
            "eligible": bool(r["eligible"]),
            "verified": bool(r["verified"]),
            "reasons": [
                {
                    "criterion": rr["criterion_key"],
                    "met": bool(rr["met"]),
                    "reason_en": rr["reason_en"],
                    "reason_bn": rr["reason_bn"],
                }
                for rr in reasons
            ],
            "citation": {"snapshot_id": str(r["snapshot_id"])} if r.get("snapshot_id") else None,
        }

    async def get_scholarship(self, user_id: int, public_id: str) -> dict:
        match = await self._scholarships.get_match(user_id, public_id)
        if match is None:
            raise NotFound(
                detail_en="No match on record for that scholarship. Run a rematch first.",
                detail_bn="এই বৃত্তির জন্য কোনো মিল নেই। আগে রিম্যাচ চালান।",
            )
        reasons = await self._scholarships.list_reasons(match["id"])
        base = self._shape_match(match, reasons)
        return {
            **base,
            "provider": match["provider"],
            "coverage_type": match["coverage_type"],
            "amount": match["amount"],
            "currency": match["currency"],
            "url": match["url"],
        }

    async def rematch(self, user_id: int, user_public_id: str) -> list[dict]:
        profile = await self._profiles.get(user_id)
        if profile is None:
            raise NotFound(
                detail_en="Complete your profile before matching scholarships.",
                detail_bn="বৃত্তি মেলানোর আগে আপনার প্রোফাইল সম্পূর্ণ করুন।",
            )
        scholarships = await self._scholarships.list_active()
        scored = []
        for sc in scholarships:
            criteria = await self._scholarships.list_criteria(sc["id"])
            scored.append({**sc, "criteria": criteria})

        results = await score_eligibility(profile=profile, scholarships=scored, router=self._router)

        await self._scholarships.clear_matches_for_user(user_id)
        out = []
        for rank, result in enumerate(
            sorted(results, key=lambda r: r["score"], reverse=True), start=1
        ):
            match = await self._scholarships.create_match(
                user_id=user_id,
                scholarship_id=result["scholarship_id"],
                score=result["score"],
                rank=rank,
                eligible=result["eligible"],
                kb_version_id=result.get("kb_version_id"),
            )
            for reason in result.get("reasons", []):
                await self._scholarships.add_reason(
                    match["id"],
                    criterion_key=reason["criterion_key"],
                    met=reason["met"],
                    reason_en=reason["reason_en"],
                    reason_bn=reason["reason_bn"],
                    weight=reason.get("weight", 1.0),
                )
            out.append(match)
        await self._bus.publish(
            EventType.FUNDING_UPDATED,
            user_id=user_id,
            subject_type="user",
            subject_id=user_public_id,
            payload={"match_count": len(out)},
        )
        return out

    # -- sources (see app.repositories.budget_repo module docstring) ---------

    async def list_sources(self, user_id: int, target_public_id: str) -> list[dict]:
        target = await self._targets.get_target(user_id, target_public_id)
        if target is None:
            raise NotFound(detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।")
        budget = await self._budgets.get_for_target(user_id, target["id"])
        if budget is None:
            return []
        out = []
        for kind in ("own_funds", "awards"):
            amount = budget[f"{kind}_bdt"]
            if amount:
                out.append(
                    {
                        "id": kind,
                        "kind": kind,
                        "label_en": _SOURCE_LABELS_EN[kind],
                        "label_bn": _SOURCE_LABELS_BN[kind],
                        "amount_bdt": amount,
                    }
                )
        return out

    async def add_source(self, user_id: int, target_public_id: str, kind: str, amount_bdt: int) -> None:
        target = await self._targets.get_target(user_id, target_public_id)
        if target is None:
            raise NotFound(detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।")
        if kind == "own_funds":
            await self._budgets.adjust_own_funds(user_id, target["id"], amount_bdt)
        else:
            # Only `own_funds` is a free-form student entry; `awards` is
            # derived from accepted scholarship matches, not manually typed.
            raise NotFound(
                detail_en="Only 'own_funds' can be added manually; awards come from your matches.",
                detail_bn="শুধু 'own_funds' নিজে যোগ করা যায়; বৃত্তির অর্থ মিল থেকে আসে।",
            )
        await self._bus.publish(
            EventType.FUNDING_UPDATED,
            user_id=user_id,
            subject_type="target",
            subject_id=target_public_id,
            payload={"action": "source_added", "kind": kind},
        )

    async def remove_source(self, user_id: int, target_public_id: str, kind: str) -> None:
        target = await self._targets.get_target(user_id, target_public_id)
        if target is None:
            raise NotFound(detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।")
        budget = await self._budgets.get_for_target(user_id, target["id"])
        if budget and kind == "own_funds":
            await self._budgets.adjust_own_funds(user_id, target["id"], -budget["own_funds_bdt"])
        await self._bus.publish(
            EventType.FUNDING_UPDATED,
            user_id=user_id,
            subject_type="target",
            subject_id=target_public_id,
            payload={"action": "source_removed", "kind": kind},
        )

    # -- budget --------------------------------------------------------

    async def get_budget(self, user_id: int, target_public_id: str) -> dict:
        target = await self._targets.get_target(user_id, target_public_id)
        if target is None:
            raise NotFound(detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।")
        budget = await self._budgets.get_for_target(user_id, target["id"])
        if budget is None:
            raise NotFound(
                detail_en="No budget has been computed for this target yet.",
                detail_bn="এই টার্গেটের জন্য এখনও কোনো বাজেট হিসাব করা হয়নি।",
            )
        return budget

    # -- Agent Fee Reality Check --------------------------------------------

    async def fee_check(
        self, user_id: int, *, consultancy: str | None, quoted_bdt: int | None,
        country: str | None, document_id: str | None,
    ) -> dict:
        """Itemises a consultancy quote against what this system can actually
        certify.

        Honesty constraint: `docs/database.md` has no reference table of
        official application-fee schedules per country or university (only
        `solvency_rules`, which is a required bank balance, not a fee). Rather
        than fabricate plausible-looking BDT figures for "university
        application fees" or "courier charges" the way the contract's
        illustrative example does, this method returns only the one line it
        can certify as fact (Prohori's document check is free, per
        `agents.md`) and flags the remainder of the quote as unverified
        pending a real fee-schedule source. See the final report.
        """

        if quoted_bdt is None:
            raise NotFound(
                detail_en="Provide a quoted amount, or upload the invoice as a document first.",
                detail_bn="একটি কোটেড পরিমাণ দিন, অথবা প্রথমে চালানটি নথি হিসেবে আপলোড করুন।",
            )
        lines: list[dict] = [
            {
                "label_en": "Document checking and organisation",
                "label_bn": "নথি যাচাই ও গোছানো",
                "category": "free",
                "amount_bdt": 0,
                "note_en": "Prohori does this at no cost.",
                "note_bn": "প্রোহরি এটি বিনামূল্যে করে।",
            },
            {
                "label_en": "Remaining quoted amount",
                "label_bn": "অবশিষ্ট কোটেড পরিমাণ",
                "category": "unjustified",
                "amount_bdt": quoted_bdt,
                "note_en": (
                    "No certified official fee schedule is available yet to itemise this "
                    "amount; treat it as unverified until the consultancy provides receipts."
                ),
                "note_bn": (
                    "এই পরিমাণ বিশ্লেষণের জন্য এখনও কোনো সনদপ্রাপ্ত সরকারি ফি তালিকা নেই; "
                    "কনসালটেন্সি রশিদ না দেওয়া পর্যন্ত এটি অযাচাইকৃত হিসেবে বিবেচনা করুন।"
                ),
            },
        ]
        fair_bdt = None
        quote = await self._budgets.create_fee_quote(
            user_id=user_id, consultancy=consultancy, quoted_bdt=quoted_bdt,
            country_code=country, document_id=None, fair_bdt=fair_bdt,
        )
        for line in lines:
            await self._budgets.add_fee_line(quote["id"], **line, snapshot_id=None)
        return {"quoted_bdt": quoted_bdt, "fair_bdt": fair_bdt, "lines": lines}
