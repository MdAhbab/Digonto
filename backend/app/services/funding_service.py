"""Funding Studio and Khoji. api_contract.md section 9.

`POST /funding/rematch` re-runs Khoji's eligibility scoring through
`app.agents.khoji.score_eligibility`, which scores each award against the
student's profile and returns a reason per criterion. Every other read here
(the budget, the fee check) is real arithmetic over `budgets`, `fx_rates`,
and `solvency_rules`, none of which needs a model call.
"""

from __future__ import annotations

import logging

from app.agents.khoji import score_eligibility
from app.errors import NotFound
from app.events.bus import EventBus, EventType
from app.llm.router import ModelRouter
from app.repositories.budget_repo import BudgetRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.scholarship_repo import ScholarshipRepo
from app.repositories.target_repo import TargetRepo

log = logging.getLogger(__name__)

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
            "amount": r["amount"],
            "currency": r["currency"],
            "coverage_type": r["coverage_type"],
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

        # Khoji identifies an award by its public ULID, never by the internal
        # row id, because the model must not be handed database primary keys.
        # funding_matches.scholarship_id is a foreign key onto that internal
        # id, so the two have to be mapped back here. Without this the insert
        # fails the foreign key constraint on every single rematch.
        by_public_id = {sc["public_id"]: sc["id"] for sc in scholarships}

        await self._scholarships.clear_matches_for_user(user_id)
        out = []
        for rank, result in enumerate(
            sorted(results, key=lambda r: r["score"], reverse=True), start=1
        ):
            internal_id = by_public_id.get(result["scholarship_id"])
            if internal_id is None:
                # The model named an award that was not in the list it was
                # given. Skip it rather than write a dangling match.
                log.warning(
                    "rematch: khoji returned unknown scholarship id=%s, skipping",
                    result["scholarship_id"],
                )
                continue
            match = await self._scholarships.create_match(
                user_id=user_id,
                scholarship_id=internal_id,
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

    # What a Bangladeshi education consultancy actually bills for, and what each item
    # really is. This is the substance of the Fee Reality Check.
    #
    # It replaces a version that produced two lines: "Document checking: 0" and
    # "Remaining quoted amount: <the entire quote>". That was honest about not knowing
    # the official fee schedule and useless to the student, who learned only that we
    # could not explain their bill. A student handed a 222,222 taka quote does not need
    # a number from us to be better off; they need to know that most of what they are
    # being charged for is either free here or a government fee they pay directly to the
    # government, and that a consultancy cannot mark up a fee it does not collect.
    #
    # `amount_bdt` stays 0 for the official fees on purpose, and the note says why:
    # `docs/database.md` has no reference table of visa and application fee schedules,
    # only `solvency_rules`, which is a required bank balance rather than a fee. Putting
    # a remembered figure there would be exactly the confidently-wrong number this
    # product exists to replace. The category and the note carry the finding; the
    # arithmetic is confined to what the system can stand behind.
    _FEE_CATALOGUE: tuple[dict[str, str], ...] = (
        {
            "label_en": "Choosing universities and programmes",
            "label_bn": "বিশ্ববিদ্যালয় ও প্রোগ্রাম বাছাই",
            "category": "free",
            "note_en": "Digonto matches programmes to your profile at no cost.",
            "note_bn": "দিগন্ত আপনার প্রোফাইল অনুযায়ী প্রোগ্রাম মেলায়, বিনামূল্যে।",
        },
        {
            "label_en": "Document checking and organisation",
            "label_bn": "নথি যাচাই ও গোছানো",
            "category": "free",
            "note_en": "Prohori audits your vault against each target's checklist at no cost.",
            "note_bn": "প্রোহরি প্রতিটি লক্ষ্যের চেকলিস্ট মিলিয়ে আপনার ভল্ট যাচাই করে, বিনামূল্যে।",
        },
        {
            "label_en": "Statement of purpose review",
            "label_bn": "স্টেটমেন্ট অব পারপাস পর্যালোচনা",
            "category": "free",
            "note_en": "Lekhok checks your statement against your own documents for contradictions.",
            "note_bn": "লেখক আপনার নথির সঙ্গে বিবৃতির অসঙ্গতি যাচাই করে।",
        },
        {
            "label_en": "Scholarship search",
            "label_bn": "বৃত্তি অনুসন্ধান",
            "category": "free",
            "note_en": "Khoji lists what you qualify for, with the reason for each criterion.",
            "note_bn": "খোঁজি আপনি কোন কোন শর্ত পূরণ করেন তার কারণসহ তালিকা দেয়।",
        },
        {
            "label_en": "Visa interview preparation",
            "label_bn": "ভিসা সাক্ষাৎকারের প্রস্তুতি",
            "category": "free",
            "note_en": "Shonchari runs mock interviews scored against your own file.",
            "note_bn": "সঞ্চারী আপনার নিজের ফাইলের ভিত্তিতে মক ইন্টারভিউ নেয়।",
        },
        {
            "label_en": "Deadline tracking and reminders",
            "label_bn": "সময়সীমা পর্যবেক্ষণ ও মনে করানো",
            "category": "free",
            "note_en": "The timeline re-plans itself when a portal changes, and alerts you.",
            "note_bn": "পোর্টাল বদলালে সময়রেখা নিজেই আবার সাজায় এবং আপনাকে জানায়।",
        },
        {
            "label_en": "University application fees",
            "label_bn": "বিশ্ববিদ্যালয়ের আবেদন ফি",
            "category": "official_fee",
            "note_en": (
                "Paid to the university, not to a consultancy. Pay it yourself on the "
                "university's own portal and keep the receipt. We do not hold a verified "
                "fee schedule, so no amount is asserted here."
            ),
            "note_bn": (
                "এটি বিশ্ববিদ্যালয়কে দিতে হয়, কনসালটেন্সিকে নয়। বিশ্ববিদ্যালয়ের নিজের "
                "পোর্টালে নিজে পরিশোধ করুন এবং রশিদ রাখুন। যাচাইকৃত ফি তালিকা আমাদের "
                "কাছে নেই, তাই কোনো পরিমাণ দাবি করা হচ্ছে না।"
            ),
        },
        {
            "label_en": "Visa application and biometrics fees",
            "label_bn": "ভিসা আবেদন ও বায়োমেট্রিক ফি",
            "category": "official_fee",
            "note_en": (
                "Set by the government and paid on the official portal. A consultancy "
                "cannot mark up a fee it does not collect, so check this line against the "
                "official page before paying it to anyone else."
            ),
            "note_bn": (
                "এটি সরকার নির্ধারণ করে এবং সরকারি পোর্টালেই পরিশোধ করতে হয়। যে ফি "
                "কনসালটেন্সি নেয় না, তার উপর তারা বাড়তি চার্জ করতে পারে না; তাই অন্য "
                "কাউকে দেওয়ার আগে সরকারি পাতার সঙ্গে মিলিয়ে নিন।"
            ),
        },
        {
            "label_en": "English test fee",
            "label_bn": "ইংরেজি পরীক্ষার ফি",
            "category": "official_fee",
            "note_en": "Paid to the test centre directly. Book it yourself.",
            "note_bn": "পরীক্ষা কেন্দ্রকে সরাসরি দিতে হয়। নিজেই বুক করুন।",
        },
        {
            "label_en": "Courier and attestation",
            "label_bn": "কুরিয়ার ও সত্যায়ন",
            "category": "fair_service",
            "note_en": (
                "A real cost with a real receipt. Ask for the receipt; this is one of the "
                "few lines on a consultancy bill that should have one."
            ),
            "note_bn": (
                "এটি প্রকৃত খরচ এবং এর রশিদ থাকে। রশিদ চেয়ে নিন; কনসালটেন্সির বিলে "
                "খুব কম লাইনেরই রশিদ থাকা উচিত।"
            ),
        },
    )

    async def fee_check(
        self, user_id: int, *, consultancy: str | None, quoted_bdt: int | None,
        country: str | None, document_id: str | None,
    ) -> dict:
        """Itemise a consultancy quote against what this system can actually certify.

        The honesty constraint has not changed: there is no reference table of official
        application and visa fee schedules in this database, so no BDT figure is invented
        for a government fee. What changed is that refusing to invent a number is no
        longer the same as refusing to say anything.

        Six of the ten services a consultancy bills for are free here, and three are
        government or test-centre fees the student can and should pay directly. That is
        the finding, and it does not require knowing the amounts. The residual is
        whatever is left of the quote after the services that cost nothing, which is
        every taka of it while the official amounts are unverified, and it is labelled
        `unjustified` rather than presented as a computed fair price.
        """
        if quoted_bdt is None:
            raise NotFound(
                detail_en="Provide a quoted amount, or upload the invoice as a document first.",
                detail_bn="একটি কোটেড পরিমাণ দিন, অথবা প্রথমে চালানটি নথি হিসেবে আপলোড করুন।",
            )
        if quoted_bdt < 0:
            raise NotFound(
                detail_en="A quoted amount cannot be negative.",
                detail_bn="কোটেড পরিমাণ ঋণাত্মক হতে পারে না।",
            )

        lines: list[dict] = [{**item, "amount_bdt": 0} for item in self._FEE_CATALOGUE]

        free_count = sum(1 for line in lines if line["category"] == "free")
        official_count = sum(1 for line in lines if line["category"] == "official_fee")
        lines.append(
            {
                "label_en": "Unexplained remainder",
                "label_bn": "অব্যাখ্যাত অবশিষ্ট",
                "category": "unjustified",
                "amount_bdt": quoted_bdt,
                "note_en": (
                    f"{free_count} of the services above cost nothing here, and "
                    f"{official_count} are fees you pay to the government or the test "
                    "centre yourself. Ask the consultancy to itemise this remainder with "
                    "receipts. Until they do, treat all of it as unverified."
                ),
                "note_bn": (
                    f"উপরের {free_count}টি সেবা এখানে বিনামূল্যে, এবং {official_count}টি ফি "
                    "আপনি নিজেই সরকার বা পরীক্ষা কেন্দ্রকে দেন। এই অবশিষ্ট অংশের রশিদসহ "
                    "বিভাজন কনসালটেন্সির কাছে চান। তা না দেওয়া পর্যন্ত পুরোটাই অযাচাইকৃত "
                    "হিসেবে দেখুন।"
                ),
            }
        )

        # `fair_bdt` stays None. It is the one number a student would most like and the
        # one this system has no basis for: a fair price is the official fees plus a
        # defensible margin, and the official fees are exactly what is unverified. A
        # figure here would be a guess wearing the authority of a calculation.
        fair_bdt = None
        quote = await self._budgets.create_fee_quote(
            user_id=user_id, consultancy=consultancy, quoted_bdt=quoted_bdt,
            country_code=country, document_id=None, fair_bdt=fair_bdt,
        )
        for line in lines:
            await self._budgets.add_fee_line(quote["id"], **line, snapshot_id=None)
        return {"quoted_bdt": quoted_bdt, "fair_bdt": fair_bdt, "lines": lines}
