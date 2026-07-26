"""Visa Timeline Reactor. api_contract.md section 7.

**Scope note.** Porter (the Portal Watch agent) is the piece of this system
that reacts to a real portal change and calls `update_timeline` for every
affected student; it is one of the seven agents this build brief says to
import unresolved from `app.agents.porter` rather than reimplement, and nothing
here calls it. What this service *does* own is deterministic: building the
baseline timeline from the student's own profile, target, and the country's
real `solvency_rules` / programme deadline rows, and recomputing it when the
student completes a step or edits their profile. That is genuine business
logic over real data, not a stand-in for Porter's judgement about a portal
diff.

`POST /planner/simulate` is demonstration-only by contract: it synthesises
one `plan_changes` row scoped to the caller's own plan, exactly as if Porter
had reacted to a change, but never touches `snapshots` or another user's plan.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from app.errors import NotFound
from app.events.bus import EventBus, EventType
from app.repositories._util import utc_now_iso
from app.repositories.budget_repo import BudgetRepo
from app.repositories.plan_repo import PlanRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo

_STEP_TEMPLATES = [
    {
        "step_key": "shortlist",
        "title_en": "Shortlist programmes",
        "title_bn": "প্রোগ্রাম বাছাই",
        "desc_en": "Confirm the programmes you are applying to.",
        "desc_bn": "আপনি কোন প্রোগ্রামে আবেদন করবেন তা নিশ্চিত করুন।",
        "lead_days": 0,
        "depends_on": [],
    },
    {
        "step_key": "english_test",
        "title_en": "Sit the English proficiency test",
        "title_bn": "ইংরেজি দক্ষতার পরীক্ষা দিন",
        "desc_en": "Book and sit IELTS/TOEFL/PTE/Duolingo well before the application deadline.",
        "desc_bn": "আবেদনের সময়সীমার অনেক আগেই আইইএলটিএস/টোফেল/পিটিই/ডুয়োলিঙ্গো পরীক্ষা দিন।",
        "lead_days": 150,
        "depends_on": ["shortlist"],
    },
    {
        "step_key": "sop",
        "title_en": "Draft SOP and references",
        "title_bn": "এসওপি ও সুপারিশপত্র তৈরি করুন",
        "desc_en": "Write your statement of purpose and collect academic references.",
        "desc_bn": "আপনার উদ্দেশ্য বিবৃতি লিখুন এবং একাডেমিক সুপারিশপত্র সংগ্রহ করুন।",
        "lead_days": 90,
        "depends_on": ["shortlist"],
    },
    {
        "step_key": "apply",
        "title_en": "Submit applications",
        "title_bn": "আবেদন জমা দিন",
        "desc_en": "Submit the programme application before the deadline.",
        "desc_bn": "সময়সীমার আগেই প্রোগ্রামে আবেদন জমা দিন।",
        "lead_days": 0,
        "depends_on": ["english_test", "sop"],
    },
    {
        "step_key": "solvency",
        "title_en": "Arrange funding and solvency",
        "title_bn": "তহবিল ও সচ্ছলতা প্রস্তুত করুন",
        "desc_en": "Hold the required bank balance for the required number of days.",
        "desc_bn": "প্রয়োজনীয় দিনের জন্য নির্ধারিত ব্যাংক ব্যালেন্স বজায় রাখুন।",
        "lead_days": 45,
        "depends_on": ["apply"],
    },
    {
        "step_key": "visa",
        "title_en": "Apply for the student visa",
        "title_bn": "শিক্ষার্থী ভিসার জন্য আবেদন করুন",
        "desc_en": "Submit the visa application once the offer letter is in hand.",
        "desc_bn": "অফার লেটার হাতে পাওয়ার পর ভিসা আবেদন জমা দিন।",
        "lead_days": 14,
        "depends_on": ["solvency"],
    },
]

_MONTHS_EN = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
]

# Days added on top of a country's required holding period, so the balance has
# finished sitting *and* the bank has had time to issue the statement before the
# visa appointment. A hold that ends the morning of the application is a hold
# the student cannot yet evidence.
_SOLVENCY_STATEMENT_MARGIN_DAYS = 14


def _month_label(dt: datetime) -> str:
    """English month label, cached on the row.

    This stays English on purpose and is not what a Bangla reader sees: the
    client formats the month from `due_at` in the active locale. Storing a
    localised string would freeze the language at the moment the plan was
    generated, so a student switching to Bangla would still read "Oct 2026".
    """
    return f"{_MONTHS_EN[dt.month - 1]} {dt.year}"


def _solvency_copy(rule: dict) -> tuple[str, str]:
    """Describe this country's actual funds requirement, bilingually.

    Falls back to the generic wording when the rule carries no basis note, so a
    country added later without notes still gets a sensible step rather than an
    empty description.
    """
    amount = f"{rule['amount']:,} {rule['currency']}"
    hold_days = int(rule["hold_days"] or 0)

    if hold_days > 0:
        en = (
            f"Hold {amount} in your account for {hold_days} consecutive days, "
            f"finishing before your visa application."
        )
        bn = (
            f"আপনার অ্যাকাউন্টে {amount} টানা {hold_days} দিন ধরে রাখুন, "
            f"ভিসা আবেদনের আগেই যেন তা সম্পূর্ণ হয়।"
        )
    else:
        en = f"Have {amount} available and evidenced before your visa application."
        bn = f"ভিসা আবেদনের আগে {amount} প্রস্তুত রাখুন এবং তার প্রমাণ রাখুন।"

    if rule.get("basis_note_en"):
        en = f"{en} {rule['basis_note_en']}"
    if rule.get("basis_note_bn"):
        bn = f"{bn} {rule['basis_note_bn']}"
    return en, bn


class PlannerService:
    def __init__(
        self, plans: PlanRepo, targets: TargetRepo, profiles: ProfileRepo,
        budgets: BudgetRepo, bus: EventBus,
    ) -> None:
        self._plans = plans
        self._targets = targets
        self._profiles = profiles
        self._budgets = budgets
        self._bus = bus

    async def _build_or_get_plan(self, user_id: int, target_public_id: str | None) -> dict:
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
            if target_row is None:
                raise NotFound(
                    detail_en="Target not found.", detail_bn="টার্গেট পাওয়া যায়নি।"
                )
        target_id = target_row["id"] if target_row else None
        plan = await self._plans.get_for_user_target(user_id, target_id)
        if plan is None:
            profile = await self._profiles.get(user_id)
            intake_label = profile["intake_target"] if profile else None
            plan = await self._plans.create(user_id, target_id, intake_label)
        return plan

    async def _programme_for_target(
        self, user_id: int, target_public_id: str | None
    ) -> tuple[dict | None, dict | None]:
        """The target row and its programme, in two queries rather than four.

        The previous version called `list_targets`, discarded everything but a
        None check, then called `get_target` again to read the one column it
        actually needed, then `get_programme`. `get_target` is already scoped to
        `user_id`, so the ownership check the list was standing in for is the
        same check, done once.
        """
        if not target_public_id:
            return None, None
        target = await self._targets.get_target(user_id, target_public_id)
        if target is None:
            return None, None
        programme = await self._targets.get_programme(target["programme_id"])
        return target, programme

    @staticmethod
    def _deadline_of(programme: dict | None) -> datetime | None:
        if not programme or not programme.get("deadline_at"):
            return None
        try:
            return datetime.fromisoformat(programme["deadline_at"].replace("Z", "+00:00"))
        except ValueError:
            return None

    async def _solvency_for_target(self, programme: dict | None, target: dict | None) -> dict | None:
        """The country's real maintenance rule for this target, if there is one.

        This is the piece this module's docstring always claimed to do and never
        did: `BudgetRepo` was constructed, injected, and never called, so the
        solvency step used a flat 45-day lead for every destination. The UK
        requires the balance to sit untouched for 28 consecutive days and
        Germany's blocked account has no holding period at all; one number
        cannot be right for both, and being wrong here costs a student the
        application.
        """
        if not programme:
            return None
        country_code = programme.get("country_code")
        if not country_code:
            return None
        visa_type = (target or {}).get("visa_type") or ""
        return await self._budgets.solvency_rule(country_code, visa_type)

    async def regenerate(self, user_id: int, target_public_id: str | None) -> dict:
        plan = await self._build_or_get_plan(user_id, target_public_id)
        target, programme = await self._programme_for_target(user_id, target_public_id)
        deadline = self._deadline_of(programme)
        anchor = deadline or (datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=270))
        solvency = await self._solvency_for_target(programme, target)

        for idx, tmpl in enumerate(_STEP_TEMPLATES):
            lead_days = tmpl["lead_days"]
            desc_en, desc_bn = tmpl["desc_en"], tmpl["desc_bn"]
            snapshot_id = None

            if tmpl["step_key"] == "solvency" and solvency is not None:
                # Start the hold early enough that it is complete before the visa
                # application, plus a margin for the bank to issue the statement.
                lead_days = int(solvency["hold_days"] or 0) + _SOLVENCY_STATEMENT_MARGIN_DAYS
                desc_en, desc_bn = _solvency_copy(solvency)
                snapshot_id = solvency.get("snapshot_id")

            due = anchor - timedelta(days=lead_days)
            await self._plans.upsert_step(
                plan["id"],
                step_key=tmpl["step_key"],
                order_idx=idx,
                month_label=_month_label(due),
                due_at=due.strftime("%Y-%m-%d"),
                title_en=tmpl["title_en"],
                title_bn=tmpl["title_bn"],
                desc_en=desc_en,
                desc_bn=desc_bn,
                status="upcoming",
                depends_on=tmpl["depends_on"],
                lead_days=lead_days,
                source_snapshot_id=snapshot_id,
            )
        await self._plans.touch(plan["id"])
        await self._bus.publish(
            EventType.PLAN_STEP_CHANGED,
            user_id=user_id,
            subject_type="plan",
            subject_id=plan["public_id"],
            payload={"action": "regenerated"},
        )
        return await self.get_timeline(user_id, target_public_id)

    async def get_timeline(self, user_id: int, target_public_id: str | None) -> dict:
        plan = await self._build_or_get_plan(user_id, target_public_id)
        steps = await self._plans.list_steps(plan["id"])
        if not steps:
            return await self.regenerate(user_id, target_public_id)
        unseen = await self._plans.count_unseen(plan["id"])
        return {
            "plan_id": plan["public_id"],
            "intake_label": plan["intake_label"],
            "steps": [
                {
                    "id": s["public_id"],
                    "step_key": s["step_key"],
                    "month": s["month_label"],
                    "titleEn": s["title_en"],
                    "titleBn": s["title_bn"],
                    "descEn": s["desc_en"],
                    "descBn": s["desc_bn"],
                    "status": s["status"],
                    "due_at": s["due_at"],
                    "depends_on": json.loads(s["depends_on"] or "[]"),
                    # A step derived from a country's own published rule carries
                    # the snapshot it came from. Generic template steps have no
                    # source and stay uncited rather than borrowing one.
                    "citation": (
                        {
                            "snapshot_id": s["snapshot_public_id"],
                            "portal": s["snapshot_portal_label"],
                            "captured": s["snapshot_fetched_at"],
                        }
                        if s.get("snapshot_public_id")
                        else None
                    ),
                }
                for s in steps
            ],
            "unseen_changes": unseen,
        }

    async def list_changes(self, user_id: int, *, since: str | None, cursor: str | None) -> tuple[list[dict], str | None]:
        plan = await self._plans.get_for_user_target(user_id, None)
        if plan is None:
            return [], None
        rows, next_cursor = await self._plans.list_changes(plan["id"], since=since, cursor=cursor)
        return [
            {
                "id": str(r["id"]),
                "textEn": r["text_en"],
                "textBn": r["text_bn"],
                "source": r["source_label"],
                "trigger": r["trigger"],
                "step_key": r["step_key"],
                "created_at": r["created_at"],
                "seen": r["seen_at"] is not None,
            }
            for r in rows
        ], next_cursor

    async def _set_step_status(self, user_id: int, step_public_id: str, status: str) -> dict:
        step = await self._plans.get_step_by_public_id(step_public_id)
        if step is None:
            raise NotFound(detail_en="Step not found.", detail_bn="ধাপটি পাওয়া যায়নি।")
        plan = await self._plans.get(step["plan_id"])
        if plan is None or plan["user_id"] != user_id:
            raise NotFound(detail_en="Step not found.", detail_bn="ধাপটি পাওয়া যায়নি।")
        completed_at = utc_now_iso() if status == "done" else None
        await self._plans.set_step_status(step["id"], status, completed_at)
        await self._bus.publish(
            EventType.PLAN_STEP_CHANGED,
            user_id=user_id,
            subject_type="plan_step",
            subject_id=step_public_id,
            payload={"status": status},
        )
        # Return the timeline for *this* plan's target — not the user's most
        # recently updated plan (`get_timeline(user_id, None)`), which can be
        # a different target when the student has more than one.
        target_public_id = None
        if plan.get("target_id") is not None:
            target = await self._targets.get_target_by_id(user_id, plan["target_id"])
            if target is not None:
                target_public_id = target["public_id"]
        return await self.get_timeline(user_id, target_public_id)

    async def complete_step(self, user_id: int, step_public_id: str) -> dict:
        return await self._set_step_status(user_id, step_public_id, "done")

    async def reopen_step(self, user_id: int, step_public_id: str) -> dict:
        return await self._set_step_status(user_id, step_public_id, "active")

    async def simulate(self, user_id: int, user_public_id: str) -> dict:
        """Demonstration-only. Injects one synthetic `plan_changes` row for
        the caller's own plan and nudges one upcoming step, and nothing else.
        Never writes to `snapshots`/`portals` and never touches another
        user's plan.
        """

        plan = await self._plans.get_for_user_target(user_id, None)
        if plan is None:
            plan = await self._build_or_get_plan(user_id, None)
        steps = await self._plans.list_steps(plan["id"])
        target_step = next((s for s in steps if s["status"] in ("upcoming", "active")), None)

        text_en = "Demonstration: a portal change moved a deadline forward."
        text_bn = "প্রদর্শনী: একটি পোর্টাল পরিবর্তন সময়সীমা এগিয়ে এনেছে।"
        step_key = None
        if target_step is not None:
            step_key = target_step["step_key"]
            try:
                old_due = datetime.strptime(target_step["due_at"], "%Y-%m-%d")
            except (TypeError, ValueError):
                old_due = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=30)
            new_due = old_due - timedelta(days=7)
            await self._plans.upsert_step(
                plan["id"],
                step_key=target_step["step_key"],
                order_idx=target_step["order_idx"],
                month_label=_month_label(new_due),
                due_at=new_due.strftime("%Y-%m-%d"),
                title_en=target_step["title_en"],
                title_bn=target_step["title_bn"],
                desc_en=target_step["desc_en"],
                desc_bn=target_step["desc_bn"],
                status=target_step["status"],
                depends_on=json.loads(target_step["depends_on"] or "[]"),
                lead_days=target_step["lead_days"],
                source_snapshot_id=target_step["source_snapshot_id"],
            )
            text_en = (
                f"Demonstration: the '{target_step['title_en']}' deadline moved 7 days earlier."
            )
            text_bn = (
                f"প্রদর্শনী: '{target_step['title_bn']}' ধাপের সময়সীমা ৭ দিন এগিয়ে এসেছে।"
            )

        change = await self._plans.add_change(
            plan["id"],
            step_id=target_step["id"] if target_step else None,
            trigger="portal_change",
            text_en=text_en,
            text_bn=text_bn,
            source_label="Demonstration · simulated, not a real portal",
            snapshot_id=None,
            event_id=None,
        )
        await self._bus.publish(
            EventType.PLAN_CHANGED,
            user_id=user_id,
            subject_type="plan",
            subject_id=plan["public_id"],
            payload={"simulated": True, "step_key": step_key},
        )
        timeline = await self.get_timeline(user_id, None)
        return {
            "simulated": True,
            "change": {
                "id": str(change["id"]),
                "textEn": change["text_en"],
                "textBn": change["text_bn"],
                "source": change["source_label"],
                "trigger": change["trigger"],
                "step_key": step_key,
                "created_at": change["created_at"],
                "seen": False,
            },
            "plan": timeline,
        }
