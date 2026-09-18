"""
Live mode, tested without a live session.

There is no feed to connect to outside a race weekend, so what can be checked
offline is checked properly: the recording format parses, a dropped connection
appends rather than starting again, the reader caches instead of re-parsing on
every request, and a half-written recording reads as "not ready" rather than as
a crash — which is the normal state for the first minutes of any session.

What cannot be checked here is the connection itself. That waits for Friday
practice, which is what practice is for.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from racecraft import config
from racecraft.live import feed as feed_module
from racecraft.live import recorder

# A recording is one Python-repr list per line: category, message, timestamp.
# This is what SignalRClient writes and what FastF1's parser reads back.
RECORDING = "\n".join([
    "['TrackStatus', {'Status': '1', 'Message': 'AllClear'}, '2026-09-26T13:00:00.000Z']",
    "['LapCount', {'CurrentLap': 1, 'TotalLaps': 51}, '2026-09-26T13:02:10.000Z']",
    "['WeatherData', {'AirTemp': '27.4', 'TrackTemp': '41.1', 'Rainfall': '0'}, "
    "'2026-09-26T13:02:30.000Z']",
    "['TrackStatus', {'Status': '4', 'Message': 'SCDeployed'}, '2026-09-26T13:20:00.000Z']",
]) + "\n"


@pytest.fixture
def live_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(recorder, "LIVE_DIR", tmp_path / "live")
    return tmp_path / "live"


def test_a_recording_is_named_for_when_it_started(live_dir):
    when = datetime(2026, 9, 26, 13, 5, tzinfo=timezone.utc)
    assert recorder.recording_path(when=when).name == "2026-09-26_1305.txt"
    assert recorder.recording_path("baku").name == "baku.txt"


def test_recordings_are_listed_newest_first(live_dir):
    live_dir.mkdir(parents=True)
    for index, name in enumerate(("first", "second", "third")):
        path = live_dir / f"{name}.txt"
        path.write_text(RECORDING, encoding="utf-8")
        import os
        os.utime(path, (1_700_000_000 + index * 60, 1_700_000_000 + index * 60))

    assert [p.stem for p in recorder.recordings()] == ["third", "second", "first"]
    assert recorder.latest_recording().stem == "third"


def test_no_recordings_is_not_an_error(live_dir):
    assert recorder.recordings() == []
    assert recorder.latest_recording() is None


def test_the_recorder_appends_so_a_dropped_feed_does_not_start_a_second_file(live_dir, monkeypatch):
    """
    The feed drops after about two hours. Truncating on reconnect would leave
    two half recordings to stitch together afterwards, and a hole between them.
    """
    seen = {}

    class FakeClient:
        def __init__(self, filename, filemode, timeout):
            seen["filemode"] = filemode
            seen["filename"] = filename

        def start(self):
            raise KeyboardInterrupt

    monkeypatch.setattr("fastf1.livetiming.client.SignalRClient", FakeClient)
    path = recorder.record(live_dir / "baku.txt", reconnect=False)

    assert seen["filemode"] == "a"
    assert path.name == "baku.txt"
    assert path.parent.is_dir()          # created rather than assumed


def test_the_recording_format_parses(live_dir):
    """
    FastF1's parser reads back exactly what its client writes. If either side
    changes shape this is where it shows, rather than halfway through a race.
    """
    from fastf1.livetiming.data import LiveTimingData

    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text(RECORDING, encoding="utf-8")

    parsed = LiveTimingData(str(path))
    parsed.load()

    assert parsed.has("TrackStatus")
    assert parsed.has("WeatherData")
    assert parsed.errorcount == 0, "a line the parser could not read"

    status = parsed.get("TrackStatus")
    assert [entry[1]["Status"] for entry in status] == ["1", "4"]
    # Times come back relative to the first message, which is what the session
    # clock expects: everything in the lake is seconds since session t0.
    assert status[0][0].total_seconds() == 0
    assert status[1][0].total_seconds() == pytest.approx(20 * 60)


def test_an_empty_recording_reads_as_not_ready_rather_than_crashing(live_dir):
    """The first minutes of every session look like this."""
    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text("", encoding="utf-8")
    session = feed_module.LiveSession(2026, 17, "Race")

    with pytest.raises(feed_module.NotRecording):
        feed_module.tables_from_recording(path, session)

    live = feed_module.Feed(path=path, session=session)
    with pytest.raises(feed_module.NotRecording):
        live.tables()
    assert "is the recorder running" in live.status()["error"]


def test_the_reader_caches_instead_of_parsing_on_every_request(live_dir, monkeypatch):
    """
    Parsing a race's recording takes a second or two and the panels poll several
    times a second. Without this the server would spend all its time re-reading
    a file that changes once a lap.
    """
    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text(RECORDING, encoding="utf-8")

    parses = {"count": 0}

    def fake_parse(_path, _session, telemetry=False):
        parses["count"] += 1
        return {"laps": pd.DataFrame({"lap_number": [1, 2, 3]})}

    monkeypatch.setattr(feed_module, "tables_from_recording", fake_parse)
    live = feed_module.Feed(path=path, session=feed_module.LiveSession(2026, 17, "Race"),
                            interval_s=60.0)

    for _ in range(20):
        assert len(live.tables()["laps"]) == 3
    assert parses["count"] == 1, "re-parsed a recording that had not gone stale"

    live.tables(force=True)
    assert parses["count"] == 2, "force should always re-read"


def test_stale_tables_are_re_read(live_dir, monkeypatch):
    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text(RECORDING, encoding="utf-8")

    parses = {"count": 0}
    monkeypatch.setattr(feed_module, "tables_from_recording",
                        lambda *_a, **_k: (parses.__setitem__("count", parses["count"] + 1),
                                           {"laps": pd.DataFrame({"lap_number": [1]})})[1])
    live = feed_module.Feed(path=path, session=feed_module.LiveSession(2026, 17, "Race"),
                            interval_s=0.0)
    live.tables()
    live.tables()
    assert parses["count"] == 2


def test_a_broken_recording_is_reported_not_raised_as_a_traceback(live_dir, monkeypatch):
    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text(RECORDING, encoding="utf-8")

    def explode(*_args, **_kwargs):
        raise ValueError("half a message")

    monkeypatch.setattr(feed_module, "tables_from_recording", explode)
    live = feed_module.Feed(path=path, session=feed_module.LiveSession(2026, 17, "Race"))

    with pytest.raises(feed_module.NotRecording):
        live.tables()
    assert "half a message" in live.status()["error"]


def test_status_says_enough_to_tell_whether_live_is_working(live_dir, monkeypatch):
    live_dir.mkdir(parents=True)
    path = live_dir / "baku.txt"
    path.write_text(RECORDING, encoding="utf-8")

    monkeypatch.setattr(feed_module, "tables_from_recording",
                        lambda *_a, **_k: {"laps": pd.DataFrame({"lap_number": [1, 2]})})
    live = feed_module.Feed(path=path, session=feed_module.LiveSession(2026, 17, "Race"))
    live.tables()

    status = live.status()
    # The file on disk, not the string that was written: Windows turns each
    # newline into two bytes, and the point here is that status reports what is
    # actually there.
    assert status["bytes"] == path.stat().st_size
    assert status["laps"] == 2
    assert status["session"] == {"year": 2026, "round": 17, "name": "Race"}
    assert status["error"] is None
    assert status["last_read_ago_s"] is not None


def test_the_session_now_is_the_nearest_one_within_the_window(monkeypatch):
    """The schedule decides which session a recording belongs to."""
    schedule = pd.DataFrame([{
        "RoundNumber": 17,
        "Session1": "Practice 1", "Session1DateUtc": pd.Timestamp("2026-09-25 10:30"),
        "Session2": "Qualifying", "Session2DateUtc": pd.Timestamp("2026-09-25 14:00"),
        "Session3": "Race", "Session3DateUtc": pd.Timestamp("2026-09-26 11:00"),
        "Session4": None, "Session4DateUtc": pd.NaT,
        "Session5": None, "Session5DateUtc": pd.NaT,
    }])
    monkeypatch.setattr("fastf1.get_event_schedule", lambda *_a, **_k: schedule)
    monkeypatch.setattr(feed_module, "_use_project_cache", lambda: None)

    during = feed_module.current_session(datetime(2026, 9, 26, 11, 30, tzinfo=timezone.utc))
    assert during is not None and during.session_name == "Race"
    assert during.round_number == 17

    # Between sessions on the Friday, the nearest is qualifying, not the race.
    friday = feed_module.current_session(datetime(2026, 9, 25, 13, 0, tzinfo=timezone.utc))
    assert friday is not None and friday.session_name == "Qualifying"

    # Nothing for days: the schedule should say so rather than guess.
    quiet = feed_module.current_session(datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc))
    assert quiet is None


def test_a_live_session_is_always_the_same_key(monkeypatch):
    """Every panel reads one session key, so live never collides with the lake."""
    assert feed_module.LiveSession(2026, 17, "Race").key == "live"
    assert feed_module.SESSION_KEY == "live"


def test_a_session_further_away_than_the_window_is_ignored(monkeypatch):
    schedule = pd.DataFrame([{
        "RoundNumber": 17,
        "Session1": "Race", "Session1DateUtc": pd.Timestamp("2026-09-26 11:00"),
        "Session2": None, "Session2DateUtc": pd.NaT,
        "Session3": None, "Session3DateUtc": pd.NaT,
        "Session4": None, "Session4DateUtc": pd.NaT,
        "Session5": None, "Session5DateUtc": pd.NaT,
    }])
    monkeypatch.setattr("fastf1.get_event_schedule", lambda *_a, **_k: schedule)
    monkeypatch.setattr(feed_module, "_use_project_cache", lambda: None)

    just_inside = feed_module.current_session(
        datetime(2026, 9, 26, 14, 30, tzinfo=timezone.utc), within=timedelta(hours=4))
    assert just_inside is not None

    just_outside = feed_module.current_session(
        datetime(2026, 9, 26, 16, 30, tzinfo=timezone.utc), within=timedelta(hours=4))
    assert just_outside is None
