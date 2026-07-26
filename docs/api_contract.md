# Digonto API Contract

The complete HTTP and streaming surface. Derived from two things: the actual
TypeScript interfaces in the frontend, and the schema in `docs/database.md`.
Where those two disagreed, the frontend won and the database was shaped to serve
it, because the interface is what a student sees.

Base URL: `https://digonto.ahbab.dev/api/v1`
Local: `http://localhost:8000/api/v1`

---

## 1. Conventions

**Versioning.** The version is in the path. A breaking change means `/v2`, never a
silent change to `/v1`.

**Identifiers.** Every ID crossing the wire is the `public_id` ULID string, never
the integer primary key. Snapshot IDs are shown to users and are formatted
`SNAP-<ULID>`; the frontend renders them in monospace.

**Envelope.** Success responses return the resource directly, not wrapped. Lists
return `{ "items": [...], "next_cursor": "..."|null, "total": n }`. Wrapping every
success in `{data: ...}` costs a property access on every call and buys nothing.

**Errors** are RFC 9457 problem details, always with a bilingual message, because
an error a Bangladeshi student cannot read is a dead end:

```json
{
  "type": "https://digonto.ahbab.dev/errors/document-too-large",
  "title": "Document too large",
  "status": 413,
  "detail_en": "That file is 28 MB. The limit is 20 MB.",
  "detail_bn": "ফাইলটি ২৮ মেগাবাইট। সীমা ২০ মেগাবাইট।",
  "instance": "/api/v1/vault/documents",
  "trace_id": "01J8XQ..."
}
```

`trace_id` is the request ULID and appears in `events.db`, so a support question
resolves to an exact request.

**Auth.** `Authorization: Bearer <access_jwt>`, 15 minute lifetime. Refresh via a
rotating refresh token in an `HttpOnly; Secure; SameSite=Strict` cookie. The
access token is held in memory by the frontend and never in `localStorage`. The
current frontend stores a fake session in `localStorage` under `digonto-session`;
that is replaced.

**Idempotency.** Every POST that creates something accepts `Idempotency-Key`.
Replaying a key within 24 hours returns the original response rather than creating
a duplicate. Required on upload and on interview turn submission, where a mobile
connection retry is likely.

**Rate limits.** Returned on every response as `X-RateLimit-Limit`,
`-Remaining`, `-Reset`. Limits in section 14.

**Language.** `Accept-Language: bn` or `en` sets the default for generated prose.
Every user-facing generated field ships as a `_bn`/`_en` pair regardless, so the
client can switch language without a refetch. That is a deliberate cost: it
doubles some payloads and removes an entire class of loading state.

---

