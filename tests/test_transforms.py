import pandas as pd

from racecraft.ingest import fastf1_source as src
from racecraft.store.lake import to_arrow
from racecraft.store.schema import TABLES

from conftest import T0

KEY = "2024_01_R"


def test_laps_match_schema_exactly(fastf1_laps):
    laps = src.build_laps(fastf1_laps, KEY)
    assert list(laps.columns) == TABLES["laps"].names
    to_arrow(laps, "laps")  # raises if any column can't be stored as declared


def test_track_status_stays_a_string(fastf1_laps):
    table = to_arrow(src.build_laps(fastf1_laps, KEY), "laps")
    values = table.column("track_status").to_pylist()
    assert "12" in values
    assert all(isinstance(v, str) for v in values)


def test_laps_in_stint_is_not_tyre_life(fastf1_laps):
    laps = src.build_laps(fastf1_laps, KEY).set_index(["driver", "lap_number"])
    # VER lap 1: fourth lap on these tyres, but the first lap of the stint.
    assert laps.loc[("VER", 1), "tyre_life"] == 4
    assert laps.loc[("VER", 1), "laps_in_stint"] == 1
    # After the stop the count restarts.
    assert laps.loc[("VER", 3), "stint"] == 2
    assert laps.loc[("VER", 3), "laps_in_stint"] == 1


def test_lap_times_become_seconds_on_the_session_clock(fastf1_laps):
    laps = src.build_laps(fastf1_laps, KEY)
    first = laps.iloc[0]
    assert first["lap_start_t"] == 3600.0
    assert abs(first["lap_end_t"] - first["lap_start_t"] - first["lap_time_s"]) < 1e-9
    assert laps["is_pit_in_lap"].sum() == 1 and laps["is_pit_out_lap"].sum() == 1


def test_race_control_absolute_times_move_onto_session_clock(fastf1_race_control):
    rc = src.build_race_control(fastf1_race_control, T0, KEY)
    assert rc["t"].tolist() == [3700.5, 4000.0]
    to_arrow(rc, "race_control")


def test_blank_strings_become_null():
    s = src._nullable_str(pd.Series(["", "  ", None, "Track limits", float("nan")]))
    assert s.tolist() == [None, None, None, "Track limits", None]


def test_invalid_gears_become_null():
    # Real values from 2024 Japan car_data: 128 overflowed int8, but 10-75 fit and were stored silently.
    g = src.clean_gear(pd.Series([0, 1, 8, 10, 75, 128, -1]))
    assert g.isna().tolist() == [False, False, False, True, True, True, True]
    assert g.dropna().tolist() == [0, 1, 8]


def test_throttle_sentinel_becomes_null():
    t = src.clean_throttle(pd.Series([0.0, 55.5, 100.0, 104.0]))
    assert t.isna().tolist() == [False, False, False, True]


def test_car_data_with_feed_glitches_fits_schema():
    raw = pd.DataFrame({
        "SessionTime": pd.to_timedelta([1.0, 1.24, 1.48], unit="s"),
        "RPM": [11000.0, 11200.0, 0.0], "Speed": [300.0, 301.0, 0.0],
        "nGear": [8, 8, 128], "Throttle": [100.0, 104.0, 0.0],
        "Brake": [False, False, True], "DRS": [12, 12, 0],
    }, index=[10, 11, 12])  # FastF1 frames don't start at index 0
    cd = src.build_car_data({"4": raw}, KEY)
    table = to_arrow(cd, "car_data")
    assert table.column("gear").to_pylist() == [8, 8, None]
    assert table.column("throttle").to_pylist() == [100.0, None, 0.0]
    assert table.column("t").to_pylist() == [1.0, 1.24, 1.48]
