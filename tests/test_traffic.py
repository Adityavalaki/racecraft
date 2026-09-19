"""
Measuring the wake penalty.

The simulator used to carry a hard-coded 0.55 s a lap, attributed to a
measurement nothing in the repository made. The measurement that replaced it
turned on one decision — which laps to count — and got it wrong by a factor of
two the obvious way. These tests pin that decision.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft.model import traffic


def _frame(rows):
    """Residual rows as `_race_residuals` returns them."""
    return pd.DataFrame(rows, columns=["residual_s", "gap_ahead", "own_pace", "their_pace"])


def _laps(gap, residual, n, *, slower=True):
    """n laps at one gap, the follower slower (or quicker) than the car ahead."""
    own, their = (1.0, 0.0) if slower else (0.0, 1.0)
    return [(residual, gap, own, their)] * n


def _measure_rows(rows, monkeypatch):
    monkeypatch.setattr(traffic, "_race_residuals", lambda laps: _frame(rows))
    return traffic.measure([pd.DataFrame({"x": [1]})])


def test_the_wake_is_read_against_clear_air(monkeypatch):
    rows = (_laps(0.3, 1.30, 200) + _laps(0.8, 1.10, 200) + _laps(1.2, 1.05, 200)
            + _laps(2.0, 1.02, 200) + _laps(3.0, 1.01, 200) + _laps(6.0, 1.00, 400))
    table = _measure_rows(rows, monkeypatch)

    assert table.measured
    values = dict(table.penalties)
    assert values[0.5] == pytest.approx(0.30, abs=1e-9)
    assert values[1.0] == pytest.approx(0.10, abs=1e-9)
    assert values[4.0] == pytest.approx(0.01, abs=1e-9)


def test_being_held_up_is_not_counted_as_wake(monkeypatch):
    """
    The decision that halved the number. A quicker car stuck behind a slower one
    loses time to being held up, and the simulator models that separately, by
    blocking. Counting it here too would charge it twice.
    """
    rows = (_laps(0.3, 1.25, 200, slower=True)       # the wake alone
            + _laps(0.3, 1.80, 400, slower=False)    # wake plus being held up
            + _laps(6.0, 1.00, 300, slower=True)
            + _laps(6.0, 1.00, 300, slower=False))
    table = _measure_rows(rows, monkeypatch)

    assert dict(table.penalties)[0.5] == pytest.approx(0.25, abs=1e-9), \
        "the held-up laps leaked into the wake"
    # The naive figure, which includes them, is still reported for comparison.
    assert table.all_laps[0] > dict(table.penalties)[0.5]


def test_a_wake_never_makes_a_car_quicker(monkeypatch):
    rows = _laps(0.3, 0.90, 200) + _laps(6.0, 1.00, 300)
    table = _measure_rows(rows, monkeypatch)
    assert dict(table.penalties)[0.5] == 0.0


def test_the_penalty_never_grows_with_distance(monkeypatch):
    """Noise can put a further bin above a closer one; the air cannot."""
    rows = (_laps(0.3, 1.20, 200) + _laps(0.8, 1.05, 200) + _laps(1.2, 1.15, 200)
            + _laps(6.0, 1.00, 300))
    values = [v for _, v in _measure_rows(rows, monkeypatch).penalties]
    assert values == sorted(values, reverse=True)


def test_too_few_close_laps_is_not_a_measurement(monkeypatch):
    rows = _laps(0.3, 1.30, traffic.MIN_CLOSE_LAPS - 1) + _laps(6.0, 1.00, 300)
    table = _measure_rows(rows, monkeypatch)
    assert not table.measured
    assert table.penalties == ()
    assert "only" in table.detail


def test_no_fittable_race_is_not_a_measurement(monkeypatch):
    monkeypatch.setattr(traffic, "_race_residuals", lambda laps: None)
    table = traffic.measure([pd.DataFrame({"x": [1]})])
    assert not table.measured


def test_the_table_has_the_shape_the_simulator_reads(monkeypatch):
    from racecraft.model import race

    rows = _laps(0.3, 1.30, 200) + _laps(0.8, 1.10, 200) + _laps(6.0, 1.00, 300)
    table = _measure_rows(rows, monkeypatch)
    assert [edge for edge, _ in table.penalties] == list(traffic.EDGES)
    assert race.following_penalty(0.2, table.penalties) == pytest.approx(0.30, abs=1e-9)
    assert race.following_penalty(9.0, table.penalties) == 0.0


def test_the_gap_is_the_one_a_car_spent_the_lap_in():
    """
    Taken at the end of the previous lap, and only against cars on the same lap,
    so a car being lapped is never counted as the one ahead of the leader.
    """
    laps = pd.DataFrame({
        "driver_number": [1, 2, 3, 1, 2, 3],
        "lap_number":    [1, 1, 1, 2, 2, 2],
        "lap_end_t":     [100.0, 100.4, 103.0, 190.0, 190.3, 195.0],
    })
    gaps = traffic.gaps_ahead(laps).set_index(["driver_number", "lap_number"])

    # Lap 2 is spent at the gaps the lap-1 line crossing set up.
    assert gaps.loc[(2, 2), "gap_ahead"] == pytest.approx(0.4)
    assert gaps.loc[(2, 2), "ahead"] == 1
    assert gaps.loc[(3, 2), "gap_ahead"] == pytest.approx(2.6)
    assert pd.isna(gaps.loc[(1, 2), "gap_ahead"]), "the leader has nobody ahead"


def test_the_fallback_in_the_simulator_is_the_measured_2026_wake():
    """The old 0.55 was the wake and the holding-up together."""
    from racecraft.model import race

    assert dict(race.FOLLOWING_PENALTY_S)[0.5] < 0.35
    assert race.following_penalty(0.2) == dict(race.FOLLOWING_PENALTY_S)[0.5]
