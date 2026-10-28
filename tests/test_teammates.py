"""Teammates head to head: qualifying, race pace on shared clean laps, practice, results."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import teammates
from racecraft.store import lake
from racecraft.store.db import connect

# Team "a" runs AAA and BBB; in round 2 DDD stands in for BBB, and in round 1's FP1 the rookie EEE
# drives BBB's car. Team "b" runs one car, CCC.
DRIVERS = {1: ("AAA", "a"), 2: ("BBB", "a"), 3: ("CCC", "b"), 4: ("DDD", "a"), 5: ("EEE", "a")}
RACE_LAPS = 20


def _lap(key, car, lap, time, compound="MEDIUM", status="1", stint=1, pit_in=False, pit_out=False):
    return {"session_key": key, "driver_number": car, "driver": DRIVERS[car][0], "team": DRIVERS[car][1],
            "lap_number": lap, "stint": stint, "compound": compound, "tyre_life": lap, "laps_in_stint": lap,
            "fresh_tyre": False, "lap_time_s": time, "sector1_s": None, "sector2_s": None, "sector3_s": None,
            "lap_start_t": lap * 90.0, "lap_end_t": lap * 90.0 + time, "pit_in_t": None, "pit_out_t": None,
            "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out, "speed_i1": None, "speed_i2": None, "speed_fl": None,
            "speed_st": None, "position": car, "track_status": status, "is_personal_best": False, "deleted": False,
            "deleted_reason": None, "is_accurate": True, "fastf1_generated": False}


def _result(key, car, position, classified=None, q=(None, None, None), points=0.0):
    code, team = DRIVERS[car]
    return {"session_key": key, "driver_number": car, "abbreviation": code, "full_name": f"Driver {code}",
            "team_name": team.title(), "team_id": team, "team_color": "ffffff", "grid_position": position,
            "position": position, "classified_position": classified or str(position), "status": "",
            "points": points, "laps": RACE_LAPS, "result_time_s": None, "q1_s": q[0], "q2_s": q[1], "q3_s": q[2]}


def _write(path, rnd, code, when, results, laps=()):
    key = f"2024_{rnd:02d}_{code}"
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": [code], "date_utc": [pd.Timestamp(when, tz="UTC")], "t0_utc": [pd.Timestamp(when, tz="UTC")],
            "start_t": [0.0], "total_laps": [RACE_LAPS], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame([_result(key, *r[:2], **(r[2] if len(r) > 2 else {})) for r in results]),
    }
    if laps:
        tables["laps"] = pd.DataFrame([_lap(key, *lap[:3], **(lap[3] if len(lap) > 3 else {})) for lap in laps])
    lake.write_session(tables, 2024, rnd, code, lake=path)


def _race_laps(fast, slow, slow_car, fast_car=1):
    """`fast_car` laps at `fast`, its teammate at `slow`. Lap 6 is under a safety car, where the fast car
    loses 20 s; the teammate stops on lap 12 for hards, so their laps after it are on another compound."""
    laps = []
    for lap in range(1, RACE_LAPS + 1):
        sc = {"status": "4"} if lap == 6 else {}
        laps.append((fast_car, lap, fast + (20 if lap == 6 else 0), sc))
        tyre = {"compound": "HARD", "stint": 2} if lap > 12 else {}
        laps.append((slow_car, lap, slow, {**sc, **tyre, "pit_in": lap == 12, "pit_out": lap == 13}))
        laps.append((3, lap, 91.0, sc))
    return laps


@pytest.fixture
def con(tmp_path, monkeypatch):
    # Round 1. FP1: the rookie EEE in BBB's car. FP2: AAA 80.0 on softs, BBB 80.3; AAA's hard lap is not compared.
    _write(tmp_path, 1, "FP1", "2024-03-01 11:00", [(1, 1), (5, 2), (3, 3)],
           [(1, 3, 80.5, {"compound": "SOFT"}), (5, 3, 80.1, {"compound": "SOFT"})])
    _write(tmp_path, 1, "FP2", "2024-03-01 15:00", [(1, 1), (2, 2), (3, 3)],
           [(1, 3, 80.0, {"compound": "SOFT"}), (2, 3, 80.3, {"compound": "SOFT"}), (1, 5, 79.0, {"compound": "HARD"}),
            (2, 4, 81.0, {"compound": "MEDIUM"})])
    # Qualifying: AAA out in Q2, BBB in Q3; compared in Q2, where BBB was 0.1 s quicker.
    _write(tmp_path, 1, "Q", "2024-03-02 15:00",
           [(2, 5, {"q": (81.2, 80.4, 80.1)}), (1, 11, {"q": (81.0, 80.5, None)}), (3, 12, {"q": (82.0, None, None)})])
    # The race: AAA 0.4 s a lap quicker, wins; BBB retires.
    _write(tmp_path, 1, "R", "2024-03-03 15:00",
           [(1, 1, {"points": 25.0}), (3, 2, {"points": 18.0}), (2, 3, {"classified": "R"})],
           _race_laps(90.0, 90.4, 2))
    # Round 2: DDD stands in for BBB, outqualifies and beats AAA, and scores more.
    _write(tmp_path, 2, "Q", "2024-03-09 15:00",
           [(4, 1, {"q": (80.0, 79.5, 79.0)}), (1, 2, {"q": (80.1, 79.6, 79.2)}), (3, 3, {"q": (81.0, 80.0, 79.9)})])
    _write(tmp_path, 2, "R", "2024-03-10 15:00",
           [(4, 1, {"points": 25.0}), (1, 2, {"points": 18.0}), (3, 3, {"points": 15.0})],
           _race_laps(89.0, 89.3, 1, fast_car=4))
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def _pair(table, *codes):
    return next(p for p in table.pairs if [d["abbreviation"] for d in p["drivers"]] == list(codes))


def test_qualifying_is_compared_in_the_last_part_both_reached(con):
    q = _pair(teammates.head_to_head(con, 2024), "AAA", "BBB")["qualifying"]
    assert q["ahead"] == [0, 1]                       # BBB qualified ahead
    assert q["gap_s"] == pytest.approx(0.1)           # Q2: 80.5 against 80.4, not Q1's 81.0 against 81.2
    assert q["pct"] == pytest.approx(100 * 0.1 / 80.4, abs=1e-3)


def test_race_pace_counts_only_shared_clean_laps_on_the_same_tyre(con):
    pace = _pair(teammates.head_to_head(con, 2024), "AAA", "BBB")["race_pace"]
    # Laps 2-11 on mediums for both, less the safety-car lap 6 (lap 12 is BBB's in-lap, 13 on are hards).
    assert pace == {"faster": [1, 0], "sessions": 1, "gap_s": pytest.approx(-0.4)}


def test_practice_compares_the_softest_compound_both_ran(con):
    pair = _pair(teammates.head_to_head(con, 2024), "AAA", "BBB")
    # FP1 had the rookie in BBB's car, so only FP2 counts: softs, 80.0 against 80.3 (AAA's 79.0 hard is ignored).
    assert pair["practice"] == {"faster": [1, 0], "sessions": 1, "gap_s": pytest.approx(-0.3)}
    assert pair["rounds"][0]["practice_gap_s"] == pytest.approx(-0.3)


def test_results_keep_retirements_apart(con):
    results = _pair(teammates.head_to_head(con, 2024), "AAA", "BBB")["results"]
    assert results == {"ahead": [0, 0], "races": 1, "retired": [0, 1], "points": [25, 0]}


def test_a_stand_in_is_its_own_pair_led_by_who_scored_more(con):
    table = teammates.head_to_head(con, 2024)
    pairs = {tuple(d["abbreviation"] for d in p["drivers"]): p["rounds_together"] for p in table.pairs}
    assert pairs == {("AAA", "BBB"): 1, ("DDD", "AAA"): 1}    # no pair for the FP1 rookie, nor for one car
    stand_in = _pair(table, "DDD", "AAA")
    assert stand_in["qualifying"]["ahead"] == [1, 0] and stand_in["qualifying"]["gap_s"] == pytest.approx(-0.2)
    assert stand_in["race_pace"]["gap_s"] == pytest.approx(-0.3)
    assert stand_in["results"]["points"] == [25, 18]
    assert sum("B ran only CCC" in note for note in table.notes) == 2    # team b's one car, each round


def test_as_of_leaves_out_what_had_not_run(con):
    # Before round 1's race: qualifying and practice are in, the race is not.
    pair = _pair(teammates.head_to_head(con, 2024, as_of=pd.Timestamp("2024-03-03 12:00", tz="UTC")), "AAA", "BBB")
    assert pair["qualifying"]["sessions"] == 1 and pair["race_pace"]["sessions"] == 0
    assert pair["results"]["races"] == 0 and pair["rounds"][0]["race_gap_s"] is None
    empty = teammates.head_to_head(con, 2024, as_of=pd.Timestamp("2024-01-01", tz="UTC"))
    assert empty.pairs == [] and empty.notes


def test_the_teammates_route_counts_up_to_the_session(con):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    before = client.get("/api/sessions/2024_01_R/teammates").json()
    assert before["moment"] == "before" and before["pairs"][0]["race_pace"]["sessions"] == 0
    after = client.get("/api/sessions/2024_01_R/teammates", params={"moment": "after"}).json()
    assert after["pairs"][0]["race_pace"]["gap_s"] == pytest.approx(-0.4)
    assert client.get("/api/sessions/2024_01_R/teammates", params={"moment": "later"}).status_code == 422
    assert client.get("/api/sessions/1999_01_R/teammates").status_code == 404
    assert client.get("/api/sessions/live/teammates").status_code == 422
