"""
The sync button: the latest race weekends, brought into the lake on request.

What it must get right is the choice of sessions and the bookkeeping around
them. It must pick the latest weekends that have anything published, counting
one still in progress. It must fetch only what the lake does not have, carry
on past a session that fails, and tell the models to refit only when something
new landed. And it must not let a second writer at a session another process
is writing.
"""

import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from racecraft.ingest import cli, sync

NOW = datetime(2026, 9, 26, 18, 0, tzinfo=timezone.utc)
NAMES = ["Practice 1", "Practice 2", "Practice 3", "Qualifying", "Race"]


def _event(rnd: int, name: str, race_day: datetime) -> dict:
    """A standard weekend whose race is on `race_day`."""
    starts = [race_day - timedelta(days=2, hours=2), race_day - timedelta(days=2, hours=-2),
              race_day - timedelta(days=1, hours=2), race_day - timedelta(days=1, hours=-2), race_day]
    row = {"RoundNumber": rnd, "EventName": name}
    for index, (session, start) in enumerate(zip(NAMES, starts), start=1):
        row[f"Session{index}"] = session
        row[f"Session{index}DateUtc"] = pd.Timestamp(start).tz_localize(None)
    return row


def _schedules(this_season: list[dict], last_season: list[dict]):
    frames = {NOW.year: pd.DataFrame(this_season), NOW.year - 1: pd.DataFrame(last_season)}
    return lambda season, include_testing=False: frames[season]


@pytest.fixture
def calendar(monkeypatch):
    # Seven finished weekends a fortnight apart, then Baku in progress: its
    # practice and qualifying are published, its race is not yet.
    finished = [_event(rnd, f"GP {rnd}", NOW - timedelta(days=14 * (8 - rnd)))
                for rnd in range(1, 8)]
    baku = _event(8, "Azerbaijan Grand Prix", NOW + timedelta(hours=1))
    monkeypatch.setattr(sync.fastf1, "get_event_schedule", _schedules(finished + [baku], []))
    return finished, baku


def test_the_latest_weekends_count_the_one_in_progress(calendar):
    names, items = sync.plan(5, now=NOW)
    assert names == [f"{NOW.year} GP {rnd}" for rnd in (4, 5, 6, 7)] + [f"{NOW.year} Azerbaijan Grand Prix"]
    baku = [item.ident for item in items if item.round == 8]
    # The race has not been run, let alone published.
    assert "R" not in baku and "FP1" in baku


def test_sessions_come_oldest_first_so_the_lake_fills_in_order(calendar):
    _, items = sync.plan(5, now=NOW)
    rounds = [item.round for item in items]
    assert rounds == sorted(rounds)


def test_a_season_with_too_few_weekends_looks_back_into_the_last(monkeypatch):
    this_year = [_event(1, "Opener", NOW - timedelta(days=7))]
    last_year = [_event(rnd, f"Old {rnd}", NOW - timedelta(days=200 - rnd * 10)) for rnd in range(1, 6)]
    monkeypatch.setattr(sync.fastf1, "get_event_schedule", _schedules(this_year, last_year))
    names, _ = sync.plan(3, now=NOW)
    assert names[-1] == f"{NOW.year} Opener"
    assert names[:2] == [f"{NOW.year - 1} Old 4", f"{NOW.year - 1} Old 5"]


# ------------------------------------------------------------- the job

@pytest.fixture
def quiet(monkeypatch, tmp_path):
    """No network and no real lake: the schedule and the ingest are stand-ins."""
    monkeypatch.setattr(sync.fastf1.Cache, "enable_cache", lambda *a, **k: None)
    monkeypatch.setattr(sync.config, "FASTF1_CACHE_DIR", tmp_path / "cache")


def _plan(*items):
    return lambda weekends: (["2026 Azerbaijan Grand Prix"], [sync.Item(*item) for item in items])


def test_only_what_the_lake_lacks_is_fetched(quiet, monkeypatch):
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP1", "Azerbaijan", "Practice 1"),
                                            (2026, 15, "FP2", "Azerbaijan", "Practice 2")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda season, rnd, ident: ident == "FP1")
    fetched = []
    monkeypatch.setattr(sync.cli, "ingest_with_limits",
                        lambda season, rnd, ident, name, **k: fetched.append(ident) or "written")
    refits = []
    syncer = sync.Syncer(on_written=lambda: refits.append(True))
    syncer.start()
    syncer.wait(5)

    answer = syncer.status()
    assert fetched == ["FP2"]
    assert answer["state"] == "done"
    assert answer["counts"]["present"] == 1 and answer["counts"]["written"] == 1
    assert refits == [True], "the models were not told there was something new"


def test_a_sync_with_nothing_to_do_does_not_make_the_models_refit(quiet, monkeypatch):
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP1", "Azerbaijan", "Practice 1")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: True)
    refits = []
    syncer = sync.Syncer(on_written=lambda: refits.append(True))
    syncer.start()
    syncer.wait(5)
    assert syncer.status()["to_fetch"] == 0
    assert refits == []


