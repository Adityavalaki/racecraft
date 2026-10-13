"""Pit crews ranked by their stops against each race's typical stop."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import pit_crews
from racecraft.store import lake
from racecraft.store.db import connect

# Six cars, three teams. Team "fast" turns a car round 0.6 s quicker than team "mid", team "slow" 0.8 s slower.
CARS = {1: "fast", 2: "fast", 3: "mid", 4: "mid", 5: "slow", 6: "slow"}
# Three letters, as the feed's are: race control names cars by them.
CODE = {car: "ABCDEF"[car - 1] * 3 for car in CARS}
CREW = {"fast": -0.6, "mid": 0.0, "slow": 0.8}
LANE = 22.0
LAPS = 30
STOP_LAP = 12


def _laps(key: str, special: dict[int, dict]) -> pd.DataFrame:
    """One race: every car stops once on STOP_LAP; `special` overrides a car's stop."""
    rows = []
    for car, team in CARS.items():
        t = 0.0
        how = special.get(car, {})
        lane = how.get("lane", LANE + CREW[team])
        for lap in range(1, LAPS + 1):
            start, t = t, t + 90.0
            stopping, out = lap == STOP_LAP, lap == STOP_LAP + 1
            status = how.get("status", "1") if (stopping or out) else "1"
            rows.append({
                "session_key": key, "driver_number": car, "driver": CODE[car], "team": team,
                "lap_number": lap, "stint": 1 if lap <= STOP_LAP or how.get("same_tyres") else 2,
                "compound": "MEDIUM", "tyre_life": lap, "laps_in_stint": lap, "fresh_tyre": False,
                "lap_time_s": 90.0, "sector1_s": 30.0, "sector2_s": 30.0, "sector3_s": 30.0,
                "lap_start_t": start, "lap_end_t": t,
                "pit_in_t": t - 5.0 if stopping else None,
                "pit_out_t": (t - 90.0 - 5.0 + lane) if out else None,
                "is_pit_in_lap": stopping, "is_pit_out_lap": out,
                "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                "position": car, "track_status": status, "is_personal_best": False,
                "deleted": False, "deleted_reason": None, "is_accurate": True, "fastf1_generated": False})
    return pd.DataFrame(rows)


def _results(key: str) -> pd.DataFrame:
    return pd.DataFrame([{
        "session_key": key, "driver_number": car, "abbreviation": CODE[car], "full_name": f"Driver {car}",
        "team_name": team.title(), "team_id": team, "team_color": "ffffff", "grid_position": car, "position": car,
        "classified_position": str(car), "status": "Finished", "points": 0.0, "laps": LAPS, "result_time_s": 0.0,
        "q1_s": None, "q2_s": None, "q3_s": None} for car, team in CARS.items()])


def _race(path, rnd: int, special: dict[int, dict], messages: list[tuple[float, str]] = ()):
    key = f"2024_{rnd:02d}_R"
    when = pd.Timestamp(f"2024-04-{rnd * 7:02d} 13:00", tz="UTC")
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": ["Race"], "date_utc": [when], "t0_utc": [when], "start_t": [0.0], "total_laps": [LAPS],
            "circuit_rotation_deg": [0.0], "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "laps": _laps(key, special),
        "results": _results(key),
    }
    if messages:
        tables["race_control"] = pd.DataFrame({
            "session_key": key, "t": [t for t, _ in messages], "lap": [1] * len(messages), "category": "Other",
            "flag": None, "scope": None, "sector": None, "racing_number": None, "status": None,
            "message": [m for _, m in messages]})
    lake.write_session(tables, 2024, rnd, "R", lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    _race(tmp_path, 1, {})
    # Round 2: car 3 stops under the safety car, car 4 in a red flag, car 5 serves a penalty, car 6 changes no tyres.
    _race(tmp_path, 2, {3: {"status": "4", "lane": 19.0}, 4: {"status": "5", "lane": 900.0},
                        5: {"lane": LANE + CREW["slow"] + 5.0}, 6: {"same_tyres": True, "lane": 19.5}},
          messages=[(100.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 5 (EEE) - SPEEDING IN THE PIT LANE")])
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def test_crews_are_ranked_by_their_stops_against_the_races_typical_stop(con):
    ranking = pit_crews.ranking(con, 2024)
    order = [t["team"] for t in ranking.teams]
    assert order == ["Fast", "Mid", "Slow"]
    by = {t["team"]: t for t in ranking.teams}
    assert by["Fast"]["typical_s"] < 0 < by["Slow"]["typical_s"]
    # Round 1, every stop counted: the typical stop is Mid's, and the others sit exactly their crews' margin off it.
    round_1 = {t["driver_number"]: t["vs_typical_s"] for t in pit_crews.session_stops(con, "2024_01_R")}
    assert round_1[1] == pytest.approx(-0.6, abs=0.01) and round_1[3] == pytest.approx(0.0, abs=0.01)
    assert round_1[5] == pytest.approx(0.8, abs=0.01)


def test_what_is_not_a_crew_at_work_is_left_out_and_counted(con):
    ranking = pit_crews.ranking(con, 2024)
    assert ranking.excluded == {"safety car": 1, "red flag": 1, "penalty": 1, "no new tyres": 1}
    assert ranking.stops == 6 + 2 and ranking.races == 2
    trips = {t["driver_number"]: t for t in pit_crews.session_stops(con, "2024_02_R")}
    assert trips[3]["excluded"] == "safety car" and trips[4]["excluded"] == "red flag"
    assert trips[5]["excluded"] == "penalty" and trips[6]["excluded"] == "no new tyres"
    assert trips[1]["excluded"] is None and trips[1]["vs_typical_s"] is not None


def test_only_stops_from_before_the_moment_count(con):
    before_round_2 = pit_crews.ranking(con, 2024, pd.Timestamp("2024-04-14 13:00", tz="UTC"))
    assert before_round_2.races == 1 and before_round_2.stops == 6
    assert pit_crews.ranking(con, 2024, pd.Timestamp("2024-04-01", tz="UTC")).teams == []


def test_a_team_with_few_stops_is_ranked_last_and_says_so(con):
    ranking = pit_crews.ranking(con, 2024)
    assert all(t["thin"] for t in ranking.teams)                 # 2 to 4 stops each: not yet a pattern
    assert any("not yet a pattern" in note for note in ranking.notes)


def test_the_pit_crews_route(con):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    body = client.get("/api/sessions/2024_02_R/pit-crews").json()
    assert body["moment"] == "before" and body["races"] == 1
    assert len(body["session_stops"]) == 6
    after = client.get("/api/sessions/2024_02_R/pit-crews", params={"moment": "after"}).json()
    assert after["races"] == 2
    assert client.get("/api/sessions/live/pit-crews").status_code == 422
    assert client.get("/api/sessions/1999_01_R/pit-crews").status_code == 404
