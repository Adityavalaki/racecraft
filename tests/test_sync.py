"""
The sync button: the latest race weekends, brought into the lake on request.

What it must get right is the choice of sessions and the bookkeeping around
them. It must pick the latest weekends that have anything published, counting
one still in progress. It must fetch only what the lake does not have, carry
on past a session that fails, and tell the models to refit only when something
new landed. And it must not let a second writer at a session another process
is writing.
"""

import os
import time
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from conftest import hold_lock_elsewhere, kill, soon
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
    assert names == [f"{NOW.year} Azerbaijan Grand Prix"] + [f"{NOW.year} GP {rnd}" for rnd in (7, 6, 5, 4)]
    baku = [item.ident for item in items if item.round == 8]
    # The race has not been run, let alone published.
    assert "R" not in baku and "FP1" in baku


def test_the_newest_weekend_comes_first_and_each_weekend_runs_in_order(calendar):
    _, items = sync.plan(5, now=NOW)
    rounds = [item.round for item in items]
    assert rounds == sorted(rounds, reverse=True)
    assert [item.ident for item in items if item.round == 7] == ["FP1", "FP2", "FP3", "Q", "R"]


def _seasons(monkeypatch, *seasons):
    """One weekend in each of `seasons`, and a note of which schedules were asked for."""
    asked = []

    def schedule(season, include_testing=False):
        asked.append(season)
        if season not in seasons:
            return pd.DataFrame()
        return pd.DataFrame([_event(1, f"GP {season}", NOW.replace(year=season) - timedelta(days=30))])

    monkeypatch.setattr(sync.fastf1, "get_event_schedule", schedule)
    return asked


def test_the_season_choice_is_the_latest_season_with_anything_published(monkeypatch):
    asked = _seasons(monkeypatch, 2024, 2025)
    names, _ = sync.plan(sync.SEASON, now=NOW)
    assert names == ["2025 GP 2025"]
    assert asked == [2026, 2025], "older seasons need no asking"


def test_everything_goes_back_to_the_first_season_and_no_further(monkeypatch):
    asked = _seasons(monkeypatch, 2022, 2023, 2024, 2025, 2026)
    names, _ = sync.plan(sync.EVERYTHING, now=NOW)
    assert names == [f"{season} GP {season}" for season in (2026, 2025, 2024, 2023)]
    assert min(asked) == 2023 == sync.FIRST_SEASON


def test_a_season_with_too_few_weekends_looks_back_into_the_last(monkeypatch):
    this_year = [_event(1, "Opener", NOW - timedelta(days=7))]
    last_year = [_event(rnd, f"Old {rnd}", NOW - timedelta(days=200 - rnd * 10)) for rnd in range(1, 6)]
    monkeypatch.setattr(sync.fastf1, "get_event_schedule", _schedules(this_year, last_year))
    names, _ = sync.plan(3, now=NOW)
    assert names[0] == f"{NOW.year} Opener"
    assert names[1:] == [f"{NOW.year - 1} Old 5", f"{NOW.year - 1} Old 4"]


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
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)

    answer = syncer.status()
    assert fetched == ["FP2"]
    assert answer["state"] == "done"
    assert answer["counts"]["present"] == 1 and answer["counts"]["written"] == 1


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

def _lock_file(data_dir, key):
    return data_dir / "logs" / "locks" / f"{key}.lock"


