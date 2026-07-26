"""Nightly retention sweep. docs/database.md section 7.

Every rule here is a DELETE or an UPDATE guarded by a WHERE clause on an
age cutoff, which is what makes running this job twice in one night, or
restarting it mid-run, harmless: the second pass simply matches zero rows
for whatever the first pass already handled.
"""

from __future__ import annotations

import gzip
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.config import Settings
from app.db.connection import Databases
from app.events.bus import EventBus
from app.repositories._util import utc_now_iso
from app.repositories.user_repo import UserRepo
from app.services.auth_service import AuthService

log = logging.getLogger(__name__)

SNAPSHOT_RETENTION_DAYS = 90
REFRESH_TOKEN_GRACE_DAYS = 30
REQUEST_METRICS_RETENTION_DAYS = 90
EVENT_RETENTION_DAYS = 180
_EVENT_ARCHIVE_BATCH = 5000


def _cutoff_iso(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


async def retire_old_snapshots(dbs: Databases) -> int:
    """Set retired_at and delete the file at 90 days; keep the row so an
    old citation still resolves to a verifiable (if now file-less) record."""
    cutoff = _cutoff_iso(SNAPSHOT_RETENTION_DAYS)
    rows = await dbs.app.fetch_all(
        "SELECT id, storage_path FROM snapshots WHERE retired_at IS NULL AND fetched_at < ?",
        (cutoff,),
    )
    now = utc_now_iso()
    retired = 0
    for row in rows:
        path = Path(row["storage_path"])
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("could not delete snapshot file %s: %s", path, exc)
        await dbs.app.execute("UPDATE snapshots SET retired_at = ? WHERE id = ?", (now, row["id"]))
        retired += 1
    if retired:
        log.info("retired %d snapshots older than %d days", retired, SNAPSHOT_RETENTION_DAYS)
    return retired


async def purge_expired_refresh_tokens(dbs: Databases) -> int:
    # docs/database.md section 7: purge 30 days *past expiry*, not at issue
    # time, so a client mid-rotation near the boundary is never surprised.
    cutoff = _cutoff_iso(REFRESH_TOKEN_GRACE_DAYS)
    count = await dbs.app.fetch_val("SELECT COUNT(*) FROM refresh_tokens WHERE expires_at < ?", (cutoff,))
    await dbs.app.execute("DELETE FROM refresh_tokens WHERE expires_at < ?", (cutoff,))
    return int(count or 0)


async def purge_old_request_metrics(dbs: Databases) -> int:
    # request_metrics lives in events.db (migrations/events/003_metrics.sql).
    cutoff = _cutoff_iso(REQUEST_METRICS_RETENTION_DAYS)
    count = await dbs.events.fetch_val(
        "SELECT COUNT(*) FROM request_metrics WHERE created_at < ?", (cutoff,)
    )
    await dbs.events.execute("DELETE FROM request_metrics WHERE created_at < ?", (cutoff,))
    return int(count or 0)


async def archive_old_events(dbs: Databases, settings: Settings) -> int:
    """Compress events older than 180 days to disk, then delete the rows.

    events.db is append-only and is the durable record app/events/bus.py
    relies on for idempotency (`applied_events`) and SSE replay
    (`NotificationRepo.events_since`); only rows old enough that no live
    `Last-Event-ID` reconnect could plausibly still need them are archived.
    """
    cutoff = _cutoff_iso(EVENT_RETENTION_DAYS)
    archive_dir = settings.db_dir.parent / "archive" / "events"
    archive_dir.mkdir(parents=True, exist_ok=True)

    total = 0
    while True:
        rows = await dbs.events.fetch_all(
            "SELECT * FROM events WHERE created_at < ? ORDER BY event_id LIMIT ?",
            (cutoff, _EVENT_ARCHIVE_BATCH),
        )
        if not rows:
            break
        archive_path = archive_dir / f"events-{datetime.now(timezone.utc):%Y%m%d}.jsonl.gz"
        with gzip.open(archive_path, "at", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(dict(row), ensure_ascii=False) + "\n")
        ids = [row["event_id"] for row in rows]
        await dbs.events.execute_many("DELETE FROM events WHERE event_id = ?", [(i,) for i in ids])
        total += len(rows)
        if len(rows) < _EVENT_ARCHIVE_BATCH:
            break
    if total:
        log.info("archived and deleted %d events older than %d days", total, EVENT_RETENTION_DAYS)
    return total


async def purge_due_accounts(dbs: Databases, bus: EventBus, settings: Settings) -> int:
    """Erase accounts whose 30-day deletion window has closed.

    This is where the promise is actually kept, so it is written to keep it even
    when things go wrong. Each account is purged in its own try block: one account
    whose vault file cannot be unlinked, or whose replay samples produce a database
    error, must not stop the accounts queued behind it from being deleted. A failure
    leaves the row scheduled, so the next night tries again, and the account is never
    silently marked done.

    Idempotent for the same reason the rest of this module is: the query selects on
    `deletion_scheduled_for <= now`, and a purged account has no row left to select.
    """
    users = UserRepo(dbs.app)
    auth = AuthService(users, bus, settings)
    due = await users.list_deletions_due(now=utc_now_iso())
    purged = 0
    for account in due:
        try:
            await auth.purge_account(
                account["id"], app_db=dbs.app, events_db=dbs.events, learn_db=dbs.learn
            )
            purged += 1
        except Exception as exc:  # noqa: BLE001 - one account must not block the rest
            log.error(
                "could not purge account public_id=%s scheduled_for=%s: %s; "
                "the row stays scheduled and tonight's failure will be retried",
                account["public_id"], account["deletion_scheduled_for"], exc,
            )
    if purged:
        log.info("purged %d account(s) whose deletion window had closed", purged)
    return purged


async def run_nightly(
    dbs: Databases, settings: Settings, bus: EventBus | None = None
) -> dict[str, int]:
    results = {
        "snapshots_retired": await retire_old_snapshots(dbs),
        "refresh_tokens_purged": await purge_expired_refresh_tokens(dbs),
        "request_metrics_purged": await purge_old_request_metrics(dbs),
        "events_archived": await archive_old_events(dbs, settings),
    }
    # `bus` is optional so `python -m app.workers.retention` still runs the sweeps
    # that need no event publishing. Account deletion does publish, and skipping it
    # silently would be the worst possible failure here, so it is logged loudly.
    if bus is not None:
        results["accounts_purged"] = await purge_due_accounts(dbs, bus, settings)
    else:
        log.warning("no event bus supplied: scheduled account deletions were NOT processed")
    log.info("nightly retention complete: %s", results)
    return results


if __name__ == "__main__":
    # `python -m app.workers.retention`: run the sweep on demand.
    import asyncio

    from app.config import get_settings

    logging.basicConfig(level=logging.INFO)

    async def _main() -> None:
        s = get_settings()
        s.ensure_dirs()
        dbs = Databases(s.app_db, s.events_db, s.learn_db)
        await dbs.connect_all()
        try:
            await run_nightly(dbs, s)
        finally:
            await dbs.close_all()

    asyncio.run(_main())
