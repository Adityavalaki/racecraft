"""
A car's telemetry, shaped for the pedal map, the driver cards and the
lap-against-lap traces.

The feed carries speed, throttle (percent), brake (on or off: the public feed
never says how hard), gear and, before 2026, DRS, about four times a second,
and position separately. Two shapes come out of it:

* `lap`: one lap by distance, every `STEP_M` metres, with where the car was,
  so the same arrays draw the pedal map and the traces, and two drivers' laps
  can be laid over each other metre for metre. Distance is integrated from
  speed, as FastF1 does; it comes out within a percent or two of the published
  lap length, which is what cutting the kerbs costs.
* `recent`: the last half-minute by time, for the trace on a driver's card.

Brake zones are runs of brake-on samples along the lap: where they start and
end, how long, and the speed going in and at the slowest. Corners are FastF1's
circuit markers, which already carry their distance along a reference lap.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

STEP_M = 5.0
# A brake-on run shorter than this is a dab or a sampling glitch, not a zone.
MIN_BRAKE_ZONE_S = 0.25
RECENT_HZ = 8.0
RECENT_MAX_S = 120.0
# A lap is drawn by default only when this share of it has pedals and a
# position. The feed sometimes sends a car's pedals as nothing (throttle
# missing, brake stuck on) and its position as nothing for whole laps, early in
# a practice session above all: drawn, that is a lap of solid brake.
USABLE_SHARE = 0.8


class NoLap(LookupError):
    """There is no such lap for that car, or it has no telemetry. The message says which."""


def _lap_row(data, driver: int, lap: int | None, t: float | None, or_earlier: bool = False) -> pd.Series:
    laps = data.laps[(data.laps["driver_number"] == driver)
                     & data.laps["lap_start_t"].notna() & data.laps["lap_end_t"].notna()]
    if laps.empty:
        raise NoLap(f"no timed laps for car {driver}")
    if lap is not None and not or_earlier:
        row = laps[laps["lap_number"] == lap]
        if row.empty:
            raise NoLap(f"car {driver} has no lap {lap}")
        return row.iloc[0]
    done = laps if t is None else laps[laps["lap_end_t"] <= t]
    if lap is not None:
        done = done[done["lap_number"] <= lap]
    if done.empty:
        raise NoLap(f"car {driver} has not completed a lap yet")
    for _, row in done.sort_values("lap_end_t", ascending=False).iterrows():
        if _usable(data, driver, row):
            return row
    raise NoLap(f"car {driver} has no completed lap with usable telemetry yet")


def _usable(data, driver: int, row: pd.Series) -> bool:
    """Whether a lap's pedals and position are there for most of it."""
    start, end = float(row["lap_start_t"]), float(row["lap_end_t"])
    car = data.car.get(driver)
    if car is None or len(car.t) == 0:
        return False
    inside = (car.t >= start) & (car.t <= end)
    if inside.sum() < 20:
        return False
    if np.isfinite(car.values["throttle"][inside].astype(float)).mean() < USABLE_SHARE:
        return False
    pos = data.position.get(driver)
    if pos is None or len(pos.t) == 0:
        return True                          # no positions in this session at all: the traces still stand
    xs = pos.at(np.linspace(start, end, 40), interpolate=False)["x"]
    return sum(v is not None for v in xs) >= USABLE_SHARE * len(xs)


def lap(data, driver: int, lap_number: int | None = None, t: float | None = None,
        or_earlier: bool = False) -> dict:
    """
    One lap by distance. `lap_number` picks it; otherwise the car's latest lap
    completed by session time `t` (or its last lap of all). Without a number,
    or with `or_earlier`, a lap whose telemetry the feed broke is passed over
    for the one before it: the pedal map asks for the lap just completed, and
    would otherwise draw a lap of solid brake.
    """
    row = _lap_row(data, driver, lap_number, t, or_earlier)
    start, end = float(row["lap_start_t"]), float(row["lap_end_t"])
    car = data.car.get(driver)
    if car is None or len(car.t) == 0:
        raise NoLap(f"no car telemetry for car {driver}")
    inside = (car.t >= start) & (car.t <= end)
    if inside.sum() < 20:
        raise NoLap(f"too little telemetry on lap {int(row['lap_number'])} for car {driver}")

    times = car.t[inside]
    speed = car.values["speed"][inside].astype(float)
    # Distance from speed, trapezoid by trapezoid, from the line.
    ms = speed / 3.6
    distance = np.cumsum(np.concatenate([[ms[0] * (times[0] - start)], (ms[1:] + ms[:-1]) / 2 * np.diff(times)]))
    total = float(distance[-1] + ms[-1] * max(0.0, end - times[-1]))
    grid = np.arange(0.0, total, STEP_M)
    # Time is pinned at both lines: the first and last samples fall a little
    # inside the lap, and clamping to them would end every lap a few tenths
    # early, which is the whole gap between two cars.
    at_t = np.interp(grid, np.concatenate([[0.0], distance, [total]]), np.concatenate([[start], times, [end]]))

    def stepped(name: str) -> np.ndarray:
        values = car.values[name][inside]
        idx = np.clip(np.searchsorted(times, at_t, side="right") - 1, 0, len(values) - 1)
        return values[idx]

    speed_g = np.interp(grid, distance, speed)
    throttle_g = np.interp(grid, distance, car.values["throttle"][inside].astype(float))
    # Where the throttle is missing the brake channel is stuck on, so neither
    # pedal is known there; brake is reported off rather than on throughout.
    brake_g = (stepped("brake").astype(float) > 0) & np.isfinite(throttle_g)
    gear_g = stepped("gear").astype(int)
    pos = data.position.get(driver)
    if pos is not None and len(pos.t):
        xy = pos.at(at_t)
        x, y = xy["x"], xy["y"]
    else:
        x = y = [None] * len(grid)

    zones = brake_zones(grid, at_t - start, speed_g, brake_g)
    corners = _corners(data, total)
    return {
        "driver_number": driver,
        "abbreviation": _code(data, driver),
        "lap": int(row["lap_number"]),
        "lap_time_s": _float(row.get("lap_time_s")),
        "compound": None if pd.isna(row.get("compound")) else str(row.get("compound")),
        "tyre_life": None if pd.isna(row.get("tyre_life")) else int(row.get("tyre_life")),
        "start_t": start,
        "length_m": round(total, 1),
        "step_m": STEP_M,
        "distance": [round(float(v), 1) for v in grid],
        "t": [round(float(v), 3) for v in at_t - start],
        "speed": [round(float(v), 1) for v in speed_g],
        "throttle": [round(float(v), 1) for v in throttle_g],
        "brake": [bool(v) for v in brake_g],
        "gear": [int(v) for v in gear_g],
        "x": [None if v is None else round(float(v), 1) for v in x],
        "y": [None if v is None else round(float(v), 1) for v in y],
        "brake_zones": zones,
        "corners": corners,
        "summary": {
            "top_speed": round(float(speed_g.max()), 1),
            "min_speed": round(float(speed_g.min()), 1),
            "full_throttle_share": round(float((throttle_g >= 98).mean()), 3),
            "braking_share": round(float(brake_g.mean()), 3),
            "brake_zones": len(zones),
        },
    }


