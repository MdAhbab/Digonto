# Digonto backend container image.
#
# Two stages. The builder compiles the handful of dependencies here that ship
# C extensions (argon2-cffi, cryptography, rpds-py via jsonschema/mcp) into a
# throwaway virtualenv; the runtime stage copies only that finished venv onto
# a bare python:3.12-slim, so no compiler, header package, or apt cache ever
# ships in the image that actually runs in production.
#
# docker-compose.prod.yml builds this same image for two services: `api`
# (default CMD below) and `worker`, which overrides CMD with
# `["python", "-m", "app.workers.main"]`. Nothing here is api-specific except
# the EXPOSE/CMD at the very end.

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# build-essential + libffi-dev + libssl-dev: most pins in requirements.txt
# (cryptography, argon2-cffi, mcp's jsonschema/rpds-py transitive deps) ship
# manylinux wheels for cpython 3.12 and never touch a compiler, but this is
# the safety net for whichever platform this gets built on that doesn't have
# a matching prebuilt wheel. None of this reaches the runtime stage below.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libffi-dev \
        libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}"

# curl: the healthcheck docker-compose.prod.yml defines for the `api` service
# hits GET /healthz; keeping curl in the image also means someone debugging a
# stuck container over `docker exec` doesn't have to install it first.
# ca-certificates: app/llm/router.py's GeminiProvider and the Gemini fallback
# path call googleapis.com over HTTPS; without this package TLS verification
# fails closed, which is correct but should never be a surprise found in prod.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The venv built in the previous stage, and nothing else from it: no
# build-essential, no headers, no apt or pip cache.
COPY --from=builder /opt/venv /opt/venv

# Non-root. Fixed uid/gid so the ownership set below is stable across rebuilds
# and matches whatever the `appdata` volume was first seeded with.
RUN groupadd --system --gid 1000 digonto \
    && useradd --system --uid 1000 --gid digonto --home-dir /app --shell /usr/sbin/nologin digonto

WORKDIR /app

# app/ carries its own migrations, at app/db/migrations/{app,events,learn}/*.sql
# (see app/db/migrate.py, MIGRATIONS_ROOT). There is no separate top-level
# migrations/ directory in this codebase, so copying app/ copies the
# migrations too; nothing else needs to be listed here.
COPY app/ ./app/

# docker-compose.prod.yml mounts the `appdata` named volume at /data for both
# `api` and `worker` (see app/config.py: db_dir/vault_dir/snapshot_dir all
# resolve under here in production). Created and chowned here so the first
# time an empty named volume is mounted over this path, it inherits writable
# ownership for the non-root user instead of root:root.
RUN mkdir -p /data/db /data/vault /data/snapshots \
    && chown -R digonto:digonto /app /data

USER digonto

EXPOSE 8000

# api's command, as run by docker-compose.prod.yml. --proxy-headers and
# --forwarded-allow-ips are required because the reverse proxy in front of
# this stack runs on the host (see docker-compose.prod.yml's header comment)
# and connects in over the loopback-published port, not from inside the
# compose network; without these flags every request would appear to
# originate from the proxy instead of the real client, which breaks the
# IP-scoped rate limiter in app/deps.py (RateLimit._identity) and the
# localhost-only gate on GET /metrics in app/main.py. Trusting `*` here is
# safe specifically because `api` publishes only to 127.0.0.1:8000, so
# nothing but that local proxy can ever open the connection uvicorn sees.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
