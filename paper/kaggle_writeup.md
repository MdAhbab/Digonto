# Digonto (দিগন্ত): a free Bangla Study Abroad and Visa Navigator

**Kaggle Writeup, Build With Gemma @ Bangladesh.** Tracks: Local Language
(primary) and Autonomous Agent. Live: https://digonto.ahbab.dev
Under 2,000 words. 11 graphics, listed at the end.

## 1. Problem statement

UNESCO counted 52,799 Bangladeshi students studying abroad in 2023 across 55
countries, roughly three times the figure of fifteen years earlier. Families paid
667.77 million US dollars for overseas education in FY25 through 109,290 banking
transactions, a record for a single year.

The information behind those journeys is public. Embassy requirements, university
deadlines, and scholarship rules are all published. They are published in dense
administrative English, spread across dozens of portals, and revised without
announcement.

That gap feeds an intermediary market of roughly 2,000 consultancy firms, of
which only about 400 are registered with the sector association. The rest operate
on a general trade licence with no specialised supervision. Students pay fees
that can reach a semester's tuition for advice they cannot verify, and errors
made by an agent appear in the student's own visa file.

The cost of that is measurable. In 2024 Schengen states received 39,345 visa
applications from Bangladesh and refused 20,957 of them, a refusal rate of 54.90
percent, up from 42.8 percent one year earlier. Every refusal also costs a
non-refundable fee. One United States university found that about 65 percent of
its applications from India and Bangladesh were likely fraudulent, and traced
much of that to agent activity.

The barrier is not missing information. It is language, fragmentation, and
change. Digonto removes all three, for free.

## 2. Solution overview

Digonto (Bangla for horizon) plans and protects the whole application process.

**Ask Digonto** gives grounded Bangla answers to visa and admission questions,
with every claim cited to a timestamped snapshot of the official source. That
archive is public and is called the **Truth Ledger**, so a student can show a
bank officer or a visa officer exactly where a claim came from.

**The Visa Timeline Reactor** is a plan that re-plans itself. When an IELTS date
slips or an embassy changes a rule, every dependent step is recomputed and the
student is told what changed and why.

Four agents do the work a consultancy charges for. **Prohori** audits the
document vault against each target's real checklist and flags missing, expiring,
and inconsistent items. **Khoji** matches the student profile to scholarships
with a reason for every criterion and builds complete budgets, including the bank
balance the embassy actually requires. **Shonchari** runs mock visa interviews
conditioned on the student's own file and scores answers for consistency with
their documents, which is what a visa officer checks. **Porter** watches the
portals and alerts affected students in Bangla, quoting and citing the changed
passage.

Two further features address the local reality directly. The **Agent Fee Reality
Check** takes a consultancy quote and itemises it into free services, fixed
official fees, and a fair residual, each line cited. **Load-Shedding Mode** keeps
the app usable offline with the student's cached plan and last verified answers,
because power cuts are routine.

Digonto is not a chatbot wrapper. The conversational surface is the smallest
part. The value is in scheduled crawling, diffing, versioning, event-driven
re-planning, and agents that act.

## 3. How Gemma is used

**Model:** `gemma4:e2b`, self-hosted with Ollama on one cloud virtual machine.
Verified with `ollama show`: 2.3B effective parameters (5.1B total, using
Per-Layer Embeddings), a 131,072 token context window, Apache 2.0 licence, and
native support for tool calling, vision, audio, and thinking mode.

Those capabilities decided the architecture. Native **tool calling** drives the
four agents with no hand-written parser. Native **vision** extracts fields from
uploaded transcripts and bank statements. Native **audio** accepts Bangla voice
input for users who prefer speaking to typing. One model, one runtime, no second
service. It fits in the RAM of a modest machine, which is why inference is
self-hosted and passports never leave our deployment, and why the service can be
free permanently.

**Architecture around the model: RC-RAG (Recurrent Continual RAG), three loops.**

1. **Fast loop (per query):** hybrid retrieval over a versioned vector store,
   fused with reciprocal rank fusion, then structured JSON generation with
   citations and a confidence value, streamed over SSE. If no retrieved passage
   supports an answer, the output schema forces a refusal with a reason. A
   semantic cache serves repeated questions immediately, but only if they were
   answered under the current store version.
2. **Recurrent loop (scheduled):** crawlers re-fetch portals (embassies every 6
   hours, universities and scholarship boards daily), skip unchanged pages by
   content hash, diff changed pages at passage level, re-embed only the diffs,
   and publish a new store version atomically by flipping a collection alias. Old
   versions are kept 90 days, so every citation stays verifiable.
3. **Continual loop (every 2 to 4 weeks):** refusals, corrections, and answers
   rated unclear accumulate in a consented, PII-scrubbed replay buffer. A rank-16
   QLoRA adapter is trained on that buffer mixed 1:1 with a rehearsal set to
   prevent forgetting. It is promoted only if it passes a frozen 200-question
   Bangla benchmark with no metric regressing by more than one point. Benchmark
   items are excluded from the training export each cycle, because a gate that
   has seen its own test set proves nothing. Rollback is one command.

