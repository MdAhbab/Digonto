"""Continual-learning worker. backend/backend.md section 3.3.

Three separable jobs live here, run in sequence but independently
resumable:

1. `run_learning_cycle` — export the replay buffer (minus a benchmark
   leakage audit) to a training file and job spec, on a schedule and on
   demand (`python -m app.workers.learner`).
2. `check_for_completed_jobs` — poll for an external QLoRA run reporting
   back, then run the promotion gate against the frozen benchmark.
3. `promote_adapter` / `rollback_adapter` — the two outcomes of the human
   approval step this module deliberately stops short of; exposed here for
   whatever calls them once approved (docs/api_contract.md section 11a
   `POST /mod/adapters/{id}/promote`), since that route is a router/service
   concern this build does not own.

Training itself never happens in this process. This module writes a job
spec an external run consumes and reports back to via a `result.json` file
dropped in the same job directory — there being no HTTP endpoint for this
in the current build (routers are out of scope here) and no GPU in this
process to train on.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from qdrant_client import AsyncQdrantClient

from app.config import Settings
from app.db.connection import Databases
from app.events.bus import EventBus, EventType
from app.repositories._util import utc_now_iso
from app.workers._kb import embed_texts

log = logging.getLogger(__name__)

ADAPTER_RANK = 16
_WS_RE = re.compile(r"\s+")
_BANGLA_RE = re.compile(r"[ঀ-৿]")

# "No metric may drop more than 1 point" (backend/backend.md section 3.3).
# Every metric here is reported on a 0-100 scale, so this is 1 percentage point.
MAX_REGRESSION_POINTS = 1.0

_GROUNDED_SCHEMA = {
    "type": "object",
    "properties": {
        "answer_en": {"type": "string"},
        "answer_bn": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "snapshot_id": {"type": "integer"},
                    "quoted_span": {"type": "string"},
                },
                "required": ["snapshot_id", "quoted_span"],
            },
        },
        "confidence": {"type": "number"},
        "refusal_reason": {"type": ["string", "null"]},
    },
    "required": ["answer_en", "answer_bn", "citations", "confidence"],
}

_BENCHMARK_SYSTEM = (
    "You answer a Bangladeshi student's visa/study-abroad question using only "
    "the passages given. Cite the snapshot id of every passage you rely on. "
    "If the passages do not support an answer, set refusal_reason and leave "
    "answer_en/answer_bn brief rather than guessing. Answer in both English "
    "and natural Bangla."
)


def _training_root(settings: Settings) -> Path:
    # Sibling of data/db, data/vault, data/snapshots (app/config.py's layout),
    # not itself a Settings field: this worker owns the convention, config.py
    # does not need to know about the training pipeline's directory shape.
    return settings.db_dir.parent / "training"


def _question_hash(text: str) -> str:
    """Must match however `benchmark_questions.question_hash` was frozen.
    Nothing else in this codebase computes that hash (it predates this
    build), so this picks the most standard normalisation — lowercase,
    whitespace-collapsed, utf-8, sha256 — and the leakage audit is only as
    good as that assumption holding.
    """
    normalised = _WS_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _bangla_ratio(text: str) -> float:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 0.0
    return min(1.0, len(_BANGLA_RE.findall(text)) / len(letters))


def _new_adapter_tag() -> str:
    return f"digonto-{datetime.now(timezone.utc):%Y-%m-%d}-{secrets.token_hex(3)}"


# --- 1. Export cycle ---------------------------------------------------------


async def _write_training_artifacts(
    settings: Settings, tag: str, samples: list[dict[str, Any]]
) -> Path:
    root = _training_root(settings) / tag
    root.mkdir(parents=True, exist_ok=True)

    train_path = root / "train.jsonl"
    with train_path.open("w", encoding="utf-8") as fh:
        for s in samples:
            record = {
                "id": s["id"],
                "kind": s["kind"],
                "lang": s["lang"],
                "question": s["question"],
                # A verified correction is the highest-value training signal
                # this system produces (docs/api_contract.md section 11a);
                # prefer it over the original (possibly wrong) answer.
                "answer": s["correction"] or s["answer"],
                "is_correction": bool(s["correction"]),
            }
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    job = {
        "adapter_tag": tag,
        "base_model": settings.gemma_model,
        "rank": ADAPTER_RANK,
        "rehearsal_ratio": 1.0,
        "sample_count": len(samples),
        "train_file": "train.jsonl",
        "created_at": utc_now_iso(),
        "note": (
            "Off-VM QLoRA run (backend/backend.md section 3.3). Mix train.jsonl "
            "1:1 with the fixed rehearsal set held by the training pipeline; "
            "this application ships no rehearsal corpus of its own. On "
            "completion, write result.json in this same directory: "
            '{"status": "complete"} or {"status": "failed", "error": "..."}.'
        ),
    }
    (root / "job.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
    return root


async def run_learning_cycle(dbs: Databases, settings: Settings) -> None:
    """Export unexported, consented, scrubbed replay samples, after excluding
    anything that leaked into the frozen benchmark. Writes a job spec; does
    not train."""
    candidates = [
        dict(r)
        for r in await dbs.learn.fetch_all(
            """SELECT * FROM replay_samples
               WHERE exported_in IS NULL AND consent = 1 AND pii_scrubbed = 1
               ORDER BY created_at"""
        )
    ]
    if not candidates:
        log.info("no unexported replay samples; skipping this learning cycle")
        return

    benchmark_hashes = {
        r["question_hash"]
        for r in await dbs.learn.fetch_all("SELECT question_hash FROM benchmark_questions")
    }

    clean: list[dict[str, Any]] = []
    leaked_ids: list[int] = []
    for sample in candidates:
        if _question_hash(sample["question"]) in benchmark_hashes:
            leaked_ids.append(sample["id"])
        else:
            clean.append(sample)

    if leaked_ids:
        await dbs.learn.execute_many(
            "UPDATE replay_samples SET benchmark_leak = 1 WHERE id = ?",
            [(i,) for i in leaked_ids],
        )
        log.warning(
            "benchmark leakage audit excluded %d/%d candidate samples",
            len(leaked_ids), len(candidates),
        )

    if not clean:
        log.warning("every candidate sample this cycle matched the frozen benchmark; nothing to export")
        return

    tag = _new_adapter_tag()
    now = utc_now_iso()
    adapter_id = await dbs.learn.execute(
        """INSERT INTO adapters
           (tag, base_model, rank, sample_count, rehearsal_ratio, status, trained_at)
           VALUES (?, ?, ?, ?, ?, 'training', ?)""",
        (tag, settings.gemma_model, ADAPTER_RANK, len(clean), 1.0, now),
    )

    job_dir = await _write_training_artifacts(settings, tag, clean)

    await dbs.learn.execute_many(
        "UPDATE replay_samples SET exported_in = ? WHERE id = ?",
        [(adapter_id, s["id"]) for s in clean],
    )
    log.info(
        "learning cycle exported %d samples to %s as adapter %s (rank %d, awaiting "
        "an external QLoRA run to report back via result.json)",
        len(clean), job_dir, tag, ADAPTER_RANK,
    )


# --- 2. External-run polling and the promotion gate --------------------------


async def _model_available(http_client: httpx.AsyncClient, settings: Settings, model_tag: str) -> bool:
    try:
        r = await http_client.get(f"{settings.ollama_base_url}/api/tags", timeout=10.0)
        r.raise_for_status()
    except httpx.HTTPError:
        return False
    names = {m.get("name") for m in (r.json().get("models") or [])}
    return model_tag in names or any((n or "").split(":")[0] == model_tag for n in names)


async def _chat_json(
    http_client: httpx.AsyncClient,
    settings: Settings,
    model_tag: str,
    *,
    system: str,
    user: str,
    schema: dict[str, Any],
) -> tuple[dict[str, Any], int]:
    started = time.monotonic()
    r = await http_client.post(
        f"{settings.ollama_base_url}/api/chat",
        json={
            "model": model_tag,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "stream": False,
            "format": schema,
            "options": {"temperature": 0.1, "num_predict": 768},
            "keep_alive": settings.ollama_keep_alive,
        },
        timeout=180.0,
    )
    r.raise_for_status()
    data = r.json()
    latency_ms = int((time.monotonic() - started) * 1000)
    content = (data.get("message") or {}).get("content", "")
    return json.loads(content), latency_ms


async def _score_benchmark(
    *,
    dbs: Databases,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
    model_tag: str,
    questions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Scores one model tag against the frozen benchmark.

    Grounding, refusal-correctness, and Bangla clarity are measured
    deterministically from the model's own structured output rather than by
    a second LLM-judge call: `app/rag/pipeline.py` (the real hybrid
    retrieval + reranking pipeline) is an explicit stub in this codebase, so
    this worker does its own minimal dense-only retrieval directly against
    the live Qdrant collection, in keeping with Prohori's philosophy
    elsewhere in this build that a reproducible deterministic check beats a
    second fluent-but-unverifiable model call.
    """
    if not await _model_available(http_client, settings, model_tag):
        log.error("model tag %s is not pulled in Ollama; cannot score it", model_tag)
        return None

    live = await dbs.app.fetch_one("SELECT * FROM kb_versions WHERE status = 'live'")
    if live is None:
        log.error("no live kb_version; cannot retrieve grounding passages for the benchmark")
        return None
    live_collection = live["qdrant_collection"]

    grounded_flags: list[bool] = []
    refused_flags: list[bool] = []
    bangla_ratios: list[float] = []
    latencies: list[int] = []
    raw: list[dict[str, Any]] = []

    for q in questions:
        vectors = await embed_texts(http_client, settings, [q["question_en"]])
        vector = vectors[0]
        hits = (
            await qdrant.query_points(
                live_collection, query=vector, limit=settings.retrieval_top_k, with_payload=True
            )
        ).points
        top = hits[: settings.retrieval_rerank_to]
        passage_ids = [h.payload.get("passage_id") for h in top if h.payload]

        context = ""
        if passage_ids:
            placeholders = ",".join("?" * len(passage_ids))
            rows = await dbs.app.fetch_all(
                f"SELECT text, snapshot_id FROM passages WHERE id IN ({placeholders})",
                passage_ids,
            )
            context = "\n\n".join(f"[snapshot {r['snapshot_id']}] {r['text']}" for r in rows)

        try:
            data, latency_ms = await _chat_json(
                http_client, settings, model_tag,
                system=_BENCHMARK_SYSTEM,
                user=f"PASSAGES:\n{context or 'none retrieved'}\n\nQUESTION: {q['question_en']}",
                schema=_GROUNDED_SCHEMA,
            )
        except (httpx.HTTPError, ValueError) as exc:
            log.warning(
                "benchmark call failed model=%s question_id=%s err=%s", model_tag, q["id"], exc
            )
            grounded_flags.append(False)
            refused_flags.append(True)
            bangla_ratios.append(0.0)
            raw.append({"question_id": q["id"], "error": str(exc)})
            continue

        latencies.append(latency_ms)
        citations = data.get("citations") or []
        cited_snapshots = {c.get("snapshot_id") for c in citations if isinstance(c, dict)}
        grounded = bool(cited_snapshots) and (
            q.get("gold_snapshot_id") is None or q["gold_snapshot_id"] in cited_snapshots
        )
        refused = bool(data.get("refusal_reason"))
        grounded_flags.append(grounded)
        refused_flags.append(refused)
        bangla_ratios.append(_bangla_ratio(data.get("answer_bn", "")))
        raw.append({"question_id": q["id"], "grounded": grounded, "refused": refused})

    def _pct(flags: list[bool]) -> float:
        return round(100.0 * (sum(1 for f in flags if f) / len(flags)), 2) if flags else 0.0

    latencies.sort()

    def _pctl(p: float) -> int:
        if not latencies:
            return 0
        return latencies[min(len(latencies) - 1, int(len(latencies) * p))]

    return {
        "groundedness": _pct(grounded_flags),
        # Every benchmark question has a real gold answer, so a refusal is
        # always the wrong call here; "correctness" is "did not refuse".
        "refusal_correctness": _pct([not r for r in refused_flags]),
        "bangla_clarity": round(100.0 * (sum(bangla_ratios) / len(bangla_ratios)), 2)
        if bangla_ratios else 0.0,
        "latency_p50_ms": _pctl(0.50),
        "latency_p95_ms": _pctl(0.95),
        "question_count": len(questions),
        "raw_results": raw,
    }


