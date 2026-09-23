import pandas as pd
import pytest

from racecraft.ingest import fastf1_source as src
from racecraft.store import lake
from racecraft.store.db import connect

from conftest import T0

KEY = "2024_01_R"


@pytest.fixture
def tables(fastf1_laps, fastf1_race_control):
    results = pd.DataFrame({
        "session_key": KEY, "driver_number": [1, 44], "abbreviation": ["VER", "HAM"],
        "full_name": ["Max Verstappen", "Lewis Hamilton"], "team_name": ["Red Bull Racing", "Mercedes"],
        "team_id": ["red_bull", "mercedes"], "team_color": ["3671C6", "27F4D2"],
        "grid_position": [1, 2], "position": [1, 2], "classified_position": ["1", "2"],
        "status": ["Finished", "Finished"], "points": [25.0, 18.0], "laps": [3, 3],
        "result_time_s": [288.6, 5.0],
        "q1_s": [None, None], "q2_s": [None, None], "q3_s": [None, None],
    })
    sessions = pd.DataFrame({
        "session_key": [KEY], "event_name": ["Bahrain Grand Prix"], "country": ["Bahrain"],
        "location": ["Sakhir"], "session_name": ["Race"],
        "date_utc": [pd.Timestamp("2024-03-02 15:00", tz="UTC")], "t0_utc": [T0.tz_localize("UTC")],
        "start_t": [3600.0], "total_laps": [3], "circuit_rotation_deg": [92.0],
        "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")],
    })
    return {
        "sessions": sessions,
        "results": results,
        "laps": src.build_laps(fastf1_laps, KEY),
        "race_control": src.build_race_control(fastf1_race_control, T0, KEY),
    }


def test_write_then_query_through_duckdb(tables, tmp_path):
    report = lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    assert report["laps"]["rows"] == 6
    assert lake.is_ingested(2024, 1, "R", lake=tmp_path)

    con = connect(tmp_path)
    row = con.sql("select year, round, session, count(*) from laps group by all").fetchone()
    assert row == (2024, 1, "R", 6)
    # The old engine's CSV bug: '1' re-read as the integer 1 matched nothing.
    assert con.sql("select count(*) from laps where track_status = '1'").fetchone()[0] == 5
    assert con.sql("select typeof(track_status) from laps limit 1").fetchone()[0] == "VARCHAR"


def test_views_skip_tables_with_no_files(tables, tmp_path):
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    views = {r[0] for r in connect(tmp_path).sql("show tables").fetchall()}
    assert {"laps", "results", "sessions", "race_control"} <= views
    assert "car_data" not in views


def test_schema_violation_names_the_column_and_writes_nothing(tables, tmp_path):
    tables["laps"]["lap_number"] = "not a number"
    with pytest.raises(TypeError, match=r"laps\.lap_number"):
        lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    assert not any(tmp_path.rglob("*.parquet"))


def test_partial_ingest_is_not_counted_as_ingested(tables, tmp_path):
    # Simulate a crash after laps were written but before sessions.
    lake.write_session({"laps": tables["laps"]}, 2024, 1, "R", lake=tmp_path)
    assert not lake.is_ingested(2024, 1, "R", lake=tmp_path)


def test_files_written_before_a_column_existed_still_read(tables, tmp_path):
    # Race files from before results.q1_s existed sit beside new qualifying files.
    import pyarrow.parquet as pq
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    old_file = lake.partition_dir("results", 2024, 1, "R", tmp_path) / lake.FILE_NAME
    pq.write_table(pq.read_table(old_file).drop(["q1_s", "q2_s", "q3_s"]), old_file)
    lake.touch()      # written behind the lake's back, as an older ingest would have

    quali = {name: df.copy() for name, df in tables.items()}
    for df in quali.values():
        df["session_key"] = "2024_01_Q"
    quali["results"]["q1_s"] = [90.1, 90.4]
    lake.write_session(quali, 2024, 1, "Q", lake=tmp_path)

    rows = connect(tmp_path).sql("select session, q1_s from results order by session, q1_s").fetchall()
    assert rows == [("Q", 90.1), ("Q", 90.4), ("R", None), ("R", None)]


# ---------------------------------------------------------------- the database

def test_a_session_ingested_later_is_seen_at_once(tables, tmp_path):
    """The small tables are held in memory now; a write must still show up."""
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    assert connect(tmp_path).sql("select count(distinct session_key) from laps").fetchone()[0] == 1
    second = {name: frame.assign(session_key="2024_02_R") for name, frame in tables.items()}
    lake.write_session(second, 2024, 2, "R", lake=tmp_path)
    assert connect(tmp_path).sql("select count(distinct session_key) from laps").fetchone()[0] == 2


def test_a_deleted_session_is_gone_at_once(tables, tmp_path):
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    assert connect(tmp_path).sql("select count(*) from sessions").fetchone()[0] == 1
    lake.delete_session(2024, 1, "R", lake=tmp_path)
    names = {r[0] for r in connect(tmp_path).sql("show tables").fetchall()}
    assert "sessions" not in names


def test_another_process_writing_is_found_by_the_recheck(tables, tmp_path, monkeypatch):
    """No counter bump — as when the ingest command runs beside the server."""
    from racecraft.store import db

    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    connect(tmp_path)
    second = {name: frame.assign(session_key="2024_02_R") for name, frame in tables.items()}
    monkeypatch.setattr(lake, "touch", lambda: None)
    lake.write_session(second, 2024, 2, "R", lake=tmp_path)
    monkeypatch.setattr(db, "RECHECK_S", 0.0)
    assert connect(tmp_path).sql("select count(distinct session_key) from laps").fetchone()[0] == 2


def test_every_cursor_reads_in_utc(tables, tmp_path):
    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    for _ in range(3):
        assert connect(tmp_path).sql("select current_setting('TimeZone')").fetchone()[0] == "UTC"


def test_many_connections_share_one_database(tables, tmp_path):
    """
    A fresh in-memory database per `connect()` crashed the process after a few
    hundred; now every call is a cursor on the same one.
    """
    from racecraft.store import db

    lake.write_session(tables, 2024, 1, "R", lake=tmp_path)
    for _ in range(300):
        connect(tmp_path).sql("select count(*) from laps").fetchone()
    assert sum(1 for key in db._databases if key == str(tmp_path.resolve())) == 1


@pytest.mark.parametrize("key, clause", [
    ("2024_01_R", " and year = 2024 and round = 1 and session = 'R'"),
    ("2023_05_SQ", " and year = 2023 and round = 5 and session = 'SQ'"),
    ("live", ""),
    ("2024_01_R'; drop table laps; --", ""),
])
def test_partition_filter(key, clause):
    from racecraft.store.db import partition

    assert partition(key) == clause