**Prompt engineering that mattered.** A stable system prefix, so the shared
instructions and tool schemas are encoded once and reused across requests. A
data-only frame around retrieved passages, with tool calling disabled during
grounded answering, as defence against indirect prompt injection hidden in
crawled pages. Enum-constrained classification for Porter's change triage, so
cosmetic edits never reach a student. Per-criterion structured scoring for Khoji
and Shonchari, so every ranking is explainable rather than asserted. Thinking
mode is a per-call flag: off for retrieval answering and change triage where it
only adds latency, on for interview scoring and eligibility reasoning where it
improves quality.

## 4. Technical architecture

FastAPI with an event-driven core on Redis Streams. Every state change is an
event, consumers are idempotent, and a dead-letter stream catches poison
messages. Workers run crawling, diffing, embedding, agents, and learning.

Storage is deliberately small: Qdrant for versioned vector collections, SQLite in
WAL mode (split into an app database, an append-heavy events database, and a
learning database) for users, snapshots, audit log, and replay buffer, an
encrypted filesystem volume for vault documents and archived pages, and Redis for
the semantic cache and rate limits. Litestream streams the SQLite files off-VM
continuously. Caddy terminates TLS at digonto.ahbab.dev. Everything ships as one
Docker Compose file on a single machine. See Graphics 2 and 3.

One event, `portal.changed`, reaches four consumers: knowledge store update,
semantic cache invalidation, timeline re-planning for affected students, and a
Bangla alert. That fan-out is the specific reason the design is event-driven
rather than request-driven.

The four agents run on Gemma 4 tool calling through Ollama's OpenAI-compatible
endpoint, with custom tools exposed through three MCP servers (portal, vault,
funding). Agents are capped at eight tool steps, hold runtime-enforced tool
allow-lists (no agent has a delete tool), and log every call to an audit table.

## 5. Impact and validation

**Evaluation protocol.** A 200-question Bangla benchmark across five countries
and four question families (document requirements, financial requirements,
deadlines, process order), each with a reference answer grounded in an archived
snapshot so correctness stays checkable after the live portal changes. Metrics:
groundedness (claim-level support, two raters with adjudication), refusal
correctness, Bangla clarity on a five-point rubric, and latency on the production
machine with and without the semantic cache.

**Field validation.** A pilot with 20 to 30 students from at least three
districts outside Dhaka, comparing task completion (assembling a correct document
set for a chosen programme) against a checklist-only control group. Pilot
feedback enters the replay buffer, so the pilot trains the system rather than
only testing it.

**Design targets, not results:** groundedness above 0.90, first-token latency
under 2 seconds uncached on 8 vCPU, semantic cache hit rate above 35 percent
after a month of traffic. These are labelled as targets. They are replaced by
measured values as runs complete, and measured values are labelled as measured.

Why this matters: every consultancy service Digonto replaces (checklist
verification, scholarship search, interview preparation, deadline tracking) is
delivered free, cited, and auditable, to anyone with a mid-range phone, in
Bangla.

## 6. Responsibility

Digonto gives sourced information, never legal advice, and says so in the
interface. It refuses rather than guesses on visa-critical questions, and the
refusal is enforced by the output schema rather than by prompt wording.
Shonchari coaches truthful presentation only and refuses requests to misrepresent
facts, explaining the legal consequences of visa fraud.

Inference is self-hosted, so documents never leave the deployment. Vault files
are encrypted at rest with per-user keys. The replay buffer holds no document
contents and is PII-scrubbed and consent-gated. Students can export or
permanently delete everything.

SDG alignment: Goal 4 (equitable access to higher education), Goal 10 target 10.7
(safe, orderly, responsible migration), and Goal 16.10 (public access to
information). The business model funds free student access through institutional
partnerships, never through student fees or data sale.

## 7. Limitations and future work

No measured results are claimed before they exist. Portal redesigns can silence a
crawler, and the system reports source silence rather than guessing, but silence
is still a degraded state. A 2.3B effective-parameter model is limited when
reasoning across many documents at once; retrieval quality and schema-constrained
output compensate, and we will benchmark E4B and the 26B Mixture-of-Experts
variant for the agent runtime, where correct tool-call formatting matters more
than tokens per second. Future work: measured benchmark and pilot results, a
comparison of rehearsal alone against rehearsal with elastic weight
consolidation, more destination countries, and regional dialect output.

## Media gallery (11 graphics)

1. RC-RAG three-loop architecture diagram.
2. Event-driven backend component diagram.
3. `portal.changed` fan-out sequence diagram.
4. Screenshot: Ask Digonto answer with the Truth Ledger citation sheet open.
5. Screenshot: Visa Timeline Reactor re-planning after a deadline change (before and after).
6. Screenshot: Prohori audit memo on the Document Vault.
7. Screenshot: Khoji funding plan with the bank solvency threshold bar.
8. Screenshot: Shonchari interview report with consistency flags.
9. Screenshot: Agent Fee Reality Check itemisation.
10. Sample input and output pair: English embassy passage, cited Bangla explanation.
11. Adapter promotion gate chart (benchmark scores before and after each promotion).

**Links:** live app https://digonto.ahbab.dev · public repository
https://github.com/MdAhbab/Digonto · demo video (YouTube, under 5 minutes) ·
public notebook (Gemma integration, benchmark, and evaluation, reproducible).