## 2. Health and meta

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/healthz` | liveness. No auth. `{status, version, uptime_s}` |
| GET | `/readyz` | readiness: checks SQLite, Redis, Qdrant, Ollama. 503 if the model is not loaded |
| GET | `/metrics` | Prometheus text. Bound to localhost only |
| GET | `/meta/stats` | public counters for the About page |

`GET /meta/stats` returns real numbers, not the hardcoded ones currently in
`About.tsx`:

```json
{
  "portals_watched": 128,
  "snapshots_archived": 41230,
  "questions_answered": 9021,
  "citation_rate": 1.0,
  "commission_taken_pct": 0,
  "sdg_aligned": 4,
  "as_of": "2026-07-26T09:00:00Z"
}
```

---

## 3. Authentication

Plain email and password. No email sending, no one-time codes, no magic links. A
judge must be able to sign up and be inside the product in under fifteen seconds,
and any flow that depends on an inbox will fail during judging.

**POST `/auth/signup`** — no auth.
Request `{ "email": "...", "password": "...", "display_name": "..." }`.
Response `201 { "access_token": "...", "expires_in": 900, "user": User }` plus the
refresh cookie. The account is usable immediately; `email_verified` stays `false`
and gates nothing.
`409` if the email exists. Password rules: minimum 8 characters, checked against a
list of the 10,000 most common passwords, no composition rules. Hashed with
Argon2id.

**POST `/auth/login`** — `{ "email": "...", "password": "..." }` →
`200 { access_token, expires_in, user }`. `401` on bad credentials, with an
identical message and near-identical timing for "no such user" and "wrong
password" so the endpoint cannot be used to enumerate accounts. `423` if the
account is banned, carrying the moderator's bilingual reason.

**POST `/auth/refresh`** — refresh cookie only. Rotates the token. If an already
replaced token is presented, the whole token family is revoked and `401` is
returned. That is stolen-token detection, not a bug.

**POST `/auth/logout`** — revokes the family, clears the cookie. `204`.

**GET `/auth/session`** — the current `User`, or `401`. Called once on app load.

**POST `/auth/password`** — change password, requires the current one.

```ts
interface User {
  id: string; email: string; display_name: string;
  role: "student" | "moderator" | "admin";
  status: "active" | "suspended" | "banned";
  lang_pref: "bn" | "en"; theme_pref: "light" | "dark" | "system";
  created_at: string; profile_complete: boolean;
  consents: { improve_model: boolean; usage_analytics: boolean };
}
```

### 3.1 Seeded accounts

`run.py` seeds these when `APP_ENV` is not `production`, so a judge never has to
create data to see a populated product. Credentials are in `.env` and are printed
once by `run.py` on first start.

| Account | Role | Purpose |
| --- | --- | --- |
| `judge@digonto.ahbab.dev` | student | a fully populated student: profile, 3 targets, 6 documents, a plan mid-flight, answered questions, one completed interview |
| `moderator@digonto.ahbab.dev` | moderator | the review console |

The judge account is seeded with realistic demo data because an empty product
demonstrates nothing. Every seeded record carries `is_demo = 1` so it can be
identified, excluded from statistics, and wiped with one command.

---

## 4. Profile, targets, destinations

| Method | Path | Purpose |
| --- | --- | --- |
| GET / PATCH | `/me/profile` | student profile |
| PUT | `/me/consents` | toggle the three consents |
| GET | `/me/export` | full data export, JSON + files, as a signed download |
| DELETE | `/me` | hard delete. Requires a fresh OTP; see section 13 |
| GET | `/destinations` | country catalogue, public |
| GET | `/me/shortlist` | shortlisted countries |
| PUT | `/me/shortlist/{country_code}` | add |
| DELETE | `/me/shortlist/{country_code}` | remove |
| GET | `/programmes` | search: `?country=&level=&field=&q=&cursor=` |
| GET/POST | `/me/targets` | shortlist of programmes |
| DELETE | `/me/targets/{id}` | remove |

`GET /destinations` serves `Destinations.tsx`, whose `Country` interface is
`{id, name, lat, lng, note}`. Two changes: `name` and `note` become bilingual, and
the mock's English-only `note` becomes citable.

```json
{ "items": [ {
  "id": "uk", "name_en": "United Kingdom", "name_bn": "যুক্তরাজ্য",
  "lat": 54, "lng": -2,
  "note_en": "Graduate Route allows 2 years of post-study work.",
  "note_bn": "গ্র্যাজুয়েট রুটে পড়াশোনার পর ২ বছর কাজের সুযোগ।",
  "visa_types": ["student","short_study"],
  "shortlisted": true,
  "citation": { "snapshot_id": "SNAP-01J8...", "portal": "gov.uk", "captured": "2026-07-24T06:00:00Z" }
} ] }
```

---

## 5. Ask (the RAG surface)

**POST `/ask`** — streaming, `text/event-stream`.

Request:
```json
{ "question": "ব্যাংক সলভেন্সি কত লাগবে?",
  "conversation_id": "CONV-01J8...",
  "country": "uk",
  "lang": "bn" }
