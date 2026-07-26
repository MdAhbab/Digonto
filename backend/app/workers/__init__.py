"""Background worker layer: crawl, diff, embed, learn, retain.

Everything in this package is a consumer of `app.events.bus.EventBus` or an
APScheduler cron job, never an HTTP handler. `app/workers/main.py` is the
process entrypoint (`python -m app.workers.main`, see
docker-compose.prod.yml's `worker` service); the other modules are imported
by it and are also independently runnable for ops (`python -m
app.workers.learner`, `python -m app.workers.retention`).
"""

from __future__ import annotations
