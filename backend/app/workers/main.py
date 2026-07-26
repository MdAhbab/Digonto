"""Background worker process entrypoint.

Run as `python -m app.workers.main` (docker-compose.prod.yml's `worker`
service). Everything that is not a direct HTTP response lives here: the
crawl schedule, the diff/embed event consumers, and the nightly retention
and periodic learning cron jobs. The API process (app/main.py) never does
this work itself, per backend/backend.md section 2: "HTTP handlers stay
thin: validate, emit, respond. Workers do the heavy work."

Consumer loops are plain asyncio tasks wrapping `EventBus.consume`, which
already implements the arq-like job model this brief asks for: one handler
per message, at-least-once delivery, per-consumer-group idempotency via
`applied_events`. Reaching for the `arq` package itself here would stand up
a second, incompatible job queue next to the Redis Streams bus that
app/events/bus.py already owns; nothing under app/workers invents a second
event transport.
"""

from __future__ import annotations

import asyncio
import logging
import signal
from contextlib import suppress

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis

from app.config import Settings, get_settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.repositories.portal_repo import PortalRepo
from app.events.outbox_relay import RELAY_INTERVAL_SECONDS, relay_outbox
from app.workers import (
    crawler,
    differ,
    discovery,
    embedder,
    insights,
    learner,
    recovery,
    retention,
    student_reports,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Re-read the portals table this often for new/paused/re-cadenced portals.
# Cheap (one SELECT) and short enough that a moderator's PATCH /mod/portals
# edit takes effect without restarting the worker process.
_SCHEDULE_REFRESH_SECONDS = 300
_CRAWL_JOB_PREFIX = "crawl:"

# "Every 2 to 4 weeks" (backend/backend.md section 3.3) has no single
# correct cron; 21 days is the midpoint, and the cycle is also runnable on
# demand via `python -m app.workers.learner`.
_LEARNING_CYCLE_INTERVAL_DAYS = 21
_TRAINING_JOB_POLL_MINUTES = 30

# How often to sweep for work whose "in progress" marker outlived the work itself. Fifteen
# minutes is shorter than the tightest staleness window in app/workers/recovery.py (30
# minutes for a document scan), so a stuck row is never waiting on the sweep interval to be
# noticed once it qualifies.
_RECOVERY_SWEEP_MINUTES = 15
_NIGHTLY_RETENTION_CRON = "17 3 * * *"  # 03:17 UTC: off-peak, off the hour

# 00:40 UTC, so the day it reports on has actually ended, and 23 minutes before the
# retention sweep so a purge counted tonight is one the report has already seen.
_NIGHTLY_INSIGHTS_CRON = "40 0 * * *"

# Random offset applied to every portal's scheduled crawl. Thirty minutes across 31
# portals leaves the effective rate under two starts a minute even in the worst
# draw, and is small enough that a source on a daily cron is still checked on the
# day its cron names.
_CRAWL_JITTER_SECONDS = 1800


class WorkerApp:
    def __init__(self) -> None:
        self.settings: Settings = get_settings()
        self.dbs = Databases(self.settings.app_db, self.settings.events_db, self.settings.learn_db)
        self.redis: Redis = Redis.from_url(self.settings.redis_url, decode_responses=True)
        self.bus = EventBus(self.redis, self.dbs.events)
        self.model_router = ModelRouter(self.settings)
        self.qdrant = AsyncQdrantClient(url=self.settings.qdrant_url)
        # Separate from ModelRouter's internal client: this one talks to
        # arbitrary external portals with a crawling User-Agent, not to
        # Ollama/Gemini with the router's own headers.
        self.crawl_http = httpx.AsyncClient(
            headers={"User-Agent": crawler.USER_AGENT}, follow_redirects=True
        )
        self.scheduler = AsyncIOScheduler()
        self._consumer_tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        self.settings.ensure_dirs()
        await self.dbs.connect_all()
        # Idempotent and safe even if the API container already applied
        # every migration; running it here too means this process can also
        # be brought up standalone.
        await run_migrations(self.dbs)

        await relay_outbox(self.bus)

        # Same reason as in app/main.py: a marker left by the process that just stopped is
        # cleared before anything new starts. Run in both processes because either can be
        # brought up alone, and doing it twice is harmless: the second pass finds nothing.
        await recovery.recover_interrupted_work(self.dbs, self.settings)

        self._consumer_tasks = [
            asyncio.create_task(
                differ.consume(self.bus, self.dbs, self.model_router), name="consumer:differ"
            ),
            asyncio.create_task(
                embedder.consume(self.bus, self.dbs, self.settings, self.crawl_http, self.qdrant),
                name="consumer:embedder",
            ),
            # Closes the recurrent loop: a question that could not be answered
            # becomes a search for the source that would have answered it, and
            # the source becomes a watched portal the crawler picks up.
            asyncio.create_task(
                discovery.consume(self.bus, self.dbs, self.crawl_http),
                name="consumer:discovery",
            ),
        ]

        await self._schedule_crawls()
        self.scheduler.add_job(
            self._schedule_crawls,
            IntervalTrigger(seconds=_SCHEDULE_REFRESH_SECONDS),
            id="refresh-crawl-schedule",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_retention,
            CronTrigger.from_crontab(_NIGHTLY_RETENTION_CRON),
            id="nightly-retention",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._run_insights,
            CronTrigger.from_crontab(_NIGHTLY_INSIGHTS_CRON),
            id="nightly-insights",
            replace_existing=True,
        )
        # Startup recovery only catches an interruption that took the process with it. A task
        # that dies inside a process which keeps running leaves the same stuck marker and no
        # restart to clear it, so the sweep also runs on a timer.
        self.scheduler.add_job(
            self._run_recovery,
            IntervalTrigger(minutes=_RECOVERY_SWEEP_MINUTES),
            id="recover-interrupted-work",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.add_job(
            self._run_learning_cycle,
            IntervalTrigger(days=_LEARNING_CYCLE_INTERVAL_DAYS),
            id="continual-learning-cycle",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._poll_training_jobs,
            IntervalTrigger(minutes=_TRAINING_JOB_POLL_MINUTES),
            id="poll-training-jobs",
            replace_existing=True,
        )
        self.scheduler.add_job(
            self._relay_outbox,
            IntervalTrigger(seconds=RELAY_INTERVAL_SECONDS),
            id="relay-event-outbox",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        self.scheduler.start()
        log.info("digonto worker ready env=%s", self.settings.app_env)

    async def _schedule_crawls(self) -> None:
        portals = await PortalRepo(self.dbs.app).list_all()
        seen_job_ids: set[str] = set()
        for portal in portals:
            job_id = f"{_CRAWL_JOB_PREFIX}{portal['id']}"
            if not portal["enabled"]:
                if self.scheduler.get_job(job_id):
                    self.scheduler.remove_job(job_id)
                continue
            seen_job_ids.add(job_id)
            try:
                trigger = CronTrigger.from_crontab(portal["crawl_cron"])
            except ValueError:
                log.error(
                    "portal %s has an invalid crawl_cron %r; skipping",
                    portal["public_id"], portal["crawl_cron"],
                )
                continue
            self.scheduler.add_job(
                crawler.crawl_portal,
                trigger=trigger,
                id=job_id,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                # Every portal in migration 015 carries one of two cron
                # expressions, so twenty of them are due at 00:00 and eleven at
                # each six-hour mark. `max_instances=1` bounds one job re-entering
                # itself, not the number of distinct jobs, so without jitter the
                # worker opened twenty connections at once from a one-CPU VM,
                # several of them to the same host. Jitter is the right layer for
                # this: the cron stays a readable statement of how often a source
                # should be checked, and nothing has to renumber 31 rows to spread
                # them out. crawler.MAX_CONCURRENT_FETCHES is the hard backstop for
                # the case where the random offsets happen to cluster.
                jitter=_CRAWL_JITTER_SECONDS,
                kwargs={
                    "portal_id": portal["id"],
                    "dbs": self.dbs,
                    "bus": self.bus,
                    "settings": self.settings,
                    "http_client": self.crawl_http,
                },
            )
        for job in self.scheduler.get_jobs():
            if job.id.startswith(_CRAWL_JOB_PREFIX) and job.id not in seen_job_ids:
                self.scheduler.remove_job(job.id)

    async def _relay_outbox(self) -> None:
        await relay_outbox(self.bus)

    async def _run_retention(self) -> None:
        # The bus is required for the account-purge sweep, which publishes user.deleted.
        await retention.run_nightly(self.dbs, self.settings, bus=self.bus)

    async def _run_insights(self) -> None:
        await insights.run_nightly(self.dbs, self.settings)
        # Same schedule, run straight after: both read the same day's data, and running
        # them apart would let a purge between the two produce a pair of reports that
        # disagree about how many accounts exist.
        await student_reports.run_nightly(self.dbs, self.settings)

    async def _run_recovery(self) -> None:
        await recovery.recover_interrupted_work(self.dbs, self.settings)

    async def _run_learning_cycle(self) -> None:
        await learner.run_learning_cycle(self.dbs, self.settings)

    async def _poll_training_jobs(self) -> None:
        await learner.check_for_completed_jobs(
            self.dbs, self.bus, self.settings, self.crawl_http, self.qdrant
        )

    async def stop(self) -> None:
        log.info("worker shutting down")
        self.scheduler.shutdown(wait=False)
        for task in self._consumer_tasks:
            task.cancel()
        # Ledger-based idempotency (applied_events) is what makes this safe:
        # a handler killed mid-flight never got acked, so at-least-once
        # delivery covers it on the next run. This wait is a courtesy to let
        # an in-flight statement finish, not a correctness requirement.
        if self._consumer_tasks:
            await asyncio.wait_for(
                asyncio.gather(*self._consumer_tasks, return_exceptions=True), timeout=30
            )
        await self.model_router.aclose()
        await self.crawl_http.aclose()
        await self.qdrant.close()
        await self.redis.aclose()
        await self.dbs.close_all()


async def run() -> None:
    app = WorkerApp()
    await app.start()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, stop_event.set)

    await stop_event.wait()
    await app.stop()


if __name__ == "__main__":
    asyncio.run(run())