```

The response is SSE. The frontend's `TypesetAnswer` staggers words as they arrive,
so tokens must stream rather than arrive in one block.

| Event | Payload | Meaning |
| --- | --- | --- |
| `meta` | `{question_id, answer_id, kb_version, cache_hit, served_by}` | first, always |
| `token` | `{"t": "সলভেন্সি"}` | one or more tokens of the active language |
| `citation` | `{ordinal, snapshot_id, portal, captured, quoted}` | emitted when a `‖n‖` marker is produced |
| `alt` | `{"lang":"en","text":"..."}` | the mirror-language answer, sent after the primary completes |
| `refusal` | `{reason_en, reason_bn, watching_portal_ids}` | terminal; no `token` events follow |
| `done` | `{latency_ms, first_token_ms, confidence, tokens}` | terminal |
| `error` | problem-details object | terminal |

The `refusal` event is a first-class terminal state, not an error. `Ask.tsx`
already renders a designed refusal card; this event drives it. `watching_portal_ids`
is what lets the UI honestly say "we are watching this source for an answer".

**GET `/ask/history?conversation_id=&cursor=`** returns past exchanges shaped
exactly like the frontend `QA` interface:

```json
{ "items": [ {
  "id": "QA-01J8...", "q": "...", "answerEn": "...", "answerBn": "...",
  "citations": [ {"id":"SNAP-01J8...","portal":"gov.uk","captured":"2026-07-24T06:00:00Z","quoted":"..."} ],
  "refusal": false, "created_at": "..."
} ] }
```

Field names here intentionally match the existing TypeScript (`answerEn`, not
`answer_en`) so the page needs no mapping layer. This is the one place the API
uses camelCase, and it is documented rather than accidental.

**POST `/ask/{answer_id}/feedback`** — `{rating: "up"|"down"|"unclear", correction?}`.
Writes to `answer_feedback` and, if consent allows, to the replay buffer.

**GET `/ask/conversations`**, **POST `/ask/conversations`**, **DELETE `/ask/conversations/{id}`**.

---

## 6. Truth Ledger (public, no auth)

**GET `/ledger/snapshots/{snapshot_id}`** — the public verification endpoint that
`Ledger.tsx` calls.

```json
{ "id": "SNAP-01J8...", "portal": "gov.uk", "portal_url": "https://...",
  "captured": "2026-07-24T06:00:00Z", "content_hash": "sha256:...",
  "http_status": 200, "quoted": "...", "retired": false,
  "passages": [ {"ordinal": 12, "section_path": "Financial evidence", "text": "..."} ] }
```

`404` returns a bilingual problem-details object rather than a bare error, since
students will paste IDs by hand and typos are the normal case.

**GET `/ledger/portals`** — the watch list, public. Shows every monitored portal,
its last fetch time, and its status. A portal that has been unreachable is shown
as unreachable. Publishing our own failures is the point of the ledger.

**GET `/ledger/changes?portal_id=&since=&cursor=`** — the public change feed of
classified, non-cosmetic diffs.

---

## 7. Planner (Visa Timeline Reactor)

**GET `/planner/timeline?target_id=`** — serves `Planner.tsx`.

```json
{ "plan_id": "PLAN-01J8...", "intake_label": "Fall 2027",
  "steps": [ { "id": "STEP-01J8...", "step_key": "solvency", "month": "Jan 2027",
    "titleEn": "Arrange funding & solvency", "titleBn": "তহবিল ও সচ্ছলতা",
    "descEn": "...", "descBn": "...", "status": "upcoming",
    "due_at": "2027-01-15", "depends_on": ["ielts"],
    "citation": {"snapshot_id": "SNAP-...", "portal": "ukvi.gov.uk"} } ],
  "unseen_changes": 2 }
