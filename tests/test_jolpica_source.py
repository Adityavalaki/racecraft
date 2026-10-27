"""Jolpica's official results over OpenF1's, offline (D-011)."""

from __future__ import annotations

import pandas as pd
from fastf1 import ergast

from racecraft.ingest import jolpica_source

# Singapore 2026 race as Jolpica gives it: a winner, a lapped car (its "time" is a gap), a car
# classified after retiring, and one not classified.
JOLPICA = pd.DataFrame({
    "number": [3, 14, 23, 5], "position": [1, 16, 18, 22], "positionText": ["1", "16", "18", "R"],
    "grid": [1, 20, 16, 14], "laps": [62, 61, 59, 7], "status": ["Finished", "Lapped", "Retired", "Retired"],
    "points": [25.0, 0.0, 0.0, 0.0], "constructorId": ["red_bull", "aston_martin", "williams", "audi"],
    "givenName": ["Max", "Fernando", "Alexander", "Gabriel"], "familyName": ["Verstappen", "Alonso", "Albon", "Bortoleto"],
    "totalRaceTime": pd.to_timedelta([6120.785, 74.454, None, None], unit="s"),
})
OPENF1 = pd.DataFrame({"driver_number": [3, 14, 23, 5, 99], "position": [1.0, 16.0, 18.0, 21.0, 22.0],
                       "full_name": ["Max VERSTAPPEN", "Fernando ALONSO", None, None, "Stand In"],
                       "team_id": [None] * 5, "result_time_s": [6120.785, None, None, None, None]})


def test_official_fields_replace_openf1s():
    out, differ = jolpica_source.overlay(OPENF1, JOLPICA, "R")
    out = out.set_index("driver_number")
    assert list(out.loc[[3, 14, 23, 5], "classified_position"]) == ["1", "16", "18", "R"]
    assert out.loc[14, "result_time_s"] == 74.454 and out.loc[14, "status"] == "Lapped"
    assert out.loc[23, "team_id"] == "williams" and out.loc[3, "full_name"] == "Max Verstappen"
    assert out.loc[5, "position"] == 22                       # the official order, not OpenF1's guess
    assert out.loc[99, "full_name"] == "Stand In"             # a car Jolpica does not list is kept as it was
    assert differ == [5]


def test_qualifying_takes_the_part_times():
    q = pd.DataFrame({"number": [12], "position": [1], "Q1": pd.to_timedelta([95.39], unit="s"),
                      "Q2": pd.to_timedelta([94.278], unit="s"), "Q3": pd.to_timedelta([94.035], unit="s"),
                      "constructorId": ["mercedes"], "givenName": ["Andrea Kimi"], "familyName": ["Antonelli"]})
    openf1 = pd.DataFrame({"driver_number": [12], "position": [1.0], "q1_s": [None], "q2_s": [None], "q3_s": [None]})
    out, _ = jolpica_source.overlay(openf1, q, "Q")
    assert list(out.loc[0, ["q1_s", "q2_s", "q3_s"]]) == [95.39, 94.278, 94.035]
    assert "grid_position" not in out                         # qualifying has no grid to take


def test_without_jolpica_openf1s_results_stand():
    assert jolpica_source.overlay(OPENF1, None, "R") == (OPENF1, [])
    assert jolpica_source.official(2026, 18, "FP1") is None   # practice: Jolpica has none, nothing asked


def test_jolpica_failing_is_not_an_error(monkeypatch):
    def down(*a, **k):
        raise ConnectionError("api.jolpi.ca unreachable")

    monkeypatch.setattr(ergast.Ergast, "get_race_results", down)
    assert jolpica_source.official(2026, 18, "R") is None
