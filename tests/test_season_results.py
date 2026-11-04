"""A new install's championships: the rounds it has no session of, from Jolpica. See ingest/season_results.py."""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft import config
from racecraft.api import title_view
from racecraft.ingest import jolpica_source, season_results, sync
from racecraft.model import standings
from racecraft.store import lake
from racecraft.store.db import connect, has_table

NOW = pd.Timestamp("2026-04-20 12:00", tz="UTC")
STARTS = {1: "2026-03-08", 2: "2026-03-15", 3: "2026-03-29", 4: "2026-04-19", 5: "2026-05-03"}


def _schedule(season, include_testing=False):
    """Five rounds, one with a sprint. Round 4 ran yesterday, and round 5 is still to come."""
    rows = []
    for rnd, day in STARTS.items():
        race = pd.Timestamp(f"{day} 14:00")
        row = {"RoundNumber": rnd, "EventName": f"Round {rnd} Grand Prix", "Session1": "Practice 1",
               "Session1DateUtc": race - pd.Timedelta(days=2), "Session5": "Race", "Session5DateUtc": race}
        if rnd == 2:
            row |= {"Session3": "Sprint", "Session3DateUtc": race - pd.Timedelta(days=1)}
        rows.append(row)
    return pd.DataFrame(rows)


def _official(order, points=(25, 18)):
    return pd.DataFrame({
        "number": [1, 2], "driverCode": order, "givenName": ["A", "B"], "familyName": ["X", "Y"],
        "constructorId": ["alpha", "bravo"], "constructorName": ["Alpha", "Bravo"], "position": [1, 2],
        "positionText": ["1", "2"], "points": list(points)})


def _session(path, rnd, order=("AAA", "BBB")):
    """A session in the lake, as a sync writes one: the only kind that opens."""
    key = f"2026_{rnd:02d}_R"
    when = pd.Timestamp(f"{STARTS[rnd]} 13:00", tz="UTC")               # an OpenF1 session, dated an hour early
    results = pd.DataFrame([{
        "session_key": key, "driver_number": i + 1, "abbreviation": code, "full_name": code,
        "team_name": "Alpha" if i == 0 else "Bravo", "team_id": "alpha" if i == 0 else "bravo", "team_color": "ff0000",
        "grid_position": i + 1, "position": i + 1, "classified_position": str(i + 1), "status": "Finished",
        "points": float((25, 18)[i]), "laps": 50, "result_time_s": 0.0, "q1_s": None, "q2_s": None, "q3_s": None}
        for i, code in enumerate(order)])
    lake.write_session({
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"Round {rnd} Grand Prix"], "country": ["X"], "location": ["X"],
            "session_name": ["Race"], "date_utc": [when], "t0_utc": [when], "start_t": [0.0], "total_laps": [50],
            "circuit_rotation_deg": [0.0], "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": results}, 2026, rnd, "R", lake=path)


@pytest.fixture
def asked(tmp_path, monkeypatch):
    """A lake with only round 4, as a new install has only the latest weekends. What Jolpica was asked goes here."""
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    monkeypatch.setattr(season_results.fastf1, "get_event_schedule", _schedule)
    _session(tmp_path, 4)
    log = []

    def official(season, rnd, ident):
        log.append((rnd, ident))
        return _official(["BBB", "AAA"], (8, 7) if ident == "S" else (25, 18))

    monkeypatch.setattr(jolpica_source, "official", official)
    return log


def _table():
    return standings.standings(connect(), 2026)


def test_the_rounds_before_the_lake_count(asked):
    assert _table().races == 1 and _table().missing_rounds == [1, 2, 3]
    assert season_results.real_fill({2026}, now=NOW) == 4
    assert asked == [(1, "R"), (2, "S"), (2, "R"), (3, "R")]              # not 4: it has a session. Not 5: not run.
    table = _table()
    assert (table.races, table.sprints, table.missing_rounds) == (4, 1, [])
    points = {d["abbreviation"]: d["points"] for d in table.drivers}
    assert points == {"BBB": 25 * 3 + 8 + 18, "AAA": 18 * 3 + 7 + 25}
    teams = {t["team"]: t["points"] for t in table.constructors}
    assert sum(teams.values()) == sum(points.values()) and len(teams) == 2          # the same two teams, not four
    assert [r["round"] for r in table.rounds] == [1, 2, 3, 4]


