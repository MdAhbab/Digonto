# Digonto Backend Plan

Complete engineering plan for the Digonto backend. This document is the build
reference for Claude Code. No code here, only decisions, contracts, and step
order.

> **Scope.** This file is public. Anything that must not be published lives in
> `backend/backend.internal.md`, which is untracked by git.

---

## 0. Verified model facts (checked against the running install, 26 July 2026)

`ollama show gemma4:e2b` on the development machine reports:

| Property | Value |
| --- | --- |
| Architecture | `gemma4` |
| Total parameters | 5.1B |
| Effective parameters | 2.3B (Per-Layer Embeddings keep the active count low) |
| Context length | 131,072 tokens (128K) |
| Quantisation | Q4_K_M |
| Capabilities | `completion`, `vision`, `audio`, `tools`, `thinking` |
| Licence | Apache 2.0 |
| Ollama minimum | 0.20.0 (dev machine runs 0.32.4) |

Two of these matter more than the rest. **`tools` is present**, so the four
agents use native function calling rather than a hand-written JSON parser. The
ollama.com library page tables do not list tool support for the E-variants;
`ollama show` on the actual manifest does. Trust the local manifest, and re-run
`ollama show` on the cloud VM after pulling to confirm the same tag was fetched.
**`vision` and `audio` are also present**, which is what makes document field
extraction and Bangla voice input possible on the same served model with no
second runtime.

## 1. Stack decisions

| Concern | Choice | Reason |
| --- | --- | --- |
| API framework | FastAPI (Python 3.12, uvicorn) | async-native, typed contracts via Pydantic v2, SSE support |
| Relational store | **SQLite 3.45+ in WAL mode**, accessed with `aiosqlite` | single-VM deployment, one file to back up, no separate database container, no network round trip per query |
| Event bus | Redis Streams + consumer groups | one dependency gives bus, cache, and rate limiting |
| Task workers | `arq` (async Redis queue) | lighter than Celery, same Redis instance |
| Scheduler | APScheduler inside a dedicated worker | cron-style recurrent crawls |
| LLM serving | Ollama running `gemma4:e2b` | on-VM, private, OpenAI-compatible endpoint at `/v1` |
| Embeddings | `bge-m3` via Ollama (multilingual, handles Bangla) | one runtime for all models |
| Vector store | Qdrant (Docker container) | payload filtering, collection aliasing for versioned snapshots |
| Object store | Local encrypted filesystem volume, served only through signed API routes | pairs with SQLite; removes the MinIO container |
| Cache | Redis (separate DB index) | semantic cache, session cache, HTTP cache |
| Backup | Litestream, streaming the SQLite file to off-VM object storage | continuous point-in-time recovery, no dump window |
| Reverse proxy | Caddy | automatic TLS for digonto.ahbab.dev |
| Deployment | Docker Compose on the cloud VM | single-file reproducible deploy |

### 1.1 Working with SQLite correctly

SQLite is the right choice here because the whole product is one virtual machine
and the write rate is low (crawl diffs, event archives, vault metadata). It
becomes the wrong choice if it is used like a client-server database. Rules for
the build:

1. **WAL mode from first migration.** `PRAGMA journal_mode=WAL`,
   `PRAGMA synchronous=NORMAL`, `PRAGMA foreign_keys=ON`,
   `PRAGMA busy_timeout=5000`. WAL allows many concurrent readers alongside one
   writer, which matches the read-heavy access pattern.
2. **One writer.** Route every write through a single asynchronous writer task
   with a queue. Concurrent writers on SQLite produce `SQLITE_BUSY` under load,
   and retry storms are harder to debug than a queue.
3. **Short transactions.** Never hold a write transaction across a model call or
   an HTTP fetch. Fetch first, then write.
4. **No blobs in the database.** Vault files and page snapshots live on the
   encrypted volume; SQLite stores paths, hashes, and metadata only. This keeps
   the database file small enough for Litestream to replicate cheaply.
5. **Separate databases per concern.** `app.db` (users, vault metadata, plans),
   `events.db` (event archive, audit log, append-heavy), `learn.db` (replay
   buffer). Splitting them keeps the append-heavy write load away from the
   interactive read path, and each can be backed up on its own schedule.
