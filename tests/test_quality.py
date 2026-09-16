import pandas as pd
import pytest

from racecraft.ingest import fastf1_source as src
from racecraft.ingest import quality

KEY = "2024_01_R"


@pytest.fixture
def tables(fastf1_laps):
    laps = src.build_laps(fastf1_laps, KEY)
    results = pd.DataFrame({
        "driver_number": [1, 44] + list(range(100, 108)),
        "position": list(range(1, 11)),
        "laps": [3] * 10,
        "result_time_s": [laps.loc[laps.driver_number == 1, "lap_time_s"].sum()] + [5.0] * 9,
    })
    sessions = pd.DataFrame({"total_laps": [3], "session_name": ["Race"]})
    return {"laps": laps, "results": results, "sessions": sessions}


def severities(findings):
    return {f.check: f.severity for f in findings}


def test_clean_session_has_no_errors_and_reconciles(tables):
    found = severities(quality.check_session(tables))
    assert not quality.has_errors(quality.check_session(tables))
    assert found["results.winner_time_reconciles"] == quality.OK


def test_duplicate_lap_is_an_error(tables):
    tables["laps"] = pd.concat([tables["laps"], tables["laps"].iloc[[0]]], ignore_index=True)
    assert severities(quality.check_session(tables))["laps.unique_lap"] == quality.ERROR


def test_tyre_life_going_backwards_is_an_error(tables):
    laps = tables["laps"]
    laps.loc[(laps.driver_number == 44) & (laps.lap_number == 3), "tyre_life"] = 1
    assert severities(quality.check_session(tables))["laps.tyre_life_monotonic"] == quality.ERROR


def test_time_mismatch_with_official_result_warns(tables):
    tables["results"].loc[0, "result_time_s"] += 10
    assert severities(quality.check_session(tables))["results.winner_time_reconciles"] == quality.WARN


def test_reconciles_when_lap_times_are_missing(tables):
    # Safety-car laps often have no lap time; the check must still run.
    laps = tables["laps"]
    laps.loc[(laps.driver_number == 1) & (laps.lap_number == 2), "lap_time_s"] = float("nan")
    found = {f.check: f for f in quality.check_session(tables)}
    assert found["results.winner_time_reconciles"].severity == quality.OK
    assert "skipped" not in found["results.winner_time_reconciles"].detail


def _telemetry(n_car, n_pos):
    car = pd.DataFrame({"driver_number": 1, "t": [float(i) for i in range(n_car)],
                        "speed": 200.0, "gear": 7.0, "throttle": 100.0})
    pos = pd.DataFrame({"driver_number": 1, "t": [float(i) for i in range(n_pos)]})
    return car, pos


def test_missing_position_feed_warns(tables):
    # Shape of 2026 Monaco: position samples at 18% of car samples.
    tables["car_data"], tables["pos_data"] = _telemetry(1000, 180)
    assert severities(quality.check_session(tables))["pos_data.coverage"] == quality.WARN


def test_normal_position_coverage_is_silent(tables):
    tables["car_data"], tables["pos_data"] = _telemetry(1000, 1020)
    assert "pos_data.coverage" not in severities(quality.check_session(tables))


def test_practice_skips_race_only_checks(tables):
    tables["sessions"]["session_name"] = "Practice 2"
    tables["sessions"]["total_laps"] = None
    tables["results"]["result_time_s"] = float("nan")
    tables["laps"]["lap_time_s"] = float("nan")  # cool-down and pit laps are untimed in practice
    checks = severities(quality.check_session(tables))
    assert "results.winner_time_reconciles" not in checks
    assert "laps.lap_time_coverage" not in checks
    assert not quality.has_errors(quality.check_session(tables))


def test_time_going_backwards_is_an_error(tables):
    laps = tables["laps"]
    laps.loc[(laps.driver_number == 1) & (laps.lap_number == 3), "lap_end_t"] = 0.0
    assert severities(quality.check_session(tables))["laps.time_monotonic"] == quality.ERROR


def test_placeholder_laps_sharing_a_timestamp_only_warn(tables):
    # 2025 Spain FP3: practice opens with laps ending at -74 s and twice at 0.000.
    laps = tables["laps"]
    first = (laps.driver_number == 1) & (laps.lap_number == 1)
    second = (laps.driver_number == 1) & (laps.lap_number == 2)
    laps.loc[first, "lap_end_t"] = 0.0
    laps.loc[second, "lap_end_t"] = 0.0
    found = severities(quality.check_session(tables))
    assert found["laps.time_repeated"] == quality.WARN
    assert "laps.time_monotonic" not in found
