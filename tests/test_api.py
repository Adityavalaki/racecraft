"""API tests against a small lake built on the fly, so they need no network and no real data."""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from racecraft import config
from racecraft.api import session as session_store
from racecraft.api.app import app
from racecraft.store import lake

KEY = "2024_01_R"
LAP = 90.0
START = 1000.0


def _laps() -> pd.DataFrame:
    rows = []
    for number, driver, offset in ((1, "LEA", 0.0), (44, "SEC", 6.0)):
        for lap in (1, 2, 3):
            end = START + offset + lap * LAP
            rows.append({
                "session_key": KEY, "driver_number": number, "driver": driver, "team": "T",
                "lap_number": lap, "stint": 1, "compound": "HARD", "tyre_life": 4 + lap,
                "laps_in_stint": lap, "fresh_tyre": False, "lap_time_s": LAP,
                "sector1_s": 30.0, "sector2_s": 30.0, "sector3_s": 30.0,
                "lap_start_t": end - LAP, "lap_end_t": end, "pit_in_t": None, "pit_out_t": None,
                "is_pit_in_lap": False, "is_pit_out_lap": False,
                "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                "position": 1 if number == 1 else 2, "track_status": "1", "is_personal_best": False,
                "deleted": False, "deleted_reason": None, "is_accurate": True, "fastf1_generated": False,
            })
    return pd.DataFrame(rows)


def _telemetry(table: str) -> pd.DataFrame:
    t = np.arange(START, START + 3 * LAP, 0.24)
    frames = []
    for number in (1, 44):
        base = {"session_key": KEY, "driver_number": number, "t": t}
        if table == "pos_data":
            angle = (t - START) / LAP * 2 * np.pi
            base |= {"x": 1000 * np.cos(angle), "y": 1000 * np.sin(angle),
                     "z": np.zeros(len(t)), "status": "OnTrack"}
        else:
            base |= {"rpm": np.full(len(t), 11000.0), "speed": 200 + 50 * np.sin(t), "gear": np.full(len(t), 7.0),
                     "throttle": np.full(len(t), 80.0), "brake": np.zeros(len(t), dtype=bool),
                     "drs": np.zeros(len(t))}
        frames.append(pd.DataFrame(base))
    return pd.concat(frames, ignore_index=True)


@pytest.fixture
def client(tmp_path, monkeypatch):
    laps = _laps()
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [KEY], "event_name": ["Bahrain Grand Prix"], "country": ["Bahrain"],
            "location": ["Sakhir"], "session_name": ["Race"],
            "date_utc": [pd.Timestamp("2024-03-02 15:00", tz="UTC")],
            "t0_utc": [pd.Timestamp("2024-03-02 14:03", tz="UTC")], "start_t": [START],
            "total_laps": [3], "circuit_rotation_deg": [92.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame({
            "session_key": KEY, "driver_number": [1, 44], "abbreviation": ["LEA", "SEC"],
            "full_name": ["A Leader", "B Second"], "team_name": ["Red", "Silver"],
            "team_id": ["red", "silver"], "team_color": ["ff0000", "cccccc"],
            "grid_position": [1, 2], "position": [1, 2], "classified_position": ["1", "2"],
            "status": ["Finished", "Finished"], "points": [25.0, 18.0], "laps": [3, 3],
            "result_time_s": [270.0, 6.0], "q1_s": [None, None], "q2_s": [None, None], "q3_s": [None, None]}),
        "laps": laps,
        "pos_data": _telemetry("pos_data"),
        "car_data": _telemetry("car_data"),
        "track_status": pd.DataFrame({"session_key": [KEY], "t": [0.0], "status": ["1"], "message": ["AllClear"]}),
        "weather": pd.DataFrame({"session_key": [KEY], "t": [0.0], "air_temp": [25.0], "track_temp": [30.0],
                                 "humidity": [40.0], "pressure": [1010.0], "wind_speed": [2.0],
                                 "wind_direction": [180], "rainfall": [False]}),
        "race_control": pd.DataFrame({"session_key": [KEY], "t": [START + 5], "lap": [1], "category": ["Flag"],
                                      "flag": ["GREEN"], "scope": ["Track"], "sector": [None],
                                      "racing_number": [None], "status": [None], "message": ["GREEN LIGHT"]}),
    }
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    session_store._cache.clear()
    return TestClient(app)


def test_sessions_are_listed(client):
    body = client.get("/api/sessions").json()
    assert [s["session_key"] for s in body] == [KEY]
    assert body[0]["event_name"] == "Bahrain Grand Prix"


def test_session_info_carries_drivers_and_track_outline(client):
    body = client.get(f"/api/sessions/{KEY}").json()
    assert body["total_laps"] == 3
    assert {d["abbreviation"] for d in body["drivers"]} == {"LEA", "SEC"}
    assert len(body["outline"]) > 50           # a lap's worth of shape
    assert body["has_position_data"] is True
    assert body["bounds"]["max_x"] == pytest.approx(1000, abs=1)


def test_state_gives_order_gaps_and_car_positions(client):
    body = client.get(f"/api/sessions/{KEY}/state", params={"t": START + 2 * LAP + 30}).json()
    leader, second = body["drivers"]
    assert leader["abbreviation"] == "LEA"
    assert second["gap_to_leader_s"] == pytest.approx(6.0)
    assert second["laps_down"] == 0            # behind on time, not lapped
    assert body["cars"]["1"]["x"] is not None
    assert body["cars"]["1"]["speed"] is not None
    assert body["track_status"]["status"] == "1"


def test_frames_return_parallel_arrays_for_playback(client):
    body = client.get(f"/api/sessions/{KEY}/frames",
                      params={"start": START, "end": START + 10, "hz": 5}).json()
    assert len(body["t"]) == 51
    assert len(body["drivers"]["1"]["x"]) == 51
    assert all(v is not None for v in body["drivers"]["1"]["x"])


def test_frames_reject_an_unreasonable_window(client):
    assert client.get(f"/api/sessions/{KEY}/frames",
                      params={"start": 0, "end": 5000, "hz": 5}).status_code == 400
    assert client.get(f"/api/sessions/{KEY}/frames",
                      params={"start": 100, "end": 50, "hz": 5}).status_code == 400


def test_lap_chart_has_a_series_per_driver(client):
    body = client.get(f"/api/sessions/{KEY}/laps").json()
    by_code = {d["abbreviation"]: d for d in body["drivers"]}
    assert by_code["LEA"]["gap_to_leader_s"] == [0.0, 0.0, 0.0]
    assert by_code["SEC"]["gap_to_leader_s"] == [6.0, 6.0, 6.0]


def test_unknown_session_is_a_404(client):
    assert client.get("/api/sessions/1999_01_R").status_code == 404


def test_positions_are_null_past_the_end_of_the_telemetry(client):
    # Rather than extrapolating a car onto the track where no samples exist.
    body = client.get(f"/api/sessions/{KEY}/state", params={"t": START + 3 * LAP + 60}).json()
    assert body["cars"]["1"]["x"] is None
    assert body["drivers"][0]["status"] == "finished"