6. **Migration path is documented, not hidden.** If concurrency ever exceeds what
   one writer can serve, the schema is written to standard SQL so PostgreSQL can
   replace it without an application rewrite. Avoid SQLite-only constructs in
   application queries.

## 2. Event-driven architecture

Everything that changes state emits an event to Redis Streams. HTTP handlers stay
thin: validate, emit, respond. Workers do the heavy work.

### 2.1 Event catalogue

| Stream | Event | Producer | Consumers |
| --- | --- | --- | --- |
| `ev:crawl` | `portal.fetched`, `portal.changed`, `portal.unreachable` | crawler worker | diff worker, alert worker |
| `ev:kb` | `kb.chunk.updated`, `kb.version.published` | diff worker | embedding worker, cache invalidator |
| `ev:chat` | `query.received`, `answer.generated`, `answer.corrected`, `answer.failed` | API, RAG worker | analytics, replay-buffer writer |
| `ev:agent` | `agent.triggered`, `agent.tool_call`, `agent.completed`, `agent.failed` | agent runtime | audit log, notification worker |
| `ev:user` | `vault.doc.added`, `plan.step.changed`, `profile.updated` | API | Prohori agent, timeline reactor |
| `ev:learn` | `replay.sample.added`, `adapter.trained`, `adapter.promoted`, `adapter.rolled_back` | learning worker | model manager, metrics |

Rules: every event carries `event_id` (ULID), `ts`, `actor`, `schema_version`.
Consumers are idempotent, meaning re-processing the same event cannot corrupt
state. Enforce that with an `applied_events` table keyed by
`(consumer_name, event_id)` and a uniqueness constraint. Dead-letter stream
`ev:dlq` for poison messages, with an alert after 3 retries.

### 2.2 Why event-driven here specifically

The Visa Timeline Reactor and the Portal Watch agent are both consumers of the
same `portal.changed` event. A single embassy change reaches: knowledge store
update, semantic cache invalidation for affected topics, re-planning of every
student timeline that references the portal, and a Bangla alert. None of that
belongs in a request handler.

## 3. RC-RAG pipeline (the core)

### 3.1 Fast loop, per query

1. Normalise query (Bangla/Banglish/English detection; transliterate Banglish
   with a rule table plus a model pass).
2. **Semantic cache check:** embed query, cosine search against cached question
   and answer pairs (Qdrant `cache` collection). Hit threshold 0.93 **and** the
   same knowledge base version means the cached answer is served immediately.
   Target above 35 percent hit rate, because visa questions cluster heavily.
3. Retrieval: hybrid search on Qdrant (dense `bge-m3` plus sparse BM25), fused
   with reciprocal rank fusion, filtered by the student's target country and
   programme where known. Top-k 12, reranked to 4 passages.
4. Generation: `gemma4:e2b` with a strict grounded-answer prompt. Output contract
   is JSON: `answer_bn`, `answer_en`, `citations[] (snapshot_id, url,
   quoted_span)`, `confidence`, `refusal_reason?`. If no passage supports the
   answer, the model must return a refusal with a reason and must never guess.
   Enforced with structured output mode, not with prompt wording alone.
5. Stream to the client over SSE. Write `answer.generated`. Cache the pair.

**Thinking mode policy.** Gemma 4 supports a thinking mode that emits reasoning
tokens before the answer. Keep it **off** for retrieval answering and for
Porter's change classification, where it only adds latency. Keep it **on** for
Shonchari's answer scoring and Khoji's eligibility reasoning, where the quality
gain is worth the extra tokens. Make it a per-call flag, never a global setting.

### 3.2 Recurrent loop, scheduled

- Crawler worker fetches each registered portal on a per-source cron (embassies
  every 6 h, universities daily, scholarships daily).
- Snapshots are stored on the encrypted volume by content hash. If the hash is
  unchanged, stop. This is the cheap path and it is the common one.
- Diff worker computes passage-level diffs and emits `kb.chunk.updated` per
  changed passage.
- Embedding worker re-embeds only changed chunks into a new Qdrant collection
  version. `kb.version.published` flips a collection alias atomically. Old
  versions are retained 90 days, and every answer cites its `snapshot_id`
  (Truth Ledger).
- Cache invalidator drops semantic cache entries whose citations point at
  superseded snapshots.

