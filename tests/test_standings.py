"""The championships, added up from every Grand Prix and sprint result."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import standings
from racecraft.store import lake
from racecraft.store.db import connect

# Four drivers, three teams; CCC moves from team "b" to team "a" for the last race.
DRIVERS = {1: ("AAA", "a", "Alpha"), 2: ("BBB", "a", "Alpha"), 3: ("CCC", "b", "Bravo"), 4: ("DDD", "c", "Charlie")}


def _result(key, order, points, team_of=None, positions=None):
    """A result sheet: `order` the finishing order of car numbers, `points` theirs (None: the feed sent none)."""
    rows = []
    for place, number in enumerate(order, start=1):
        code, team_id, team = (team_of or {}).get(number, DRIVERS[number])
        status = (positions or {}).get(number, str(place))
        rows.append({
            "session_key": key, "driver_number": number, "abbreviation": code, "full_name": f"Driver {code}",
            "team_name": team, "team_id": team_id, "team_color": "ffffff", "grid_position": place,
            "position": place, "classified_position": status, "status": "Finished",
            "points": None if points is None else float(points[place - 1]), "laps": 50, "result_time_s": 0.0,
            "q1_s": None, "q2_s": None, "q3_s": None})
    return pd.DataFrame(rows)


def _write(path, rnd, code, when, result):
    key = f"2024_{rnd:02d}_{code}"
    lake.write_session({
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": [code], "date_utc": [pd.Timestamp(when, tz="UTC")], "t0_utc": [pd.Timestamp(when, tz="UTC")],
            "start_t": [0.0], "total_laps": [50], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": result(key),
    }, 2024, rnd, code, lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    # Round 1: AAA wins. Round 2: a sprint the feed sent without points (CCC wins it),
    # then BBB wins and CCC retires. Round 3: DDD wins, CCC now driving for team "a".
    _write(tmp_path, 1, "R", "2024-03-02 15:00", lambda k: _result(k, [1, 2, 3, 4], [25, 18, 15, 12]))
    _write(tmp_path, 2, "S", "2024-03-08 12:00", lambda k: _result(k, [3, 1, 2, 4], None))
    _write(tmp_path, 2, "R", "2024-03-09 17:00", lambda k: _result(k, [2, 4, 1, 3], [25, 18, 15, 12],
                                                                    positions={3: "R"}))
    _write(tmp_path, 3, "R", "2024-03-24 05:00", lambda k: _result(
        k, [4, 3, 2, 1], [25, 18, 15, 12], team_of={3: ("CCC", "a", "Alpha")}))
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def test_points_add_up_over_races_and_sprints(con):
    table = standings.standings(con, 2024)
    points = {d["abbreviation"]: d["points"] for d in table.drivers}
    # The sprint had no points in the feed: scored 8, 7, 6, 5 from its places.
    assert points == {"AAA": 25 + 7 + 15 + 12, "BBB": 18 + 6 + 25 + 15, "CCC": 15 + 8 + 12 + 18, "DDD": 12 + 5 + 18 + 25}
    assert (table.races, table.sprints) == (3, 1)
    assert table.last == {"round": 3, "event_name": "Round 3 Grand Prix", "session": "Grand Prix"}
    assert any("sent no points" in note for note in table.notes)
    leader = table.drivers[0]
    assert leader["gap"] == 0 and all(d["gap"] == leader["points"] - d["points"] for d in table.drivers)


def test_level_on_points_the_most_wins_goes_first(con):
    table = standings.standings(con, 2024)
    order = [d["abbreviation"] for d in table.drivers]
    # BBB 64, DDD 60, AAA 59, CCC 53: no tie in the season, so a level pair is checked directly.
    assert order == ["BBB", "DDD", "AAA", "CCC"]
    rows = pd.DataFrame({"abbreviation": ["X", "X", "Y"], "code": ["R", "R", "R"], "classified": [2.0, 2.0, 1.0]})
    ranked = standings._ranked({"X": 36, "Y": 36}, lambda code: rows[rows["abbreviation"] == code])
    assert ranked == ["Y", "X"]                              # one win beats two second places


def test_a_driver_who_moved_scores_for_each_team_they_drove_for(con):
    teams = {t["team"]: t for t in standings.standings(con, 2024).constructors}
    assert teams["Alpha"]["points"] == (25 + 7 + 15 + 12) + (18 + 6 + 25 + 15) + 18
    assert teams["Bravo"]["points"] == 15 + 8 + 12
    assert {d["abbreviation"] for d in teams["Alpha"]["drivers"]} == {"AAA", "BBB", "CCC"}
    by_driver = {d["abbreviation"]: d for d in standings.standings(con, 2024).drivers}
    assert by_driver["CCC"]["team_name"] == "Alpha"         # shown with the team they drive for now


def test_only_results_from_before_the_moment_count(con):
    before_round_2 = standings.standings(con, 2024, as_of=pd.Timestamp("2024-03-08 12:00", tz="UTC"))
    assert (before_round_2.races, before_round_2.sprints) == (1, 0)
    assert before_round_2.drivers[0]["abbreviation"] == "AAA"
    nothing = standings.standings(con, 2024, as_of=pd.Timestamp("2024-03-01", tz="UTC"))
    assert nothing.drivers == [] and nothing.last is None


def test_wins_podiums_form_and_movement(con):
    rows = {d["abbreviation"]: d for d in standings.standings(con, 2024).drivers}
    assert rows["BBB"]["wins"] == 1 and rows["BBB"]["podiums"] == 3
    assert rows["CCC"]["sprint_wins"] == 1 and rows["CCC"]["wins"] == 0
    assert [f["position"] for f in rows["CCC"]["form"]] == [3, None, 2]
    assert rows["CCC"]["form"][1]["status"] == "R"
    # Before round 3: BBB 49, AAA 47, CCC 23 (retired), DDD 35. After: BBB, DDD, AAA, CCC.
    assert rows["DDD"]["change"] == 1 and rows["AAA"]["change"] == -1 and rows["BBB"]["change"] == 0


def test_the_standings_route_counts_up_to_the_session(con, monkeypatch):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    client = TestClient(app, base_url="http://127.0.0.1")
    before = client.get("/api/sessions/2024_02_R/standings").json()
    assert before["moment"] == "before" and (before["races"], before["sprints"]) == (1, 1)
    after = client.get("/api/sessions/2024_02_R/standings", params={"moment": "after"}).json()
    assert (after["races"], after["sprints"]) == (2, 1)
    assert client.get("/api/sessions/2024_02_R/standings", params={"moment": "later"}).status_code == 422
    assert client.get("/api/sessions/1999_01_R/standings").status_code == 404
    assert client.get("/api/sessions/live/standings").status_code == 422


def test_a_team_is_one_team_however_the_feed_names_it():
    """2026: some sessions give the id as "nan", some an id and no name, one sprint neither."""
    df = pd.DataFrame({
        "abbreviation": ["AAA", "AAA", "AAA", "AAA", "BBB"],
        "team_id": ["alpha", "nan", "alpha", None, "bravo"],
        "team_name": ["Alpha", "Alpha", None, None, "Bravo"],
        "team_color": ["111111", "nan", None, None, "222222"],
        "date_utc": pd.to_datetime(["2026-03-01", "2026-03-08", "2026-03-15", "2026-03-22", "2026-03-01"], utc=True),
    })
    resolved = standings._resolve_teams(df)
    assert resolved["team_key"].tolist() == ["alpha", "alpha", "alpha", "alpha", "bravo"]
    assert resolved["team_name"].tolist() == ["Alpha"] * 4 + ["Bravo"]
    assert resolved["team_color"].iloc[3] == "111111"
