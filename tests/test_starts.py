"""Starts: places gained on lap 1, raw and against the grid slot's average."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import starts
from racecraft.store import lake
from racecraft.store.db import connect

DRIVERS = {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD", 5: "EEE"}


def _write(path, year, rnd, code, when, cars):
    """`cars`: (car, grid, position after lap 1 or None, classified)."""
    key = f"{year}_{rnd:02d}_{code}"
    lake.write_session({
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": [code], "date_utc": [pd.Timestamp(when, tz="UTC")], "t0_utc": [pd.Timestamp(when, tz="UTC")],
            "start_t": [0.0], "total_laps": [10], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame([{
            "session_key": key, "driver_number": car, "abbreviation": DRIVERS[car], "full_name": f"Driver {DRIVERS[car]}",
            "team_name": "Team", "team_id": "team", "team_color": "ffffff", "grid_position": grid, "position": i + 1,
            "classified_position": classified, "status": "", "points": 0.0, "laps": 10, "result_time_s": None,
            "q1_s": None, "q2_s": None, "q3_s": None} for i, (car, grid, _, classified) in enumerate(cars)]),
        "laps": pd.DataFrame([{
            "session_key": key, "driver_number": car, "driver": DRIVERS[car], "team": "team", "lap_number": 1, "stint": 1,
            "compound": "MEDIUM", "tyre_life": 1, "laps_in_stint": 1, "fresh_tyre": True, "lap_time_s": 95.0,
            "sector1_s": None, "sector2_s": None, "sector3_s": None, "lap_start_t": 0.0, "lap_end_t": 95.0,
            "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": False, "is_pit_out_lap": False, "speed_i1": None,
            "speed_i2": None, "speed_fl": None, "speed_st": None, "position": lap1, "track_status": "1",
            "is_personal_best": False, "deleted": False, "deleted_reason": None, "is_accurate": True,
            "fastf1_generated": False} for car, _, lap1, classified in cars if classified != "W"]),
    }, year, rnd, code, lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    # The year before: everyone holds their slot, so it pulls each slot's average towards 0.
    _write(tmp_path, 2023, 1, "R", "2023-03-05 15:00", [(1, 1, 1, "1"), (2, 2, 2, "2"), (3, 3, 3, "3")])
    # Round 1: AAA loses one from pole, BBB gains one, DDD from the pit lane, EEE out on lap 1.
    _write(tmp_path, 2024, 1, "R", "2024-03-03 15:00",
           [(2, 2, 1, "1"), (1, 1, 2, "2"), (3, 3, 3, "3"), (4, 0, 4, "4"), (5, 4, None, "R")])
    # Round 2: a sprint where nothing changes, then the race: AAA gains one, BBB loses two, CCC gains one; EEE does not start.
    _write(tmp_path, 2024, 2, "S", "2024-03-09 15:00", [(1, 1, 1, "1"), (2, 2, 2, "2")])
    _write(tmp_path, 2024, 2, "R", "2024-03-10 15:00",
           [(1, 2, 1, "1"), (3, 3, 2, "2"), (2, 1, 3, "3"), (5, 4, None, "W")])
    # Round 3: no grid published.
    _write(tmp_path, 2024, 3, "R", "2024-03-17 15:00", [(1, -1, 1, "1"), (2, -1, 2, "2")])
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def _row(table, kind, code):
    return next(d for d in table.drivers[kind] if d["abbreviation"] == code)


def test_places_gained_against_the_slot_average(con):
    table = starts.season(con, 2024)
    # Race slot averages over 2023-24: P1 (0, -1, -2) = -1, P2 (0, +1, +1) = 2/3, P3 (0, 0, +1) = 1/3.
    aaa, bbb, ccc = (_row(table, "races", c) for c in ("AAA", "BBB", "CCC"))
    assert aaa["gained"] == 0 and aaa["vs_normal"] == pytest.approx(1 / 6, abs=0.01)    # -1 vs -1, +1 vs 2/3
    assert bbb["gained"] == -0.5 and bbb["vs_normal"] == pytest.approx(-1 / 3, abs=0.01)
    assert ccc["vs_normal"] == pytest.approx(1 / 6, abs=0.01)
    assert (bbb["up"], bbb["same"], bbb["down"]) == (1, 0, 1)
    assert bbb["best"] == {"event_name": "Round 1 Grand Prix", "grid": 2, "lap1": 1, "gain": 1}
    assert bbb["worst"]["gain"] == -2
    assert [d["abbreviation"] for d in table.drivers["races"]] == ["AAA", "CCC", "BBB", "EEE"]


def test_lap_one_retirements_pit_lane_and_no_grid_are_kept_apart(con):
    table = starts.season(con, 2024)
    eee = _row(table, "races", "EEE")
    assert eee["out_lap1"] == 1 and eee["starts"] == 0 and eee["vs_normal"] is None    # the W in round 2 is not a start
    assert "DDD" not in {d["abbreviation"] for d in table.drivers["races"]}
    assert any("DDD started from the pit lane" in n for n in table.notes)
    assert any("Round 3 Grand Prix: no grid published" in n for n in table.notes)
    assert table.sessions == {"races": 2, "sprints": 1, "both": 3}


def test_sprints_apart_and_together(con):
    table = starts.season(con, 2024)
    assert _row(table, "sprints", "AAA")["starts"] == 1 and _row(table, "sprints", "AAA")["vs_normal"] == 0
    assert _row(table, "both", "AAA")["starts"] == 3


def test_as_of_and_the_route(con):
    before = starts.season(con, 2024, as_of=pd.Timestamp("2024-03-08", tz="UTC"))
    assert before.sessions["races"] == 1 and _row(before, "races", "BBB")["gained"] == 1
    assert starts.season(con, 2024, as_of=pd.Timestamp("2024-01-01", tz="UTC")).notes

    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    body = client.get("/api/sessions/2024_02_R/starts").json()
    assert body["moment"] == "before" and body["sessions"]["races"] == 1
    assert client.get("/api/sessions/2024_02_R/starts", params={"moment": "after"}).json()["sessions"]["races"] == 2
    assert client.get("/api/sessions/2024_02_R/starts", params={"moment": "later"}).status_code == 422
    assert client.get("/api/sessions/1999_01_R/starts").status_code == 404
    assert client.get("/api/sessions/live/starts").status_code == 422