```

`step_key` is stable across re-plans while `month` and `status` are not. That is
what allows the page's `layout` animation to move a row rather than replace it.

**GET `/planner/changes?since=&cursor=`** — the "what changed" drawer, matching
`ChangeEntry`:

```json
{ "items": [ { "id": "CHG-01J8...", "textEn": "...", "textBn": "...",
  "source": "ukvi.gov.uk · SNAP-01J8...", "trigger": "portal_change",
  "step_key": "solvency", "created_at": "...", "seen": false } ] }
```

**POST `/planner/steps/{id}/complete`** and **`/reopen`** — student marks progress;
triggers a re-plan of dependents.

**POST `/planner/regenerate`** — rebuild from the current profile and targets.

**POST `/planner/simulate`** — *demonstration only, and labelled as such in the
response.* `Planner.tsx` has a "simulate a portal change" button that judges will
press. It injects a synthetic `portal.changed` event scoped to the caller's own
plan and returns `{"simulated": true, ...}`. It never writes to the knowledge
store and never notifies another user. Keeping it honest matters: the response
carries `"simulated": true` and the UI must show that label.

---

## 8. Vault and Prohori

**POST `/vault/documents`** — `multipart/form-data`, fields `file`, `kind`,
optional `expires_on`. Max 20 MB. Accepts PDF, JPEG, PNG, HEIC.
Returns `202` with the document in `status: "scanning"`, because extraction is
asynchronous. `Vault.tsx` currently fakes the upload and never reads the file.

**GET `/vault/documents`** — serves the vault grid. Shapes onto the `Doc`
interface, with the mock's flat fields backed by a real audit:

```json
{ "items": [ { "id":"DOC-01J8...", "kind":"passport",
  "nameEn":"Passport","nameBn":"পাসপোর্ট","count":1,
  "expiresDays":190, "severity":"warn",
  "findingEn":"...","findingBn":"...","actionEn":"...","actionBn":"...",
  "status":"extracted","uploaded_at":"..." } ] }
```

`severity`, `finding*` and `action*` come from the highest-severity open
`audit_finding` for that document, so the card is a real audit result.

**GET `/vault/documents/{id}`**, **GET `/vault/documents/{id}/download`** (signed,
15 min), **DELETE `/vault/documents/{id}`** (hard delete, shreds the key).

**POST `/vault/audit`** — run Prohori now. `202 {audit_id}`.
**GET `/vault/audit/latest`** — the memo: findings with severity, evidence,
bilingual action, and a citation per finding.

**GET `/vault/events`** — SSE. Emits `document.status` and `audit.finding` events
so the page can move a card from "scanning" to a finished audit without polling.

---

## 9. Funding and Khoji

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/funding/scholarships?sort=&order=&country=&cursor=` | ranked matches |
| GET | `/funding/scholarships/{id}` | detail with per-criterion reasons |
| POST | `/funding/rematch` | re-run Khoji |
| GET/POST/DELETE | `/funding/sources` | the budget composition bar |
| GET | `/funding/budget?target_id=` | tuition, living, awards, gap, solvency line |
| POST | `/funding/fee-check` | Agent Fee Reality Check |

`GET /funding/scholarships` serves the sortable broadsheet. `Funding.tsx` sorts on
`name|country|coverage|deadline`, so those are the permitted `sort` values and
sorting happens server-side over the full set rather than client-side over a page.

```json
{ "items": [ { "id":"SCH-01J8...", "name":"Chevening", "country":"uk",
  "coverage": 100, "deadline":"2026-11-05",
  "score": 0.82, "rank": 2, "eligible": true, "verified": true,
  "reasons": [ {"criterion":"cgpa_min","met":true,
                "reason_en":"Your CGPA 3.6 clears the 3.3 minimum.",
                "reason_bn":"আপনার সিজিপিএ ৩.৬, ন্যূনতম ৩.৩ পার হয়েছে।"} ],
  "citation": {"snapshot_id":"SNAP-..."} } ] }
```

`eligible` and `score` are always accompanied by `reasons`. The API makes an
unexplained score impossible to return, which is the honesty rule from `agents.md`
enforced at the contract level.

