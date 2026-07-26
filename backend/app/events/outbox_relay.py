"""Replay durable `events.db` rows into Redis when `xadd` failed after insert.

SQLite is written first in `EventBus.publish`; Redis is best-effort delivery.
This module closes the gap so crawl/diff/ask side effects are not stranded.
"""

from __future__ import annotations

import logging

from app.events.bus import EventBus

log = logging.getLogger(__name__)

# How often the worker replays the outbox (see app/workers/main.py).
RELAY_INTERVAL_SECONDS = 60


async def relay_outbox(bus: EventBus, *, batch_size: int = 200) -> int:
    """Relay pending archived events. Returns how many were xadd'd."""
    count = await bus.relay_pending(batch_size=batch_size)
    if count:
        log.info("outbox relay delivered %d event(s) to Redis", count)
    return count
