"""`GET /meta/stats` — real public counters for the About page.

api_contract.md section 2 is explicit that these must be real numbers, not
the hardcoded ones in `About.tsx`. `commission_taken_pct` and `sdg_aligned`
are not counts of anything in the database; they are facts about the
product's business model (docs/business_model.md), so they are fixed
constants here rather than a query, exactly like the contract's own example
response shows a bare `0` and `4`.
"""

from __future__ import annotations

from app.repositories._util import utc_now_iso
from app.repositories.answer_repo import AnswerRepo
from app.repositories.portal_repo import PortalRepo
from app.repositories.snapshot_repo import SnapshotRepo

_COMMISSION_TAKEN_PCT = 0
_SDG_ALIGNED = 4


class StatsService:
    def __init__(self, portals: PortalRepo, snapshots: SnapshotRepo, answers: AnswerRepo) -> None:
        self._portals = portals
        self._snapshots = snapshots
        self._answers = answers

    async def get_public_stats(self) -> dict:
        portals_watched = await self._portals.count_enabled()
        snapshots_archived = await self._snapshots.count_all()
        questions_answered = await self._answers.count_answered()
        citation_rate = await self._answers.citation_rate()
        return {
            "portals_watched": portals_watched,
            "snapshots_archived": snapshots_archived,
            "questions_answered": questions_answered,
            "citation_rate": citation_rate,
            "commission_taken_pct": _COMMISSION_TAKEN_PCT,
            "sdg_aligned": _SDG_ALIGNED,
            "as_of": utc_now_iso(),
        }
