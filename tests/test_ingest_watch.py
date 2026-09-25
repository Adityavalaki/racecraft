"""
Keeping the lake up to date without being asked.

A session's timing data is published a while after it ends, so the rule is
simple: a session is ingestable `PUBLISH_DELAY` after it starts, and anything
already in the lake is left alone. These tests pin that clock, because a
watcher that reaches for a session too early spends the day failing and one
that reaches too late is no better than doing it by hand.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from racecraft import config
from racecraft.ingest import cli

ALL = tuple(config.ALL_SESSIONS)


def _schedule(*offsets_hours: float) -> pd.DataFrame:
    """One event whose sessions start the given number of hours from now."""
    now = datetime.now(timezone.utc)
    row = {"RoundNumber": 15, "EventName": "Azerbaijan Grand Prix"}
    for index, offset in enumerate(offsets_hours, start=1):
        row[f"Session{index}"] = ["Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race"][index - 1]
        row[f"Session{index}DateUtc"] = pd.Timestamp(now + timedelta(hours=offset)).tz_localize(None)
    for index in range(len(offsets_hours) + 1, 6):
        row[f"Session{index}"] = None
        row[f"Session{index}DateUtc"] = pd.NaT
    return pd.DataFrame([row])


@pytest.fixture
def schedule(monkeypatch):
    def use(*offsets):
        monkeypatch.setattr(cli.fastf1, "get_event_schedule",
                            lambda season, include_testing=False: _schedule(*offsets))
    return use


def test_a_session_is_not_reached_for_until_its_data_is_published(schedule, monkeypatch):
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a: False)
    # Started an hour ago: over, but the feed is not out yet.
    schedule(-1)
    assert cli.completed_sessions(2026, None, ALL) == []
    # Started five hours ago: published.
    schedule(-5)
    assert [ident for _, ident, _, _ in cli.completed_sessions(2026, None, ALL)] == ["FP1"]


def test_what_it_is_waiting_for_is_the_sessions_it_cannot_have_yet(schedule):
    schedule(-5, 1, 25)
    waiting = dict(cli.waiting_for(2026, None, ALL))
    # The one already published is not waited for; the one 25 hours out is.
    assert not any("Practice 1" in name for name in waiting)
    assert any("Practice 2" in name for name in waiting)
    assert any("Practice 3" in name for name in waiting)


def test_a_session_days_away_is_not_worth_announcing(schedule):
    schedule(80)
    assert cli.waiting_for(2026, None, ALL) == []


def test_the_watcher_ingests_only_what_is_missing(schedule, monkeypatch):
    schedule(-5, -5)
    in_lake = {"FP1"}
    monkeypatch.setattr(cli.lake, "is_ingested",
                        lambda season, rnd, ident: ident in in_lake)
    asked = []

    def fake_ingest(season, rnd, ident, name, **kwargs):
        asked.append(ident)
        return "skipped" if ident in in_lake else "written"

    monkeypatch.setattr(cli, "ingest_with_limits", fake_ingest)
    monkeypatch.setattr(cli, "brief", lambda *a: None)
    counts = cli.run_once(_args())

    assert asked == ["FP1", "FP2"]          # both are offered
    assert counts == {"written": 1, "skipped": 1, "busy": 0, "failed": 0}   # one is actually written


def test_a_race_that_lands_gets_its_brief(schedule, monkeypatch):
    schedule(-5)
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a: False)
    monkeypatch.setattr(cli.config, "SESSION_CODES", {"Practice 1": "R"})
    monkeypatch.setattr(cli, "ingest_with_limits", lambda *a, **k: "written")
    briefed = []
    monkeypatch.setattr(cli, "brief", lambda season, rnd, event: briefed.append(event))
    cli.run_once(_args())
    assert briefed == ["Azerbaijan Grand Prix"]


def test_one_broken_session_does_not_stop_the_rest(schedule, monkeypatch):
    schedule(-5, -5)
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a: False)
    monkeypatch.setattr(cli, "brief", lambda *a: None)

    def sometimes(season, rnd, ident, name, **kwargs):
        if ident == "FP1":
            raise RuntimeError("the feed was half written")
        return "written"

    monkeypatch.setattr(cli, "ingest_with_limits", sometimes)
    counts = cli.run_once(_args())
    assert counts == {"written": 1, "skipped": 0, "busy": 0, "failed": 1}


def _args():
    class Args:
        season = [2026]
        rounds = None
        sessions = list(config.ALL_SESSIONS)
        no_telemetry = True
        force = False
        prune_cache = False
        verbose = False
        no_brief = False
    return Args()


def test_two_watchers_do_not_ingest_over_each_other(tmp_path):
    """Both writing the same Parquet files is the one way this breaks the lake."""
    lock = tmp_path / "watch.lock"
    assert cli.take_lock(lock) is True
    assert cli.take_lock(lock) is False, "a second watcher started anyway"


def test_a_lock_left_behind_by_a_killed_watcher_is_taken_over(tmp_path, monkeypatch):
    import os, time

    lock = tmp_path / "watch.lock"
    lock.write_text("999999")
    stale = time.time() - cli.LOCK_STALE_AFTER.total_seconds() - 60
    os.utime(lock, (stale, stale))
    assert cli.take_lock(lock) is True
    assert lock.read_text() == str(os.getpid())


def test_an_empty_parse_in_the_cache_is_thrown_away_and_the_session_asked_for_again(monkeypatch):
    """
    Baku 2026 practice sat unfetched for two hours behind an empty parse cached
    during the session. The first failure clears the cache; the second attempt
    starts from nothing and gets the real data.
    """
    from fastf1.exceptions import DataNotLoadedError

    attempts, cleared = [], []

    def ingest(season, rnd, ident, name, **kwargs):
        attempts.append(ident)
        if len(attempts) == 1:
            raise DataNotLoadedError("stale")
        return "written"

    monkeypatch.setattr(cli, "ingest_one", ingest)
    monkeypatch.setattr(cli, "wait_for_api_budget", lambda key: None)
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a: False)
    monkeypatch.setattr(cli, "forget_session", lambda *a: cleared.append(a) or 3)

    assert cli.ingest_with_limits(2026, 15, "FP1", "Practice 1", force=False,
                                  telemetry=False, prune=False) == "written"
    assert len(attempts) == 2 and len(cleared) == 1


def test_a_session_still_empty_after_a_fresh_start_really_is_not_published(monkeypatch):
    from fastf1.exceptions import NoLapDataError

    def always_empty(*a, **k):
        raise NoLapDataError()

    monkeypatch.setattr(cli, "ingest_one", always_empty)
    monkeypatch.setattr(cli, "wait_for_api_budget", lambda key: None)
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a: False)
    monkeypatch.setattr(cli, "forget_session", lambda *a: 0)
    with pytest.raises(NoLapDataError):
        cli.ingest_with_limits(2026, 15, "FP2", "Practice 2", force=False,
                               telemetry=False, prune=False)
