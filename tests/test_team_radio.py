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
    session = pd.DataFrame([{n: None for n in TABLES["sessions"].names}]).assign(
        session_key="2026_17_R", session_name="Race", date_utc=START, t0_utc=T0, fastf1_version="3.8.3")
    lake.write_session({"sessions": session}, 2026, 17, "R")

    asked = []

    def get(endpoint, **params):
        asked.append(endpoint)
        if endpoint == "sessions":
            return [{"session_key": 11388, "date_start": START.isoformat()}]
        return [{"driver_number": 1, "date": (START + pd.Timedelta(minutes=30)).isoformat(),
                 "recording_url": "https://livetiming.formula1.com/static/NOR_1.mp3"}]

    monkeypatch.setattr(openf1_source, "_get", get)
    assert cli.backfill_radio([2026]) == 1

    con = connect()
    radio = con.execute("select driver_number, t, url from team_radio").df()
    assert radio[["driver_number", "t"]].values.tolist() == [[1, 52 * 60 + 30 * 60.0]]     # on FastF1's clock
    sources = con.execute("select table_name, source from sources order by table_name").fetchall()
    assert sources == [("all", "FastF1"), ("team_radio", "OpenF1")]

    assert cli.backfill_radio([2026]) == 0             # already has its radio: nothing asked
    assert asked == ["sessions", "team_radio"]
