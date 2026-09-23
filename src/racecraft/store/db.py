"""
DuckDB access to the lake.

    from racecraft.store.db import connect
    con = connect()
    con.sql("select driver, count(*) from laps where session_key = '2024_01_R' group by 1").show()

The Parquet files are the source of truth; the database is in-memory and holds
nothing that cannot be rebuilt from them, so there is no database file to lock,
corrupt or keep in sync.

## Why it is built the way it is: DuckDB crashes on repeated many-file scans

Scanning a table spread over hundreds of Parquet files, over and over in one
process, kills that process with a native fault — `PyEval_SaveThread: the GIL
is released` — after roughly 1,000 to 3,000 scans. It is not an exception and
cannot be caught. Measured on this lake, each table 420 files:

* one file scanned 12,000 times: stable, handles and memory flat;
* the same table as a glob: dead after about 1,500, and likewise as an explicit
  file list, without hive partitioning, without `union_by_name`, on one thread,
  with the external file cache off and with the Parquet metadata cache on;
* DuckDB 1.4.5, 1.5.4 and 1.5.5 all do it.

The API used to scan on ordinary requests — a view over every table, and a new
in-memory database on every `connect()` — so a long session, a race weekend in
live mode above all, would eventually take the server down. Three changes keep
repeated many-file scans off every request path:

* **One database per lake**, built once. Every caller gets its own cursor on it,
  DuckDB's pattern for use from several threads.
* **The small tables are held in memory.** Everything but telemetry is 18 MB and
  330,000 rows, so it is loaded once and reloaded only when its files change —
  that is, after an ingest. A request never scans them.
* **Telemetry stays on disk** (1.4 GB, 370 million rows) as views, and is only
  ever read one session at a time with the partition columns in the filter, so
  DuckDB opens the one file it needs: `api/session.py` does this.

A session ingested while the server is running is still seen. A write through
`store/lake` in this process — the tests, an ingest run in-process — bumps a
counter and the next `connect()` reloads at once. A write from another process,
the ingest command run while the server is up, is found by comparing each
table's files (count and newest modification time) with what was last loaded.
That walk covers every partition directory, about 0.45 s on this lake, so it runs
at most once every `RECHECK_S` rather than on every request.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from pathlib import Path

import duckdb

from racecraft import config
from racecraft.store import lake as lake_store
from racecraft.store.lake import FILE_NAME
from racecraft.store.schema import TABLES

HIVE_TYPES = "{'year': SMALLINT, 'round': SMALLINT, 'session': VARCHAR}"

# Too large to hold in memory; read one session at a time, by partition.
STREAMED = ("car_data", "pos_data")

# Lakes kept open at once. Production has one; the test suite makes a fresh lake
# per test, and an evicted database is closed so they do not pile up.
MAX_LAKES = 4

# How stale the database may get before another process's ingest is looked for.
RECHECK_S = 10.0

Signature = tuple[int, float]


class _Lake:
    """One lake's database, and what it was last loaded from."""

    def __init__(self) -> None:
        self.database = duckdb.connect()
        self.loaded: dict[str, Signature] = {}
        self.generation = -1                  # never synced
        self.checked_at = float("-inf")


_databases: OrderedDict[str, _Lake] = OrderedDict()
_lock = threading.Lock()


def _signature(table_dir: Path) -> Signature | None:
    """(file count, newest modification time) for one table, or None if it has no files."""
    count, newest = 0, 0.0
    stack = [str(table_dir)]
    while stack:
        try:
            entries = os.scandir(stack.pop())
        except (FileNotFoundError, NotADirectoryError):
            continue
        with entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                elif entry.name == FILE_NAME:
                    count += 1
                    newest = max(newest, entry.stat().st_mtime)
    return (count, newest) if count else None


def _source(lake: Path, table: str) -> str:
    glob = (lake / table / "*" / "*" / "*" / FILE_NAME).as_posix()
    # Match columns by name: files written before a column was added
    # (results.q1_s) read it as null instead of failing the query.
    return (f"read_parquet('{glob}', hive_partitioning = true, "
            f"hive_types = {HIVE_TYPES}, union_by_name = true)")


def _sync(database: duckdb.DuckDBPyConnection, lake: Path,
          loaded: dict[str, Signature], present: dict[str, Signature | None]) -> dict[str, Signature]:
    """Bring each table in line with its files, touching only the ones that changed."""
    out: dict[str, Signature] = {}
    for table in TABLES:
        now, before = present[table], loaded.get(table)
        kind = "view" if table in STREAMED else "table"
        if now is None:
            if before is not None:
                database.execute(f"drop {kind} if exists {table}")
            continue
        out[table] = now
        if now == before:
            continue
        if table in STREAMED:
            # A view resolves its glob when queried, so new files are seen
            # without recreating it; it only needs to exist.
            if before is None:
                database.execute(f"create or replace view {table} as select * from {_source(lake, table)}")
        else:
            database.execute(f"create or replace table {table} as select * from {_source(lake, table)}")
    return out


def connect(lake: Path | None = None) -> duckdb.DuckDBPyConnection:
    """A cursor on this lake's database, for one caller in one thread."""
    lake = (lake or config.LAKE_DIR).resolve()
    key = str(lake)
    with _lock:
        state = _databases.get(key)
        if state is None:
            state = _databases[key] = _Lake()
        now = time.monotonic()
        written = lake_store.generation()
        if written != state.generation or now - state.checked_at >= RECHECK_S:
            present = {table: _signature(lake / table) for table in TABLES}
            state.loaded = _sync(state.database, lake, state.loaded, present)
            state.generation, state.checked_at = written, now
        _databases.move_to_end(key)
        while len(_databases) > MAX_LAKES:
            _, evicted = _databases.popitem(last=False)
            evicted.database.close()
        cursor = state.database.cursor()
    # TIMESTAMPTZ columns otherwise come back in the machine's local zone
    # (IST here), which is correct but easy to misread as UTC. A setting of the
    # cursor, not the database, so it is made on every one.
    cursor.execute("set TimeZone = 'UTC'")
    return cursor


def partition(session_key: str) -> str:
    """
    The partition filter for one session, so a telemetry read opens one file.

    `2024_01_R` is `year = 2024 and round = 1 and session = 'R'`. Anything that
    is not a lake session key gives no filter rather than a wrong one.
    """
    parts = str(session_key).split("_", 2)
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit() or not parts[2].isalnum():
        return ""
    return f" and year = {int(parts[0])} and round = {int(parts[1])} and session = '{parts[2]}'"