def brake_zones(distance: np.ndarray, t: np.ndarray, speed: np.ndarray, brake: np.ndarray) -> list[dict]:
    """Runs of brake-on samples along a lap, each with where, how long and the speeds."""
    zones = []
    on = np.flatnonzero(brake)
    if not len(on):
        return zones
    breaks = np.flatnonzero(np.diff(on) > 1)
    for first, last in zip(np.concatenate([[on[0]], on[breaks + 1]]), np.concatenate([on[breaks], [on[-1]]])):
        stop = min(last + 1, len(distance) - 1)
        duration = float(t[stop] - t[first])
        if duration < MIN_BRAKE_ZONE_S:
            continue
        zones.append({
            "start_m": round(float(distance[first]), 1),
            "end_m": round(float(distance[stop]), 1),
            "duration_s": round(duration, 2),
            "entry_speed": round(float(speed[max(first - 1, 0)]), 1),     # the speed it braked from
            "min_speed": round(float(speed[first:stop + 1].min()), 1),
        })
    return zones


def recent(data, driver: int, t: float, seconds: float = 30.0) -> dict:
    """The last `seconds` before `t`, by time: speed, throttle, brake and gear."""
    seconds = float(min(max(seconds, 1.0), RECENT_MAX_S))
    car = data.car.get(driver)
    if car is None or len(car.t) == 0:
        raise NoLap(f"no car telemetry for car {driver}")
    times = np.linspace(t - seconds, t, int(seconds * RECENT_HZ) + 1)
    sampled = car.at(times)
    # As in `lap`: where the throttle is missing the brake is stuck on, so unknown.
    known = [v is not None and np.isfinite(v) for v in sampled["throttle"]]
    sampled["brake"] = [v if ok else None for v, ok in zip(sampled["brake"], known)]
    return {
        "driver_number": driver,
        "seconds": seconds,
        "t": [round(float(v - t), 2) for v in times],
        "speed": sampled["speed"],
        "throttle": sampled["throttle"],
        "brake": [None if v is None else bool(v) for v in sampled["brake"]],
        "gear": [None if v is None else int(v) for v in sampled["gear"]],
    }


def compare(subject: dict, reference: dict) -> dict:
    """
    The time between two laps along the subject's distance: positive where the
    subject is behind. The reference is stretched to the subject's length, so
    two cars that cut the same kerbs differently still line up corner for corner.
    """
    d_s = np.asarray(subject["distance"], dtype=float)
    t_s = np.asarray(subject["t"], dtype=float)
    d_r = np.asarray(reference["distance"], dtype=float) * (subject["length_m"] / max(reference["length_m"], 1.0))
    t_r = np.interp(d_s, d_r, np.asarray(reference["t"], dtype=float))
    delta = t_s - t_r
    return {"distance": subject["distance"], "delta_s": [round(float(v), 3) for v in delta],
            "final_s": round(float(delta[-1]), 3) if len(delta) else None}


def _corners(data, total: float) -> list[dict]:
    markers = getattr(data, "markers", None)
    if markers is None or markers.empty:
        return []
    corners = markers[markers["kind"] == "corner"].sort_values("distance")
    return [{"number": int(r.number), "letter": None if pd.isna(r.letter) or not r.letter else str(r.letter),
             "distance": round(float(r.distance), 1)}
            for r in corners.itertuples() if pd.notna(r.distance) and 0 <= r.distance <= total * 1.05]


def _code(data, driver: int) -> str | None:
    row = data.drivers[data.drivers["driver_number"] == driver]
    return None if row.empty or pd.isna(row.iloc[0]["abbreviation"]) else str(row.iloc[0]["abbreviation"])


def _float(value) -> float | None:
    return None if value is None or pd.isna(value) else round(float(value), 3)