def test_a_session_being_written_is_left_alone_until_its_writer_lets_go(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    held = cli.session_lock("2026_15_FP1")
    assert held is not None
    assert cli.session_lock("2026_15_FP1") is None, "two writers on one session"
    held.release()
    again = cli.session_lock("2026_15_FP1")
    assert again is not None
    again.release()


def test_a_session_being_written_by_another_process_is_left_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    writer = hold_lock_elsewhere(_lock_file(tmp_path, "2026_15_FP1"))
    try:
        assert cli.session_lock("2026_15_FP1") is None
    finally:
        kill(writer)


# ------------------------------------------------------------- over HTTP

def test_the_button_starts_a_sync_and_its_progress_can_be_read(monkeypatch):
    from fastapi.testclient import TestClient

    from racecraft.api import sync_view
    from racecraft.api.app import app

    calls = []
    monkeypatch.setattr(sync_view, "start",
                        lambda weekends=None, telemetry=True: calls.append((weekends, telemetry))
                        or {"state": "planning"})
    monkeypatch.setattr(sync_view, "status", lambda: {"state": "running", "counts": {}})
    client = TestClient(app, base_url="http://127.0.0.1")

    assert client.post("/api/sync").json()["state"] == "planning"
    assert calls == [(None, True)]
    assert client.get("/api/sync").json()["state"] == "running"
    assert client.post("/api/sync", params={"weekends": 50}).status_code == 422


# ------------------------------------------------------------- how much to download

@pytest.fixture
def install(monkeypatch, tmp_path):
    """Empty folders, and a note of what a sync was started with instead of starting one."""
    from racecraft.api import sync_view

    monkeypatch.setattr(sync_view.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(sync_view.config, "LAKE_DIR", tmp_path / "lake")
    started = []
    monkeypatch.setattr(sync_view.syncer, "start", lambda what, telemetry=True: started.append(what) or {"state": "planning"})
    return sync_view, tmp_path, started


def test_a_new_install_downloads_nothing_until_it_has_chosen(install):
    sync_view, _, started = install
    assert sync_view.choice() == {"choice": None, "ask": True}
    sync_view.start()                       # what the automatic sync calls ten seconds after launch
    assert started == []


def test_the_choice_is_kept_and_every_later_sync_follows_it(install):
    sync_view, _, started = install
    sync_view.choose("everything")
    sync_view.start()
    assert started == [sync.EVERYTHING, sync.EVERYTHING]
    assert sync_view.choice() == {"choice": "everything", "ask": False}


def test_someone_with_sessions_is_not_asked_and_keeps_five_weekends(install):
    sync_view, tmp_path, started = install
    session = tmp_path / "lake" / "sessions" / "year=2026" / "round=01" / "session=R"
    session.mkdir(parents=True)
    (session / "data.parquet").write_bytes(b"")
    assert sync_view.choice() == {"choice": "last5", "ask": False}
    sync_view.start()
    assert started == [5]


def test_a_season_of_official_results_alone_still_asks(install):
    """The standings' rows are written before any session, and open nothing."""
    sync_view, tmp_path, _ = install
    results = tmp_path / "lake" / "official_results" / "year=2026" / "round=01" / "session=R"
    results.mkdir(parents=True)
    (results / "data.parquet").write_bytes(b"")
    assert sync_view.choice()["ask"] is True


def test_a_damaged_choice_only_asks_again(install):
    sync_view, tmp_path, started = install
    (tmp_path / "data_choice.txt").write_text("all of it please", encoding="utf-8")
    assert sync_view.choice() == {"choice": None, "ask": True}
    sync_view.start()
    assert started == []


def test_the_choice_over_http_takes_only_the_three_offered(install):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    _, tmp_path, started = install
    client = TestClient(app, base_url="http://127.0.0.1")
    assert client.get("/api/data-choice").json()["ask"] is True
    assert client.post("/api/data-choice", params={"choice": "../../evil"}).status_code == 422
    assert not (tmp_path / "data_choice.txt").exists()
    assert client.post("/api/data-choice", params={"choice": "season"}).status_code == 200
    assert started == [sync.SEASON]
    assert client.get("/api/data-choice").json() == {"choice": "season", "ask": False}


def test_new_sessions_change_the_key_every_model_cache_uses(tmp_path, monkeypatch):
    """Caches keyed by lake_key never serve a fit made before an ingest, from any process."""
    from racecraft.store import db, lake

    def write(rnd):
        lake.write_session({"sessions": pd.DataFrame({
            "session_key": [f"2026_{rnd:02d}_R"], "event_name": ["Test"], "country": ["X"],
            "location": ["Testville"], "session_name": ["Race"],
            "date_utc": [pd.Timestamp("2026-06-01", tz="UTC")], "t0_utc": [pd.Timestamp("2026-06-01", tz="UTC")],
            "start_t": [0.0], "total_laps": [50], "circuit_rotation_deg": [0.0],
            "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]})}, 2026, rnd, "R", lake=tmp_path)

    write(1)
    first = db.lake_key(tmp_path)
    assert db.lake_key(tmp_path) == first, "nothing changed, so the key must not"
    write(2)                                     # this process: seen at once
    second = db.lake_key(tmp_path)
    assert second != first

    # Another process's ingest: the files change without this process knowing.
    monkeypatch.setattr(db, "RECHECK_S", 0.0)
    newest = next(tmp_path.rglob("data.parquet"))
    later = time.time() + 5
    os.utime(newest, (later, later))
    assert db.lake_key(tmp_path) != second


# ------------------------------------------------------------- the FP2 morning

def test_a_lock_whose_owner_has_gone_is_released_at_once(monkeypatch, tmp_path):
    """
    Baku FP2: a watcher took the session's lock and was closed. Six minutes
    later the lock was young, its owner long gone, and the sync stood aside.
    """
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    writer = hold_lock_elsewhere(_lock_file(tmp_path, "2026_15_FP2"))
    kill(writer)
    lock = soon(lambda: cli.session_lock("2026_15_FP2"))
    assert lock is not None, "a killed writer still blocks the session"
    lock.release()


def test_a_slow_writer_that_is_still_running_is_respected_however_old(monkeypatch, tmp_path):
    """No age limit: a long telemetry load is not a dead writer."""
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    path = _lock_file(tmp_path, "2026_15_FP2")
    writer = hold_lock_elsewhere(path)
    try:
        ancient = time.time() - 24 * 3600
        os.utime(path, (ancient, ancient))
        assert cli.session_lock("2026_15_FP2") is None
        assert path.read_text() == str(writer.holder_pid)
    finally:
        kill(writer)


def test_a_write_that_fails_lets_go_of_the_session(monkeypatch, tmp_path):
    monkeypatch.setattr(cli.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(cli.lake, "is_ingested", lambda *a, **k: False)

    def boom(*a, **k):
        raise RuntimeError("the feed fell over")

    monkeypatch.setattr(cli, "_ingest_locked", boom)
    with pytest.raises(RuntimeError):
        cli.ingest_one(2026, 15, "FP2", "Practice 2", telemetry=False, force=False, prune=False)
    lock = cli.session_lock(cli.fastf1_source.make_session_key(2026, 15, "FP2"))
    assert lock is not None, "a failed write kept the session locked"
    lock.release()


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


def test_a_session_once_in_the_lake_leaves_nothing_behind_in_fastf1s_cache(quiet, monkeypatch):
    """The app's sync used to keep every download: 1.9 GB on a nearly full system drive."""
    monkeypatch.setattr(sync, "plan", _plan((2026, 15, "FP2", "Azerbaijan", "Practice 2")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)
    calls, compacted = [], []
    monkeypatch.setattr(sync.cli, "ingest_with_limits", lambda *a, **k: calls.append(k) or "written")
    monkeypatch.setattr(sync.cli, "compact_http_cache", lambda: compacted.append(True) or 0.0)
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    assert calls and all(k["prune"] is True for k in calls)
    assert compacted == [True]


def test_a_session_no_source_has_does_not_stop_the_ones_after_it(quiet, monkeypatch):
    """A cancelled FP3 has no source, and it must not hold back the qualifying that followed."""
    monkeypatch.setattr(sync, "plan", _plan((2026, 18, "FP1", "United States", "Practice 1"),
                                            (2026, 18, "FP2", "United States", "Practice 2"),
                                            (2026, 18, "Q", "United States", "Qualifying")))
    monkeypatch.setattr(sync.lake, "is_ingested", lambda *a: False)
    asked = []
    monkeypatch.setattr(sync.cli, "ingest_with_limits", lambda *a, **k: asked.append(a[2]) or ("written" if a[2] == "Q" else "locked"))
    syncer = sync.Syncer()
    syncer.start()
    syncer.wait(5)
    answer = syncer.status()
    assert asked == ["FP1", "FP2", "Q"]
    assert answer["state"] == "done" and answer["counts"]["locked"] == 2 and answer["counts"]["written"] == 1
    assert all("no free source" in item["detail"] for item in answer["items"] if item["state"] == "locked")
