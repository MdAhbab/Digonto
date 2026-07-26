# Digonto Agentic Workflows

Seven autonomous agents, each asking **Gemma 4 E2B** for one JSON reply
constrained to a schema (Ollama's structured-output mode, not native function
calling and not a hand-written parser over free text), served locally through
Ollama's OpenAI-compatible API. A shared helper (`app/agents/runtime.py`)
validates every reply against its schema and retries once, with the
validation error fed back, if it fails to validate. Agents are called
directly by the service or worker that owns the moment they run (the diff
worker calls Porter, `vault_service.py` calls Prohori/Bicharok/Lekhok/Dalil,
`funding_service.py` calls Khoji, `interview_service.py` calls Shonchari), not
as jobs on a queue. `events.db` already has an `agent_runs`/`agent_tool_calls`
schema for a per-agent step cap and a per-tool-call audit trail
(`backend/backend.md` section 6), but nothing currently writes to either
table: today's calls are single schema-constrained requests, not an audited,
multi-step tool-calling loop. Building that loop is tracked future work, not
a current capability.

**Capability check before building any of this.** `ollama show gemma4:e2b` on the development machine lists `tools`, `vision`, `audio`, and `thinking` alongside `completion`. Tool support is confirmed against the live model (`backend/tests/test_model_contracts.py`) and backs the three MCP servers below, independently of the seven agents above, which use schema-constrained generation instead. Note that the ollama.com library page tables do not show tool support for the E-variants; the local manifest is authoritative. Native `vision` is used directly by Prohori's `extract_fields`, Bicharok, and Dalil, over native image types only; a PDF degrades to previously stored fields rather than being rasterised, since no rasterisation step exists in this codebase. Native `audio` is not wired up: Shonchari's interview room accepts typed answers only, because no speech-to-text service is deployed alongside the model.

**Thinking mode is a per-agent decision, not a global switch.** Porter's change triage and any enum classification run with thinking off, because the added reasoning tokens buy nothing and cost latency. Khoji's eligibility scoring and Shonchari's answer scoring run with thinking on, because the quality difference is worth the tokens.

Custom tools are exposed to the model two ways: internal tools (direct async Python functions) and **MCP servers** (Model Context Protocol, an open standard that lets a model discover and call external tools over a uniform interface). Digonto ships three custom MCP servers so the same tools are reusable from any MCP client, including Claude Code during development:

- **`digonto-portal-mcp`:** `fetch_snapshot`, `diff_snapshots`, `list_watched_portals`, `register_portal`
- **`digonto-vault-mcp`:** `list_documents`, `read_doc_metadata`, `extract_fields` (OCR + Gemma vision pass), `flag_document` (no delete tool exists)
- **`digonto-funding-mcp`:** `search_scholarships`, `get_fx_rate`, `get_solvency_rules`, `compose_budget`, `get_fee_benchmarks`

---

## Agent 1: Porter, the Portal Watch agent

**Purpose:** no student should learn about a deadline change after it matters.

**Trigger:** `portal.changed` event from the recurrent crawl loop, consumed by the diff worker (`app/workers/differ.py`). A daily sweep was part of the original design; only the event-driven path is built today.

**Tools:** `digonto-portal-mcp.diff_snapshots`, internal `find_affected_students(portal_id)`, internal `classify_change(diff)` (Gemma call with enum output: deadline, fee, document_requirement, policy, cosmetic), internal `send_alert(student_id, payload)`, internal `update_timeline(student_id, change)`.

**Workflow:** on a change event, Porter pulls the diff, classifies it, and discards cosmetic changes (wording-only edits). For material changes it queries affected students, then for each one calls `update_timeline` (which feeds the Visa Timeline Reactor) and composes a Bangla alert that quotes the changed passage, cites the snapshot pair, and states the concrete consequence ("your Chevening reference deadline moved forward 9 days; your new latest-safe date is 14 October"). Alerts batch per student per day.