### 3.3 Continual loop, periodic

- Replay-buffer writer captures refusals, thumbs-down answers with reviewer
  corrections, and questions where retrieval succeeded but the explanation was
  rated unclear. Stored in `learn.db` with provenance and consent flags.
- Every 2 to 4 weeks the learning worker exports the buffer, mixes it 1:1 with a
  fixed rehearsal set (samples from the original instruction distribution), and
  runs a QLoRA fine-tune off-VM or during low-traffic hours (rank 16, adapters
  only).
- Evaluation gate before promotion: a frozen benchmark of 200 held-out visa
  questions scored for groundedness, citation faithfulness, and Bangla clarity.
  Promote only if no metric regresses by more than 1 point. Emit
  `adapter.promoted` or `adapter.rolled_back`. Rebuild the Ollama Modelfile with
  the new adapter and keep the previous model tag for instant rollback.
- **Benchmark leakage audit each cycle.** Before training, hash every benchmark
  question and exclude near-duplicates from the buffer export. A gate that has
  seen its own test set proves nothing.

## 4. Caching plan (three layers)

1. **HTTP layer:** Caddy plus `Cache-Control` for static assets and snapshot
   reads; ETag on vault listings.
2. **Semantic cache:** described above. Keyed by (embedding, KB version, target
   country). TTL 7 days, invalidated by events, never served across KB versions.
3. **Inference-side cache:** Ollama `keep_alive` pinned so the model stays
   resident in RAM, and a stable system prefix (system prompt plus tool schemas)
   so prefix reuse applies. Embedding cache in Redis keyed by text hash.

## 5. API surface (contract sketch)

- `POST /v1/ask` (SSE stream), `POST /v1/ask/feedback`
- `GET/POST /v1/plan` (timeline), `POST /v1/plan/react` (internal, event-triggered)
- `POST /v1/vault/docs`, `GET /v1/vault/audit` (Prohori)
- `GET /v1/scholarships/matches` (Khoji)
- `POST /v1/interview/session` (Shonchari, WebSocket for turn-taking)
- `POST /v1/feecheck` (Agent Fee Reality Check)
- `GET /v1/sources/{snapshot_id}` (Truth Ledger, public, no auth)
- `GET /healthz`, `GET /metrics` (Prometheus)

Auth: email OTP plus JWT (short-lived access, rotating refresh). Rate limits per
user and per IP via a Redis token bucket.

## 6. Agent runtime

Agents (see `agents.md`) run as arq jobs triggered by events or cron. The runtime
loop: build context, call `gemma4:e2b` with tool schemas through Ollama's
OpenAI-compatible `/v1/chat/completions` with `tools`, execute returned tool
calls against internal services or MCP servers, iterate to a maximum of 8 steps,
emit `agent.completed` with a typed result. Every tool call is logged to the
audit table in `events.db` (input, output hash, latency). Tools are allow-listed
per agent by the runtime, not by the prompt. No agent has a delete tool.

Validation failures on structured output get one retry with the schema error fed
back. A second failure escalates per section 9.

## 7. Security and privacy

- Vault files encrypted at rest (AES-256-GCM, per-user data key wrapped by a
  master key held in an `age` keyfile outside the web root). TLS 1.3 everywhere.
  Signed URLs for uploads, 15-minute expiry.
- The SQLite files sit on the same encrypted volume, and Litestream replicas are
  encrypted before leaving the VM. A stolen backup must be useless.
- Inference is local to the VM: passports and bank statements are never sent to
  any third-party model API. This holds on the degraded path too (section 9).
- PII minimisation: the replay buffer stores no document contents, only question
  and answer text after a scrub pass (regex plus named-entity recognition for
  names, passport numbers, account numbers). Consent flag checked at write time.
- Full export and hard delete endpoints. Deletion cascades to files on the
  volume and to buffer rows, and is recorded as an event.
- Prompt-injection defence for crawled content: retrieved passages are wrapped in
  a data-only frame, tool calling is disabled during grounded answering, and
  agents treat portal text as untrusted input.

## 8. Model sizing: does a bigger model respond faster?

**No. A bigger model is always slower per token.** Decoding speed is limited by
memory bandwidth, so tokens per second falls roughly in proportion to the number
of *active* parameters. The useful question is different: does the bigger model
finish the *task* sooner, and is it correct more often?

