"""Race review: overtakes made and lost, and places lost at each pit stop."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import race_review
from racecraft.store import lake
from racecraft.store.db import connect

CARS = {1: "AAA", 2: "BBB", 3: "CCC", 4: "DDD", 5: "EEE"}
A, B, C, D, E = CARS


def _write(path, rnd, when, order, pit_in=(), neutral=(), finish=("1", "2", "3", "4", "R")):
    """`order`: {lap: cars front to back}; `pit_in`: (car, in-lap), the out-lap is the next one; `neutral`: safety-car laps."""
    key = f"2024_{rnd:02d}_R"
    stops = set(pit_in)
    outs = {(car, lap + 1) for car, lap in stops}
    finishers = order[max(order)]
    rows = [{
        "session_key": key, "driver_number": car, "driver": CARS[car], "team": "team", "lap_number": lap, "stint": 1,
        "compound": "MEDIUM", "tyre_life": lap, "laps_in_stint": lap, "fresh_tyre": True, "lap_time_s": 90.0,
        "sector1_s": None, "sector2_s": None, "sector3_s": None, "lap_start_t": 90.0 * (lap - 1), "lap_end_t": 90.0 * lap,
        "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": (car, lap) in stops, "is_pit_out_lap": (car, lap) in outs,
        "speed_i1": None, "speed_i2": None, "speed_fl": None, "speed_st": None, "position": float(place + 1),
        "track_status": "4" if lap in neutral else "1", "is_personal_best": False, "deleted": False, "deleted_reason": None,
        "is_accurate": True, "fastf1_generated": False} for lap, cars in order.items() for place, car in enumerate(cars)]
    lake.write_session({
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": ["Race"], "date_utc": [pd.Timestamp(when, tz="UTC")], "t0_utc": [pd.Timestamp(when, tz="UTC")],
            "start_t": [0.0], "total_laps": [max(order)], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame([{
            "session_key": key, "driver_number": car, "abbreviation": CARS[car], "full_name": f"Driver {CARS[car]}",
            "team_name": "Team", "team_id": "team", "team_color": "ffffff", "grid_position": car, "position": i + 1,
            "classified_position": finish[i], "status": "", "points": 0.0, "laps": 10, "result_time_s": None,
            "q1_s": None, "q2_s": None, "q3_s": None} for i, car in enumerate(finishers + [c for c in CARS if c not in finishers and any(c in o for o in order.values())])]),
        "laps": pd.DataFrame(rows),
    }, 2024, rnd, "R", lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    every = [A, B, C, D]
    order = {1: every + [E], 2: every + [E],
             3: [A, C, B, D, E],               # C passes B on track
             4: [A, C, D, B], 5: [A, C, D, B],   # B stops on lap 4 and comes out behind D: one place
             6: [A, C, D, B], 7: [A, C, D, B],   # A stops under the safety car (laps 6-7) and keeps the lead
             8: [A, D, C, B],                    # D past C, but lap 7 was neutralised: not counted
             9: [A, D, C, B], 10: [A, D, B, C]}  # B passes C on track
    # EEE stops on lap 3 and goes no further: retired at the stop, so left out.
    _write(tmp_path, 1, "2024-03-03 15:00", order, pit_in=[(B, 4), (A, 6), (E, 3)], neutral=(6, 7))
    _write(tmp_path, 2, "2024-03-10 15:00", {1: every, 2: every}, finish=("1", "2", "3", "4"))
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def _row(body, code):
    return next(d for d in body["drivers"] if d["abbreviation"] == code)


def test_overtakes_on_track_only(con):
    body = race_review.latest(con, 2024, pd.Timestamp("2024-03-05", tz="UTC"))
    assert body["session_key"] == "2024_01_R"
    assert {c: (_row(body, c)["passes_made"], _row(body, c)["passes_lost"]) for c in ("AAA", "BBB", "CCC", "DDD")} == \
        {"AAA": (0, 0), "BBB": (1, 1), "CCC": (1, 1), "DDD": (0, 0)}


def test_places_lost_at_each_stop(con):
    body = race_review.latest(con, 2024, pd.Timestamp("2024-03-05", tz="UTC"))
    assert _row(body, "BBB")["stops"] == [{"lap": 4, "kind": "green", "places": 1}]
    assert _row(body, "AAA")["stops"] == [{"lap": 6, "kind": "safety car", "places": 0}]
    assert _row(body, "EEE")["stops"] == [] and _row(body, "EEE")["status"] == "R" and _row(body, "EEE")["position"] is None
    assert body["green_stop_places"] == 1
    assert [d["abbreviation"] for d in body["drivers"]] == ["AAA", "DDD", "BBB", "CCC", "EEE"]


def test_as_of_and_the_route(con):
    assert race_review.latest(con, 2024)["session_key"] == "2024_02_R"
    assert race_review.latest(con, 2024, pd.Timestamp("2024-01-01", tz="UTC"))["drivers"] == []

    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    url = "/api/sessions/2024_02_R/race-review"
    assert client.get(url).json()["session_key"] == "2024_01_R"                  # before: no spoiler
    assert client.get(url, params={"moment": "after"}).json()["session_key"] == "2024_02_R"
    assert client.get(url, params={"moment": "later"}).status_code == 422
    assert client.get("/api/sessions/1999_01_R/race-review").status_code == 404
    assert client.get("/api/sessions/live/race-review").status_code == 422