**Failure handling:** classification below confidence 0.7 routes to a human review queue instead of alerting. Unreachable portals for 48 h produce a single "source silent" notice, never fabricated status.

## Agent 2: Prohori, the Document Guardian agent

**Purpose:** replace the consultancy's one real service, document checking, with an auditable free equivalent.

**Trigger:** on-demand only today, from the Vault page (`POST /vault/audit`). Automatic triggering on `vault.doc.added`/`profile.updated` and a weekly cron were part of the original design; neither is wired up yet, since no worker consumes those events for Prohori.

**Tools:** `digonto-vault-mcp.list_documents`, `read_doc_metadata`, `extract_fields`, `flag_document`; internal `get_checklist(university_id, visa_type)` (built from crawled portal snapshots, cited); internal `draft_letter(kind, context)`.

**Workflow:** Prohori builds the authoritative checklist for each of the student's targets from the versioned knowledge store, then audits the vault: missing items, items expiring before the projected visa date (passports need 6 months validity beyond arrival in most regimes), field inconsistencies across documents (name spelling against passport, amounts across bank papers). It emits a structured memo (finding, severity, evidence, action) rendered on Prohori's Desk, and offers drafted request letters (transcript request, bank solvency certificate request) in Bangla and English.

**Safety:** read-only over documents; `flag_document` annotates, nothing more. Extracted fields stay inside the VM (self-hosted inference), and none enter the learning replay buffer.

## Agent 3: Khoji, the Scholarship Scout agent

**Purpose:** funding is the highest-stakes gap; most students never hear of half the awards they qualify for.

**Trigger:** on-demand only today, via `POST /funding/rematch`. Automatic re-matching on `profile.updated` and a monthly refresh cron were part of the original design; neither is wired up yet.

**Tools:** `digonto-funding-mcp.search_scholarships`, `get_fx_rate`, `get_solvency_rules`, `compose_budget`; internal `score_eligibility(profile, award)` (Gemma structured output with per-criterion reasoning); internal `send_digest`.

**Workflow:** Khoji filters the funding index by hard criteria (degree level, field, nationality, CGPA floor), then has Gemma score soft criteria per award with a reason string for each criterion, producing a ranked list where every rank is explainable. It then calls `compose_budget` to build a complete funding plan per target: tuition, living cost, award coverage, remaining gap in BDT at current rates, and the bank solvency amount the embassy actually requires, cited. Output feeds the Funding Studio broadsheet and a monthly Bangla digest.

**Honesty rule:** eligibility scores are presented as estimates with reasons, never as promises; awards with unverifiable pages are marked unverified.

## Agent 4: Shonchari, the Interview Rehearsal agent

**Purpose:** visa interview failure is common, feedback is nonexistent; rehearsal with grounded feedback changes outcomes.

**Trigger:** on-demand from the Interview Room; suggested automatically by the Timeline Reactor once an interview date exists.

**Tools:** internal `get_student_file_summary` (profile, targets, funding plan; a consented, PII-minimised summary), internal `get_interview_bank(country, visa_type)` (real question patterns from the knowledge store), internal `score_answer(question, answer, file_summary)` (Gemma structured rubric: relevance, consistency with file, credibility signals, red flags), internal `compose_report`.

