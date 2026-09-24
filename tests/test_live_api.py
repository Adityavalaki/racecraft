"""
Serving a session that is still happening.

The claim live mode rests on is that nothing downstream can tell a live session
from a historic one. These tests are that claim: a `SessionData` built from
tables in memory has to answer the same questions, in the same shapes, as one
built from the lake — including in the states a live session passes through and
a historic one never does.

Three of those states matter and none of them is an error:

* nothing recorded yet, because the recorder has only just started;
* a session with no classification, because nobody has finished;
* a session with no completed laps, because the lights have not gone out.
"""

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from racecraft.api import live_store
from racecraft.api import session as session_store
from racecraft.api.app import app
from racecraft.live import feed as feed_module
from racecraft.live import recorder

LAP = 92.0
START = 100.0


def _live_tables(laps: int = 3, with_results: bool = False) -> dict[str, pd.DataFrame]:
    """The shape a recording parses into: no telemetry, often no classification."""
    rows = []
    for number, code, team, offset in ((1, "VER", "Red Bull", 0.0), (4, "NOR", "McLaren", 5.0)):
        for lap in range(1, laps + 1):
            end = START + offset + lap * LAP
            rows.append({
                "session_key": "live", "driver_number": number, "driver": code, "team": team,
                "lap_number": lap, "stint": 1, "compound": "MEDIUM", "tyre_life": lap,
                "laps_in_stint": lap, "fresh_tyre": True, "lap_time_s": LAP,
                "sector1_s": 30.0, "sector2_s": 31.0, "sector3_s": 31.0,
                "lap_start_t": end - LAP, "lap_end_t": end,
                "pit_in_t": None, "pit_out_t": None,
                "is_pit_in_lap": False, "is_pit_out_lap": False,
                "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                "position": 1 if number == 1 else 2, "track_status": "1",
                "is_personal_best": False, "deleted": False, "deleted_reason": None,
                "is_accurate": True, "fastf1_generated": False,
            })
    tables = {
        "sessions": pd.DataFrame({
            "session_key": ["live"], "event_name": ["Azerbaijan Grand Prix"],
            "country": ["Azerbaijan"], "location": ["Baku"], "session_name": ["Race"],
            "date_utc": [pd.Timestamp("2026-09-26 11:00", tz="UTC")],
            "t0_utc": [pd.Timestamp("2026-09-26 10:00", tz="UTC")],
            "start_t": [START], "total_laps": [51], "circuit_rotation_deg": [0.0],
            "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "laps": pd.DataFrame(rows),
        "track_status": pd.DataFrame({"session_key": ["live"], "t": [0.0],
                                      "status": ["1"], "message": ["AllClear"]}),
        "weather": pd.DataFrame({"session_key": ["live"], "t": [0.0], "air_temp": [27.0],
                                 "track_temp": [41.0], "humidity": [30.0], "pressure": [1010.0],
                                 "wind_speed": [2.0], "wind_direction": [180], "rainfall": [False]}),
    }
    if with_results:
        tables["results"] = pd.DataFrame({
            "session_key": "live", "driver_number": [1, 4], "abbreviation": ["VER", "NOR"],
            "full_name": ["Max Verstappen", "Lando Norris"], "team_name": ["Red Bull", "McLaren"],
            "team_id": ["rb", "mcl"], "team_color": ["3671C6", "F47600"],
            "grid_position": [1, 2], "position": [1, 2], "classified_position": ["1", "2"],
            "status": ["Finished", "Finished"], "points": [25.0, 18.0], "laps": [laps, laps],
            "result_time_s": [0.0, 5.0], "q1_s": None, "q2_s": None, "q3_s": None})
    return tables


# ------------------------------------------------------- building a session

def test_a_live_session_answers_the_same_questions_as_a_historic_one():
    live = session_store.SessionData.from_tables(_live_tables(), "live")

    info = live.info()
    assert info["total_laps"] == 51
    assert {d["abbreviation"] for d in info["drivers"]} == {"VER", "NOR"}
    assert info["has_position_data"] is False        # no telemetry carried live, by choice
    assert info["outline"] == []                     # so no track map, rather than a wrong one

    state = live.state(START + 2 * LAP + 30)
    assert [d["abbreviation"] for d in state["drivers"]] == ["VER", "NOR"]
    assert state["drivers"][1]["gap_to_leader_s"] == pytest.approx(5.0)

    chart = live.lap_chart()
    assert len(chart["drivers"]) == 2
    assert chart["drivers"][0]["position"] == [1, 1, 1]


def test_drivers_come_from_the_laps_when_nobody_has_finished():
    """A session in progress has no classification. The tower still has to fill."""
    live = session_store.SessionData.from_tables(_live_tables(with_results=False), "live")
    assert {d["abbreviation"] for d in live.info()["drivers"]} == {"VER", "NOR"}

    classified = session_store.SessionData.from_tables(_live_tables(with_results=True), "live")
    names = {d["abbreviation"]: d for d in classified.info()["drivers"]}
    assert names["VER"]["team_color"] == "3671C6", "a classification should be preferred to the laps"


def test_a_session_before_the_lights_go_out_is_not_an_error():
    """Zero completed laps is the first two minutes of every session."""
    tables = _live_tables()
    tables["laps"] = tables["laps"].iloc[:0]
    live = session_store.SessionData.from_tables(tables, "live")

    assert live.t_end > live.t_start, "an empty session still needs a clock range to divide by"
    assert live.info()["drivers"] == []
    assert live.lap_chart()["drivers"] == []


def test_a_recording_with_no_session_yet_is_refused_clearly():
    with pytest.raises(KeyError):
        session_store.SessionData.from_tables({}, "live")


# ------------------------------------------------------------- the store

@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(recorder, "LIVE_DIR", tmp_path / "live")
    fresh = live_store.LiveStore()
    monkeypatch.setattr(live_store, "store", fresh)
    return fresh


def _attach(store, monkeypatch, tables=None, error=None):
    path = recorder.LIVE_DIR / "baku.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("['Heartbeat', {}, '2026-09-26T11:00:00.000Z']\n", encoding="utf-8")

    def parse(*_args, **_kwargs):
        if error:
            raise error
        return tables if tables is not None else _live_tables()

    monkeypatch.setattr(feed_module, "tables_from_recording", parse)
    monkeypatch.setattr(feed_module, "current_session",
                        lambda *_a, **_k: feed_module.LiveSession(2026, 17, "Race"))
    return store.attach()


def test_the_store_serves_a_session_and_keeps_it_until_it_goes_stale(store, monkeypatch):
    _attach(store, monkeypatch)
    first = store.session()
    assert first.session_key == "live"
    assert store.session() is first, "rebuilt a session that had not gone stale"

    store._built_at = 0.0                       # as if the window had passed
    assert store.session() is not first


def test_a_recording_with_nothing_in_it_reads_as_not_ready(store, monkeypatch):
    _attach(store, monkeypatch, error=feed_module.NotRecording("is the recorder running?"))
    with pytest.raises(live_store.NotLive):
        store.session()
    assert "recorder running" in store.status()["error"]


def test_attaching_without_a_recording_says_how_to_make_one(store):
    with pytest.raises(live_store.NotLive) as raised:
        store.attach()
    assert "racecraft-live record" in str(raised.value)


def test_status_never_raises_even_when_nothing_works(store):
    status = store.status()
    assert status["attached"] is False
    assert "no recording" in status["error"]


# --------------------------------------------------------------- the API

@pytest.fixture
def client(store):
    return TestClient(app)


def test_live_is_offered_in_the_session_list_once_something_is_recorded(client, store, monkeypatch):
    assert all(s["session_key"] != "live" for s in client.get("/api/sessions").json())

    _attach(store, monkeypatch)
    listed = client.get("/api/sessions").json()
    assert listed[0]["session_key"] == "live", "live belongs at the top, not buried by date"
    assert listed[0]["session"] == "LIVE"


def test_every_session_endpoint_works_against_live(client, store, monkeypatch):
    _attach(store, monkeypatch)

    info = client.get("/api/sessions/live").json()
    assert info["total_laps"] == 51

    state = client.get("/api/sessions/live/state", params={"t": START + 2 * LAP + 10}).json()
    assert state["drivers"][0]["abbreviation"] == "VER"

    laps = client.get("/api/sessions/live/laps").json()
    assert len(laps["drivers"]) == 2


def test_a_session_that_is_not_ready_is_409_not_404(client, store, monkeypatch):
    """
    The difference decides what the interface does: 404 means give up, 409 means
    it is coming. During the first minutes of a session it is always coming.
    """
    _attach(store, monkeypatch, error=feed_module.NotRecording("nothing yet"))
    response = client.get("/api/sessions/live/state", params={"t": 0})
    assert response.status_code == 409
    assert "nothing yet" in response.json()["detail"]

    assert client.get("/api/sessions/nope_01_R/state", params={"t": 0}).status_code == 404


def test_attach_and_detach_over_http(client, store, monkeypatch):
    path = recorder.LIVE_DIR / "baku.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("['Heartbeat', {}, '2026-09-26T11:00:00.000Z']\n", encoding="utf-8")
    monkeypatch.setattr(feed_module, "tables_from_recording", lambda *_a, **_k: _live_tables())
    monkeypatch.setattr(feed_module, "current_session",
                        lambda *_a, **_k: feed_module.LiveSession(2026, 17, "Race"))

    attached = client.post("/api/live/attach").json()
    assert attached["attached"] is True
    assert attached["session"]["name"] == "Race"

    assert client.get("/api/live").json()["attached"] is True
    assert client.post("/api/live/detach").json()["attached"] is False


def test_attaching_with_no_recording_is_409(client, store):
    assert client.post("/api/live/attach").status_code == 409


def test_the_models_run_against_a_live_session(client, store, monkeypatch, tmp_path):
    """
    The strategy panel is most use during a race, not after it. A live session
    has no row in the lake, so the circuit, distance and laps come from the
    recording while everything the models are built on still comes from the
    lake — which is the only place a season of finished races can come from.
    """
    from racecraft.api import insight

    _attach(store, monkeypatch)
    live = store.session()

    monkeypatch.setattr(insight, "_circuit_constants", lambda: {
        "pit_loss": {"Baku": {"circuit": "Baku", "seconds": 21.0, "spread_s": 1.0,
                              "stops": 42, "seasons": 3}},
        "safety_car": {"Baku": {"circuit": "Baku", "races": 3, "share_of_races": 1.0,
                                "probability": 0.83, "periods_per_race": 1.0,
                                "per_lap": 0.02, "median_laps_lost": 4.1}},
        "laps": {"Baku": 51},
    })
    monkeypatch.setattr(insight, "_season_fits", lambda year: insight.SeasonFits(
        year=year,
        by_session={},
        names={},
        fuel_s_per_lap=0.05,
    ))
    monkeypatch.setattr(insight.SeasonFits, "combined",
                        lambda self, exclude=None: ({"SOFT": 0.033, "MEDIUM": 0.036},
                                                    {"SOFT": 0.0, "MEDIUM": -0.1},
                                                    ["Bahrain Grand Prix"]))

    out = insight.for_live(live)
    assert out["circuit"] == "Baku"
    assert out["total_laps"] == 51
    assert out["is_live"] is True
    assert out["is_race"] is True
    # Nothing is held out during a race: the model is fitted on every race that
    # finished before this one, and the response has to say which arrangement
    # it is rather than let a reader assume the stricter one.
    assert out["held_out"] is False
    assert out["fitted_on_count"] == 1
    assert out["plans"], out.get("plans_unavailable")
    assert out["stints"], "a live race should still show what the field is running"


def test_the_insight_endpoint_serves_live_and_says_when_it_cannot(client, store, monkeypatch):
    _attach(store, monkeypatch, error=feed_module.NotRecording("nothing yet"))
    assert client.get("/api/sessions/live/insight").status_code == 409


def test_an_empty_recording_is_not_offered_as_a_session(client, store, monkeypatch):
    """
    A recorder started before a session begins sits connected and writes
    nothing. That is correct behaviour and not a session: listing it would put
    LIVE at the top of the dropdown and hand back an error when clicked.

    It also made the plain API tests depend on whether this machine happened to
    have a stray file in data/live, which is how it was found.
    """
    empty = recorder.LIVE_DIR / "baku-2026.txt"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_text("", encoding="utf-8")

    assert all(s["session_key"] != "live" for s in client.get("/api/sessions").json())

    status = client.get("/api/live").json()
    assert status["attached"] is False
    assert status["recording"] is None
    assert "is empty" in status["error"]
    assert "has not started" in status["error"]

    # And attaching says why rather than failing obscurely.
    response = client.post("/api/live/attach")
    assert response.status_code == 409
    assert "is empty" in response.json()["detail"]

    # One byte of feed and it becomes a session.
    empty.write_text("['Heartbeat', {}, '2026-09-26T11:00:00.000Z']\n", encoding="utf-8")
    monkeypatch.setattr(feed_module, "tables_from_recording", lambda *_a, **_k: _live_tables())
    monkeypatch.setattr(feed_module, "current_session",
                        lambda *_a, **_k: feed_module.LiveSession(2026, 17, "Race"))
    assert client.get("/api/sessions").json()[0]["session_key"] == "live"


def test_a_recording_nobody_is_writing_any_more_is_not_offered_as_live(monkeypatch, tmp_path):
    """
    This morning's practice recording is still on disk this evening. Opening the
    interface on it lands on "not attached" instead of on the sessions since.
    """
    import os
    import time

    from racecraft.api import app as app_module

    stale = tmp_path / "baku-2026-fp1.txt"
    stale.write_text("['Heartbeat', '{}', '']\n")
    hours_ago = time.time() - 6 * 3600
    os.utime(stale, (hours_ago, hours_ago))
    assert app_module._recording_now(str(stale)) is False

    fresh = tmp_path / "baku-2026-fp2.txt"
    fresh.write_text("['Heartbeat', '{}', '']\n")
    assert app_module._recording_now(str(fresh)) is True
    assert app_module._recording_now(str(tmp_path / "missing.txt")) is False
