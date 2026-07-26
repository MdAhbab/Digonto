"""SQLite access layer.

The whole product runs on one machine, which makes SQLite the right choice. It
becomes the wrong choice the moment it is used like a client-server database, so
this module enforces the rules rather than documenting them:

  * WAL mode and the rest of the pragmas are applied on every connection, not
    once in a migration. `foreign_keys` in particular is per-connection and off
    by default, which is a classic source of silent orphan rows.
  * Every write goes through a single serialised writer task per database file.
    Concurrent writers produce SQLITE_BUSY under load, and a queue is far easier
    to reason about than a retry storm.
  * Reads run concurrently. WAL allows many readers alongside the one writer,
    which is exactly the access pattern here.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import aiosqlite

log = logging.getLogger(__name__)

# Applied to every connection. Two of these are memory decisions and are sized
# for the deployment target, not for a database server.
#
# `cache_size` is per connection and is not shared between them. At the previous
# -64000 (64 MB) and 13 connections across the three files, SQLite could claim
# ~832 MB of page cache on a machine whose RAM is budgeted around a resident
# 7.2 GB model. -8000 (8 MB) per connection caps the total near 104 MB, which is
# ample for a working set of this size: the databases hold metadata only, since
# rule 4 keeps blobs out on the encrypted volume.
#
# `mmap_size` is different: it maps the file, so connections to the same file
# share those pages and the cost is bounded by file size rather than multiplied
# by connection count. 64 MB is well above the expected size of these files.
PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA mmap_size=67108864",
    "PRAGMA cache_size=-8000",
    # Bound the WAL. Without this a long-lived reader can hold checkpointing back
    # and let the -wal file grow without limit, which Litestream then replicates.
    "PRAGMA journal_size_limit=16777216",
)


@dataclass(slots=True)
class _WriteJob:
    fn: Callable[[aiosqlite.Connection], Any]
    future: asyncio.Future


class Database:
    """One instance per SQLite file."""

    def __init__(self, path: Path, *, read_pool_size: int = 4) -> None:
        self.path = path
        self._read_pool_size = read_pool_size
        self._readers: asyncio.Queue[aiosqlite.Connection] | None = None
        self._writer: aiosqlite.Connection | None = None
        self._write_q: asyncio.Queue[_WriteJob] | None = None
        self._writer_task: asyncio.Task | None = None
        self._closing = False

    # -- lifecycle ---------------------------------------------------------

    async def connect(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        self._writer = await self._open()
        self._write_q = asyncio.Queue()
        self._writer_task = asyncio.create_task(
            self._writer_loop(), name=f"sqlite-writer:{self.path.name}"
        )

        self._readers = asyncio.Queue(maxsize=self._read_pool_size)
        for _ in range(self._read_pool_size):
            self._readers.put_nowait(await self._open())

        log.info("sqlite connected path=%s readers=%d", self.path, self._read_pool_size)

    async def _open(self) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(self.path, isolation_level=None)
        conn.row_factory = aiosqlite.Row
        for pragma in PRAGMAS:
            await conn.execute(pragma)
        return conn

    async def close(self) -> None:
        self._closing = True
        if self._writer_task:
            await self._write_q.join()  # type: ignore[union-attr]
            self._writer_task.cancel()
            try:
                await self._writer_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            await self._writer.close()
        if self._readers:
            while not self._readers.empty():
                await (self._readers.get_nowait()).close()

    # -- reads -------------------------------------------------------------

    @asynccontextmanager
    async def reader(self) -> AsyncIterator[aiosqlite.Connection]:
        assert self._readers is not None, "connect() first"
        conn = await self._readers.get()
        try:
            yield conn
        finally:
            self._readers.put_nowait(conn)

    async def fetch_all(self, sql: str, params: Sequence[Any] = ()) -> list[aiosqlite.Row]:
        async with self.reader() as conn:
            async with conn.execute(sql, params) as cur:
                return list(await cur.fetchall())

    async def fetch_one(self, sql: str, params: Sequence[Any] = ()) -> aiosqlite.Row | None:
        async with self.reader() as conn:
            async with conn.execute(sql, params) as cur:
                return await cur.fetchone()

    async def fetch_val(self, sql: str, params: Sequence[Any] = ()) -> Any:
        row = await self.fetch_one(sql, params)
        return None if row is None else row[0]

    # -- writes ------------------------------------------------------------

    async def _writer_loop(self) -> None:
        assert self._write_q is not None and self._writer is not None
        while True:
            job = await self._write_q.get()
            try:
                result = await job.fn(self._writer)
                if not job.future.done():
                    job.future.set_result(result)
            except Exception as exc:  # noqa: BLE001 - surfaced to the caller
                if not job.future.done():
                    job.future.set_exception(exc)
            finally:
                self._write_q.task_done()

    async def write(self, fn: Callable[[aiosqlite.Connection], Any]) -> Any:
        """Run `fn` on the single writer connection.

        `fn` receives a live connection and may issue several statements. Keep it
        short: never await a model call or an HTTP fetch inside it, or every
        other writer on this database file waits behind you.
        """
        if self._closing:
            raise RuntimeError("database is closing")
        assert self._write_q is not None
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        await self._write_q.put(_WriteJob(fn, fut))
        return await fut

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        async def _run(conn: aiosqlite.Connection) -> int:
            cur = await conn.execute(sql, params)
            return cur.lastrowid or 0

        return await self.write(_run)

    async def execute_count(self, sql: str, params: Sequence[Any] = ()) -> int:
        """Like `execute`, but returns how many rows changed.

        `execute` returns `lastrowid`, which is the right answer for an INSERT and
        meaningless for an UPDATE or DELETE. A sweep that reports how much it repaired needs
        the count, and counting with a separate SELECT first is both slower and a race.
        """

        async def _run(conn: aiosqlite.Connection) -> int:
            cur = await conn.execute(sql, params)
            return cur.rowcount or 0

        return await self.write(_run)

    async def execute_many(self, sql: str, rows: Sequence[Sequence[Any]]) -> None:
        async def _run(conn: aiosqlite.Connection) -> None:
            await conn.executemany(sql, rows)

        await self.write(_run)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["_Tx"]:
        """Group several statements atomically on the writer connection.

        Usage:
            async with db.transaction() as tx:
                await tx.execute(...)
                await tx.execute(...)
        """
        statements: list[tuple[str, Sequence[Any]]] = []
        tx = _Tx(statements)
        yield tx

        async def _run(conn: aiosqlite.Connection) -> None:
            await conn.execute("BEGIN IMMEDIATE")
            try:
                for sql, params in statements:
                    await conn.execute(sql, params)
                await conn.execute("COMMIT")
            except Exception:
                await conn.execute("ROLLBACK")
                raise

        await self.write(_run)


@dataclass(slots=True)
class _Tx:
    _statements: list[tuple[str, Sequence[Any]]]

    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        self._statements.append((sql, params))


class Databases:
    """The three database files, held together for lifespan management."""

    def __init__(self, app_path: Path, events_path: Path, learn_path: Path) -> None:
        self.app = Database(app_path, read_pool_size=6)
        self.events = Database(events_path, read_pool_size=2)
        self.learn = Database(learn_path, read_pool_size=2)

    async def connect_all(self) -> None:
        await asyncio.gather(
            self.app.connect(), self.events.connect(), self.learn.connect()
        )

    async def close_all(self) -> None:
        await asyncio.gather(
            self.app.close(), self.events.close(), self.learn.close()
        )