def test_each_round_is_asked_for_once(asked):
    season_results.real_fill({2026}, now=NOW)
    asked.clear()
    assert season_results.real_fill({2026}, now=NOW) == 0
    assert asked == []


def test_going_into_a_round_counts_only_what_came_before(asked):
    season_results.real_fill({2026}, now=NOW)
    con = connect()
    year, cut = standings.as_of(con, "2026_04_R", "before")
    table = standings.standings(con, year, cut)
    assert table.races == 3 and table.last["round"] == 3                      # opening a race gives nothing away


def test_a_real_session_wins_over_the_official_copy(asked, tmp_path):
    season_results.real_fill({2026}, now=NOW)
    _session(tmp_path, 3, ("AAA", "BBB"))                                     # the user later fetches round 3
    rows = standings.results(connect(), 2026, official=True)
    mine = rows[rows["session_key"] == "2026_03_R"]
    assert len(mine) == 2 and mine.iloc[0]["abbreviation"] == "AAA"


def test_these_rounds_are_not_sessions(asked):
    """No replay to open, no sync skipped, nothing for what reads laps."""
    season_results.real_fill({2026}, now=NOW)
    con = connect()
    assert [row[0] for row in con.execute("select session_key from sessions").fetchall()] == ["2026_04_R"]
    assert not lake.is_ingested(2026, 3, "R")
    assert set(standings.results(con, 2026)["session_key"]) == {"2026_04_R"}   # only `official` adds them


def test_jolpica_down_costs_one_request_a_pass_and_says_so(asked, monkeypatch):
    calls = []
    monkeypatch.setattr(jolpica_source, "official", lambda *a: calls.append(a))
    assert season_results.real_fill({2026}, now=NOW) == 0
    assert len(calls) == 1
    table = _table()
    assert table.missing_rounds == [1, 2, 3]
    assert any("points are short" in note for note in table.notes)
    title_view.forget()
    with pytest.raises(title_view.NotAvailable, match="points are short"):
        title_view.for_session("2026_04_R", "after")


def test_title_odds_say_how_little_pace_they_rest_on(asked):
    """Points from every round, pace only from those with laps: the odds must not pass for the full season's."""
    season_results.real_fill({2026}, now=NOW)
    title_view.forget()
    body = title_view.for_session("2026_04_R", "after")
    assert any("1 of 4 Grands Prix" in note for note in body["notes"])
    assert {d["abbreviation"] for d in body["drivers"]} == {"AAA", "BBB"}


def test_a_race_not_yet_published_is_not_asked_for(asked):
    assert (1, "R") not in [(g["round"], g["ident"]) for g in season_results.missing(connect(), 2026, pd.Timestamp("2026-03-08 15:00", tz="UTC"))]


def test_a_fresh_lake_has_no_table_to_read(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    monkeypatch.setattr(season_results.fastf1, "get_event_schedule", _schedule)
    assert not has_table(connect(), "official_results")
    assert len(season_results.missing(connect(), 2026, NOW)) == 5


def test_the_sync_fetches_them_first_and_reports_them(monkeypatch, tmp_path):
    monkeypatch.setattr(sync.fastf1.Cache, "enable_cache", lambda *a, **k: None)
    monkeypatch.setattr(sync.config, "FASTF1_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(sync, "plan", lambda weekends: (["2026 A"], [sync.Item(2026, 4, "R", "A", "Race")]))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)
    order = []
    monkeypatch.setattr(sync.cli, "ingest_with_limits", lambda *a, **k: order.append("session") or "written")
    monkeypatch.setattr(sync.cli, "compact_http_cache", lambda: 0)
    monkeypatch.setattr(season_results, "fill", lambda seasons, now=None: order.append(sorted(seasons)) or 3)
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    assert order == [[2026], "session"]
    assert syncer.status()["topped_up"] == 3
