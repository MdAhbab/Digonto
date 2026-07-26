# Digonto MCP servers

Three stdio [Model Context Protocol](https://modelcontextprotocol.io) servers,
built on the official `mcp` Python package (`requirements.txt`), so the tools
behind Porter, Prohori, and Khoji (see `../../agents.md`) are reusable from
any MCP client, not just from this repo's own agent runtime. Every tool calls
into an existing repository or service under `app/repositories/` or
`app/services/`; none of these servers issues its own SQL.

| Server | Module | Backs |
| --- | --- | --- |
| `digonto-portal-mcp` | `app/mcp/portal_server.py` | Porter, the Truth Ledger |
| `digonto-vault-mcp` | `app/mcp/vault_server.py` | Prohori, and the vision-extraction step Bicharok/Dalil reuse |
| `digonto-funding-mcp` | `app/mcp/funding_server.py` | Khoji, and Dalil's fee benchmarking |

`app/mcp/_common.py` holds the shared bootstrap (`AppContext`, `app_context()`,
`build_dispatcher`, stdio-safe logging) all three import; it has no tools of
its own.

## Running a server directly

Each module is a standalone entrypoint. Run it from `backend/` so the `app`
package resolves, with the same environment a normal `uvicorn app.main:app`
process would use (`.env` in the repo root, or real env vars in production):

```bash
cd backend
python -m app.mcp.portal_server
python -m app.mcp.vault_server
python -m app.mcp.funding_server
```

Each connects to the same three SQLite files and Redis instance the API uses
(`app/config.py`'s `Settings`), so run it against a real, migrated `data/db/`
directory — same as the API, it does not create one from nothing beyond
what `app/db/migrate.py` already does on any process's startup.

## Registering with an MCP client

Any MCP client that speaks stdio works. For Claude Code or Claude Desktop,
add an entry per server to the client's MCP config (Claude Code:
`.mcp.json` in the repo, or `claude mcp add`; Claude Desktop:
`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "digonto-portal-mcp": {
      "command": "python",
      "args": ["-m", "app.mcp.portal_server"],
      "cwd": "/absolute/path/to/Digonto/backend"
    },
    "digonto-vault-mcp": {
      "command": "python",
      "args": ["-m", "app.mcp.vault_server"],
      "cwd": "/absolute/path/to/Digonto/backend"
    },
    "digonto-funding-mcp": {
      "command": "python",
      "args": ["-m", "app.mcp.funding_server"],
      "cwd": "/absolute/path/to/Digonto/backend"
    }
  }
}
```

If the venv isn't on `PATH` for the client's own process, point `command` at
its interpreter directly, e.g. `"/absolute/path/to/Digonto/backend/.venv/bin/python"`.
Set `env` in the same config block for anything `Settings` needs that isn't
already in the repo-root `.env` (`REDIS_URL`, `VAULT_MASTER_KEY`, etc.); none
of these servers accept secrets as tool arguments.

## Every server's identifiers are public ids, never raw row ids

Every tool argument named `*_id` (`user_id`, `document_id`, `target_id`,
`snapshot_id`, `portal_id`, ...) is the table's `public_id` (a ULID, e.g.
`SNAP-01J8...`), the same identifier the HTTP API exposes — never the
internal integer primary key, matching docs/database.md section 1 ("Anything
exposed in a URL or shown to a user gets an additional `public_id`"). Every
handler resolves that public id to an internal row itself.

Every tool call that resolves to no such record, or is refused for a policy
reason (e.g. `register_portal` by a non-moderator), raises one of
`app/errors.py`'s existing `AppError` subclasses; the `mcp` package's own
`call_tool` wrapper turns that into an `isError: true` tool result carrying
the bilingual `detail_en` message. Nothing in `app/mcp/` builds a second
error-shaping layer on top of that.

---

## `digonto-portal-mcp`

Calls `app.services.ledger_service.LedgerService` (public, read-only) and
`app.services.moderation_service.ModerationService.create_portal` (the one
write, which also records a `portal_add` row in `moderation_actions`).

### `fetch_snapshot`

Fetch one captured snapshot by public id, with its passages and a short
quoted excerpt. Reads an already-captured snapshot; does not trigger a crawl.

```json
{
  "snapshot_id": "string, required — e.g. 'SNAP-01J8XQ...'"
}
```

### `diff_snapshots`

Passage-level diffs for a watched portal.

```json
{
  "portal_id": "string — required unless only_pending_review is true",
  "since": "string — ISO-8601 UTC, e.g. '2026-07-01T00:00:00Z'",
  "cursor": "string — opaque pagination cursor from a previous call",
  "only_pending_review": "boolean, default false — pull the moderator review queue instead of the public feed",
  "limit": "integer, default 20"
}
```

### `list_watched_portals`

No arguments. Returns every watched portal: url, kind, country, crawl
cadence, last fetch status.

### `register_portal`

Restricted to a `moderator` or `admin` account.

```json
{
  "moderator_id": "string, required — acting user's public id",
  "url": "string, required",
  "kind": "string, required — one of embassy | university | scholarship | government | bank",
  "label": "string, required — short UI label, e.g. 'ukvi.gov.uk'",
  "country_code": "string — ISO-3166-1 alpha-2",
  "parser_key": "string, default 'generic'",
  "crawl_cron": "string, default '0 */6 * * *'"
}
```

---

## `digonto-vault-mcp`

### SECURITY: this server never returns decrypted document bytes or a decrypted field value

This is the one non-negotiable rule this whole server is built around
(agents.md, Agent 2's "Safety" note; docs/database.md section 3.6 on
`document_fields.value_hash`), and it is enforced in code, not only by
convention:

- **`read_doc_metadata`** returns exactly the fields of
  `app.models.vault.DocumentDetail` — kind, original filename, mime type,
  byte size, page count, issue/expiry dates, status, upload time — via an
  explicit allow-list (`_metadata_only` in `vault_server.py`), never
  `documents.storage_path`, `.wrapped_dek`, or `.nonce`.
- **`extract_fields`** decrypts the document *inside this process* to run the
  vision pass and to persist each extracted field re-encrypted under the
  document's own key (`app.security.vault_crypto`), but the value returned to
  the MCP caller carries only `field_key`, `confidence`, `page_no`, and
  `value_hash` — a normalised comparison hash, never the plaintext. Two
  documents can be checked for a name mismatch by comparing `value_hash`
  values; neither name is ever visible to whatever called this tool.
- **There is no delete tool** (agents.md: "no delete tool exists, by
  design"). `flag_document` only adds an `audit_findings` annotation; it
  never touches `documents.storage_path`, `.wrapped_dek`, `.nonce`, or the
  row's `deleted_at`.

If a change to this file ever adds a field to a tool's return value, check it
against this list before merging: is it something a plaintext value could be
derived from? If yes, it does not belong in this server's output.

### `list_documents`

```json
{
  "user_id": "string, required"
}
```

### `read_doc_metadata`

```json
{
  "user_id": "string, required",
  "document_id": "string, required"
}
```

### `extract_fields`

Runs (or re-runs) the vision extraction pass. Only native image types
(`image/jpeg`, `image/png`, `image/heic`) are extracted today; a PDF document
degrades to returning any previously stored field hashes with a note, since
nothing in this codebase rasterises a PDF page to an image first.

```json
{
  "user_id": "string, required",
  "document_id": "string, required"
}
```

Returns:

```json
{
  "document_id": "string",
  "fields": [
    {"field_key": "string", "confidence": 0.0, "page_no": 1, "value_hash": "sha256 hex"}
  ],
  "note": "string, present only on a degraded/fallback response"
}
```

### `flag_document`

Additive-only annotation (`audits`/`audit_findings` rows).

```json
{
  "user_id": "string, required",
  "document_id": "string, required",
  "code": "string, required — short machine code, e.g. 'NAME_MISMATCH'",
  "severity": "string, required — critical | warning | info",
  "title_en": "string, required",
  "title_bn": "string, required",
  "detail_en": "string, required",
  "detail_bn": "string, required",
  "evidence": "object — small JSON-serialisable evidence blob",
  "action_en": "string",
  "action_bn": "string"
}
```

---

## `digonto-funding-mcp`

Calls `app.repositories.scholarship_repo`, `app.repositories.budget_repo`,
`app.repositories.target_repo` directly for reference data, and
`app.services.funding_service.FundingService.fee_check` for fee benchmarking.

### `search_scholarships`

Filters the active scholarship index by hard criteria read from
`scholarship_criteria` rows. Every criterion checked is returned as
`met: true | false | null` (`null` means "no profile field to check this
against", never silently treated as a pass).

```json
{
  "country": "string — ISO-3166-1 alpha-2",
  "profile": {
    "cgpa": 3.6, "cgpa_scale": 4.0, "degree_level": "master",
    "field_of_study": "string", "nationality": "BD",
    "graduation_year": 2026, "english_overall": 7.0
  },
  "limit": 20
}
```

### `get_fx_rate`

```json
{"base": "USD", "quote": "BDT"}
```

### `get_solvency_rules`

```json
{"country_code": "GB", "visa_type": "student"}
```

### `compose_budget`

Composes and persists (`budgets` table, via `BudgetRepo.upsert`) a full
funding plan for one target: tuition converted to BDT from the programme's
own currency when an fx rate is on file, living/travel/visa-fee inputs,
award coverage, the remaining gap, and the required solvency amount.
`awards_bdt`/`own_funds_bdt` default to whatever is already recorded for this
target when omitted.

```json
{
  "user_id": "string, required",
  "target_id": "string, required — student_targets public id",
  "living_bdt": 0,
  "travel_bdt": 0,
  "visa_fee_bdt": 0,
  "tuition_bdt": "integer — only used if the target's programme has no tuition_amount on file",
  "awards_bdt": "integer",
  "own_funds_bdt": "integer",
  "country_code": "string — only used if the programme has no institution country",
  "visa_type": "string — only used if the target has no visa_type set"
}
```

### `get_fee_benchmarks`

```json
{
  "user_id": "string, required",
  "consultancy": "string",
  "quoted_bdt": 50000,
  "country": "string",
  "document_id": "string"
}
```
