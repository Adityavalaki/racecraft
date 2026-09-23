"""
Reads and writes the Parquet lake.

Layout: <lake>/<table>/year=YYYY/round=RR/session=S/data.parquet

A session counts as ingested only when its `sessions` file exists, and that
file is written last. An ingest that dies halfway therefore looks
un-ingested and gets redone on the next run, rather than leaving a session
that has laps but silently no telemetry.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from racecraft import config
from racecraft.store.schema import TABLES

FILE_NAME = "data.parquet"


# Bumped by every write and delete in this process, so `store/db.connect` knows
# to reload without walking the lake to find out. Writes from another process —
# the ingest command while the server runs — are found by its periodic walk.
_generation = 0


def generation() -> int:
    """How many times this process has changed a lake."""
    return _generation


def touch() -> None:
    """Record a change made to the lake outside `write_session` and `delete_session`."""
    global _generation
    _generation += 1


def partition_dir(table: str, year: int, round_number: int, session: str, lake: Path | None = None) -> Path:
    lake = lake or config.LAKE_DIR
    return lake / table / f"year={year}" / f"round={round_number:02d}" / f"session={session}"


def to_arrow(df: pd.DataFrame, table: str) -> pa.Table:
    """
    Convert column by column against the declared schema, so a type mismatch
    names the table and column instead of surfacing as a generic Arrow error.
    """
    schema = TABLES[table]
    arrays = []
    for field in schema:
        try:
            arrays.append(pa.array(df[field.name], type=field.type, from_pandas=True))
        except (pa.ArrowInvalid, pa.ArrowTypeError, TypeError, ValueError) as e:
            sample = df[field.name].dropna().head(3).tolist()
            raise TypeError(f"{table}.{field.name}: cannot store as {field.type} (sample {sample!r}): {e}") from e
    return pa.Table.from_arrays(arrays, schema=schema)


def is_ingested(year: int, round_number: int, session: str, lake: Path | None = None) -> bool:
    return (partition_dir("sessions", year, round_number, session, lake) / FILE_NAME).exists()


def write_session(tables: dict[str, pd.DataFrame], year: int, round_number: int, session: str,
                  lake: Path | None = None) -> dict[str, dict]:
    """
    Write every table for one session. Returns {table: {rows, bytes}}.
    Each file is written to a temp name and renamed into place, so readers
    never see a half-written Parquet file.
    """
    # Convert everything before writing anything: a schema error in the last
    # table shouldn't leave the first nine on disk.
    arrow_tables = {name: to_arrow(df, name) for name, df in tables.items()}

    order = sorted(arrow_tables, key=lambda n: n == "sessions")  # sessions last
    report = {}
    for name in order:
        target_dir = partition_dir(name, year, round_number, session, lake)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / FILE_NAME
        tmp = target_dir / (FILE_NAME + ".tmp")
        pq.write_table(arrow_tables[name], tmp, compression="zstd", compression_level=6)
        os.replace(tmp, target)
        report[name] = {"rows": arrow_tables[name].num_rows, "bytes": target.stat().st_size}
    touch()
    return report


def delete_session(year: int, round_number: int, session: str, lake: Path | None = None) -> None:
    for table in TABLES:
        d = partition_dir(table, year, round_number, session, lake)
        if d.exists():
            shutil.rmtree(d)
    touch()


def lake_size_bytes(lake: Path | None = None) -> int:
    lake = lake or config.LAKE_DIR
    return sum(p.stat().st_size for p in lake.rglob("*.parquet")) if lake.exists() else 0
