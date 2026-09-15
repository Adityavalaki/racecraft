"""
DuckDB access to the lake.

The connection is in-memory and holds only views over the Parquet files, so
there is no database file to lock, corrupt or keep in sync. Globs are
resolved at query time, which means a session ingested after the connection
was opened is still visible to the next query.

    from racecraft.store.db import connect
    con = connect()
    con.sql("select driver, count(*) from laps where session_key = '2024_01_R' group by 1").show()
"""

from __future__ import annotations

from pathlib import Path

import duckdb

from racecraft import config
from racecraft.store.lake import FILE_NAME
from racecraft.store.schema import TABLES

HIVE_TYPES = "{'year': SMALLINT, 'round': SMALLINT, 'session': VARCHAR}"


def connect(lake: Path | None = None) -> duckdb.DuckDBPyConnection:
    lake = (lake or config.LAKE_DIR).resolve()
    con = duckdb.connect()
    # TIMESTAMPTZ columns otherwise come back in the machine's local zone
    # (IST here), which is correct but easy to misread as UTC.
    con.execute("set TimeZone = 'UTC'")
    for table in TABLES:
        table_dir = lake / table
        if not table_dir.exists() or next(table_dir.rglob(FILE_NAME), None) is None:
            continue  # read_parquet errors on a glob with no matches
        glob = (table_dir / "*" / "*" / "*" / FILE_NAME).as_posix()
        con.execute(
            f"create or replace view {table} as "
            f"select * from read_parquet('{glob}', hive_partitioning = true, hive_types = {HIVE_TYPES})"
        )
    return con
