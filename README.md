# Digonto (দিগন্ত)

**A free, Bangla-first Study Abroad and Visa Navigator, powered by Gemma 4 E2B.**

Digonto is the Bangla word for horizon. The project exists so that a student in
Rangpur or Barishal can plan an international education without paying a
consultancy firm a semester's worth of tuition for advice that is often wrong.

Competition: [Build With Gemma @ Bangladesh](https://kaggle.com/competitions/build-with-gemma-bangladesh)
Tracks: **1. The Local Language Track** (primary, Study Abroad and Visa Navigator
theme) and **5. The Autonomous Agent Track** (Gemma 4 native function calling
drives four agents).
Deployment target: **https://digonto.ahbab.dev** (Docker on a cloud virtual machine).

---

## The problem, in verified numbers

Every figure below was checked against its source on 26 July 2026. Sources are
listed in `docs/paper/references.bib`.

- **52,799** Bangladeshi students were studying abroad in 2023 across 55
  countries (UNESCO), roughly three times the number fifteen years earlier.
- **667.77 million US dollars** left the country for overseas education in FY25,
  through 109,290 banking transactions. That is a record for a single year.
- **About 2,000** student consultancy firms operate in Bangladesh. **About 400**
  are registered with the sector association (FACD-CAB). The rest run on a
  general trade licence with no specialised supervision.
- **54.90 percent**: the Schengen visa refusal rate for Bangladeshi applicants in
  2024. Of 39,345 applications, 20,957 were refused, up from a 42.8 percent
  refusal rate in 2023. Every refusal also costs a non-refundable fee.
- **About 65 percent** of applications from India and Bangladesh to one United
  States university were found likely fraudulent, much of it traced to agents.

The information a student needs is public. It is also scattered across
jargon-heavy English portals that change without notice. Digonto reads those
portals so the student does not have to, and answers in clear Bangla.

## What Digonto is not

Digonto is not a chatbot with a knowledge base attached. The conversational
surface is the smallest part of the system. The value comes from automation:
portals are crawled and diffed on a schedule, changes become events, events
update a versioned knowledge store, agents act on the student's behalf, and the
model itself improves from real usage through a gated continual learning cycle.

## Core architecture: Recurrent Continual RAG (RC-RAG)

Digonto runs three loops of different speed around a single Gemma 4 E2B model
served by Ollama.

1. **Fast loop (milliseconds):** a question is embedded, matched against a
   semantic cache, and answered from the versioned vector store with citations to
   the exact portal snapshot used.
2. **Recurrent loop (hours):** scheduled crawlers re-fetch embassy, university,
   and scholarship portals. A diff engine detects any addition, removal, or edit
   in the source text. Changed passages are re-embedded and written to a new
   store version. Affected students receive alerts. Nothing waits for a user to
   ask.
3. **Continual loop (weeks):** unanswerable questions, corrected answers, and
   verified reviewer feedback accumulate in a replay buffer. A periodic LoRA
   fine-tune (low-rank adaptation, a lightweight training method) consolidates
   this experience into the model, using rehearsal so earlier ability in Bangla
   explanation is not lost. The updated adapter is promoted only after passing a
   frozen benchmark, and is hot-swapped into Ollama with a rollback path.

Retrieval keeps facts current daily. Continual learning keeps the model's Bangla
explanation quality improving monthly. Each mechanism compensates for a specific
weakness of the other. The full treatment is in `docs/paper/digonto.tex`.

## Why Gemma 4 E2B

Verified against the running install with `ollama show gemma4:e2b`:

| Property | Value |
| --- | --- |
| Effective parameters | 2.3B (5.1B total, Per-Layer Embeddings) |
| Context length | 131,072 tokens |
| Capabilities | completion, **vision**, **audio**, **tools**, thinking |
| Licence | Apache 2.0 |

Native tool calling is what makes the four agents possible without a fragile
hand-written parser. Native vision handles document field extraction. Native
audio handles Bangla voice input. One model, one runtime, no second service. It
fits in the RAM of a modest virtual machine, so inference is self-hosted and
student passports never leave the deployment.

## Four agentic features (Gemma 4 native function calling)

Detailed specifications with tool schemas and MCP servers are in `agents.md`.

1. **Porter, the Portal Watch agent:** monitors deadline and policy changes for
   each student's saved programmes and files structured Bangla alerts before
   deadlines move past recovery.
2. **Prohori, the Document Guardian agent:** audits the student's document vault
   against the actual checklist of each target university and embassy, flags
   missing, expiring, or inconsistent documents, and drafts request letters.
3. **Khoji, the Scholarship Scout agent:** continuously matches the student's
   profile against a funding index and produces a ranked, budgeted funding plan
   in Bangla, including bank solvency requirements.
4. **Shonchari, the Interview Rehearsal agent:** runs mock visa interviews
   grounded in the student's own file, then delivers a structured weakness report
   explaining in Bangla what each question is really testing.

## Four innovative features beyond the brief

1. **Visa Timeline Reactor:** a living plan that automatically re-plans every
   downstream step when one input changes (an IELTS date slips, an embassy
   changes a rule). Most navigators are static checklists. Digonto's plan is
   recomputed from events.
2. **Truth Ledger:** every answer carries a citation to a timestamped snapshot of
   the source portal, so a student can show a bank or an embassy exactly where a
   claim came from. This is a direct answer to unverifiable agent advice.
3. **Agent Fee Reality Check:** a student enters what a consultancy quoted.
   Digonto itemises which services are free, which are official fees with fixed
   prices, and what a fair residual would be, with sources for each line.
4. **Load-Shedding Mode:** the client caches the student's plan, vault status, and
   last verified answers locally, so the app stays usable during power and
   connectivity outages, which are a daily reality in much of Bangladesh.

## Repository layout

```
Digonto/
├── README.md                     you are here
├── agents.md                     four agentic workflows, tools, MCP servers
├── backend/
│   └── backend.md                full backend plan (FastAPI, events, SQLite, caching)
├── frontend/
│   └── design/
│       └── design_instructions.md Claude Opus design brief
├── paper/
│   ├── research_paper.md         readable mirror of the paper
│   └── kaggle_writeup.md         competition writeup (<2,000 words, 11 graphics)
└── docs/
    ├── business_model.md         sustainability, SDG, ethics, HCD, security
    ├── submission_checklist.md   the five required components, mapped to the rubric
    ├── video_script.md           the 3 to 5 minute demo video, shot by shot
    ├── notebook_plan.md          the public reproducible notebook
    └── paper/                    Overleaf drag-and-drop package (LaTeX, not in git)
```

## Free for students, sustainable anyway

Digonto is free for every student, permanently. Sustainability comes from
institutional revenue, not from students: university partnership listings,
verified-consultancy certification, an institutional API, and grant funding. The
full model, including cost projections for self-hosted Gemma inference, is in
`docs/business_model.md`.

## Responsibility commitments (summary)

**SDG alignment:** SDG 4 (quality education, equitable access to higher
education), SDG 10 target 10.7 (orderly, safe, and responsible migration), SDG 8
(reducing exploitative intermediary costs), SDG 16.10 (public access to
information). **Engineering ethics:** no legal advice is given, only sourced
information; every generated claim is citable; the system states uncertainty
instead of guessing on visa-critical questions; no dark patterns and no data
resale. **Human-centred design:** Bangla-first interface, voice input for
low-literacy users, offline tolerance, and design decisions tested with students
rather than assumed. **Security:** passports and financial documents are
encrypted at rest with per-user keys, inference is self-hosted so documents never
leave the deployment, and the vault supports full export and deletion. Details
and the threat model are in `docs/business_model.md` and `backend/backend.md`.

## Team and licence

Built by Team Digonto. Project code will be released under Apache-2.0. Gemma 4 is
used under the Apache 2.0 licence.
