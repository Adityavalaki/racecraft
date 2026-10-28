"""Recent sessions completed once Jolpica and TracingInsights publish, offline (D-019)."""

from __future__ import annotations

import pandas as pd

from racecraft import config
from racecraft.ingest import jolpica_source, topup, tracinginsights_source
from racecraft.store import lake
from racecraft.store.db import connect
from racecraft.store.schema import TABLES

KEY = "2026_19_Q"
START = pd.Timestamp("2026-10-31 21:00", tz="UTC")
NOW = START + pd.Timedelta(days=1)


def _rows(name: str, rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame([{**dict.fromkeys(TABLES[name].names), **r} for r in rows], columns=TABLES[name].names)


def _openf1_session(tmp_path, monkeypatch):
    """A qualifying session built from OpenF1 alone, as ingest writes one before the others publish."""
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path / "lake")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    laps = [{"session_key": KEY, "driver_number": 4, "driver": "NOR", "lap_number": n, "stint": 1.0,
             "compound": "SOFT", "tyre_life": float(n), "laps_in_stint": float(n), "fresh_tyre": True,
             "lap_time_s": 77.0 + n, "lap_start_t": 3600.0 + 80 * n, "lap_end_t": 3680.0 + 80 * n} for n in (1, 2)]
    sources = {"sessions": "OpenF1", "results": "OpenF1", "laps": "OpenF1",
               "circuit_markers": "earlier session at this circuit"}
    lake.write_session({
        "sessions": _rows("sessions", [{"session_key": KEY, "event_name": "Mexico City Grand Prix",
                                        "session_name": "Qualifying", "date_utc": START,
                                        "t0_utc": START - pd.Timedelta(hours=1), "fastf1_version": "openf1",
                                        "circuit_rotation_deg": 0.0}]),
        "results": _rows("results", [{"session_key": KEY, "driver_number": 4, "abbreviation": "NOR", "position": 1.0}]),
        "laps": _rows("laps", laps),
        "circuit_markers": _rows("circuit_markers", [{"session_key": KEY, "kind": "corner", "number": 1,
                                                      "x": 0.0, "y": 0.0, "angle": 0.0, "distance": 10.0}]),
        "sources": pd.DataFrame([(KEY, t, s, START) for t, s in sources.items()], columns=TABLES["sources"].names),
    }, 2026, 19, "Q")


OFFICIAL = pd.DataFrame({"number": [4], "position": [1], "Q1": pd.to_timedelta([77.1], unit="s"),
                         "Q2": pd.to_timedelta([76.8], unit="s"), "Q3": pd.to_timedelta([76.5], unit="s"),
                         "constructorId": ["mclaren"], "givenName": ["Lando"], "familyName": ["Norris"]})
# FastF1's tyre history: a used set of softs (life 4 on the first lap), as TracingInsights has it.
LAPTIMES = {"lap": [1, 2], "dNum": ["4", "4"], "drv": ["NOR", "NOR"], "team": ["McLaren"] * 2,
            "compound": ["SOFT"] * 2, "stint": [1, 1], "life": [4, 5], "fresh": [False, False],
            "time": [78.0, 79.0], "s1": [26.0] * 2, "s2": [26.0] * 2, "s3": [26.0, 27.0], "lST": [3680.0, 3760.0],
            "sesT": [3760.0, 3840.0], "pin": ["None"] * 2, "pout": ["None"] * 2, "vi1": [300] * 2, "vi2": [300] * 2,
            "vfl": [300] * 2, "vst": [320] * 2, "pos": ["None"] * 2, "status": ["1"] * 2, "pb": [True, False],
            "del": [False] * 2, "delR": [""] * 2, "ff1G": [False] * 2, "iacc": [True] * 2}
CORNERS = {"CornerNumber": [1, 2], "CornerLetter": ["", ""], "X": [1.0, 2.0], "Y": [3.0, 4.0], "Angle": [0.0, 90.0],
           "Distance": [100.0, 400.0], "Rotation": 36.0}


def _sources() -> dict[str, str]:
    return dict(connect().execute("select table_name, source from sources").fetchall())


def test_gaps_are_filled_as_each_source_publishes(tmp_path, monkeypatch):
    _openf1_session(tmp_path, monkeypatch)
    published = {}
    monkeypatch.setattr(jolpica_source, "official", lambda *a: OFFICIAL)
    monkeypatch.setattr(tracinginsights_source, "_get", lambda season, event, session, file: published.get(file))

    # Jolpica has published, TracingInsights not yet: the results are filled, the tyres wait.
    assert topup.real_top_up(now=NOW) == 1
    con = connect()
    result = con.execute("select team_id, q3_s from results").fetchone()
    assert result == ("mclaren", 76.5)
    assert _sources()["results"] == "OpenF1 + Jolpica" and _sources()["laps"] == "OpenF1"

    # Twelve hours on, TracingInsights too: FastF1's tyre history and this session's corners.
    published.update({"session_laptimes.json": LAPTIMES, "corners.json": CORNERS})
    assert topup.real_top_up(now=NOW) == 1
    con = connect()
    assert [row[0] for row in con.execute("select tyre_life from laps order by lap_number").fetchall()] == [4, 5]
    assert con.execute("select count(*) from circuit_markers").fetchone()[0] == 2
    assert con.execute("select circuit_rotation_deg from sessions").fetchone()[0] == 36.0
    assert _sources() == {"sessions": "OpenF1", "results": "OpenF1 + Jolpica", "laps": "OpenF1 + TracingInsights",
                          "circuit_markers": "TracingInsights"}

    # Nothing left to ask for.
    assert topup.gaps(connect(), NOW) == []
    assert topup.real_top_up(now=NOW) == 0


def test_old_sessions_are_left_alone(tmp_path, monkeypatch):
    _openf1_session(tmp_path, monkeypatch)
    assert topup.gaps(connect(), NOW + pd.Timedelta(days=30)) == []      # beyond the window


def test_nothing_published_writes_nothing(tmp_path, monkeypatch):
    _openf1_session(tmp_path, monkeypatch)
    monkeypatch.setattr(jolpica_source, "official", lambda *a: None)
    monkeypatch.setattr(tracinginsights_source, "_get", lambda *a: None)
    assert topup.real_top_up(now=NOW) == 0
    assert _sources()["results"] == "OpenF1"
