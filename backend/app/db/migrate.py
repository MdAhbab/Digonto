"""SQL migration runner.

Plain numbered .sql files per database, applied once, tracked in a
`schema_migrations` table with a sha256 checksum of the file (docs/database.md
section 6). No ORM migration framework: the schema is small enough that
generated migrations would add more risk than they remove.

`schema_migrations` itself is bootstrapped here with `CREATE TABLE IF NOT
EXISTS` rather than shipped as migration file 000: it needs to exist before we
can even ask "which migrations have run", so it is infrastructure for this
module rather than a versioned step.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from app.db.connection import Database, Databases

log = logging.getLogger(__name__)

MIGRATIONS_ROOT = Path(__file__).resolve().parent / "migrations"

_CREATE_SCHEMA_MIGRATIONS = """
CREATE TABLE IF NOT EXISTS schema_migrations (
  version    TEXT PRIMARY KEY,
  applied_at TEXT NOT NULL,
  checksum   TEXT NOT NULL
)
"""


class MigrationError(RuntimeError):
    """Raised when it is not safe to start the application.

    Startup must fail loudly here rather than silently running against a
    schema different from the one recorded, per docs/database.md section 6.
    """


@dataclass(slots=True)
class _Migration:
    version: str
    path: Path
    checksum: str
    statements: list[str]


def _split_statements(script: str) -> list[str]:
    """Split a .sql file into individual statements.

    Deliberately not sqlite3's executescript(): every statement in a migration
    file must run inside the same explicit transaction as the
    schema_migrations bookkeeping row it produces (see Database.transaction in
    app/db/connection.py), so we need a plain list of statement strings to
    feed it one at a time. This tracks single-quoted string literals ('' is an
    escaped quote) and both comment styles so a semicolon inside a string or a
    comment is never mistaken for a statement boundary.
    """
    statements: list[str] = []
    buf: list[str] = []
    i, n = 0, len(script)
    in_string = False
    in_line_comment = False
    in_block_comment = False
    while i < n:
        ch = script[i]
        nxt = script[i + 1] if i + 1 < n else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                continue
            i += 1
            continue
        if in_string:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":
                    buf.append(nxt)
                    i += 2
                    continue
                in_string = False
            i += 1
            continue

        if ch == "'":
            in_string = True
            buf.append(ch)
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                statements.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        statements.append(tail)
    return statements


def _load_migrations(directory: Path) -> list[_Migration]:
    if not directory.is_dir():
        return []
    migrations: list[_Migration] = []
    for path in sorted(directory.glob("*.sql")):
        raw = path.read_bytes()
        checksum = hashlib.sha256(raw).hexdigest()
        statements = _split_statements(raw.decode("utf-8"))
        migrations.append(
            _Migration(version=path.stem, path=path, checksum=checksum, statements=statements)
        )
    return migrations


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def _apply(db: Database, directory: Path, *, label: str) -> None:
    await db.execute(_CREATE_SCHEMA_MIGRATIONS)

    migrations = _load_migrations(directory)
    if not migrations:
        log.warning("no migration files found for %s in %s", label, directory)
        return

    applied_rows = await db.fetch_all("SELECT version, checksum FROM schema_migrations")
    applied = {row["version"]: row["checksum"] for row in applied_rows}

    for m in migrations:
        recorded = applied.get(m.version)
        if recorded is not None:
            if recorded != m.checksum:
                raise MigrationError(
                    f"[{label}] migration {m.path.name} has changed on disk since it "
                    f"was applied (recorded checksum {recorded}, file now hashes to "
                    f"{m.checksum}). Migrations are append-only once applied anywhere; "
                    "add a new migration instead of editing this one. Refusing to start."
                )
            continue

        log.info("[%s] applying migration %s", label, m.path.name)
        async with db.transaction() as tx:
            for stmt in m.statements:
                await tx.execute(stmt)
            await tx.execute(
                "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, ?, ?)",
                (m.version, _now_iso(), m.checksum),
            )


async def run_migrations(dbs: Databases) -> None:
    """Apply every pending migration to all three database files, in order.

    Call once during application startup, after `dbs.connect_all()` and before
    the app accepts traffic. Raises MigrationError if an already-applied
    file's checksum no longer matches what is recorded.
    """
    await _apply(dbs.app, MIGRATIONS_ROOT / "app", label="app")
    await _apply(dbs.events, MIGRATIONS_ROOT / "events", label="events")
    await _apply(dbs.learn, MIGRATIONS_ROOT / "learn", label="learn")
    log.info("migrations up to date")
