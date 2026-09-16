"""
Running order and gaps, on hand-built laps where the right answer is obvious.

The shape of the fixture matters: cars cross the line one after another, so
for most of a lap the leader has completed one more lap than everyone else
without anybody being lapped.
"""

import pandas as pd
import pytest

from racecraft.api import timing

LAP = 90.0


def lap_row(number, driver, lap, end_t, lap_time=LAP, compound="HARD", life=5,
            pit_in=False, deleted=False):
    return {
        "driver_number": number, "driver": driver, "lap_number": lap,
        "lap_end_t": end_t, "lap_time_s": lap_time, "compound": compound,
        "tyre_life": life, "laps_in_stint": life, "is_pit_in_lap": pit_in,
        "deleted": deleted,
    }


@pytest.fixture
def race():
    """Three cars, 3 laps. Second is 6 s back, third is a full lap down."""
    rows = []
    for lap in (1, 2, 3):
        rows.append(lap_row(1, "LEA", lap, 1000 + lap * LAP))
        rows.append(lap_row(2, "SEC", lap, 1006 + lap * LAP))
    for lap in (1, 2):
        rows.append(lap_row(3, "LAP", lap, 1000 + (lap + 1) * LAP + 4))
    laps = pd.DataFrame(rows)
    drivers = pd.DataFrame({
        "driver_number": [1, 2, 3], "abbreviation": ["LEA", "SEC", "LAP"],
        "team_name": ["A", "B", "C"], "team_color": ["ff0000", "00ff00", "0000ff"],
        "grid_position": [2, 1, 3], "status": ["Finished", "Finished", "Lapped"],
        "classified_position": ["1", "2", "3"],
    })
    return laps, drivers


def test_gap_is_measured_at_the_line(race):
    laps, drivers = race
    result = timing.classify(laps, drivers, 1000 + 3 * LAP + 1, "Race")
    leader, second = result.drivers[0], result.drivers[1]
    assert (leader.abbreviation, leader.gap_text) == ("LEA", "")
    assert second.abbreviation == "SEC"
    assert second.gap_to_leader_s == pytest.approx(6.0)
    assert second.gap_text == "+6.000"


def test_car_behind_is_not_lapped_just_because_the_leader_crossed_first(race):
    laps, drivers = race
    # One second after the leader completes lap 3; SEC has completed only 2.
    result = timing.classify(laps, drivers, 1000 + 3 * LAP + 1, "Race")
    second = result.drivers[1]
    assert second.laps_completed == 2
    assert second.laps_down == 0
    assert "LAP" not in second.gap_text


def test_a_genuinely_lapped_car_is_shown_in_laps(race):
    laps, drivers = race
    result = timing.classify(laps, drivers, 1000 + 3 * LAP + 1, "Race")
    lapped = result.drivers[2]
    assert lapped.abbreviation == "LAP"
    assert lapped.laps_down == 1
    assert lapped.gap_text == "+1 LAP"
    assert lapped.gap_to_leader_s is None  # a time gap across different laps is meaningless


def test_interval_is_the_gap_to_the_car_ahead(race):
    laps, drivers = race
    laps = pd.concat([laps, pd.DataFrame([lap_row(4, "THR", lap, 1010 + lap * LAP) for lap in (1, 2, 3)])],
                     ignore_index=True)
    drivers = pd.concat([drivers, pd.DataFrame([{
        "driver_number": 4, "abbreviation": "THR", "team_name": "D", "team_color": "ffff00",
        "grid_position": 4, "status": "Finished", "classified_position": "4"}])], ignore_index=True)
    result = timing.classify(laps, drivers, 1000 + 3 * LAP + 1, "Race")
    third = [d for d in result.drivers if d.abbreviation == "THR"][0]
    assert third.gap_to_leader_s == pytest.approx(10.0)
    assert third.interval_s == pytest.approx(4.0)   # 10 s to leader, 6 s to the car ahead


def test_before_the_start_the_order_is_the_grid(race):
    laps, drivers = race
    result = timing.classify(laps, drivers, 0.0, "Race")
    assert [d.abbreviation for d in result.drivers] == ["SEC", "LEA", "LAP"]
    assert all(d.status == "not_started" for d in result.drivers)
    assert result.leader_lap == 0


def test_finished_and_retired_are_distinguished(race):
    laps, drivers = race
    drivers.loc[drivers.driver_number == 3, "classified_position"] = "R"  # retired, not classified
    result = timing.classify(laps, drivers, 10_000.0, "Race")
    by_code = {d.abbreviation: d.status for d in result.drivers}
    assert by_code == {"LEA": "finished", "SEC": "finished", "LAP": "out"}


def test_practice_is_ordered_by_best_lap(race):
    laps, drivers = race
    laps.loc[(laps.driver_number == 2) & (laps.lap_number == 3), "lap_time_s"] = 88.0  # SEC sets the pace
    result = timing.classify(laps, drivers, 10_000.0, "Practice 2")
    assert [d.abbreviation for d in result.drivers][:2] == ["SEC", "LEA"]
    assert result.drivers[0].best_lap_s == 88.0
    assert result.drivers[0].is_session_best
    assert result.drivers[1].gap_to_leader_s == pytest.approx(2.0)


def test_deleted_laps_do_not_count_in_qualifying(race):
    laps, drivers = race
    laps.loc[(laps.driver_number == 2) & (laps.lap_number == 3), ["lap_time_s", "deleted"]] = [80.0, True]
    result = timing.classify(laps, drivers, 10_000.0, "Qualifying")
    assert result.drivers[0].best_lap_s == LAP  # the 80 s lap was deleted, so it is ignored