async def _run_promotion_gate(
    *,
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
    adapter: dict[str, Any],
) -> None:
    questions = [dict(r) for r in await dbs.learn.fetch_all("SELECT * FROM benchmark_questions")]
    if not questions:
        log.error(
            "no frozen benchmark_questions; cannot gate adapter %s. Leaving it at "
            "status='training' until an operator freezes a benchmark.",
            adapter["tag"],
        )
        return

    candidate_metrics = await _score_benchmark(
        dbs=dbs, settings=settings, http_client=http_client, qdrant=qdrant,
        model_tag=adapter["tag"], questions=questions,
    )
    if candidate_metrics is None:
        return  # already logged why; adapter stays 'training' for a later retry

    incumbent_row = await dbs.learn.fetch_one(
        "SELECT * FROM adapters WHERE status = 'promoted' ORDER BY promoted_at DESC LIMIT 1"
    )
    incumbent_tag = incumbent_row["tag"] if incumbent_row else settings.gemma_model
    incumbent_metrics = await _score_benchmark(
        dbs=dbs, settings=settings, http_client=http_client, qdrant=qdrant,
        model_tag=incumbent_tag, questions=questions,
    )
    if incumbent_metrics is None:
        log.error("incumbent model %s unavailable; cannot compare, leaving adapter pending", incumbent_tag)
        return

    now = utc_now_iso()
    for adapter_id, model_tag, metrics in (
        (adapter["id"], adapter["tag"], candidate_metrics),
        (incumbent_row["id"] if incumbent_row else None, incumbent_tag, incumbent_metrics),
    ):
        await dbs.learn.execute(
            """INSERT INTO benchmark_runs
               (adapter_id, model_tag, groundedness, refusal_correctness, bangla_clarity,
                latency_p50_ms, latency_p95_ms, question_count, raw_results, run_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                adapter_id, model_tag, metrics["groundedness"], metrics["refusal_correctness"],
                metrics["bangla_clarity"], metrics["latency_p50_ms"], metrics["latency_p95_ms"],
                metrics["question_count"], json.dumps(metrics["raw_results"]), now,
            ),
        )

    regressions = {
        metric: incumbent_metrics[metric] - candidate_metrics[metric]
        for metric in ("groundedness", "refusal_correctness", "bangla_clarity")
        if incumbent_metrics[metric] - candidate_metrics[metric] > MAX_REGRESSION_POINTS
    }

    if regressions:
        reason = "; ".join(f"{k} dropped {v:.1f} points" for k, v in regressions.items())
        await rollback_adapter(dbs, bus, adapter["id"], reason=f"promotion gate failed: {reason}")
        return

    await dbs.learn.execute("UPDATE adapters SET status = 'candidate' WHERE id = ?", (adapter["id"],))
    log.info(
        "adapter %s passed the promotion gate against %s; awaiting moderator approval "
        "(docs/api_contract.md section 11a, POST /mod/adapters/%s/promote)",
        adapter["tag"], incumbent_tag, adapter["id"],
    )


async def check_for_completed_jobs(
    dbs: Databases,
    bus: EventBus,
    settings: Settings,
    http_client: httpx.AsyncClient,
    qdrant: AsyncQdrantClient,
) -> None:
    """Poll job directories for a `result.json` an external training run
    dropped, then run the promotion gate. Idempotent: once an adapter leaves
    status='training' it is never selected here again."""
    training_rows = [
        dict(r) for r in await dbs.learn.fetch_all("SELECT * FROM adapters WHERE status = 'training'")
    ]
    for adapter in training_rows:
        result_path = _training_root(settings) / adapter["tag"] / "result.json"
        if not result_path.exists():
            continue
        try:
            result = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("unreadable result.json for adapter %s: %s", adapter["tag"], exc)
            continue

        if result.get("status") != "complete":
            await dbs.learn.execute(
                "UPDATE adapters SET status = 'failed', notes = ? WHERE id = ?",
                (str(result.get("error") or "external training run reported failure"), adapter["id"]),
            )
            log.warning("adapter %s training failed: %s", adapter["tag"], result.get("error"))
            continue

        await bus.publish(
            EventType.ADAPTER_TRAINED,
            payload={"adapter_id": adapter["id"], "tag": adapter["tag"], "sample_count": adapter["sample_count"]},
            actor="worker:learner",
            subject_type="adapter",
            subject_id=adapter["tag"],
        )
        await _run_promotion_gate(
            dbs=dbs, bus=bus, settings=settings, http_client=http_client, qdrant=qdrant, adapter=adapter
        )


# --- 3. Human-approved outcomes -----------------------------------------------


async def promote_adapter(
    dbs: Databases, bus: EventBus, adapter_id: int, *, note: str | None = None
) -> None:
    """Flip a gated, human-approved adapter live.

    Nothing in app/workers reaches this on its own: promotion is the human
    step docs/api_contract.md section 11a requires
    (`POST /mod/adapters/{id}/promote`), which lives in a router this build
    does not own. This is the mechanics that route is expected to call.
    """
    now = utc_now_iso()
    await dbs.learn.execute(
        "UPDATE adapters SET status = 'promoted', promoted_at = ?, notes = COALESCE(?, notes) WHERE id = ?",
        (now, note, adapter_id),
    )
    row = await dbs.learn.fetch_one("SELECT * FROM adapters WHERE id = ?", (adapter_id,))
    if row is None:
        return
    await bus.publish(
        EventType.ADAPTER_PROMOTED,
        payload={"adapter_id": adapter_id, "tag": row["tag"]},
        actor="worker:learner",
        subject_type="adapter",
        subject_id=row["tag"],
    )


async def rollback_adapter(dbs: Databases, bus: EventBus, adapter_id: int, *, reason: str) -> None:
    now = utc_now_iso()
    await dbs.learn.execute(
        "UPDATE adapters SET status = 'rolled_back', rolled_back_at = ?, notes = ? WHERE id = ?",
        (now, reason, adapter_id),
    )
    row = await dbs.learn.fetch_one("SELECT * FROM adapters WHERE id = ?", (adapter_id,))
    if row is None:
        return
    await bus.publish(
        EventType.ADAPTER_ROLLED_BACK,
        payload={"adapter_id": adapter_id, "tag": row["tag"], "reason": reason},
        actor="worker:learner",
        subject_type="adapter",
        subject_id=row["tag"],
    )


if __name__ == "__main__":
    # `python -m app.workers.learner`: run one export cycle on demand,
    # outside the 2-4 week schedule app/workers/main.py otherwise drives it on.
    import asyncio

    from app.config import get_settings
    from app.db.connection import Databases as _Databases

    logging.basicConfig(level=logging.INFO)

    async def _main() -> None:
        settings = get_settings()
        settings.ensure_dirs()
        dbs = _Databases(settings.app_db, settings.events_db, settings.learn_db)
        await dbs.connect_all()
        try:
            await run_learning_cycle(dbs, settings)
        finally:
            await dbs.close_all()

    asyncio.run(_main())
