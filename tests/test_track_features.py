"""
What the map draws besides the cars: DRS zones and the safety car, and the
whole-number channels (gear, DRS, brake) the driver cards show.

All on a synthetic circular track, so the right answer is known exactly: a
circle of radius 1 km, driven anticlockwise from angle 0 (the start line),
with the outline as 600 evenly spaced points in the direction of travel.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft.api import session as S

RADIUS = 10_000.0                         # tenths of a metre: 1 km
LAP_S = 90.0
N = S.OUTLINE_POINTS


def circle(fraction):
    angle = 2 * np.pi * np.asarray(fraction)
    return RADIUS * np.cos(angle), RADIUS * np.sin(angle)


def session_on_a_circle(laps=6, drivers=(1, 44), drs_window=None):
    """
    A session whose cars lap the circle; DRS open (code 12) while a car is
    between the two lap fractions in `drs_window`, if given.
    """
    data = S.SessionData.__new__(S.SessionData)
    outline_x, outline_y = circle(np.arange(N) / N)
    data.outline = [[float(x), float(y)] for x, y in zip(outline_x, outline_y)] + \
                   [[float(outline_x[0]), float(outline_y[0])]]
    rows = []
    data.position, data.car = {}, {}
    for offset, number in enumerate(drivers):
        t = np.arange(0, laps * LAP_S, 0.25) + offset * 3.0
        fraction = (t - offset * 3.0) / LAP_S % 1.0
        x, y = circle(fraction)
        data.position[number] = S.Channel(t=t, values={"x": x, "y": y})
        drs = np.zeros_like(t)
        if drs_window is not None:
            lo, hi = drs_window                      # lo > hi: a window across the line
            inside = (fraction >= lo) & (fraction <= hi) if lo <= hi else (fraction >= lo) | (fraction <= hi)
            drs[inside] = 12.0
        data.car[number] = S.Channel(t=t, values={"speed": np.full_like(t, 250.0), "gear": np.full_like(t, 7.0),
                                                  "throttle": np.full_like(t, 100.0), "brake": np.zeros_like(t),
                                                  "drs": drs})
        for lap in range(1, laps + 1):
            start = offset * 3.0 + (lap - 1) * LAP_S
            rows.append({"driver_number": number, "lap_number": lap, "lap_time_s": LAP_S,
                         "lap_start_t": start, "lap_end_t": start + LAP_S,
                         "is_pit_in_lap": False, "is_pit_out_lap": False})
    data.laps = pd.DataFrame(rows)
    return data


# ------------------------------------------------------------------ DRS zones

def test_a_drs_zone_is_found_where_the_flap_opens():
    data = session_on_a_circle(drs_window=(0.25, 0.40))
    zones = data._build_drs_zones()
    assert len(zones) == 1
    first, last = zones[0]
    assert first == pytest.approx(0.25 * N, abs=3)
    assert last == pytest.approx(0.40 * N, abs=3)


def test_a_zone_across_the_start_line_wraps():
    data = session_on_a_circle(drs_window=(0.92, 0.08))
    (first, last), = data._build_drs_zones()
    assert first > last, "a zone over the line runs from near the end of the outline to near its start"
    assert first == pytest.approx(0.92 * N, abs=3)
    assert last == pytest.approx(0.08 * N, abs=3)


def test_no_drs_means_no_zones_as_in_2026():
    assert session_on_a_circle(drs_window=None)._build_drs_zones() == []


def test_eligible_but_closed_is_not_a_zone():
    """Code 8 is 'within a second, flap shut': not where DRS opens."""
    data = session_on_a_circle(drs_window=(0.25, 0.40))
    data.car = {n: S.Channel(t=c.t, values={**c.values, "drs": np.where(c.values["drs"] > 0, 8.0, 0.0)})
                for n, c in data.car.items()}
    assert data._build_drs_zones() == []


def test_one_stray_opening_does_not_draw_a_zone():
    data = session_on_a_circle(drs_window=(0.25, 0.40))
    drs = data.car[1].values["drs"].copy()
    stray = int(np.argmin(np.abs((data.car[1].t / LAP_S % 1.0) - 0.70)))
    drs[stray] = 12.0                                  # one sample, somewhere else
    data.car[1] = S.Channel(t=data.car[1].t, values={**data.car[1].values, "drs": drs})
    assert len(data._build_drs_zones()) == 1


# ------------------------------------------------------------------ safety car

def test_the_safety_car_is_drawn_500m_up_the_road_from_the_leader():
    data = session_on_a_circle()
    x, y = circle(0.10)
    car = data.safety_car_at({"x": float(x), "y": float(y)})
    assert car["simulated"] is True
    ahead_m = S.SAFETY_CAR_LEAD_M
    perimeter_m = 2 * np.pi * RADIUS / S.POSITION_UNITS_PER_M
    expected = circle(0.10 + ahead_m / perimeter_m)
    assert car["x"] == pytest.approx(float(expected[0]), abs=RADIUS * 0.02)
    assert car["y"] == pytest.approx(float(expected[1]), abs=RADIUS * 0.02)


def test_the_safety_car_wraps_past_the_start_line():
    data = session_on_a_circle()
    x, y = circle(0.98)
    car = data.safety_car_at({"x": float(x), "y": float(y)})
    angle = np.arctan2(car["y"], car["x"]) / (2 * np.pi) % 1.0
    assert 0.0 < angle < 0.2, "past the line, so near the start of the lap"


@pytest.mark.parametrize("leader", [None, {}, {"x": None, "y": 5.0}])
def test_no_safety_car_without_the_leaders_position(leader):
    assert session_on_a_circle().safety_car_at(leader) is None


def test_no_safety_car_without_a_track_outline():
    data = session_on_a_circle()
    data.outline = []
    assert data.safety_car_at({"x": 1.0, "y": 2.0}) is None


# ------------------------------------------------------------------ whole-number channels

def test_gear_drs_and_brake_take_the_last_sample_rather_than_an_average():
    channel = S.Channel(t=np.array([0.0, 1.0]),
                        values={"gear": np.array([6.0, 7.0]), "drs": np.array([8.0, 12.0]),
                                "brake": np.array([1.0, 0.0]), "speed": np.array([200.0, 220.0])})
    halfway = channel.at(np.array([0.5]))
    assert halfway["gear"] == [6.0], "a car is in one gear or the other, never 6.5"
    assert halfway["drs"] == [8.0], "10 between 8 and 12 would be an invented code"
    assert halfway["brake"] == [1.0]
    assert halfway["speed"] == [210.0], "quantities are still interpolated"


# ---- overtake mode, 2026's successor to DRS

def test_overtake_mode_follows_race_controls_switch():
    import pandas as pd

    from racecraft.api import session as session_model

    rc = pd.DataFrame({"t": [100.0, 50.0, 300.0, 200.0], "message": [
        "OVERTAKE ENABLED", "RISK OF RAIN 0%", " overtake disabled", "SAFETY CAR DEPLOYED"]})
    changes = session_model._overtake_changes(rc)
    assert changes.to_dict("records") == [{"t": 100.0, "enabled": True}, {"t": 300.0, "enabled": False}]
    assert session_model._overtake_changes(rc.iloc[[1, 3]]) is None        # a DRS-era session never mentions it


def test_a_car_within_a_second_is_eligible_only_while_it_is_on():
    from racecraft.api.session import overtake_status

    close = {"status": "racing", "interval_s": 0.6}
    assert overtake_status(close, True) == "eligible"
    assert overtake_status(close, False) == "disabled"
    assert overtake_status({"status": "racing", "interval_s": 1.4}, True) == "not_eligible"
    assert overtake_status({"status": "racing", "interval_s": None}, True) == "not_eligible"   # the leader, or a lap down
    assert overtake_status({"status": "out", "interval_s": 0.3}, True) == "not_eligible"