Gemma 4 tags and what they cost, from the published family:

| Tag | Active params | Disk | Context | Use |
| --- | --- | --- | --- | --- |
| `gemma4:e2b` | 2.3B effective (5.1B total) | 7.2 GB | 128K | default chat and retrieval answering |
| `gemma4:e4b` | 4.5B effective (8B total) | 9.6 GB | 128K | agent runtime if RAM allows |
| `gemma4:12b` | 12B dense | 7.6 GB | 256K | only with a GPU |
| `gemma4:26b` | ~4B active of 26B (Mixture-of-Experts) | 18 GB | 256K | best quality per token of speed, needs RAM |
| `gemma4:31b` | 31B dense | 20 GB | 256K | GPU only, not planned |

Three practical conclusions:

1. **For chat, keep `e2b`.** Latency to first token is what a student notices.
2. **For agents, accuracy beats speed.** A malformed tool call costs a retry, and
   a retry costs a whole extra generation. A model that formats tool calls
   correctly on the first attempt can finish an agent task sooner in wall-clock
   time even though it produces fewer tokens per second. Measure end-to-end agent
   task time, not tokens per second, before choosing.
3. **`gemma4:26b` is the interesting option if the VM has 24 GB or more of RAM.**
   It is a Mixture-of-Experts model, meaning only a few expert subnetworks run
   per token, so roughly 4B parameters are active. Decode speed is therefore
   close to `e4b` while answer quality is closer to a 26B dense model. On a
   CPU-only VM this is the best quality-per-token-of-speed trade available.

Recommended plan: serve `e2b` for `/v1/ask`, and run a benchmark of the agent
task suite against `e2b`, `e4b`, and `26b` on the target VM before committing.
Two models can be served at once if RAM allows, with `keep_alive` set on both.
Thinking mode changes these numbers considerably, so benchmark with the same
thinking-mode flags the production path will use.

## 9. Degraded-mode routing

If the local model server is unavailable or an agent task fails structured-output
validation twice, requests take a degraded path behind the same internal
interface. The routing contract is specified in `backend/backend.internal.md`,
which is deliberately untracked and stays on the development machine.

Two constraints hold regardless of which path serves a request. Vault document
content never leaves the VM. Every answer carries the same citation and refusal
requirements, so a student cannot tell the difference in correctness terms.

## 10. Deployment

Docker Compose services: `caddy`, `api`, `worker-crawl`, `worker-agents`,
`worker-learn`, `ollama`, `qdrant`, `redis`, `litestream`. Dropping PostgreSQL
and MinIO removes two containers and their memory reservations, which leaves more
RAM for the model. One `docker compose up -d` on the VM behind
`digonto.ahbab.dev` DNS.

Volumes: `./data/db` (SQLite files), `./data/vault` (encrypted documents),
`./data/snapshots` (archived pages), `./data/qdrant`. Litestream replicates
`./data/db` continuously; a nightly job copies the vault and snapshot volumes
off-VM. Prometheus and Grafana are an optional profile for judging demos.

Pull the model explicitly on first boot and verify it:
`ollama pull gemma4:e2b && ollama show gemma4:e2b` should report `tools` in the
capability list before the API is allowed to start.

## 11. Build order for Claude Code

1. Scaffold FastAPI app, settings, health check, Docker Compose with all services.
2. SQLite schema and migrations across `app.db`, `events.db`, `learn.db`, with the
   PRAGMA block and the single-writer queue in place from the start.
3. Crawler worker, snapshot, diff, event chain, with two real portals as fixtures.
4. Embedding worker, Qdrant versioned collections, alias flip.
5. `/v1/ask` fast loop with semantic cache, SSE streaming, structured output contract.
6. Truth Ledger endpoint and the cache-invalidation consumer.
7. Agent runtime, then Porter, Prohori, Khoji, Shonchari in that order.
8. Timeline Reactor consumer.
9. Learning worker (buffer export, leakage audit, QLoRA job spec, evaluation gate, adapter swap).
10. Auth, rate limiting, PII scrub, audit log.
11. Degraded-mode router, last, behind a feature flag, default off. See
    `backend/backend.internal.md`.
