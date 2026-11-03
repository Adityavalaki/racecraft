"""The head start at launch: never worth a crash."""

from __future__ import annotations

import duckdb

from racecraft.api import preload


def test_it_finds_the_latest_race_and_session():
    con = duckdb.connect()
    assert preload.latest_sessions(con) == (None, None)            # a new install: nothing yet
    con.sql("""create table sessions as select * from (values ('2026_18_R', 'R', timestamp '2026-10-25'),
               ('2026_19_FP1', 'FP1', timestamp '2026-10-30')) t(session_key, "session", date_utc)""")
    assert preload.latest_sessions(con) == ("2026_18_R", "2026_19_FP1")


def test_a_failing_model_costs_only_the_head_start(monkeypatch):
    asked = []

    def fails(key):
        asked.append(key)
        raise ValueError("the prediction is made once qualifying is in")

    monkeypatch.setattr(preload, "connect", lambda: None)
    monkeypatch.setattr(preload, "latest_sessions", lambda con: ("2026_18_R", "2026_19_FP1"))
    monkeypatch.setattr(preload.insight, "for_session", fails)
    monkeypatch.setattr(preload.prediction_view, "for_session", fails)
    preload.run()                                                  # no exception, and the second still tried
    assert asked == ["2026_18_R", "2026_19_FP1"]
