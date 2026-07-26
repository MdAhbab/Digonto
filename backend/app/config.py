"""Application settings.

Every value is read from the environment. Nothing here has a production-safe
default that could silently ship: secrets default to empty and are validated at
startup, so a missing key fails loudly instead of running with a known value.
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Application ---------------------------------------------------------
    app_env: Literal["development", "staging", "production"] = "development"
    app_name: str = "Digonto"
    api_base_path: str = "/api/v1"
    public_base_url: str = "http://localhost:5173"
    backend_host: str = "127.0.0.1"
    backend_port: int = 8000
    frontend_port: int = 5173

    # --- Security ------------------------------------------------------------
    jwt_secret: str = ""
    jwt_access_ttl_seconds: int = 900
    jwt_refresh_ttl_days: int = 30
    vault_master_key: str = ""

    # --- Storage -------------------------------------------------------------
    db_dir: Path = REPO_ROOT / "data" / "db"
    vault_dir: Path = REPO_ROOT / "data" / "vault"
    snapshot_dir: Path = REPO_ROOT / "data" / "snapshots"
    # Operator-only output: the nightly aggregate usage report
    # (app/workers/insights.py). Excluded from the repository, because this
    # repository is public and a usage report is the operator's business even when
    # it holds no personal data.
    private_dir: Path = REPO_ROOT / "backend" / "private"
    redis_url: str = "redis://localhost:6379/0"
    qdrant_url: str = "http://localhost:6333"

    # --- Models --------------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    gemma_model: str = "gemma4:e2b"
    embed_model: str = "bge-m3"
    ollama_keep_alive: str = "30m"

    # Provider routing. See app/llm/router.py for what "fast" and "core" mean.
    # These defaults are the intended deployment, not a placeholder: the previous
    # default lived only in an untracked .env, so a fresh checkout silently ran a
    # different routing to the one the deployment was tuned for.
    fast_path_provider: Literal["gemma", "gemini"] = "gemini"
    core_path_provider: Literal["gemma", "gemini"] = "gemma"
    fallback_enabled: bool = True

    # Ordered chain of remote models, tried left to right. The first with capacity serves
    # the request; when one is rate limited the next takes over; when none is left the local
    # model takes over. Entries are `name` or `name:rpm:rpd`, and a missing limit falls back
    # to `fallback_max_rpm` / `fallback_daily_budget`.
    #
    # The per-model limits are the published free-tier ceilings for this project, and they
    # differ by a factor of twenty five, which is why they cannot be one shared number. The
    # order puts the four strongest models first, each with only 20 requests a day, and then
    # rests on the two lite models that allow 500. Once the small quotas are spent the chain
    # settles on the high-volume ones by itself, so the good models are used where they can
    # be and nothing stops working when they run out.
    #
    # Excluded because this project has no free quota for them (0 per minute, 0 per day):
    # every `gemini-2.0-*`, `gemini-2.5-pro`, `gemini-3-pro-preview`, `gemini-3.1-pro-*` and
    # `gemini-omni-flash`. Also excluded: the image, TTS, embedding and robotics variants,
    # which do not answer text prompts.
    fallback_models: str = (
        "gemini-3.6-flash:5:20,"
        "gemini-3.5-flash:5:20,"
        "gemini-3-flash-preview:5:20,"
        "gemini-2.5-flash:5:20,"
        "gemini-3.5-flash-lite:15:500,"
        "gemini-3.1-flash-lite:15:500,"
        "gemini-2.5-flash-lite:10:20"
    )

    # Defaults for a chain entry that does not carry its own limits.
    #
    # These were 2.0 requests per second and 2000 per day, which is 120 a minute against a
    # real limit of 5, so the local ceiling could never trip before Google's did and the
    # first sign of trouble was a 429 in production.
    fallback_max_rpm: int = 5
    fallback_daily_budget: int = 20
    gemini_api_key: str = ""

    @property
    def fallback_model_chain(self) -> list[tuple[str, int, int]]:
        """`(name, rpm, rpd)` per entry, in priority order.

        Malformed limits fall back to the defaults rather than raising. A typo in one entry
        of an environment variable should cost that entry its tuning, not stop the process
        from starting.
        """
        chain: list[tuple[str, int, int]] = []
        for raw in self.fallback_models.split(","):
            entry = raw.strip()
            if not entry:
                continue
            parts = entry.split(":")
            name = parts[0].strip()
            if not name:
                continue

            def _num(index: int, default: int) -> int:
                try:
                    return int(parts[index])
                except (IndexError, ValueError):
                    return default

            chain.append((name, _num(1, self.fallback_max_rpm), _num(2, self.fallback_daily_budget)))
        return chain

    @property
    def fallback_model(self) -> str:
        """The preferred remote model. Logs and reports name this one."""
        chain = self.fallback_model_chain
        return chain[0][0] if chain else ""

    # --- Retrieval tuning ----------------------------------------------------
    retrieval_top_k: int = 12
    retrieval_rerank_to: int = 4
    semantic_cache_threshold: float = 0.93
    semantic_cache_ttl_days: int = 7

    # --- Limits --------------------------------------------------------------
    max_upload_bytes: int = 20 * 1024 * 1024
    agent_max_steps: int = 8

    # --- Seeding -------------------------------------------------------------
    seed_judge_email: str = "judge@digonto.ahbab.dev"
    seed_judge_password: str = ""
    seed_moderator_email: str = "moderator@digonto.ahbab.dev"
    seed_moderator_password: str = ""
    seed_demo_data: bool = True

    # --- Derived -------------------------------------------------------------
    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def app_db(self) -> Path:
        return self.db_dir / "app.db"

    @property
    def events_db(self) -> Path:
        return self.db_dir / "events.db"

    @property
    def learn_db(self) -> Path:
        return self.db_dir / "learn.db"

    @property
    def cors_origins(self) -> list[str]:
        if self.is_production:
            return [self.public_base_url]
        return [
            f"http://localhost:{self.frontend_port}",
            f"http://127.0.0.1:{self.frontend_port}",
        ]

    @field_validator("db_dir", "vault_dir", "snapshot_dir", "private_dir", mode="after")
    @classmethod
    def _resolve_dir(cls, v: Path) -> Path:
        return v if v.is_absolute() else (REPO_ROOT / v).resolve()

    @model_validator(mode="after")
    def _validate_secrets(self) -> "Settings":
        # Development convenience: generate ephemeral secrets so a first run
        # works. Production must supply them, because an ephemeral JWT secret
        # would log every user out on each restart.
        if not self.jwt_secret:
            if self.is_production:
                raise ValueError("JWT_SECRET must be set in production")
            self.jwt_secret = secrets.token_urlsafe(48)
        if not self.vault_master_key:
            if self.is_production:
                raise ValueError("VAULT_MASTER_KEY must be set in production")
            self.vault_master_key = secrets.token_urlsafe(32)

        if self.fallback_enabled and not self.gemini_api_key:
            # Not fatal. The system is designed to run entirely on the local
            # model; the alternate provider is an optimisation, not a
            # dependency. Degrade to local-only rather than refusing to start.
            self.fallback_enabled = False
            self.fast_path_provider = "gemma"
            self.core_path_provider = "gemma"
        return self

    def ensure_dirs(self) -> None:
        for d in (self.db_dir, self.vault_dir, self.snapshot_dir, self.private_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
