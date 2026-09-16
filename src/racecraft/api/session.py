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

import numpy as np
import pandas as pd

from racecraft.api import timing
from racecraft.store.db import connect

log = logging.getLogger(__name__)

MAX_CACHED_SESSIONS = 2
OUTLINE_POINTS = 400
# Position samples arrive about every 0.24 s. Beyond a second, the car has
# moved far enough that interpolating across the gap would invent a path.
MAX_INTERPOLATION_GAP_S = 1.0


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
        meta = con.sql(f"select * from sessions where session_key = '{session_key}'").df()
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
        """The track shape, taken from the position trace of the fastest lap."""
        timed = self.laps[self.laps["lap_time_s"].notna()]
        if timed.empty or not self.position:
            return []
        for _, lap in timed.sort_values("lap_time_s").head(5).iterrows():
            channel = self.position.get(int(lap["driver_number"]))
            if channel is None or len(channel.t) == 0:
                continue
            start, end = lap["lap_start_t"], lap["lap_end_t"]
            mask = (channel.t >= start) & (channel.t <= end)
            if mask.sum() < 50:
                continue
            x, y = channel.values["x"][mask], channel.values["y"][mask]
            step = max(1, len(x) // OUTLINE_POINTS)
            return [[round(float(a), 1), round(float(b), 1)] for a, b in zip(x[::step], y[::step])]
        return []

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


_cache: OrderedDict[str, SessionData] = OrderedDict()
_lock = threading.Lock()


def load(session_key: str) -> SessionData:
    with _lock:
        if session_key in _cache:
            _cache.move_to_end(session_key)
            return _cache[session_key]
    data = SessionData(session_key)          # loaded outside the lock: it takes about a second
    with _lock:
        _cache[session_key] = data
        _cache.move_to_end(session_key)
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
