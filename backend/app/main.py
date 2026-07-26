"""Digonto FastAPI application factory.

Lifespan wires up the three SQLite databases, runs migrations, and constructs
the shared Redis client, EventBus, and ModelRouter once, storing them on
`app.state` for app/deps.py to hand out. Routers are mounted defensively: the
routers/services/agents package is owned by a different work stream and may
not exist yet, so a missing `app.routers` module must not stop this app from
booting health checks and the auth foundation on its own.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from redis.asyncio import Redis
from ulid import ULID

from app.config import get_settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.errors import Forbidden, install_exception_handlers
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.security.passwords import hash_password

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _seed_demo_accounts(dbs: Databases) -> None:
    """Create the judge and moderator accounts, idempotently.

    Only the accounts themselves: docs/api_contract.md section 3.1 describes
    the judge account as "a fully populated student" with targets, documents,
    a plan, and a completed interview, but populating that realistic scenario
    means writing rows through the profile/vault/planner/interview services
    that another work stream owns. Creating them here would either duplicate
    that logic or invent schema shortcuts. Scope for this factory is the two
    user rows, both flagged is_demo=1 so they can be excluded from stats and
    wiped in one command; a follow-up seed script (or the owning services'
    fixtures) is the right place for the rest.
    """
    settings = get_settings()
    if settings.is_production or not settings.seed_demo_data:
        return

    now = _now_iso()
    accounts = (
        (settings.seed_judge_email, settings.seed_judge_password, "student", "Judge"),
        (settings.seed_moderator_email, settings.seed_moderator_password, "moderator", "Moderator"),
    )
    for email, password, role, display_name in accounts:
        if not email or not password:
            log.warning("skipping seed account email=%s: SEED_* password not configured", email)
            continue
        existing = await dbs.app.fetch_val("SELECT id FROM users WHERE email = ?", (email,))
        if existing:
            continue
        await dbs.app.execute(
            """
            INSERT INTO users
                (public_id, email, password_hash, display_name, role, status,
                 email_verified, is_demo, created_at)
            VALUES (?, ?, ?, ?, ?, 'active', 1, 1, ?)
            """,
            (str(ULID()), email, hash_password(password), display_name, role, now),
        )
        log.info("seeded demo account role=%s email=%s", role, email)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    settings.ensure_dirs()

    dbs = Databases(settings.app_db, settings.events_db, settings.learn_db)
    await dbs.connect_all()
    await run_migrations(dbs)

    # decode_responses=True: app/events/bus.py and app/deps.py both assume
    # str fields, not bytes, out of this client.
    redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)
    bus = EventBus(redis_client, dbs.events)
    model_router = ModelRouter(settings)
    http_client = httpx.AsyncClient()

    app.state.settings = settings
    app.state.dbs = dbs
    app.state.redis = redis_client
    app.state.bus = bus
    app.state.model_router = model_router
    app.state.http_client = http_client
    app.state.started_at = time.monotonic()

    await _seed_demo_accounts(dbs)

    log.info("digonto backend ready env=%s", settings.app_env)
    try:
        yield
    finally:
        await model_router.aclose()
        await http_client.aclose()
        await redis_client.aclose()
        await dbs.close_all()


def _register_routers(app: FastAPI) -> None:
    try:
        from app.routers import router as api_router  # type: ignore[import-not-found]
    except ImportError as exc:
        log.warning(
            "app.routers not available yet (%s); booting with health checks only", exc
        )
        return
    app.include_router(api_router, prefix=get_settings().api_base_path)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def _observe_request(request: Request, call_next):  # type: ignore[no-untyped-def]
        # trace_id: the request ULID that appears in events.db and in every
        # problem-details body (docs/api_contract.md section 1).
        request.state.trace_id = str(ULID())
        started = time.monotonic()
        response = await call_next(request)
        elapsed = time.monotonic() - started

        route = request.scope.get("route")
        path_label = route.path if route is not None else request.url.path
        REQUEST_COUNT.labels(request.method, path_label, response.status_code).inc()
        REQUEST_LATENCY.labels(request.method, path_label).observe(elapsed)

        response.headers["X-Trace-Id"] = request.state.trace_id
        return response

    install_exception_handlers(app)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {
            "status": "ok",
            "version": settings.app_name,
            "uptime_s": int(time.monotonic() - app.state.started_at),
        }

    @app.get("/readyz")
    async def readyz() -> JSONResponse:
        checks: dict[str, str] = {}

        try:
            await app.state.dbs.app.fetch_val("SELECT 1")
            checks["sqlite"] = "ok"
        except Exception as exc:  # noqa: BLE001 - readiness must never 500
            checks["sqlite"] = f"error: {exc}"

        try:
            await app.state.redis.ping()
            checks["redis"] = "ok"
        except Exception as exc:  # noqa: BLE001
            checks["redis"] = f"error: {exc}"

        try:
            r = await app.state.http_client.get(f"{settings.qdrant_url}/readyz", timeout=3.0)
            checks["qdrant"] = "ok" if r.status_code == 200 else f"status {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            checks["qdrant"] = f"error: {exc}"

        try:
            checks["ollama"] = "ok" if await app.state.model_router.gemma.available() else "unavailable"
        except Exception as exc:  # noqa: BLE001
            checks["ollama"] = f"error: {exc}"

        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(status_code=200 if healthy else 503, content={"checks": checks})

    @app.get("/metrics")
    async def metrics(request: Request) -> PlainTextResponse:
        # Prometheus text; Caddy is expected to keep this off the public
        # internet (docs/api_contract.md section 2), this is a second,
        # best-effort gate for anything that talks to the app directly.
        if settings.is_production:
            client_host = request.client.host if request.client else ""
            if client_host not in ("127.0.0.1", "::1", "localhost"):
                raise Forbidden(
                    detail_en="Metrics are only available from localhost.",
                    detail_bn="মেট্রিক্স শুধুমাত্র লোকালহোস্ট থেকে দেখা যায়।",
                )
        return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    _register_routers(app)
    return app


app = create_app()
