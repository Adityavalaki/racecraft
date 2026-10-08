"""A car's lap by distance, its brake zones, and two laps laid over each other."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from racecraft.api import telemetry
from racecraft.api.session import Channel


def _car(lap_s=60.0, slow_from=20.0, slow_to=26.0, hz=4.0, start=1000.0, shift=0.0):
    """
    One lap at 216 km/h (60 m/s), braking to 108 km/h for six seconds in the
    middle. Samples deliberately miss both lines, as the feed's do.
    """
    t = np.arange(start + 0.13 + shift, start + lap_s - 0.11, 1 / hz)
    rel = t - start
    braking = (rel >= slow_from) & (rel < slow_to)
    # Slowing from 216 to 108 km/h over the first two seconds on the brakes, as a car does.
    speed = np.where(braking, np.maximum(108.0, 216.0 - 54.0 * (rel - slow_from)), 216.0)
    return Channel(t=t, values={
        "speed": speed, "throttle": np.where(braking, 0.0, 100.0), "brake": braking.astype(float),
        "gear": np.where(braking, 4, 7).astype(float), "drs": np.zeros_like(t),
    })


def _data(cars: dict[int, Channel], laps: list[tuple[int, int, float, float]]):
    return SimpleNamespace(
        car=cars,
        position={n: Channel(t=c.t, values={"x": c.t * 10.0, "y": c.t * 0.0}) for n, c in cars.items()},
        laps=pd.DataFrame([{"driver_number": d, "lap_number": n, "lap_start_t": s, "lap_end_t": e,
                            "lap_time_s": e - s, "compound": "MEDIUM", "tyre_life": 5} for d, n, s, e in laps]),
        drivers=pd.DataFrame({"driver_number": list(cars), "abbreviation": [f"D{n}" for n in cars]}),
        markers=pd.DataFrame({"kind": ["corner", "corner", "marshal_light"], "number": [1, 2, 1],
                              "letter": [None, "A", None], "distance": [1300.0, 2800.0, 50.0]}),
    )


def test_a_lap_by_distance_runs_line_to_line_with_its_brake_zone():
    data = _data({1: _car()}, [(1, 1, 1000.0, 1060.0)])
    lap = telemetry.lap(data, 1, 1)
    # 54 s at 60 m/s, 2 s slowing to 30 m/s, 4 s at 30 m/s.
    assert lap["length_m"] == pytest.approx(54 * 60 + 2 * 45 + 4 * 30, rel=0.01)
    assert lap["t"][0] == pytest.approx(0.0, abs=0.01)
    assert lap["t"][-1] == pytest.approx(60.0, abs=0.15)          # pinned to the line, not the last sample
    assert len(lap["distance"]) == len(lap["speed"]) == len(lap["brake"]) == len(lap["x"])
    [zone] = lap["brake_zones"]
    assert zone["start_m"] == pytest.approx(20 * 60, abs=20)
    assert zone["duration_s"] == pytest.approx(6.0, abs=0.3)
    assert zone["entry_speed"] == pytest.approx(216, abs=6) and zone["min_speed"] == pytest.approx(108, abs=1)
    assert [c["number"] for c in lap["corners"]] == [1, 2] and lap["corners"][1]["letter"] == "A"
    assert lap["summary"]["brake_zones"] == 1


def test_without_a_lap_number_the_latest_lap_finished_by_the_clock_is_used():
    data = _data({1: _car()}, [(1, 1, 1000.0, 1060.0), (1, 2, 1060.0, 1120.0)])
    assert telemetry.lap(data, 1, t=1090.0)["lap"] == 1
    with pytest.raises(telemetry.NoLap, match="not completed a lap"):
        telemetry.lap(data, 1, t=1010.0)
    with pytest.raises(telemetry.NoLap, match="no lap 9"):
        telemetry.lap(data, 1, 9)


def test_two_laps_compare_corner_for_corner_and_end_on_the_lap_time_gap():
    quick = _car(lap_s=60.0)
    slow = _car(lap_s=61.0, slow_from=20.0, slow_to=27.0, start=2000.0)    # brakes a second longer
    data = _data({1: quick, 2: slow}, [(1, 1, 1000.0, 1060.0), (2, 1, 2000.0, 2061.0)])
    a, b = telemetry.lap(data, 1, 1), telemetry.lap(data, 2, 1)
    delta = telemetry.compare(a, b)
    assert len(delta["delta_s"]) == len(a["distance"])
    assert delta["delta_s"][10] == pytest.approx(0.0, abs=0.1)              # level before the corner
    assert delta["final_s"] == pytest.approx(-1.0, abs=0.15)                # car 1 a second up at the line


def test_recent_is_the_last_half_minute_by_time():
    data = _data({1: _car()}, [(1, 1, 1000.0, 1060.0)])
    window = telemetry.recent(data, 1, t=1024.0, seconds=30)
    assert window["t"][0] == -30.0 and window["t"][-1] == 0.0
    assert len(window["t"]) == 30 * 8 + 1
    assert window["brake"][-1] is True                                     # 24 s in: braking
    assert window["speed"][-1] == pytest.approx(108)
