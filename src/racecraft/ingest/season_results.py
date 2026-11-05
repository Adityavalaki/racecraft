"""
A season's official Grand Prix and sprint results, for rounds the lake has no session of (D-031).

A new install fetches five weekends (`sync.DEFAULT_WEEKENDS`), and the championships add up
results: without the other rounds, five rounds' points would read as the season. This asks
Jolpica for each one, once: a request a session, about thirty for a season, no telemetry.

They have a table of their own because a row in `sessions` means a session that can be opened,
with laps to read. A round that later gets a real session takes its results from there
(`standings.results`), and these stay unread.
"""

from __future__ import annotations

import logging

import fastf1
import pandas as pd

from racecraft import config
from racecraft.ingest import cli, jolpica_source
from racecraft.store import lake
from racecraft.store.db import connect, has_table

log = logging.getLogger(__name__)

RACES = ("R", "S")


def missing(con, season: int, now: pd.Timestamp) -> list[dict]:
    """The season's published races and sprints the lake has no results of, in running order."""
    held = set()
    for table in ("sessions", "official_results"):
        if has_table(con, table):
            held |= {row[0] for row in con.execute(f"select session_key from {table} where year = ?", [season]).fetchall()}
    out = []
    for _, event in fastf1.get_event_schedule(season, include_testing=False).iterrows():
        for index in range(1, 6):
            ident = config.SESSION_CODES.get(event.get(f"Session{index}"))
            start = event.get(f"Session{index}DateUtc")
            if ident not in RACES or pd.isna(start):
                continue
            start = pd.Timestamp(start).tz_localize("UTC")
            key = f"{season}_{int(event['RoundNumber']):02d}_{ident}"
            if key not in held and start + cli.PUBLISH_DELAY <= now:
                out.append({"key": key, "round": int(event["RoundNumber"]), "ident": ident,
                            "event": str(event["EventName"]), "start": start})
    return out


def _rows(gap: dict, official: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame({
        "session_key": gap["key"], "event_name": gap["event"], "date_utc": gap["start"],
        "driver_number": pd.to_numeric(official["number"]), "abbreviation": official["driverCode"],
        "full_name": official["givenName"] + " " + official["familyName"],
        "team_name": official["constructorName"], "team_id": official["constructorId"],
        "position": pd.to_numeric(official["position"]), "classified_position": official["positionText"].astype(str),
        "points": pd.to_numeric(official["points"]),
    })


def fill(seasons, now: pd.Timestamp | None = None) -> int:
    """Fetch the seasons' missing results; how many sessions it added."""
    now = now if now is not None else pd.Timestamp.now(tz="UTC")
    con = connect()
    added = 0
    # Newest first: what a new user opens first, and an error stops the rest of this pass.
    for season in sorted(seasons, reverse=True):
        for gap in missing(con, season, now):
            official = jolpica_source.official(season, gap["round"], gap["ident"])
            if official is None:
                # Oldest first, so what follows is no likelier to be there: while Jolpica
                # is down or has not published, this costs one request a pass, not thirty.
                log.info("%s: Jolpica has no results yet; the rest of %d waits for the next pass", gap["key"], season)
                break
            lake.write_session({"official_results": _rows(gap, official)}, season, gap["round"], gap["ident"])
            added += 1
    return added
