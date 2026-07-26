"""Digonto FastAPI application factory.

Lifespan wires up the three SQLite databases, runs migrations, and constructs
the shared Redis client, EventBus, ModelRouter, Qdrant client, and Embedder
once, storing them on `app.state` for app/deps.py to hand out. Nothing in a
request path builds its own connection pool.
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
from qdrant_client import AsyncQdrantClient
from redis.asyncio import Redis
from ulid import ULID

from app.config import get_settings
from app.db.connection import Databases
from app.db.migrate import run_migrations
from app.db.seed_demo import seed_demo
from app.errors import Forbidden, install_exception_handlers
from app.events.bus import EventBus
from app.llm.router import ModelRouter
from app.rag.cache import SemanticCache
from app.rag.embeddings import Embedder
from app.rag.retrieval import Retriever

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

REQUEST_COUNT = Counter(
    "http_requests_total", "Total HTTP requests", ["method", "path", "status"]
)
REQUEST_LATENCY = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["method", "path"]
)


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
    # An explicit timeout, because httpx's default is 5 seconds and this client is
    # shared with the model router and the embedder. Cold-loading an embedding model
    # takes longer than 5 seconds on a small machine, so every question failed with a
    # bare `ReadTimeout` once bge-m3 had been evicted from memory: the retrieval
    # fallback could not help, because the request died before retrieval was reached.
    #
    # Split rather than a single float. A slow *connect* means the model server is not
    # there and should fail quickly; a slow *read* means it is loading or generating and
    # should be waited for. One number cannot express both.
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=180.0, write=30.0, pool=10.0)
    )
    model_router = ModelRouter(settings, client=http_client)

    # Retrieval clients are built once here, not per question. Constructing them
    # inside the ask path meant every question created two AsyncQdrantClient
    # instances that were never closed, and an Embedder with no Redis handle,
    # which silently disabled the embedding cache that backend.md section 4.3
    # describes. Both are corrected by owning them for the process lifetime.
    qdrant = AsyncQdrantClient(url=settings.qdrant_url)
    embedder = Embedder(settings, redis=redis_client, client=http_client)
    # `db=dbs.app` gives the retriever the SQLite lexical fallback, so a Qdrant
    # outage or an unpublished first knowledge version degrades recall instead of
    # taking every question down. See Retriever.lexical_only.
    retriever = Retriever(embedder, settings, qdrant=qdrant, db=dbs.app)
    semantic_cache = SemanticCache(embedder, settings, qdrant=qdrant)
    await retriever.ensure_collections()

    app.state.settings = settings
    app.state.dbs = dbs
    app.state.redis = redis_client
    app.state.bus = bus
    app.state.model_router = model_router
    app.state.http_client = http_client
    app.state.qdrant = qdrant
    app.state.embedder = embedder
    app.state.retriever = retriever
    app.state.semantic_cache = semantic_cache
    app.state.started_at = time.monotonic()

    await seed_demo(dbs, settings)

    log.info("digonto backend ready env=%s", settings.app_env)
    try:
        yield
    finally:
        # Order matters: close borrowers of the shared httpx client before the
        # client itself, and the databases last so a shutdown-time write still
        # has somewhere to go.
        await embedder.aclose()
        await qdrant.close()
        await model_router.aclose()
        await http_client.aclose()
        await redis_client.aclose()
        await dbs.close_all()


def _register_routers(app: FastAPI) -> None:
    """Mount the API surface.

    This deliberately does not catch ImportError. It used to, from the period
    when the router package was being written by a separate work stream and a
    missing module legitimately meant "not built yet". That tolerance is now a
    hazard: a typo or a missing dependency anywhere in the router tree would
    boot an API with zero endpoints, 404 every route, and still report healthy
    on /healthz, which is the worst possible failure shape for something a
    judge or a student is about to use. A broken import should stop the process.
    """
    from app.routers import router as api_router

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