**POST `/funding/fee-check`** accepts either a typed quote or an uploaded
consultancy invoice (`document_id`), and returns the itemisation:

```json
{ "quoted_bdt": 480000, "fair_bdt": 191000,
  "lines": [ { "label_en":"University application fees (x6)","label_bn":"...",
               "category":"official_fee","amount_bdt": 42000,
               "citation": {"snapshot_id":"SNAP-..."} },
             { "label_en":"Document checking","label_bn":"...",
               "category":"free","amount_bdt": 0,
               "note_en":"Prohori does this at no cost." } ] }
```

---

## 10. Interview and Shonchari

Turn-taking with audio needs a socket, not request/response.

**POST `/interview/sessions`** → `{session_id, mode, first_question}`.

**WS `/interview/sessions/{id}/ws`** — the live channel.

Client sends: `{"type":"answer_text","text":"..."}` or binary audio frames framed
by `{"type":"audio_start"}` / `{"type":"audio_end"}`.

Server sends, matching the page's `idle → listening → thinking → speaking` machine:

| Message | Payload |
| --- | --- |
| `transcript.partial` | `{text}` while the student speaks |
| `transcript.final` | `{text, confidence}` |
| `phase` | `{"phase":"thinking"}` replaces the hardcoded 1400 ms timeout |
| `score` | `{relevance, consistency, credibility, contradicts:[{document_id, field, said, document_says}]}` |
| `question` | `{ordinal, text_en, text_bn, probes, audio_url?}` |
| `session.complete` | `{report_id}` |

`contradicts` is the feature that matters: it compares a spoken answer against the
student's own uploaded documents, which is what a visa officer does.

**GET `/interview/sessions/{id}/report`** — bilingual weakness report with a
per-question grade and concrete rewrites.
**GET `/interview/sessions`** — history.

---

## 11. The three new agents

**Bicharok, rejection autopsy.**
`POST /rejection/cases` `{document_id}` → `202`. Gemma vision reads the refusal
letter.
`GET /rejection/cases/{id}` → grounds, each with the quoted refusal text, a plain
Bangla explanation of what it means, whether it is remediable, the remedy, and a
citation to the rule.
`POST /rejection/cases/{id}/apply-to-plan` → writes remedial steps into the
timeline.

**Lekhok, statement forensics.**
`POST /statements` `{kind, body, target_id}` → `202`.
`GET /statements/{id}/findings` → contradictions against the student's own
documents, unsupported claims, and vague passages, each with a bilingual
suggestion.

**Dalil, contract auditor.**
`POST /contracts` `{document_id}` → `202`.
`GET /contracts/{id}` → clause-by-clause risk with a fair alternative for each
predatory clause.

All three refuse to help fabricate anything and say so in the response body rather
than silently degrading.

---

## 11a. Moderator console

A second stakeholder. Every endpoint below requires `role in (moderator, admin)`
and is enforced by a dependency on the router, not by a check inside each handler.

### What a moderator can never see

This is the first design decision, not an afterthought. The product promises that
documents are encrypted per user and that inference is self-hosted. A moderator
who could open a student's passport would make that promise false.

| Moderator can see | Moderator can never see |
| --- | --- |
| That a document of kind `passport` exists, its status and expiry | The file, its contents, or any extracted field value |
| Question and answer text on escalated items only | A student's full question history |
| Aggregate counts, statuses, timings | `document_fields.value_enc`, ever |
| A student's plan step keys and statuses | The student's real name, unless the student escalated |

Moderators hold no key material. The vault decryption path is not reachable from
any moderator route, so this is enforced by the absence of code rather than by a
permission flag. Every moderator read of student-linked data writes an
`moderation.viewed` event, and a student can see that log in their own account.

### Change review queue (the human in the loop that matters)