def test_one_session_that_fails_does_not_stop_the_rest(quiet, monkeypatch):
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP1", "Azerbaijan", "Practice 1"),
                                            (2026, 15, "FP2", "Azerbaijan", "Practice 2")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)

    def ingest(season, rnd, ident, name, **k):
        if ident == "FP1":
            raise RuntimeError("feed half written")
        return "written"

    monkeypatch.setattr(sync.cli, "ingest_with_limits", ingest)
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    items = {item["ident"]: item for item in syncer.status()["items"]}
    assert items["FP1"]["state"] == "failed" and "feed half written" in items["FP1"]["detail"]
    assert items["FP2"]["state"] == "written"


def test_a_second_click_while_it_runs_reports_the_running_sync(quiet, monkeypatch):
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP1", "Azerbaijan", "Practice 1")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)
    started = []

    def slow(season, rnd, ident, name, **k):
        started.append(ident)
        time.sleep(0.3)
        return "written"

    monkeypatch.setattr(sync.cli, "ingest_with_limits", slow)
    syncer = sync.Syncer()
    first = syncer.start()
    second = syncer.start()
    syncer.wait(5)
    assert first["started_at"] == second["started_at"]
    assert started == ["FP1"], "the second click started another sync"


# ------------------------------------------------------------- one writer per session

def test_a_session_being_written_by_another_process_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    held = cli.session_lock("2026_15_FP1")
    assert held is not None
    assert cli.session_lock("2026_15_FP1") is None, "two writers on one session"
    held.unlink()
    assert cli.session_lock("2026_15_FP1") is not None


def test_a_lock_left_by_a_writer_that_died_is_taken_over(monkeypatch, tmp_path):
    import os

    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    path = cli.session_lock("2026_15_FP2")
    stale = time.time() - cli.SESSION_LOCK_STALE.total_seconds() - 60
    os.utime(path, (stale, stale))
    assert cli.session_lock("2026_15_FP2") is not None


# ------------------------------------------------------------- over HTTP

def test_the_button_starts_a_sync_and_its_progress_can_be_read(monkeypatch):
    from fastapi.testclient import TestClient

    from racecraft.api import sync_view
    from racecraft.api.app import app

    calls = []
    monkeypatch.setattr(sync_view, "start",
                        lambda weekends=5, telemetry=True: calls.append((weekends, telemetry))
                        or {"state": "planning"})
    monkeypatch.setattr(sync_view, "status", lambda: {"state": "running", "counts": {}})
    client = TestClient(app)

    assert client.post("/api/sync").json()["state"] == "planning"
    assert calls == [(5, True)]
    assert client.get("/api/sync").json()["state"] == "running"
    assert client.post("/api/sync", params={"weekends": 50}).status_code == 422


def test_new_sessions_make_every_cached_fit_let_go():
    from racecraft.api import insight, places_view, sync_view
    from racecraft.model import race_inputs, tyre_sets

    insight._season_cache[("lake", 2026)] = "stale"
    places_view._cache[("stale",)] = {}
    race_inputs._race_cache[("lake", "2026_15_R")] = ("stale",)
    tyre_sets._weekend_cache[("lake", 2026, 15, None)] = "stale"
    sync_view.forget_models()
    assert not insight._season_cache and not places_view._cache
    assert not race_inputs._race_cache and not tyre_sets._weekend_cache


# ------------------------------------------------------------- the FP2 morning

def test_a_lock_whose_owner_has_gone_is_released_at_once(monkeypatch, tmp_path):
    """
    Baku FP2: a watcher took the session's lock and was closed. Six minutes
    later the lock was young, its owner long gone, and the sync stood aside.
    """
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    path = cli.session_lock("2026_15_FP2")
    path.write_text("4764")                    # a process that no longer exists
    monkeypatch.setattr(cli, "process_alive", lambda pid: False)
    assert cli.session_lock("2026_15_FP2") is not None


def test_a_lock_whose_owner_is_still_running_is_respected(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    cli.session_lock("2026_15_FP2")
    monkeypatch.setattr(cli, "process_alive", lambda pid: True)
    assert cli.session_lock("2026_15_FP2") is None


def test_this_process_is_alive_and_a_made_up_one_is_not():
    import os

    assert cli.process_alive(os.getpid()) is True
    assert cli.process_alive(0) is False


def test_a_session_someone_else_is_fetching_is_never_reported_as_present(quiet, monkeypatch):
    """What hid FP2: 'another process has it' was shown as 'already there'."""
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP2", "Azerbaijan", "Practice 2")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)
    monkeypatch.setattr(sync.cli, "ingest_with_limits", lambda *a, **k: "busy")
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    item = syncer.status()["items"][0]
    assert item["state"] == "busy" and "another process" in item["detail"]
    assert syncer.status()["counts"]["present"] == 0


def test_a_busy_session_that_lands_meanwhile_is_counted_present(quiet, monkeypatch):
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP2", "Azerbaijan", "Practice 2")))
    landed = {"yet": False}
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: landed["yet"])

    def other_process_finishes(*a, **k):
        landed["yet"] = True                   # the other writer finishes while we look away
        return "busy"

    monkeypatch.setattr(sync.cli, "ingest_with_limits", other_process_finishes)
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    assert syncer.status()["items"][0]["state"] == "present"
