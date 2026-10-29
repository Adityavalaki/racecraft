"""Qualifying laps: each driver's best lap against their own best sectors added up."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import quali_laps
from racecraft.store import lake
from racecraft.store.db import connect

DRIVERS = {1: "AAA", 2: "BBB", 3: "CCC"}


def _write(path, year, rnd, code, when, laps):
    """`laps`: (car, sector 1, sector 2, sector 3, deleted); a lap with a missing sector has no lap time."""
    key = f"{year}_{rnd:02d}_{code}"
    cars = sorted({lap[0] for lap in laps})
    lake.write_session({
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": [code], "date_utc": [pd.Timestamp(when, tz="UTC")], "t0_utc": [pd.Timestamp(when, tz="UTC")],
            "start_t": [0.0], "total_laps": [0], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame([{
            "session_key": key, "driver_number": car, "abbreviation": DRIVERS[car], "full_name": f"Driver {DRIVERS[car]}",
            "team_name": "Team", "team_id": "team", "team_color": "ffffff", "grid_position": None, "position": i + 1,
            "classified_position": str(i + 1), "status": "", "points": 0.0, "laps": 3, "result_time_s": None,
            "q1_s": None, "q2_s": None, "q3_s": None} for i, car in enumerate(cars)]),
        "laps": pd.DataFrame([{
            "session_key": key, "driver_number": car, "driver": DRIVERS[car], "team": "team", "lap_number": n + 1, "stint": 1,
            "compound": "SOFT", "tyre_life": 1, "laps_in_stint": 1, "fresh_tyre": True,
            "lap_time_s": None if None in (s1, s2, s3) else s1 + s2 + s3,
            "sector1_s": s1, "sector2_s": s2, "sector3_s": s3, "lap_start_t": 0.0, "lap_end_t": 90.0,
            "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": False, "is_pit_out_lap": False, "speed_i1": None,
            "speed_i2": None, "speed_fl": None, "speed_st": None, "position": None, "track_status": "1",
            "is_personal_best": False, "deleted": deleted, "deleted_reason": None, "is_accurate": True,
            "fastf1_generated": False} for n, (car, s1, s2, s3, deleted) in enumerate(laps)]),
    }, year, rnd, code, lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    # Round 1: AAA's best lap is 93.0 but their best sectors add to 92.9 (0.1 lost in S1); a quicker
    # deleted lap counts for nothing. BBB strings their best lap together. CCC sets no time.
    _write(tmp_path, 2024, 1, "Q", "2024-03-02 15:00", [
        (1, 30.0, 31.0, 32.0, False), (1, 29.9, 31.2, 32.1, False), (1, 29.0, 30.0, 31.0, True),
        (2, 30.0, 30.0, 30.0, False), (2, 30.5, 30.5, 30.5, False),
        (3, 31.0, None, None, False)])
    # Round 2: AAA leaves 0.3 in S3; a sprint qualifying the day before.
    _write(tmp_path, 2024, 2, "SQ", "2024-03-08 15:00", [(1, 30.0, 30.0, 30.0, False)])
    _write(tmp_path, 2024, 2, "Q", "2024-03-09 15:00", [
        (1, 30.0, 30.0, 30.3, False), (1, 30.2, 30.2, 30.0, False), (2, 30.0, 30.0, 30.0, False)])
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def _row(body, code):
    return next(d for d in body["drivers"] if d["abbreviation"] == code)


def test_time_left_against_own_best_sectors(con):
    body = quali_laps.latest(con, 2024, pd.Timestamp("2024-03-05", tz="UTC"))
    assert body["session_key"] == "2024_01_Q" and body["sessions"] == 1
    aaa = _row(body, "AAA")
    assert aaa["best_s"] == 93.0 and aaa["ideal_s"] == 92.9                     # the deleted 90.0 is ignored
    assert aaa["left_s"] == pytest.approx(0.1) and aaa["sectors_left"] == pytest.approx([0.1, 0.0, 0.0])
    assert _row(body, "BBB")["left_s"] == 0
    ccc = _row(body, "CCC")
    assert ccc["best_s"] is None and ccc["left_s"] is None and "CCC set no lap time that counted" in body["notes"]
    assert [d["abbreviation"] for d in body["drivers"]] == ["AAA", "BBB", "CCC"]


def test_season_average_kind_and_as_of(con):
    body = quali_laps.latest(con, 2024)
    assert body["session_key"] == "2024_02_Q" and body["sessions"] == 2
    aaa = _row(body, "AAA")
    assert aaa["left_s"] == pytest.approx(0.3) and aaa["sectors_left"] == pytest.approx([0.0, 0.0, 0.3])
    assert aaa["season_left_s"] == pytest.approx(0.2) and aaa["season_sessions"] == 2
    assert quali_laps.latest(con, 2024, code="SQ")["session_key"] == "2024_02_SQ"
    empty = quali_laps.latest(con, 2024, pd.Timestamp("2024-01-01", tz="UTC"))
    assert empty["drivers"] == [] and empty["notes"]


def test_the_route(con):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    url = "/api/sessions/2024_02_Q/qualifying"
    assert client.get(url).json()["session_key"] == "2024_01_Q"                 # before: no spoiler
    assert client.get(url, params={"moment": "after"}).json()["session_key"] == "2024_02_Q"
    assert client.get(url, params={"kind": "SQ"}).json()["session_key"] == "2024_02_SQ"
    assert client.get(url, params={"kind": "R"}).status_code == 422
    assert client.get("/api/sessions/1999_01_Q/qualifying").status_code == 404
    assert client.get("/api/sessions/live/qualifying").status_code == 422
