"""Team radio added to sessions already in the lake, offline (D-014)."""

from __future__ import annotations

import pandas as pd

from racecraft import config
from racecraft.ingest import cli, openf1_source
from racecraft.store import lake
from racecraft.store.db import connect
from racecraft.store.schema import TABLES

START = pd.Timestamp("2026-10-11 12:00", tz="UTC")       # Singapore 2026's race
T0 = START - pd.Timedelta(minutes=52)                    # FastF1 puts t0 a little before


def test_a_fastf1_session_gains_its_radio_and_keeps_its_source(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path / "lake")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    blank = pd.DataFrame([{n: None for n in TABLES["sessions"].names}])
    lake.write_session({"sessions": blank.assign(session_key="2026_17_R", session_name="Race", date_utc=START,
                                                 t0_utc=T0, fastf1_version="3.8.3")}, 2026, 17, "R")
    # An OpenF1 session from before radio was stored: it already has source rows, which
    # the lake reads back with its partition columns (year, round, session) beside them.
    later = START + pd.Timedelta(days=14)
    lake.write_session({
        "sessions": blank.assign(session_key="2026_18_R", session_name="Race", date_utc=later,
                                 t0_utc=later - pd.Timedelta(hours=1), fastf1_version="openf1"),
        "sources": pd.DataFrame([("2026_18_R", "laps", "OpenF1 + TracingInsights", later)],
                                columns=["session_key", "table_name", "source", "fetched_at"]),
    }, 2026, 18, "R")

    asked = []

    def get(endpoint, **params):
        asked.append(endpoint)
        if endpoint == "sessions":
            return [{"session_key": 11388, "date_start": START.isoformat()},
                    {"session_key": 11396, "date_start": later.isoformat()}]
        when = START if params["session_key"] == 11388 else later
        return [{"driver_number": 1, "date": (when + pd.Timedelta(minutes=30)).isoformat(),
                 "recording_url": f"https://livetiming.formula1.com/static/NOR_{params['session_key']}.mp3"}]

    monkeypatch.setattr(openf1_source, "_get", get)
    assert cli.backfill_radio([2026]) == 2

    con = connect()
    radio = con.execute("select session_key, driver_number, t from team_radio order by session_key").df()
    assert radio.values.tolist() == [["2026_17_R", 1, 52 * 60 + 30 * 60.0],      # on FastF1's clock
                                     ["2026_18_R", 1, 90 * 60.0]]
    sources = con.execute("select session_key, table_name, source from sources order by 1, 2").fetchall()
    assert sources == [("2026_17_R", "all", "FastF1"), ("2026_17_R", "team_radio", "OpenF1"),
                       ("2026_18_R", "laps", "OpenF1 + TracingInsights"), ("2026_18_R", "team_radio", "OpenF1")]

    assert cli.backfill_radio([2026]) == 0             # both have their radio now: nothing asked
    assert asked == ["sessions", "team_radio", "team_radio"]
