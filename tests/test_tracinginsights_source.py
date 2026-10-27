"""TracingInsights' archive as the lake's tables, offline (D-012)."""

from __future__ import annotations

import fastf1
import pandas as pd
import pytest

from racecraft.ingest import quality, tracinginsights_source as ti

# Two laps of NOR in FP1, as `session_laptimes.json` has them (Austin 2026): an out-lap from
# the garage, then a timed lap on a used set of softs. Missing values are the string "None".
LAPTIMES = {
    "time": ["None", 98.715], "lap": [1, 2], "compound": ["SOFT", "SOFT"], "stint": [3, 3], "life": [7, 8],
    "fresh": [False, False], "s1": ["None", 27.1], "s2": [44.0, 41.5], "s3": [30.1, 30.115], "pos": ["None", "None"],
    "status": ["1", "12"], "pb": [False, True], "sesT": [1023.706, 1122.421], "drv": ["NOR", "NOR"], "dNum": ["1", "1"],
    "pout": [883.704, "None"], "pin": ["None", "None"], "vi1": [250, 300], "vi2": [260, 310], "vfl": [270, 290],
    "vst": [300, 330], "team": ["McLaren", "McLaren"], "lST": [883.704, 1023.706],
    "lSD": ["2026-10-23T17:31:39.757000000", "2026-10-23T17:33:59.759000000"], "del": [False, False],
    "delR": ["", ""], "ff1G": [False, False], "iacc": [False, True],
}
CORNERS = {"CornerNumber": [1, 2], "CornerLetter": ["", "A"], "X": [3743.5, 3414.0], "Y": [10.0, 20.0],
           "Angle": [-44.6, -200.3], "Distance": [624.5, 893.2], "Rotation": 90.0,
           "MarshalLightNumber": [1], "MarshalLightX": [1.0], "MarshalLightY": [2.0], "MarshalLightAngle": [0.0],
           "MarshalLightDistance": [100.0], "MarshalSectorNumber": [], "Location": "Austin"}


def test_laps_read_as_fastf1_wrote_them():
    laps = ti.laps(LAPTIMES, "2026_18_FP1").set_index("lap_number")
    assert pd.isna(laps.loc[1, "lap_time_s"]) and laps.loc[2, "lap_time_s"] == 98.715
    assert list(laps["tyre_life"]) == [7, 8] and not laps["fresh_tyre"].any()      # a used set
    assert list(laps["laps_in_stint"]) == [1, 2]
    assert laps.loc[1, "is_pit_out_lap"] and laps.loc[1, "pit_out_t"] == 883.704 and not laps["is_pit_in_lap"].any()
    assert laps.loc[2, "lap_end_t"] == 1122.421 and laps.loc[2, "track_status"] == "12"


def test_corners_and_marshal_lights_become_markers():
    markers, rotation = ti.markers(CORNERS, "k")
    assert rotation == 90.0
    corners = markers[markers["kind"] == "corner"]
    assert list(corners["number"]) == [1, 2] and corners["letter"].tolist()[1] == "A"
    assert pd.isna(corners["letter"].tolist()[0])                                    # "" is no letter
    assert list(markers["kind"]) == ["corner", "corner", "marshal_light"]
    assert ti.markers({"CornerNumber": []}, "k") is None


def test_fastf1s_tyres_replace_openf1s():
    theirs = ti.laps(LAPTIMES, "k")
    openf1 = theirs.assign(tyre_life=[1.0, 2.0], fresh_tyre=True, stint=1.0,       # OpenF1: "a new set"
                           lap_time_s=[None, 98.9])
    out, differ = ti.tyres_over(openf1, theirs)
    assert list(out["tyre_life"]) == [7, 8] and not out["fresh_tyre"].any() and list(out["stint"]) == [3, 3]
    assert list(out.columns) == list(openf1.columns)
    assert differ == 1                                                                # 98.9 against 98.715


def test_a_session_openf1_lacks_is_built_from_the_archive(monkeypatch):
    rcm = {"time": ["2026-10-23T17:40:00.000000000", "2026-10-23T17:41:00.000000000"], "cat": ["Flag", "Flag"],
           "msg": ["YELLOW IN TRACK SECTOR 5", "CLEAR IN TRACK SECTOR 5"], "status": ["None", "None"],
           "flag": ["YELLOW", "CLEAR"], "scope": ["Sector", "Sector"], "sector": [5.0, 5.0], "dNum": ["None", "None"],
           "lap": [2, 2]}
    files = {"session_laptimes.json": LAPTIMES, "corners.json": CORNERS, "rcm.json": rcm,
             "weather.json": {"wT": [60.0], "wAT": [26.9], "wH": [42.3], "wP": [1005.3], "wR": [False],
                              "wTT": [38.3], "wWD": [115], "wWS": [3.1]},
             "drivers.json": {"drivers": [{"driver": "NOR", "team": "McLaren", "dn": "1", "fn": "Lando",
                                           "ln": "Norris", "tc": "F47600"}]}}

    class Schedule:
        date = pd.Timestamp("2026-10-23 17:30")
        name = "Practice 1"
        event = {"EventName": "United States Grand Prix", "Country": "United States", "Location": "Austin"}

    monkeypatch.setattr(ti, "_get", lambda season, event, session, file: files.get(file))
    monkeypatch.setattr(fastf1, "get_session", lambda *a: Schedule())
    tables = ti.extract(2026, 18, "FP1", "Practice 1", "2026_18_FP1")

    # t0 is FastF1's: lap 1 started 883.704 s after it.
    assert tables["sessions"].loc[0, "t0_utc"] == pd.Timestamp("2026-10-23 17:16:56.053", tz="UTC")
    assert tables["sessions"].loc[0, "fastf1_version"] == "tracinginsights"
    assert tables["race_control"]["t"].tolist() == pytest.approx([1383.947, 1443.947])
    assert tables["track_status"]["status"].tolist() == ["1", "2", "1"]
    assert tables["results"].loc[0, "full_name"] == "Lando Norris"
    assert tables["sessions"].loc[0, "circuit_rotation_deg"] == 90.0 and len(tables["circuit_markers"]) == 3
    findings = [f for f in quality.check_session(tables) if f.check != "results.drivers"]   # a one-car field
    assert not quality.has_errors(findings), findings


def test_nothing_published_is_none(monkeypatch):
    monkeypatch.setattr(ti, "_get", lambda *a: None)
    monkeypatch.setattr(fastf1, "get_session", lambda *a: type("S", (), {"event": {"EventName": "X"}})())
    assert ti.extract(2026, 19, "R", "Race", "2026_19_R") is None
