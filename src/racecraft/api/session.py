"""
One session, held in memory and ready to replay.

Telemetry is far too large to query per frame: a race carries 1.4 million
position and car-data rows, and the interface asks for a new frame several
times a second while playing. So a session is read from the lake once into
per-driver numpy arrays, and every later question is answered by a binary
search. Loading costs about a second and 50 MB; a frame then costs
microseconds.

Two sessions are kept at a time, enough to compare or switch back without
reloading, and little enough to stay comfortable in memory.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

from racecraft import config
from racecraft.api import timing
from racecraft.store.db import connect

log = logging.getLogger(__name__)

MAX_CACHED_SESSIONS = 2
OUTLINE_POINTS = 600
OUTLINE_LAPS = 12          # fast laps blended into the track shape
MAX_OUTLINE_STEP_FACTOR = 12   # a step this many times the usual spacing means a dropout
# Position samples arrive about every 0.24 s. Gaps over a second are rare
# (0.11% of intervals in 2024 Bahrain, the longest 1.3 s), so interpolating
# across them keeps a car moving instead of blinking it off the map; beyond
# two seconds the gap is long enough that a straight line would invent a path.
MAX_INTERPOLATION_GAP_S = 2.0


@dataclass
class Channel:
    """One driver's samples for one table: times plus the columns they carry."""
    t: np.ndarray
    values: dict[str, np.ndarray]

    def at(self, times: np.ndarray, interpolate: bool = True) -> dict[str, list]:
        if len(self.t) == 0:
            return {name: [None] * len(times) for name in self.values}
        idx = np.searchsorted(self.t, times, side="right") - 1
        stale = (idx < 0) | (np.abs(times - self.t[np.clip(idx, 0, len(self.t) - 1)]) > MAX_INTERPOLATION_GAP_S)
        out: dict[str, list] = {}
        for name, series in self.values.items():
            if interpolate and series.dtype.kind == "f":
                sampled = np.interp(times, self.t, series)
            else:
                sampled = series[np.clip(idx, 0, len(series) - 1)]
            out[name] = [None if bad else v for bad, v in zip(stale, sampled.tolist())]
        return out


