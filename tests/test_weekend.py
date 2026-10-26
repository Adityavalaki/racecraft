"""What a weekend says about each driver before the race: practice long runs and qualifying."""

import numpy as np
import pandas as pd
import pytest

from racecraft.model import weekend

DEG = {"SOFT": 0.10, "MEDIUM": 0.05, "HARD": 0.02}
OFFSETS = {"SOFT": 0.0, "MEDIUM": 0.4, "HARD": 0.8}


def _stint(driver, base, compound="MEDIUM", laps=8, start_age=1, stint=1, **over):
    rows = []
    for i in range(laps):
        age = start_age + i
        rows.append({"driver_number": driver, "stint": stint, "lap_number": stint * 100 + i,
                     "compound": compound, "tyre_life": age,
                     "lap_time_s": base + OFFSETS[compound] + DEG[compound] * age,
                     "track_status": "1", "is_pit_in_lap": False, "is_pit_out_lap": False,
                     "deleted": False, "is_accurate": True, **over})
    return rows


def test_long_runs_are_corrected_for_compound_and_tyre_age():
    """Same car pace, one on old hards and one on new mediums: the same long-run pace."""
    laps = pd.DataFrame(_stint(1, 95.0, "HARD", start_age=15) + _stint(2, 95.0, "MEDIUM")
                        + _stint(3, 96.0, "MEDIUM"))
    runs = weekend.long_runs({"FP2": laps}, DEG, OFFSETS)
    assert runs.loc[1, "long_run_s"] == pytest.approx(runs.loc[2, "long_run_s"], abs=1e-6)
    assert runs.loc[3, "long_run_s"] - runs.loc[2, "long_run_s"] == pytest.approx(1.0, abs=1e-6)


def test_short_runs_and_laps_that_are_not_pace_are_left_out():
    laps = pd.DataFrame(
        _stint(1, 95.0) + _stint(2, 95.0, laps=4)                      # a qualifying run: too short
        + _stint(3, 95.0, track_status="2")                            # under yellow
        + _stint(4, 95.0, deleted=True)
        + _stint(5, 95.0, compound="SOFT", is_pit_out_lap=True)
        + _stint(6, 96.0))
    runs = weekend.long_runs({"FP2": laps}, DEG, OFFSETS)
    assert set(runs.index) == {1, 6}


def test_a_lap_spent_in_traffic_does_not_move_a_long_run():
    clean = _stint(1, 95.0)
    held_up = _stint(1, 95.0)
    held_up[3]["lap_time_s"] += 12.0                                   # stuck behind a car on a cool-down
    base = weekend.long_runs({"FP2": pd.DataFrame(clean + _stint(2, 96.0))}, DEG, OFFSETS)
    slow = weekend.long_runs({"FP2": pd.DataFrame(held_up + _stint(2, 96.0))}, DEG, OFFSETS)
    assert slow.loc[1, "long_run_s"] == pytest.approx(base.loc[1, "long_run_s"], abs=0.02)


def test_each_session_counts_relative_to_its_own_field_and_fp2_counts_most():
    fp1 = pd.DataFrame(_stint(1, 97.0) + _stint(2, 96.0))              # a quicker track for everyone in FP2,
    fp2 = pd.DataFrame(_stint(1, 94.0) + _stint(2, 95.0))              # and the order flipped
    runs = weekend.long_runs({"FP1": fp1, "FP2": fp2}, DEG, OFFSETS)
    assert runs.loc[1, "long_run_s"] < runs.loc[2, "long_run_s"]       # FP2's verdict wins
    assert runs.loc[1, "long_run_laps"] == pytest.approx(8 * 0.5 + 8 * 1.0)


def test_no_practice_running_means_no_long_runs():
    assert weekend.long_runs({}, DEG, OFFSETS).empty
    wet = pd.DataFrame(_stint(1, 95.0))
    wet["compound"] = "INTERMEDIATE"
    assert weekend.long_runs({"FP2": wet}, DEG, OFFSETS).empty


# ---- the grid

class _Con:
    """Just enough of a connection for `grid`: results by session key."""
    def __init__(self, tables):
        self.tables = tables

    def execute(self, sql, params):
        class Out:
            def __init__(self, df):
                self._df = df

            def df(self):
                return self._df
        return Out(self.tables.get(params[0], pd.DataFrame(columns=["driver_number", "grid_position", "position"])))


def test_a_grid_the_feed_never_published_is_read_from_qualifying_not_the_result():
    """Rows are stored in finishing order; ranking a grid of -1s by row order would be the answer itself."""
    race = pd.DataFrame({"driver_number": [63, 3, 6, 16], "grid_position": [-1, -1, -1, -1], "position": [1, 2, 3, 4]})
    quali = pd.DataFrame({"driver_number": [63, 3, 6, 16], "position": [1, 2, 4, 3]})
    slots, source = weekend.grid(_Con({"R": race, "Q": quali}), "R", "Q")
    assert source == "qualifying"
    assert slots.to_dict() == {63: 1, 3: 2, 6: 4, 16: 3}


def test_pit_lane_starters_go_to_the_back_in_qualifying_order():
    race = pd.DataFrame({"driver_number": [1, 2, 3, 4, 5], "grid_position": [1, 0, 2, 0, 3],
                         "position": [1, 2, 3, 4, 5]})
    quali = pd.DataFrame({"driver_number": [1, 2, 3, 4, 5], "position": [2, 5, 1, 4, 3]})
    slots, source = weekend.grid(_Con({"R": race, "Q": quali}), "R", "Q")
    assert source == "race"
    assert slots.to_dict() == {1: 1, 3: 2, 5: 3, 4: 4, 2: 5}
