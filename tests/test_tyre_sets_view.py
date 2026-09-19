"""
Tyre sets over HTTP, from a lake written the way ingest writes it.

One weekend, two cars. Car 1 runs a medium for four laps in qualifying and
starts the race on it; car 2 reaches Q3. The endpoint must say what each had at
the start of each session, follow the sets fitted during it, and — for the
race — check the strategy model's plans against the tyres each car actually had.
"""

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from racecraft import config
from racecraft.api import tyre_sets_view
from racecraft.api.app import app
from racecraft.store import lake

YEAR, ROUND = 2025, 5
SESSIONS = [("FP1", "Practice 1", "2025-05-02 10:00"), ("FP2", "Practice 2", "2025-05-02 14:00"),
            ("FP3", "Practice 3", "2025-05-03 10:00"), ("Q", "Qualifying", "2025-05-03 14:00"),
            ("R", "Race", "2025-05-04 13:00")]
# (session, car, compound, age at start, laps)
STINTS = [
    ("FP1", 1, "HARD", 1, 12), ("FP1", 1, "SOFT", 1, 4), ("FP1", 2, "SOFT", 1, 6),
    ("FP2", 1, "SOFT", 1, 9), ("FP2", 2, "MEDIUM", 1, 14),
    ("FP3", 1, "SOFT", 1, 5), ("FP3", 2, "SOFT", 1, 5),
    ("Q", 1, "MEDIUM", 1, 4), ("Q", 1, "SOFT", 1, 3), ("Q", 2, "SOFT", 1, 3), ("Q", 2, "SOFT", 1, 3),
    ("R", 1, "MEDIUM", 5, 20), ("R", 1, "HARD", 1, 30), ("R", 2, "HARD", 1, 25), ("R", 2, "MEDIUM", 1, 25),
]


def _laps(session_key, session):
    rows = []
    stint_of = {}
    for code, car, compound, age, laps in STINTS:
        if code != session:
            continue
        stint_of[car] = stint_of.get(car, 0) + 1
        start = 100.0 * stint_of[car] * 60
        for i in range(laps):
            rows.append({
                "session_key": session_key, "driver_number": car, "driver": f"D{car:02d}", "team": "T",
                "lap_number": i + 1, "stint": stint_of[car], "compound": compound,
                "tyre_life": age + i, "laps_in_stint": i + 1, "fresh_tyre": age == 1,
                "lap_time_s": 90.0, "sector1_s": 30.0, "sector2_s": 30.0, "sector3_s": 30.0,
                "lap_start_t": start + 90.0 * i, "lap_end_t": start + 90.0 * (i + 1),
                "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": False, "is_pit_out_lap": False,
                "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                "position": car, "track_status": "1", "is_personal_best": False, "deleted": False,
                "deleted_reason": None, "is_accurate": True, "fastf1_generated": False,
            })
    return pd.DataFrame(rows)


def _results(session_key, session):
    rows = []
    for car in (1, 2):
        rows.append({
            "session_key": session_key, "driver_number": car, "abbreviation": f"D{car:02d}",
            "full_name": f"Driver {car}", "team_name": "T", "team_id": "t", "team_color": "ffffff",
            "grid_position": car, "position": car, "classified_position": str(car), "status": "Finished",
            "points": 0.0, "laps": 50, "result_time_s": 0.0, "q1_s": 90.0 if session == "Q" else None,
            "q2_s": 89.0 if session == "Q" else None,
            "q3_s": (88.0 if car == 2 else None) if session == "Q" else None,
        })
    return pd.DataFrame(rows)