Porter classifies each portal change with a confidence score. Below 0.7 it does
not alert anyone; it waits here. A wrong "your deadline moved" alert sent to five
hundred students is worse than a slow one.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/mod/changes?status=pending&cursor=` | the queue, oldest first, with the diff, both snapshots, and the model's proposed category and confidence |
| POST | `/mod/changes/{id}/approve` | `{category, notify: true}` confirms and releases alerts |
| POST | `/mod/changes/{id}/reclassify` | `{category, reason}` corrects the model; the correction enters the replay buffer |
| POST | `/mod/changes/{id}/discard` | cosmetic or spurious; no alert, recorded with a reason |

### Answer review and refusal triage

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/mod/answers?filter=downvoted\|escalated\|low_confidence` | answers needing a human |
| POST | `/mod/answers/{id}/verify` | mark correct; closes the report |
| POST | `/mod/answers/{id}/correct` | `{correction_bn, correction_en, note}` writes the verified correction, which is the highest-value training signal the system produces |
| GET | `/mod/refusals?cursor=` | questions the system could not answer, clustered by topic |
| POST | `/mod/refusals/{cluster_id}/add-portal` | `{url, kind, country}` registers a new source to close the gap |

Refusal triage is the loop that makes the product improve at coverage rather than
only at phrasing. A cluster of twenty students asking the same unanswerable
question is a missing portal, and this is where a human turns that into one.

### Source and funding verification

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/mod/portals` | every watched portal with health, failure streak, last change |
| POST | `/mod/portals` / `PATCH /mod/portals/{id}` | register, pause, change cadence, fix a parser key |
| GET | `/mod/scholarships?verified=false` | funding entries awaiting a human check |
| POST | `/mod/scholarships/{id}/verify` | `{verified: true\|false, note}` |

An unverified scholarship is shown to students marked unverified rather than
hidden. Hiding it would lose real opportunities; mislabelling it would mislead.

### People

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/mod/users?status=&q=&cursor=` | list with activity summary, never with documents |
| GET | `/mod/users/{id}` | status, counts, flags, moderation history |
| POST | `/mod/users/{id}/suspend` | `{reason_en, reason_bn, until}` reversible |
| POST | `/mod/users/{id}/ban` | `{reason_en, reason_bn}` permanent, blocks login with `423` |
| POST | `/mod/users/{id}/reinstate` | `{note}` |
| GET | `/mod/reports` | abuse reports, including attempts to make Shonchari coach dishonesty |

Every action requires a bilingual reason, because the reason is shown to the user.
A ban with no stated cause is not moderation. All actions are reversible except a
deletion the user requested themselves, and every one writes an immutable event.

