"""The championships played out: title odds from the standings and the rest of the season."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from racecraft import config
from racecraft.model import predict, title
from racecraft.store import lake
from racecraft.store.db import connect

SPLIT = {"race_noise_s": 0.4, "lasting_share": 0.5}
CAL = predict.Calibration(scale={}, noise_sd={}, prior_sd=0.5, inflate=1.0)


def test_every_grand_prix_hands_out_its_points_and_one_win():
    rng = np.random.default_rng(0)
    pace = np.linspace(-1.0, 1.0, 20).astype(np.float32)
    points, wins = title.simulate_races(pace, np.full(20, 0.2, np.float32), [False, True, False], 0.4, 0.0, 500, rng)
    assert np.allclose(points.sum(axis=1), 101 + 36 + 101)     # two Grands Prix and a sprint, nobody out
    assert (wins.sum(axis=1) == 2).all()                       # sprints do not count as wins
    assert points.dtype == np.float32                          # single precision: half the memory


def test_a_much_quicker_car_wins_nearly_every_season():
    rng = np.random.default_rng(1)
    pace = np.array([-2.0] + [0.0] * 9, dtype=np.float32)
    points, wins = title.simulate_races(pace, np.full(10, 0.1, np.float32), [False] * 10, 0.4, 0.05, 2000, rng)
    champion = title.champions(points, wins, rng)
    assert (champion == 0).mean() > 0.95


def test_retired_cars_score_nothing():
    rng = np.random.default_rng(2)
    points, _ = title.simulate_races(np.zeros(10, np.float32), np.zeros(10, np.float32), [False], 0.4, 1.0, 100, rng)
    assert points.sum() == 0


def test_the_most_still_to_score():
    events = [title.Event(20, "A", False), title.Event(21, "B", True), title.Event(21, "B", False)]
    assert title.most_points_left(events) == 25 + 8 + 25
    assert title.most_points_left(events, cars=2) == 43 + 15 + 43


# ------------------------------------------------------------------ a season in the lake

def _season(path):
    """Four drivers, two teams, two Grands Prix run of 2024: AAA 50, BBB 36, CCC 27, DDD 27."""
    for rnd, order in ((1, [1, 2, 3, 4]), (2, [1, 2, 4, 3])):
        key = f"2024_{rnd:02d}_R"
        when = pd.Timestamp(f"2024-03-{rnd * 7:02d} 15:00", tz="UTC")
        results = pd.DataFrame([{
            "session_key": key, "driver_number": n, "abbreviation": f"{'ABCD'[n - 1] * 3}", "full_name": f"D{n}",
            "team_name": "Alpha" if n <= 2 else "Bravo", "team_id": "a" if n <= 2 else "b", "team_color": "ffffff",
            "grid_position": p, "position": p, "classified_position": str(p), "status": "Finished",
            "points": float([25, 18, 15, 12][p - 1]), "laps": 50, "result_time_s": 0.0,
            "q1_s": None, "q2_s": None, "q3_s": None} for p, n in enumerate(order, start=1)])
        lake.write_session({
            "sessions": pd.DataFrame({
                "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
                "session_name": ["Race"], "date_utc": [when], "t0_utc": [when], "start_t": [0.0], "total_laps": [50],
                "circuit_rotation_deg": [0.0], "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
            "results": results}, 2024, rnd, "R", lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    _season(tmp_path)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def test_a_lead_nobody_can_close_is_the_title(con):
    odds = title.odds(con, 2024, uncertainty=SPLIT, calibration=CAL, events=[], runs=500)
    assert odds.drivers[0]["abbreviation"] == "AAA" and odds.drivers[0]["title"] == 1.0
    assert any("season is over" in note for note in odds.notes)


def test_who_can_still_win_and_who_is_out(con):
    def odds_with(events):
        return {d["abbreviation"]: d for d in title.odds(con, 2024, uncertainty=SPLIT, calibration=CAL,
                                                         events=events, runs=2000).drivers}

    # A Grand Prix left is 25 points: everyone can still reach AAA's 50, if AAA scores nothing.
    gp = odds_with([title.Event(3, "Round 3 Grand Prix", False)])
    assert all(d["alive"] for d in gp.values())
    assert gp["BBB"]["max_points"] == 61 and gp["CCC"]["max_points"] == 52
    assert gp["AAA"]["title"] > gp["BBB"]["title"] > 0
    assert sum(d["title"] for d in gp.values()) == pytest.approx(1.0, abs=1e-3)
    # Only a sprint left is 8: nobody can, and the title is settled.
    sprint = odds_with([title.Event(3, "Round 3 Grand Prix", True)])
    assert not sprint["BBB"]["alive"] and sprint["BBB"]["max_points"] == 44
    assert sprint["AAA"]["title"] == 1.0


def test_constructors_add_up_their_drivers(con):
    events = [title.Event(3, "Round 3 Grand Prix", False)]
    teams = {t["team"]: t for t in title.odds(con, 2024, uncertainty=SPLIT, calibration=CAL,
                                              events=events, runs=1000).constructors}
    # Alpha 86, Bravo 54: a one-two is 43, so Bravo can still pass if Alpha scores nothing.
    assert teams["Alpha"]["points"] == 86 and teams["Alpha"]["title"] > 0.9
    assert teams["Bravo"]["max_points"] == 54 + 43 and teams["Bravo"]["alive"]


def test_the_title_route(con, monkeypatch):
    from fastapi.testclient import TestClient

    from racecraft.api import title_view
    from racecraft.api.app import app

    monkeypatch.setattr(title, "calendar_events", lambda year, after: [title.Event(3, "Round 3 Grand Prix", False)])
    monkeypatch.setattr(title, "load_uncertainty", lambda path=None: SPLIT)
    title_view.forget()
    client = TestClient(app, base_url="http://127.0.0.1")
    body = client.get("/api/sessions/2024_02_R/title", params={"moment": "after"}).json()
    assert body["moment"] == "after" and [e["round"] for e in body["remaining"]] == [3]
    assert body["drivers"][0]["abbreviation"] == "AAA"
    # The results-only odds beside them (D-018): the same drivers, chances that add up.
    second = body["second_opinion"]
    assert set(second) <= {d["abbreviation"] for d in body["drivers"]}
    assert sum(second.values()) == pytest.approx(1.0, abs=0.01)
    assert client.get("/api/sessions/1999_01_R/title").status_code == 404
    assert client.get("/api/sessions/live/title").status_code == 422


def test_offline_with_the_season_unfinished_says_so(con, monkeypatch):
    from racecraft.api import title_view

    def offline(year, after):
        raise OSError("no network")

    monkeypatch.setattr(title, "calendar_events", offline)
    title_view.forget()
    with pytest.raises(title_view.NotAvailable, match="not known offline"):
        title_view.for_session("2024_02_R", "after")


def test_the_shipped_split_was_measured_before_2026():
    split = title.load_uncertainty()
    assert split["fitted_on"] and all(int(y) < 2026 for y in split["fitted_on"])
    assert 0.2 < split["race_noise_s"] < 0.8 and 0.2 < split["lasting_share"] < 1.0
