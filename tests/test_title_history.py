"""The results-only title odds on f1db history, offline (D-017)."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft.model import title_history as th

# Two eight-round seasons of four drivers. In 1990 A wins everything; in 1991 B and C share
# the wins and D (a retirement every race) scores nothing. 1991 has a sprint in round 4.
DRIVERS = ["a", "b", "c", "d"]
POINTS = {1: 9.0, 2: 6.0, 3: 4.0}


def _season(year, orders, sprint_round=None):
    races, results, sprints, standings = [], [], [], []
    total = dict.fromkeys(DRIVERS, 0.0)
    for rnd, order in enumerate(orders, start=1):
        race_id = year * 100 + rnd
        races.append({"id": race_id, "year": year, "round": rnd, "date": f"{year}-01-{rnd:02d}",
                      "has_sprint": rnd == sprint_round})
        for place, driver in enumerate(order, start=1):
            classified = driver != "d"
            p = POINTS.get(place, 0.0) if classified else 0.0
            results.append({"raceId": race_id, "year": year, "round": rnd, "positionNumber": place if classified else None,
                            "driverId": driver, "points": p})
            total[driver] += p
        if rnd == sprint_round:
            sprints.append({"raceId": race_id, "year": year, "round": rnd, "positionNumber": 1, "driverId": "b",
                            "points": 3.0})
            total["b"] += 3.0
        standings += [{"raceId": race_id, "year": year, "round": rnd, "driverId": d, "points": total[d]}
                      for d in DRIVERS]
    champion = max(total, key=total.get)
    final = [{"year": year, "driverId": d, "points": total[d], "championshipWon": d == champion} for d in DRIVERS]
    return races, results, sprints, standings, final


@pytest.fixture
def history(tmp_path):
    parts = [_season(1990, [["a", "b", "c", "d"]] * 8),
             _season(1991, [["b", "c", "a", "d"], ["c", "b", "a", "d"]] * 4, sprint_round=4)]
    names = ["races", "race_results", "sprint_results", "standings", "season_standings"]
    for i, name in enumerate(names):
        rows = [row for part in parts for row in part[i]]
        pd.DataFrame(rows).to_parquet(tmp_path / f"{name}.parquet", index=False)
    return tmp_path


def test_each_season_brings_its_own_points_champion_and_sprints(history):
    seasons = {s.year: s for s in th.seasons(into=history)}
    assert seasons[1990].champion == "a" and seasons[1991].champion == "b"
    assert seasons[1990].race_points.tolist() == [9.0, 6.0, 4.0]
    assert seasons[1991].sprint_points.tolist() == [3.0] and seasons[1991].sprint[4]
    assert seasons[1990].sprint_points.tolist() == []


def test_a_dominant_leader_is_favoured_beyond_the_points_alone(history):
    season = next(s for s in th.seasons(into=history) if s.year == 1990)
    split = {"race_noise": 1.0, "lasting_sd": 0.3}
    model = th.odds_after(season, 3, split, runs=2000)
    flat = th.odds_after(season, 3, split, flat=True, runs=2000)
    assert model["a"] > flat["a"] > 0.5            # A leads either way; the form makes it surer
    # D has never finished: no form, so the field's (as `title` treats a driver without form),
    # and 27 points behind with five races (45 points) left: a long shot, not an impossibility.
    assert 0.0 < model["d"] < 0.05
    assert sum(model.values()) == pytest.approx(1.0)


def test_the_backtest_leaves_each_season_out_of_its_own_measurement(history):
    seasons = th.seasons(into=history)
    checkpoints, split_for = th.backtest(seasons, runs=500)
    assert [c.after_round for c in checkpoints if c.year == 1990] == list(range(1, 8))
    stats = {s.year: th._season_stats(s) for s in seasons}
    assert split_for[1990] == th.measure([stats[1991]])
    assert all(0.0 <= c.model <= 1.0 and 0.0 <= c.points_only <= 1.0 for c in checkpoints)
