# Digonto Agentic Workflows

Four autonomous agents built on **Gemma 4 E2B native function calling**, served locally by Ollama through its OpenAI-compatible API (`/v1/chat/completions` with `tools`). Any OpenAI-compatible client SDK works against this endpoint unchanged, which keeps the agent code portable. Agents run in the backend's arq worker (see `backend/backend.md`, section 6), are triggered by events or cron, are limited to 8 reasoning-tool steps, and log every tool call to an audit table in `events.db`.

**Capability check before building any of this.** `ollama show gemma4:e2b` on the development machine lists `tools`, `vision`, `audio`, and `thinking` alongside `completion`. Tool support is what makes these four agents native function callers rather than regex parsers over free text, so verify it on the cloud VM after pulling the model and refuse to start the API if the capability is absent. Note that the ollama.com library page tables do not show tool support for the E-variants; the local manifest is authoritative. Native `vision` is used by Prohori's `extract_fields`, and native `audio` is used by Shonchari's voice mode, so all four agents plus the voice and document paths run on one served model with no second runtime.

**Thinking mode is a per-agent decision, not a global switch.** Porter's change triage and any enum classification run with thinking off, because the added reasoning tokens buy nothing and cost latency. Khoji's eligibility scoring and Shonchari's answer scoring run with thinking on, because the quality difference is worth the tokens.

Custom tools are exposed to the model two ways: internal tools (direct async Python functions) and **MCP servers** (Model Context Protocol, an open standard that lets a model discover and call external tools over a uniform interface). Digonto ships three custom MCP servers so the same tools are reusable from any MCP client, including Claude Code during development:

- **`digonto-portal-mcp`:** `fetch_snapshot`, `diff_snapshots`, `list_watched_portals`, `register_portal`
- **`digonto-vault-mcp`:** `list_documents`, `read_doc_metadata`, `extract_fields` (OCR + Gemma vision pass), `flag_document` (no delete tool exists)
- **`digonto-funding-mcp`:** `search_scholarships`, `get_fx_rate`, `get_solvency_rules`, `compose_budget`

---

## Agent 1: Porter, the Portal Watch agent

**Purpose:** no student should learn about a deadline change after it matters.

**Trigger:** `portal.changed` event from the recurrent crawl loop; also a daily 07:00 sweep.

**Tools:** `digonto-portal-mcp.diff_snapshots`, internal `find_affected_students(portal_id)`, internal `classify_change(diff)` (Gemma call with enum output: deadline, fee, document_requirement, policy, cosmetic), internal `send_alert(student_id, payload)`, internal `update_timeline(student_id, change)`.

**Workflow:** on a change event, Porter pulls the diff, classifies it, and discards cosmetic changes (wording-only edits). For material changes it queries affected students, then for each one calls `update_timeline` (which feeds the Visa Timeline Reactor) and composes a Bangla alert that quotes the changed passage, cites the snapshot pair, and states the concrete consequence ("your Chevening reference deadline moved forward 9 days; your new latest-safe date is 14 October"). Alerts batch per student per day.

**Failure handling:** classification below confidence 0.7 routes to a human review queue instead of alerting. Unreachable portals for 48 h produce a single "source silent" notice, never fabricated status.

## Agent 2: Prohori, the Document Guardian agent

**Purpose:** replace the consultancy's one real service, document checking, with an auditable free equivalent.

**Trigger:** `vault.doc.added`, `profile.updated`, weekly cron, and on-demand from the Vault page.

**Tools:** `digonto-vault-mcp.list_documents`, `read_doc_metadata`, `extract_fields`, `flag_document`; internal `get_checklist(university_id, visa_type)` (built from crawled portal snapshots, cited); internal `draft_letter(kind, context)`.

**Workflow:** Prohori builds the authoritative checklist for each of the student's targets from the versioned knowledge store, then audits the vault: missing items, items expiring before the projected visa date (passports need 6 months validity beyond arrival in most regimes), field inconsistencies across documents (name spelling against passport, amounts across bank papers). It emits a structured memo (finding, severity, evidence, action) rendered on Prohori's Desk, and offers drafted request letters (transcript request, bank solvency certificate request) in Bangla and English.

**Safety:** read-only over documents; `flag_document` annotates, nothing more. Extracted fields stay inside the VM (self-hosted inference), and none enter the learning replay buffer.

## Agent 3: Khoji, the Scholarship Scout agent

**Purpose:** funding is the highest-stakes gap; most students never hear of half the awards they qualify for.

**Trigger:** `profile.updated`, new scholarship index entries from the crawl loop, monthly refresh cron.

**Tools:** `digonto-funding-mcp.search_scholarships`, `get_fx_rate`, `get_solvency_rules`, `compose_budget`; internal `score_eligibility(profile, award)` (Gemma structured output with per-criterion reasoning); internal `send_digest`.

**Workflow:** Khoji filters the funding index by hard criteria (degree level, field, nationality, CGPA floor), then has Gemma score soft criteria per award with a reason string for each criterion, producing a ranked list where every rank is explainable. It then calls `compose_budget` to build a complete funding plan per target: tuition, living cost, award coverage, remaining gap in BDT at current rates, and the bank solvency amount the embassy actually requires, cited. Output feeds the Funding Studio broadsheet and a monthly Bangla digest.

**Honesty rule:** eligibility scores are presented as estimates with reasons, never as promises; awards with unverifiable pages are marked unverified.

## Agent 4: Shonchari, the Interview Rehearsal agent

**Purpose:** visa interview failure is common, feedback is nonexistent; rehearsal with grounded feedback changes outcomes.

**Trigger:** on-demand from the Interview Room; suggested automatically by the Timeline Reactor once an interview date exists.

**Tools:** internal `get_student_file_summary` (profile, targets, funding plan; a consented, PII-minimised summary), internal `get_interview_bank(country, visa_type)` (real question patterns from the knowledge store), internal `score_answer(question, answer, file_summary)` (Gemma structured rubric: relevance, consistency with file, credibility signals, red flags), internal `compose_report`.

**Workflow:** Shonchari runs a turn-based mock interview (text, or voice via the app's speech layer) asking questions conditioned on the student's actual file, including the uncomfortable ones (funding gaps, study-gap years, weak ties). Each answer is scored against the student's own documents for consistency, which is exactly what a visa officer checks. The final report explains, in Bangla, what each question is really probing and where the student's answers contradicted their file, with concrete rewrites.

**Boundary:** Shonchari coaches truthful presentation only. If a student asks how to misrepresent facts, the agent refuses and explains the legal consequences of visa fraud.

---

## Shared conventions

Every agent: structured JSON outputs validated against Pydantic schemas with one retry on validation failure; all model calls grounded with citations where a factual claim is made; `agent.completed` events carry a typed result consumed by the frontend; per-agent tool allow-lists enforced by the runtime, not by the prompt. Escalation to the model fallback path follows `backend/backend.md` section 9 and is invisible to this document's contracts.