class SessionData:
    def __init__(self, session_key: str, con=None):
        con = con or connect()
        self.session_key = session_key
        try:
            meta = con.sql(f"select * from sessions where session_key = '{session_key}'").df()
        except duckdb.CatalogException as e:
            # An empty lake has no views at all. That is a missing session, not
            # a server fault, so it must reach the caller as a 404.
            raise KeyError(f"{session_key} (empty lake at {config.LAKE_DIR})") from e
        if meta.empty:
            raise KeyError(session_key)
        self.meta = meta.iloc[0].to_dict()
        self.session_name = self.meta["session_name"]

        self.laps = con.sql(f"select * from laps where session_key = '{session_key}'").df()
        self.drivers = con.sql(f"""
            select driver_number, abbreviation, full_name, team_name, team_color,
                   grid_position, position, classified_position, status
            from results where session_key = '{session_key}' order by driver_number""").df()
        self.track_status = con.sql(
            f"select t, status, message from track_status where session_key = '{session_key}' order by t").df()
        self.race_control = con.sql(f"""
            select t, lap, category, flag, scope, message from race_control
            where session_key = '{session_key}' order by t""").df()
        self.weather = con.sql(
            f"select t, air_temp, track_temp, rainfall, wind_speed from weather where session_key = '{session_key}' order by t").df()

        self.position = self._load_channels(con, "pos_data", ["x", "y"])
        self.car = self._load_channels(con, "car_data", ["speed", "gear", "throttle", "brake", "drs"])

        self.t_start = float(np.nanmin([self.meta.get("start_t") or np.inf,
                                        self.laps["lap_start_t"].min(skipna=True)]))
        self.t_end = float(self.laps["lap_end_t"].max(skipna=True))
        self.outline = self._build_outline()
        self.bounds = self._bounds()
        log.info("loaded %s: %d laps, %d drivers, %d position samples",
                 session_key, len(self.laps), len(self.drivers),
                 sum(len(c.t) for c in self.position.values()))

    # ------------------------------------------------------------- loading

    def _load_channels(self, con, table: str, columns: list[str]) -> dict[int, Channel]:
        df = con.sql(f"""select driver_number, t, {', '.join(columns)}
                         from {table} where session_key = '{self.session_key}' order by driver_number, t""").df()
        out: dict[int, Channel] = {}
        if df.empty:
            return out
        for number, group in df.groupby("driver_number", sort=True):
            out[int(number)] = Channel(
                t=group["t"].to_numpy(dtype=float),
                values={c: group[c].to_numpy(dtype=float) for c in columns},
            )
        return out

    def _build_outline(self) -> list[list[float]]:
        """
        The track shape, from the position traces of the fastest clean laps.

        A single lap makes a poor outline: samples are spread by time, so
        straights are sparse and any dropout in that one lap becomes a chord
        cutting across a corner (2025 Monaco had a 77 m gap). Instead several
        fast laps are each resampled at even distances around the lap, which
        puts every lap on the same scale from the start line, and the median
        is taken point by point. One lap's dropout can then no longer move the
        line, and the result is evenly spaced and closes on itself.
        """
        timed = self.laps[self.laps["lap_time_s"].notna()
                          & ~self.laps["is_pit_in_lap"].fillna(False)
                          & ~self.laps["is_pit_out_lap"].fillna(False)]
        if timed.empty or not self.position:
            return []

        paths = []
        for _, lap in timed.sort_values("lap_time_s").head(OUTLINE_LAPS).iterrows():
            path = self._resample_lap(lap)
            if path is not None:
                paths.append(path)
        if not paths:
            return []

        outline = np.median(np.stack(paths), axis=0)
        outline = np.vstack([outline, outline[:1]])           # close the loop
        return [[round(float(x), 1), round(float(y), 1)] for x, y in outline]

    def _resample_lap(self, lap) -> np.ndarray | None:
        """One lap's positions at OUTLINE_POINTS even steps of distance, or None if too sparse."""
        channel = self.position.get(int(lap["driver_number"]))
        if channel is None or len(channel.t) == 0:
            return None
        mask = (channel.t >= lap["lap_start_t"]) & (channel.t <= lap["lap_end_t"])
        if mask.sum() < 100:
            return None
        x, y = channel.values["x"][mask], channel.values["y"][mask]
        finite = np.isfinite(x) & np.isfinite(y)
        x, y = x[finite], y[finite]
        if len(x) < 100:
            return None

        steps = np.hypot(np.diff(x), np.diff(y))
        distance = np.concatenate([[0.0], np.cumsum(steps)])
        if distance[-1] <= 0:
            return None
        # A gap far larger than the usual spacing means the feed dropped out;
        # that lap would only invent a straight line across the circuit.
        if steps.max() > MAX_OUTLINE_STEP_FACTOR * np.median(steps[steps > 0]):
            return None
        even = np.linspace(0, distance[-1], OUTLINE_POINTS, endpoint=False)
        return np.column_stack([np.interp(even, distance, x), np.interp(even, distance, y)])

    def _bounds(self) -> dict[str, float]:
        xs = [c.values["x"] for c in self.position.values() if len(c.t)]
        ys = [c.values["y"] for c in self.position.values() if len(c.t)]
        if not xs:
            return {}
        x, y = np.concatenate(xs), np.concatenate(ys)
        finite = np.isfinite(x) & np.isfinite(y)
        if not finite.any():
            return {}
        return {"min_x": float(np.min(x[finite])), "max_x": float(np.max(x[finite])),
                "min_y": float(np.min(y[finite])), "max_y": float(np.max(y[finite]))}

    # -------------------------------------------------------------- queries

    def info(self) -> dict:
        meta = {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in self.meta.items()}
        meta["date_utc"] = str(meta.get("date_utc")) if meta.get("date_utc") is not None else None
        meta["t0_utc"] = str(meta.get("t0_utc")) if meta.get("t0_utc") is not None else None
        meta["ingested_at"] = None
        return {
            "session": meta,
            "t_start": self.t_start,
            "t_end": self.t_end,
            "total_laps": _int_or_none(self.meta.get("total_laps")),
            "drivers": [
                {k: (None if pd.isna(v) else v) for k, v in row.items()}
                for row in self.drivers.to_dict("records")
            ],
            "outline": self.outline,
            "bounds": self.bounds,
            "has_position_data": bool(self.position),
            "track_status": _records(self.track_status),
        }

    def state(self, t: float) -> dict:
        """Everything the panels need at one instant."""
        classification = timing.classify(self.laps, self.drivers, t, self.session_name)
        times = np.array([t], dtype=float)
        cars = {}
        for driver in classification.drivers:
            number = driver.driver_number
            pos = self.position.get(number)
            car = self.car.get(number)
            point = pos.at(times) if pos else {"x": [None], "y": [None]}
            telemetry = car.at(times) if car else {}
            cars[number] = {
                "x": _round(point["x"][0], 1), "y": _round(point["y"][0], 1),
                **{name: _round(values[0], 1) for name, values in telemetry.items()},
            }
        return {
            **classification.as_dict(),
            "cars": cars,
            "track_status": self.track_status_at(t),
            "weather": self.weather_at(t),
        }

    def frames(self, start: float, end: float, hz: float = 5.0) -> dict:
        """
        Car positions over a window, for smooth playback without a request per
        frame. Returns parallel arrays: one time list, and x/y lists per driver.
        """
        count = max(1, min(int((end - start) * hz) + 1, 3000))
        times = np.linspace(start, end, count)
        drivers = {}
        for number, channel in self.position.items():
            sampled = channel.at(times)
            drivers[str(number)] = {
                "x": [_round(v, 1) for v in sampled["x"]],
                "y": [_round(v, 1) for v in sampled["y"]],
            }
        return {"t": [round(float(v), 2) for v in times], "drivers": drivers}

    def lap_chart(self) -> dict:
        """
        Race trace: each driver's gap to the lap leader at every crossing.
        This is the view where a strategy shows up as a shape.
        """
        laps = self.laps[self.laps["lap_end_t"].notna()]
        if laps.empty:
            return {"drivers": []}
        leader_by_lap = laps.groupby("lap_number")["lap_end_t"].min().sort_index()
        out = []
        for number, group in laps.groupby("driver_number"):
            group = group.sort_values("lap_number")
            gaps = group["lap_end_t"] - leader_by_lap.reindex(group["lap_number"]).to_numpy()
            meta = self.drivers[self.drivers["driver_number"] == number]
            out.append({
                "driver_number": int(number),
                "abbreviation": None if meta.empty else meta.iloc[0]["abbreviation"],
                "team_color": None if meta.empty else meta.iloc[0]["team_color"],
                "laps": [int(v) for v in group["lap_number"]],
                "gap_to_leader_s": [_round(v, 2) for v in gaps],
                "lap_time_s": [_round(v, 3) for v in group["lap_time_s"]],
                "compound": [None if pd.isna(v) else v for v in group["compound"]],
                "pit_in": [bool(v) for v in group["is_pit_in_lap"]],
            })
        # When the leader crossed the line to complete each lap, so the
        # interface can jump the clock to a lap instead of estimating it.
        return {
            "drivers": out,
            "leader_crossings": {
                "laps": [int(v) for v in leader_by_lap.index],
                "t": [_round(v, 2) for v in leader_by_lap.to_numpy()],
            },
        }

    def track_status_at(self, t: float) -> dict | None:
        if self.track_status.empty:
            return None
        past = self.track_status[self.track_status["t"] <= t]
        if past.empty:
            return None
        row = past.iloc[-1]
        return {"status": row["status"], "message": row["message"]}

    def weather_at(self, t: float) -> dict | None:
        if self.weather.empty:
            return None
        past = self.weather[self.weather["t"] <= t]
        if past.empty:
            return None
        return {k: (None if pd.isna(v) else v) for k, v in past.iloc[-1].to_dict().items()}

    def messages(self, until: float, limit: int = 30) -> list[dict]:
        past = self.race_control[self.race_control["t"] <= until].tail(limit)
        return _records(past)


# Keyed by lake as well as session: the same key names different data in a
# different lake, and handing back the wrong one would be silent and wrong.
_cache: OrderedDict[tuple[str, str], SessionData] = OrderedDict()
_lock = threading.Lock()


def load(session_key: str) -> SessionData:
    key = (str(config.LAKE_DIR.resolve()), session_key)
    with _lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    data = SessionData(session_key)          # loaded outside the lock: it takes about a second
    with _lock:
        _cache[key] = data
        _cache.move_to_end(key)
        while len(_cache) > MAX_CACHED_SESSIONS:
            _cache.popitem(last=False)
    return data


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in df.to_dict("records")]


def _round(value, digits: int):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), digits)


def _int_or_none(value):
    return None if value is None or pd.isna(value) else int(value)