### Model oversight

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/mod/adapters` | candidate adapters with benchmark scores before and after |
| POST | `/mod/adapters/{id}/promote` | the final human check before a model reaches students |
| POST | `/mod/adapters/{id}/rollback` | `{reason}` |
| GET | `/mod/health` | queue depths, crawl failures, dead letters, model latency |

An adapter passes the automatic gate and *then* waits for a person. The gate stops
regressions it can measure; the human stops the ones it cannot.

### Moderator dashboard

**GET `/mod/overview`** returns the single screen a moderator opens first:
pending changes, escalated answers, unverified scholarships, portals silent for
more than 48 hours, dead letters, adapters awaiting promotion, and new users
today. Each is a count plus a link, so the console opens on work rather than on
statistics.

## 12. Notifications

**GET `/notifications?unread=true&cursor=`** and **POST `/notifications/{id}/read`**.

**GET `/stream`** — one authenticated SSE connection per client, multiplexing
everything the user needs to see live:

| Event | Emitted when |
| --- | --- |
| `notification` | any new notification |
| `plan.changed` | the reactor re-planned; carries the `ChangeEntry` |
| `audit.updated` | Prohori finished |
| `funding.updated` | Khoji re-ranked |
| `document.status` | extraction finished or failed |

One stream, not five. A student on a mobile connection should hold one socket.
Reconnect uses `Last-Event-ID`, and the server replays from `events.db`.

---

## 13. Privacy operations

**GET `/me/export`** — everything: profile, questions, answers, plan, vault
metadata, and a signed archive of the actual files. Generated asynchronously,
delivered by email link, expires in 24 hours.

**DELETE `/me`** — requires a fresh OTP confirmation in the body. Deletes vault
files, cascades `app.db`, anonymises `events.db` rows rather than deleting them
(the audit trail survives without identifying anyone), deletes replay samples, and
emits `user.deleted`. Returns `202` with a completion receipt sent by email.

**POST `/me/consents/withdraw`** — withdrawing `improve_model` deletes the user's
replay samples and flags every adapter trained on them for review. Documented
because "you can withdraw consent" is meaningless if the data is already in a
model.

---

## 14. Rate limits

| Scope | Limit | Reason |
| --- | --- | --- |
| `POST /auth/request-code` | 3 per email per hour, 10 per IP per hour | OTP abuse |
| `POST /auth/verify-code` | 5 per code | brute force |
| `POST /ask` | 30 per user per hour, 6 per minute | one model, many students |
| `POST /vault/documents` | 20 per user per day, 100 MB per day | disk |
| WS `/interview` | 1 concurrent session per user | GPU or CPU contention |
| Public `GET /ledger/*` | 60 per IP per minute | it is public on purpose |
| Everything else | 120 per user per minute | |

Exceeding a limit returns `429` with `Retry-After` and a bilingual explanation.
The Ask limit is real and will be hit; the message must explain that the model is
shared and free, not simply refuse.

---

## 15. Frontend mapping

Every mock in the frontend and the endpoint that replaces it.

| Page | Mock replaced | Endpoint |
| --- | --- | --- |
| `Auth.tsx` | `login(email)` into localStorage | `/auth/request-code`, `/auth/verify-code` |
| `Ask.tsx` | `seed` array, always-refuse `submit()` | `POST /ask` (SSE), `GET /ask/history` |
| `Ask.tsx` | citation side sheet | `GET /ledger/snapshots/{id}` |
| `Planner.tsx` | `initialSteps` (7), `simulate()` | `GET /planner/timeline`, `POST /planner/simulate` |
| `Planner.tsx` | `changes` array | `GET /planner/changes`, `plan.changed` on `/stream` |
| `Vault.tsx` | `docs` (4), fake drop handler | `GET /vault/documents`, `POST /vault/documents` |
| `Funding.tsx` | `scholarships` (6) | `GET /funding/scholarships` |
| `Funding.tsx` | `initialSources` (2), `SOLVENCY_REQUIRED` | `/funding/sources`, `/funding/budget` |
| `Funding.tsx` | `feeLines` (4), `quotedTotal` | `POST /funding/fee-check` |
| `Interview.tsx` | `questions` (4), 1400 ms timeout, static `Report` | `POST /interview/sessions`, WS, `/report` |
| `Destinations.tsx` | `countries` (6), `shortlist` | `GET /destinations`, `/me/shortlist` |
| `Ledger.tsx` | `known` map (1 entry) | `GET /ledger/snapshots/{id}` |
| `About.tsx` | 3 hardcoded counters | `GET /meta/stats` |
| `Layout.tsx` | offline banner | removed; the product is online only |

**Two frontend problems this contract does not fix, listed so they are not
forgotten.** First, several pages hold English-only literal strings that bypass
`t()` entirely (`Security.tsx` commitments and threats, `About.tsx` prose,
`Interview.tsx` report lines, `Destinations.tsx` notes). For a Bangla-first
product that is a defect, and the fix is content work, not API work. Second, the
seed data uses two different bilingual patterns: `t()` with a 145-key dictionary,
and manual `xEn`/`xBn` fields. Server-supplied content uses the `_en`/`_bn` pair
pattern; the dictionary stays for interface chrome only.