**Workflow:** Shonchari runs a turn-based mock interview (text, or voice via the app's speech layer) asking questions conditioned on the student's actual file, including the uncomfortable ones (funding gaps, study-gap years, weak ties). Each answer is scored against the student's own documents for consistency, which is exactly what a visa officer checks. The final report explains, in Bangla, what each question is really probing and where the student's answers contradicted their file, with concrete rewrites.

**Boundary:** Shonchari coaches truthful presentation only. If a student asks how to misrepresent facts, the agent refuses and explains the legal consequences of visa fraud.

## Agent 5: Bicharok (বিচারক), the Rejection Autopsy agent

**Purpose:** more than half of Bangladeshi Schengen applications were refused in 2024. The refusal letter states the grounds, in administrative English, using paragraph references the applicant has never seen. A student who cannot read the refusal cannot correct it, so they pay an agent again, or give up.

**Trigger:** on-demand when a document of kind `visa_refusal` is added to the vault.

**Tools:** `digonto-vault-mcp.extract_fields` (Gemma **vision** pass over the letter), internal `match_ground_to_rule(quoted_text, country, visa_type)` (retrieval against the knowledge store), internal `assess_remediable(ground, student_file)` (Gemma structured output: yes, partly, no, with reasoning), internal `write_remedial_steps(case_id)`.

**Workflow:** Bicharok reads the letter with the model's vision capability rather than a separate OCR service, since the same served model handles both. It splits the refusal into distinct grounds, quotes each verbatim, and matches each to the rule it references in the knowledge store. For every ground it produces a plain Bangla explanation of what the officer actually meant, a judgement of whether it is remediable, and the concrete remedy. Grounds that are not remediable are said to be not remediable; that is more useful than false hope. The output can be written directly into the Visa Timeline Reactor as remedial steps before a second attempt.

**Boundary:** Bicharok never suggests concealing a prior refusal. Most application forms ask about refusal history directly, and advising otherwise would be advising visa fraud. It says this explicitly when a student asks.

## Agent 6: Lekhok (লেখক), the Statement Forensics agent

**Purpose:** a statement of purpose that contradicts the applicant's own documents is a common, avoidable refusal ground. Consultancies frequently write these statements, which is exactly how the contradictions get in.

**Trigger:** on-demand from the statement editor; automatically re-run when a target or a document changes.

**Tools:** internal `get_student_file_summary` (PII-minimised, consented), `digonto-vault-mcp.read_doc_metadata`, internal `check_claim(claim, file_summary)` (Gemma structured output per claim), internal `suggest_rewrite(excerpt, finding)`.

**Workflow:** Lekhok extracts every factual claim from the statement, then checks each against the student's own record: dates against transcripts, funding claims against the budget, employment against the CV. It reports contradictions, unsupported claims, vague passages that assert nothing, and clichés that occupy space a visa officer is scanning. Each finding carries a bilingual explanation and a suggested rewrite that the student edits themselves.

**Boundary:** Lekhok does not write the statement. It reports problems and suggests phrasing for claims the student has already made truthfully. A statement written by a model is exactly the artefact that admissions offices are now screening for.

## Agent 7: Dalil (দলিল), the Contract Auditor

**Purpose:** students sign consultancy agreements they have not read, in a language they may not read well, containing clauses that keep their original documents or forfeit their whole fee on refusal.

**Trigger:** on-demand when a document of kind `consultancy_contract` is uploaded.

**Tools:** `digonto-vault-mcp.extract_fields` (vision pass), internal `classify_clause(text)` (Gemma enum: fee, refund, document_retention, exclusivity, liability, guarantee, other), internal `assess_risk(clause, category)`, `digonto-funding-mcp.get_fee_benchmarks`.

**Workflow:** Dalil segments the contract into clauses, classifies each, and rates the risk it transfers onto the student. For every high-risk clause it explains in Bangla what the clause actually permits the firm to do, and states a fair alternative. Two categories get special attention because they cause the most harm: original document retention, which leaves a student unable to apply elsewhere, and any clause guaranteeing a visa outcome, which no agent can lawfully promise. The fee clauses feed the Agent Fee Reality Check.

**Boundary:** Dalil reports what a contract says and how unusual it is. It does not give legal advice and says so, and it recommends a lawyer where the amounts justify one.

---

## Shared conventions

Every agent: one schema-constrained JSON reply per call, validated with one retry on failure (`app/agents/runtime.py`); model calls grounded with citations where a factual claim is made; no agent has a delete tool. `agent.completed` (`app/events/bus.py`) exists as an event type and is published today only by the interview flow (`app/services/interview_service.py`), at the end of a session; Porter, Prohori, Khoji, Bicharok, Lekhok, and Dalil do not yet publish it. Escalation to the model fallback path follows `backend/backend.md` section 9 and is invisible to this document's contracts.