@pytest.fixture
def client(tmp_path, monkeypatch):
    for code, name, date in SESSIONS:
        key = f"{YEAR}_{ROUND:02d}_{code}"
        lake.write_session({
            "sessions": pd.DataFrame({
                "session_key": [key], "event_name": ["Test Grand Prix"], "country": ["X"],
                "location": ["Testville"], "session_name": [name],
                "date_utc": [pd.Timestamp(date, tz="UTC")], "t0_utc": [pd.Timestamp(date, tz="UTC")],
                "start_t": [0.0], "total_laps": [50], "circuit_rotation_deg": [0.0],
                "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
            "laps": _laps(key, code),
            "results": _results(key, code),
        }, YEAR, ROUND, code, lake=tmp_path)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    tyre_sets_view._cache.clear()
    tyre_sets_view._weekends.clear()
    return TestClient(app)


def _car(body, number):
    return next(car for car in body["cars"] if car["driver_number"] == number)


def test_a_race_shows_what_each_car_held_and_what_it_fitted(client):
    body = client.get(f"/api/sessions/{YEAR}_{ROUND:02d}_R/tyre-sets").json()
    assert body["rules"]["name"] == "standard weekend"
    assert [r["after"] for r in body["returns_so_far"]] == ["FP1", "FP2", "FP3"]

    one = _car(body, 1)
    assert one["at_start"]["MEDIUM"]["used"] == [{"set": 5, "laps": 4}]
    assert one["at_start"]["HARD"]["new"] == 1          # one of two hards ran in FP1
    medium = next(s for s in one["this_session"] if s["compound"] == "MEDIUM")
    assert medium["new_at_start"] is False and medium["laps_at_start"] == 4
    assert len(medium["runs"][0]["lap_end_t"]) == 20

    # Car 2 reached Q3 and handed a soft back after qualifying: six sets, not seven.
    two = _car(body, 2)
    assert [r["after"] for r in two["returned"]].count("Q") == 1
    held = sum(c["new"] + len(c["used"]) for c in two["at_start"].values())
    assert held == 6


def test_a_practice_session_counts_only_what_came_before_it(client):
    body = client.get(f"/api/sessions/{YEAR}_{ROUND:02d}_FP2/tyre-sets").json()
    one = _car(body, 1)
    # Two sets ran in FP1 and two went back after it.
    assert one["at_start"]["SOFT"] == {"new": 7, "used": []}
    assert one["at_start"]["HARD"] == {"new": 1, "used": []}
    assert [s["compound"] for s in one["this_session"]] == ["SOFT"]


def test_the_strategy_board_checks_its_plans_against_each_cars_tyres(client):
    from racecraft.api import insight
    weekend, code = tyre_sets_view.weekend_for(f"{YEAR}_{ROUND:02d}_R")
    out = {"is_race": True, "degradation_used": {"SOFT": 0.1, "MEDIUM": 0.06, "HARD": 0.04},
           "plans": [{"plan": "medium 20 > hard 30"}, {"plan": "hard 25 > hard 25"}],
           "plans_with_risk": [{"plan": "medium 20 > hard 30"},
                               {"plan": "medium 20 > medium 15 > medium 15"}]}
    checks = insight._tyre_sets(f"{YEAR}_{ROUND:02d}_R", out)["cars"]

    one = checks["1"]["plans"]
    assert [p["plan"] for p in one] == ["medium 20 > hard 30", "hard 25 > hard 25",
                                        "medium 20 > medium 15 > medium 15"]
    # Two new mediums left: a single medium stint runs on one of them, at no cost.
    assert one[0]["feasible"] and one[0]["extra_s"] == 0.0
    # Car 1 ran a hard in FP1 that went back: one hard left, so two hard stints cannot happen.
    assert not one[1]["feasible"] and one[1]["reason"] == "needs 2 hard sets, has 1"
    # Three medium stints need the qualifying medium too, on a short stint: 4 laps x 15.
    assert one[2]["feasible"] and one[2]["extra_s"] == pytest.approx(0.06 * 4 * 15, abs=0.05)


def test_an_unknown_session_is_404(client):
    assert client.get("/api/sessions/1999_01_R/tyre-sets").status_code == 404


def test_live_needs_to_know_its_weekend(client):
    with pytest.raises(tyre_sets_view.NoSets):
        tyre_sets_view.for_session("live", live=object(), live_status={"session": {}})


def test_live_puts_the_session_in_progress_on_top_of_the_lake(client, monkeypatch):
    class Live:
        laps = _laps("live", "R")

    monkeypatch.setattr(tyre_sets_view, "_scheduled_sprint", lambda year, rnd: False)
    status = {"session": {"year": YEAR, "round": ROUND, "name": "Race"}}
    body = tyre_sets_view.for_session("live", live=Live(), live_status=status)
    assert body["session"] == "R"
    assert _car(body, 1)["at_start"]["MEDIUM"]["used"] == [{"set": 5, "laps": 4}]
