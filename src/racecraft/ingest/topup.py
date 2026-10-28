"""
Sessions built before every free source had published, completed afterwards (D-019).

A session F1's archive refuses is built from OpenF1 straight away (D-010). Jolpica's official
results follow some hours later (D-011), TracingInsights' tyre history and corners about twelve
hours later (D-012). Ingested before them, a session keeps OpenF1's versions, and the lake
counts it as done, so nothing would ever ask again. Each table's `sources` row says where it
came from (D-013), so this finds the gaps and fills only them: one request to Jolpica, two to
TracingInsights, no telemetry. Only the tables it changes (and `sources`) are rewritten, under
the session's lock. A source that has still not published is simply asked again next time.

Runs after every ingest pass, every Refresh data, and with `racecraft-ingest --top-up`.
"""

from __future__ import annotations

import logging

import pandas as pd

from racecraft.ingest import jolpica_source, tracinginsights_source
from racecraft.store import lake
from racecraft.store.db import connect, has_table
from racecraft.store.schema import TABLES

log = logging.getLogger(__name__)

WINDOW = pd.Timedelta(days=14)              # older gaps would have been filled long since
OFFICIAL = {"R", "S", "Q"}                  # the sessions Jolpica publishes results for


def gaps(con, now: pd.Timestamp) -> list[dict]:
    """Recent sessions with a table still waiting for a source, and which tables."""
    if not (has_table(con, "sources") and has_table(con, "sessions")):
        return []
    rows = con.execute("""
        select s.session_key, s.year, cast(s.round as integer) as round, s."session" as ident,
               s.event_name, s.session_name, s.date_utc, x.table_name, x.source
        from sessions s join sources x using (session_key)
        where s.date_utc >= ?""", [(now - WINDOW).to_pydatetime()]).df()
    out = []
    for key, mine in rows.groupby("session_key"):
        source = dict(zip(mine["table_name"], mine["source"]))
        first = mine.iloc[0]
        missing = set()
        if first["ident"] in OFFICIAL and "results" in source and "Jolpica" not in source["results"]:
            missing.add("results")
        if source.get("laps") == "OpenF1":
            missing.add("laps")
        if source.get("circuit_markers", "TracingInsights") != "TracingInsights" or (
                "laps" in source and "circuit_markers" not in source):
            missing.add("circuit_markers")
        if missing:
            out.append({"key": key, "season": int(first["year"]), "round": int(first["round"]),
                        "ident": str(first["ident"]), "event": str(first["event_name"]),
                        "session": str(first["session_name"]), "sources": source, "missing": missing})
    return out


def _table(con, name: str, key: str) -> pd.DataFrame:
    """One session's rows of a lake table, in its schema's columns (not its partition columns)."""
    if not has_table(con, name):
        return pd.DataFrame(columns=TABLES[name].names)
    columns = ", ".join(f'"{c}"' for c in TABLES[name].names)
    return con.execute(f"select {columns} from {name} where session_key = ?", [key]).df()


def fill(con, gap: dict) -> set[str]:
    """Fill one session's gaps from what has published; the tables it changed."""
    key, season, rnd, ident = gap["key"], gap["season"], gap["round"], gap["ident"]
    sources, tables = dict(gap["sources"]), {}
    if "results" in gap["missing"]:
        official = jolpica_source.official(season, rnd, ident)
        if official is not None:
            tables["results"], differ = jolpica_source.overlay(_table(con, "results", key), official, ident)
            sources["results"] += " + Jolpica"
            if differ:
                log.warning("%s: OpenF1 and Jolpica place cars %s differently; Jolpica's order kept", key, differ)
    if gap["missing"] & {"laps", "circuit_markers"}:
        found = {"laps": _table(con, "laps", key), "sessions": _table(con, "sessions", key),
                 "circuit_markers": _table(con, "circuit_markers", key)}
        found, improved = tracinginsights_source.improve(found, season, gap["event"], gap["session"], key)
        if "laps" in improved and "laps" in gap["missing"]:
            tables["laps"], sources["laps"] = found["laps"], "OpenF1 + TracingInsights"
        if "circuit_markers" in improved and "circuit_markers" in gap["missing"]:
            tables["circuit_markers"], tables["sessions"] = found["circuit_markers"], found["sessions"]
            sources["circuit_markers"] = "TracingInsights"
    if not tables:
        return set()
    now = pd.Timestamp.now(tz="UTC")
    known = _table(con, "sources", key).set_index("table_name")["fetched_at"]
    tables["sources"] = pd.DataFrame(
        [(key, name, source, now if name in tables else known.get(name)) for name, source in sources.items()],
        columns=TABLES["sources"].names)
    lake.write_session(tables, season, rnd, ident)
    return set(tables) - {"sources", "sessions"}


def top_up(now: pd.Timestamp | None = None) -> int:
    """Fill every recent gap whose source has published since; how many sessions gained something."""
    from racecraft.ingest.cli import session_lock          # cli runs this after its passes

    con = connect()
    filled = 0
    for gap in gaps(con, now or pd.Timestamp.now(tz="UTC")):
        lock = session_lock(gap["key"])
        if lock is None:
            continue                                        # being written: next pass
        try:
            done = fill(con, gap)
        except Exception as error:                          # an extra: never stops the pass it follows
            log.warning("%s: top-up failed: %s: %s", gap["key"], type(error).__name__, error)
            done = set()
        finally:
            lock.release()
        if done:
            filled += 1
            log.info("%s: topped up %s (%s)", gap["key"], ", ".join(sorted(done)),
                     ", ".join(sorted(gap["missing"] - done)) + " still waiting" if gap["missing"] - done
                     else "complete")
    return filled
