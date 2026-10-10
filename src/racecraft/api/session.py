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
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree

from racecraft import config
from racecraft.api import penalties as penalties_model
from racecraft.api import timing
from racecraft.store.db import connect, partition

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
# Width of the window used to denoise the time-to-distance mapping when
# serving positions. Half a second removes the feed's timestamp jitter while
# moving the car about a metre along its own path.
DEFAULT_SMOOTHING_S = 0.5
# Channels that hold a state, not a quantity: between two samples a car is in
# one gear or the other, never 6.5, and DRS codes are labels (8 eligible, 10+
# open), so averaging two of them invents a code. These take the last sample.
STEPPED_CHANNELS = frozenset({"gear", "drs", "brake"})

# 2026 replaced DRS with overtake mode: extra electrical deployment for a car
# within a second of the one ahead at a detection point. Race control switches
# it on and off as it did DRS. The feed never says when a driver used it, so
# eligibility is estimated from the timing interval at the last line crossing.
OVERTAKE_WINDOW_S = 1.0
OVERTAKE_ON, OVERTAKE_OFF = "OVERTAKE ENABLED", "OVERTAKE DISABLED"

# DRS flap open, in the feed's codes (8 is eligible-but-closed). Only 2023-2025
# carry it: the 2026 cars have active aero instead, and the channel is all 0.
DRS_OPEN = 10
# DRS is sampled about four times a second, a few outline points apart at speed,
# so open samples this close together along the lap are one stretch.
DRS_GAP_POINTS = 6
DRS_MIN_ZONE_POINTS = 5
DRS_MIN_OPENINGS = 3
DRS_SHARE = 0.10

# F1 publishes no position for the safety car. It is drawn where it usually is,
# a short way up the road from the leader, along the outline.
SAFETY_CAR_LEAD_M = 500.0
POSITION_UNITS_PER_M = 10.0      # FastF1's X/Y are tenths of a metre
SAFETY_CAR_STATUS = "4"


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
            if interpolate and series.dtype.kind == "f" and name not in STEPPED_CHANNELS:
                sampled = np.interp(times, self.t, series)
            else:
                sampled = series[np.clip(idx, 0, len(series) - 1)]
            out[name] = [None if bad else v for bad, v in zip(stale, sampled.tolist())]
        return out


# A session key is a partition code the lake wrote, like `2024_01_R`. Every
# query below puts it straight into SQL, so anything that is not a plain code is
# refused here rather than reaching DuckDB, which can read and write files.
_KEY = re.compile(r"[A-Za-z0-9_]+")


class SessionData:
    def __init__(self, session_key: str, con=None):
        if not _KEY.fullmatch(session_key):
            raise KeyError(session_key)
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
        # Corner numbers and where they fall along the lap, for the traces.
        try:
            self.markers = con.sql(f"""select kind, number, letter, distance from circuit_markers
                                       where session_key = '{session_key}'""").df()
        except duckdb.Error:
            self.markers = pd.DataFrame(columns=["kind", "number", "letter", "distance"])
        self._assemble()
        log.info("loaded %s: %d laps, %d drivers, %d position samples",
                 session_key, len(self.laps), len(self.drivers),
                 sum(len(c.t) for c in self.position.values()))

    @classmethod
    def from_tables(cls, tables: dict[str, pd.DataFrame], session_key: str = "live") -> "SessionData":
        """
        The same object, built from tables already in memory rather than the lake.

        This is what live mode needs, and the reason it is cheap: a recording
        parses into exactly the tables the lake stores, so once they are here
        nothing downstream can tell a live session from a historic one.

        Three things are thinner than the lake and have to be tolerated rather
        than assumed away. A session in progress has no classification, so the
        driver list is taken from the laps when `results` is missing. It has no
        car telemetry or positions here by choice, so the track map is absent
        rather than wrong. And in the opening minutes it has no completed laps
        at all, which is a session that has not started, not a broken one.
        """
        self = cls.__new__(cls)
        self.session_key = session_key

        sessions = tables.get("sessions")
        if sessions is None or sessions.empty:
            raise KeyError(f"{session_key}: the recording carries no session yet")
        self.meta = sessions.iloc[0].to_dict()
        self.session_name = self.meta.get("session_name") or "Live"

        self.laps = tables.get("laps", _empty(_LAP_COLUMNS)).copy()
        self.drivers = _drivers_from(tables)
        self.track_status = _ordered(tables.get("track_status"), ["t", "status", "message"])
        self.race_control = _ordered(tables.get("race_control"),
                                     ["t", "lap", "category", "flag", "scope", "message"])
        self.weather = _ordered(tables.get("weather"),
                                ["t", "air_temp", "track_temp", "rainfall", "wind_speed"])
        self.position = {}
        self.car = {}
        self.markers = tables.get("circuit_markers", pd.DataFrame(columns=["kind", "number", "letter", "distance"]))
        self._assemble()
        return self

    def _assemble(self) -> None:
        """Everything derived from the tables, however they arrived."""
        starts = self.laps["lap_start_t"] if "lap_start_t" in self.laps else pd.Series(dtype=float)
        ends = self.laps["lap_end_t"] if "lap_end_t" in self.laps else pd.Series(dtype=float)
        first = starts.min(skipna=True) if len(starts) else np.nan
        last = ends.max(skipna=True) if len(ends) else np.nan

        declared = self.meta.get("start_t")
        candidates = [v for v in (declared, first) if v is not None and np.isfinite(v)]
        self.t_start = float(min(candidates)) if candidates else 0.0
        # A session with no completed laps has no end yet. One second of range
        # keeps the clock and every axis built on it from dividing by zero.
        self.t_end = float(last) if np.isfinite(last) else self.t_start + 1.0

        self.outline = self._build_outline()
        self.bounds = self._bounds()
        self.drs_zones = self._build_drs_zones()
        self.overtake_changes = _overtake_changes(self.race_control)

    # ------------------------------------------------------------- loading

    def _load_channels(self, con, table: str, columns: list[str]) -> dict[int, Channel]:
        # The partition columns in the filter let DuckDB open only this session's
        # file. Without them it opens all 420 to check each one, and repeated
        # many-file scans crash DuckDB outright; see `store/db.py`.
        #
        # Read straight into arrays, not through a DataFrame: a race is some
        # 800,000 samples, and the frame and its per-driver copies cost several
        # times the arrays kept. Each column is then held at the size it needs
        # (`_compact`), and each driver's channel is a view of it.
        arrays = con.sql(f"""select driver_number, t, {', '.join(columns)}
                             from {table} where session_key = '{self.session_key}'{partition(self.session_key)}
                             order by driver_number, t""").fetchnumpy()
        numbers = np.ma.filled(arrays["driver_number"], -1)
        if len(numbers) == 0:
            return {}
        times = np.ma.filled(arrays["t"], np.nan).astype(np.float64, copy=False)
        values = {c: _compact(c, arrays[c]) for c in columns}
        del arrays
        if "x" in values and "y" in values:
            # (0, 0) is the feed's "no position", not a place: a car in the
            # garage, before it goes out, or while its transponder drops out,
            # and still marked OnTrack. Kept, it puts the car at the origin
            # and draws a line to it across the circuit; dropped, the car has
            # no position there, and is not drawn.
            real = ~((values["x"] == 0) & (values["y"] == 0))
            if not real.all():
                numbers, times = numbers[real], times[real]
                values = {c: v[real] for c, v in values.items()}
                if len(numbers) == 0:
                    return {}
        edges = np.concatenate([[0], np.flatnonzero(np.diff(numbers)) + 1, [len(numbers)]])
        out: dict[int, Channel] = {}
        for first, last in zip(edges[:-1], edges[1:]):
            out[int(numbers[first])] = Channel(t=times[first:last],
                                               values={c: v[first:last] for c, v in values.items()})
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
            "drs_zones": self.drs_zones,
            "has_overtake": self.overtake_changes is not None,
        }

    def state(self, t: float) -> dict:
        """Everything the panels need at one instant."""
        classification = timing.classify(self.laps, self.drivers, t, self.session_name)
        # Race control read up to the same t as the running order, so the PEN
        # column and the gap beside it can never describe different moments.
        penalties = penalties_model.state_at(self.race_control, self.drivers, t)
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
        state = classification.as_dict()
        overtake = self.overtake_enabled_at(t)
        for row in state["drivers"]:
            against = penalties.get(int(row["driver_number"]))
            row["penalties"] = None if against is None else against.as_dict()
            row["overtake"] = None if overtake is None else overtake_status(row, overtake)
        track_status = self.track_status_at(t)
        leader = next((d.driver_number for d in classification.drivers if d.status == "racing"), None)
        return {
            **state,
            "cars": cars,
            "track_status": track_status,
            "weather": self.weather_at(t),
            "overtake": None if overtake is None else {"enabled": overtake},
            "safety_car": self.safety_car_at(cars.get(leader)) if (
                track_status and track_status["status"] == SAFETY_CAR_STATUS) else None,
        }

    def _nearest_outline_index(self, xy: np.ndarray) -> np.ndarray:
        """For each (x, y), the index of the closest outline point (the closing duplicate left out)."""
        tree = getattr(self, "_outline_tree", None)
        if tree is None:
            # Built once: a race maps tens of thousands of DRS samples, and
            # comparing each with all 600 points was most of a second.
            tree = self._outline_tree = cKDTree(np.asarray(self.outline[:-1], dtype=float))
        _, nearest = tree.query(xy)
        return np.asarray(nearest, dtype=int)

    def safety_car_at(self, leader_car: dict | None) -> dict | None:
        """
        Where to draw the safety car: SAFETY_CAR_LEAD_M up the road from the
        leader, along the outline (which runs in the direction of travel from
        the start line). Simulated — F1 publishes no position for it — and
        None when the leader's own position is not known.
        """
        if len(self.outline) < 3 or not leader_car:
            return None
        x, y = leader_car.get("x"), leader_car.get("y")
        if x is None or y is None:
            return None
        points = np.asarray(self.outline[:-1], dtype=float)
        perimeter = float(np.hypot(*np.diff(np.asarray(self.outline, dtype=float), axis=0).T).sum())
        if perimeter <= 0:
            return None
        step = perimeter / len(points)
        ahead = int(round(SAFETY_CAR_LEAD_M * POSITION_UNITS_PER_M / step))
        here = int(self._nearest_outline_index(np.array([[x, y]], dtype=float))[0])
        px, py = points[(here + ahead) % len(points)]
        return {"x": round(float(px), 1), "y": round(float(py), 1), "simulated": True}

    def _build_drs_zones(self) -> list[list[int]]:
        """
        Where DRS opens, as [first, last] outline indices (wrapping past the line
        when first > last). Empty for 2026, whose cars have no DRS, and for live.

        The flap can only open inside a zone, so every opening by every car in
        the session is evidence of one. Using only the fastest laps lost zones:
        in a race DRS needs the car ahead within a second, and the fastest laps
        are mostly set in clean air, so Bahrain came out with one zone of three.
        A point counts when enough openings covered it (DRS_MIN_OPENINGS, and
        DRS_SHARE of the busiest point), which keeps a stray sample mapped to
        the wrong part of the circuit from drawing a zone of its own.
        """
        if len(self.outline) < 3 or not self.car or not self.position:
            return []
        n = len(self.outline) - 1
        counts = np.zeros(n, dtype=int)
        for number, car in self.car.items():
            pos = self.position.get(number)
            if pos is None or "drs" not in car.values:
                continue
            open_t = car.t[car.values["drs"] >= DRS_OPEN]
            if len(open_t) == 0:
                continue
            at = pos.at(open_t)
            known = [i for i, (px, py) in enumerate(zip(at["x"], at["y"])) if px is not None and py is not None]
            if not known:
                continue
            times = open_t[known]
            xy = np.array([[at["x"][i], at["y"][i]] for i in known], dtype=float)
            indices = self._nearest_outline_index(xy)
            # One opening is a run of samples less than a second apart; its
            # samples sit a few outline points apart and are joined into a span.
            for run in np.split(np.arange(len(indices)), np.flatnonzero(np.diff(times) > 1.0) + 1):
                points = indices[run]
                span = np.zeros(n, dtype=bool)
                span[points] = True
                for a, b in zip(points[:-1], points[1:]):
                    gap = (b - a) % n
                    if 0 < gap <= DRS_GAP_POINTS:
                        span[(a + np.arange(gap + 1)) % n] = True
                counts += span
        if counts.max() == 0:
            return []
        is_open = counts >= max(DRS_MIN_OPENINGS, DRS_SHARE * counts.max())
        if is_open.all():
            return [[0, n - 1]]
        # Runs of open points around the loop, starting just after a closed one.
        first_closed = int(np.argmin(is_open))
        zones, start = [], None
        for k in range(1, n + 1):
            i = (first_closed + k) % n
            if is_open[i] and start is None:
                start = i
            elif not is_open[i] and start is not None:
                last = (i - 1) % n
                if (last - start) % n + 1 >= DRS_MIN_ZONE_POINTS:
                    zones.append([int(start), int(last)])
                start = None
        return zones

    def frames(self, start: float, end: float, hz: float = 5.0,
               smooth_s: float = DEFAULT_SMOOTHING_S) -> dict:
        """
        Car positions over a window, for smooth playback without a request per
        frame. Returns parallel arrays: one time list, and x/y lists per driver.

        The feed's timestamps jitter - intervals of 0.08 to 0.50 s where the
        cadence is 0.24 s - while the positions themselves are smooth. Sampling
        an even grid straight off those timestamps therefore makes a car leap:
        4.9% of intervals imply over 340 km/h when the cars themselves never
        exceed 331. `smooth_s` denoises the mapping from time to distance
        along the path, which fixes the motion without moving the car off the
        line it actually drove: at 0.5 s the overshoot falls to 0.02% and the
        path shifts by about 1.3 m, which is invisible on a circuit 5 km round.
        Pass 0 to get the raw feed.
        """
        count = max(1, min(int((end - start) * hz) + 1, 3000))
        times = np.linspace(start, end, count)
        drivers = {}
        for number, channel in self.position.items():
            if smooth_s > 0:
                x, y = _smooth_positions(channel, times, smooth_s)
            else:
                sampled = channel.at(times)
                x, y = sampled["x"], sampled["y"]
            drivers[str(number)] = {"x": [_round(v, 1) for v in x], "y": [_round(v, 1) for v in y]}
        return {"t": [round(float(v), 2) for v in times], "drivers": drivers}

    def lap_chart(self) -> dict:
        """
        The whole race, lap by lap: position and gap to the leader.

        Position comes from the timing feed's own classification rather than
        from ranking the crossing times, because ranking by time puts a lapped
        car ahead of the leader it is a lap behind. It is missing on 0.13% of
        race laps, and a chart drawing it should break its line there rather
        than join across the hole.
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
                "position": [None if pd.isna(v) else int(v) for v in group["position"]],
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

    def overtake_enabled_at(self, t: float) -> bool | None:
        """Whether race control had overtake mode on at `t`; None for a session without it."""
        if self.overtake_changes is None:
            return None
        past = self.overtake_changes[self.overtake_changes["t"] <= t]
        return bool(past["enabled"].iloc[-1]) if not past.empty else False

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

    def messages(self, until: float, limit: int = 30,
                 topic: str | None = None) -> list[dict]:
        """
        Race control up to `until`, newest first, with each message read.

        `topic` picks one of `stewards`, `track` or `noise`; None gives all
        three. The raw columns are kept alongside so nothing is lost to the parse.
        """
        return penalties_model.feed(self.race_control, self.drivers, until, limit, topic)


_LAP_COLUMNS = ["driver_number", "driver", "lap_number", "lap_start_t", "lap_end_t"]


def _overtake_changes(race_control: pd.DataFrame) -> pd.DataFrame | None:
    """Every switch of overtake mode, in time order; None when race control never mentions it."""
    if race_control is None or race_control.empty or "message" not in race_control:
        return None
    message = race_control["message"].astype(str).str.strip().str.upper()
    switches = race_control.loc[message.isin([OVERTAKE_ON, OVERTAKE_OFF]), ["t"]].copy()
    if switches.empty:
        return None
    switches["enabled"] = message[switches.index] == OVERTAKE_ON
    return switches.sort_values("t", kind="stable").reset_index(drop=True)


def overtake_status(row: dict, enabled: bool) -> str:
    """
    'disabled' while race control has it off; 'eligible' for a running car
    within a second of the car ahead at the last line crossing; otherwise
    'not_eligible'. An estimate: the real detection points are around the lap.
    """
    if not enabled:
        return "disabled"
    interval = row.get("interval_s")
    if row.get("status") == "racing" and interval is not None and 0 <= interval < OVERTAKE_WINDOW_S:
        return "eligible"
    return "not_eligible"


def _empty(columns: list[str]) -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})


def _ordered(frame: pd.DataFrame | None, columns: list[str]) -> pd.DataFrame:
    """The columns this class reads, in time order, whatever the source carried."""
    if frame is None or frame.empty:
        return _empty(columns)
    present = [c for c in columns if c in frame.columns]
    out = frame[present].copy()
    for missing in (c for c in columns if c not in present):
        out[missing] = None
    return out.sort_values("t") if "t" in out else out


def _drivers_from(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    The driver list, from the classification if there is one and the laps if not.

    A session in progress has no result, so falling back to the laps is what
    lets the tower fill in before anyone has finished anything.
    """
    columns = ["driver_number", "abbreviation", "full_name", "team_name", "team_color",
               "grid_position", "position", "classified_position", "status"]
    results = tables.get("results")
    if results is not None and not results.empty:
        return _ordered(results, columns).sort_values("driver_number")

    laps = tables.get("laps")
    if laps is None or laps.empty:
        return _empty(columns)
    seen = laps.groupby("driver_number").agg(
        abbreviation=("driver", "last"), team_name=("team", "last")).reset_index()
    seen["full_name"] = seen["abbreviation"]
    for blank in ("team_color", "grid_position", "position", "classified_position", "status"):
        seen[blank] = None
    return seen[columns].sort_values("driver_number")


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


def _smooth_positions(channel: "Channel", times: np.ndarray, bandwidth: float) -> tuple[list, list]:
    """
    Positions at `times`, taken along the car's own path at a steadied speed.

    Distance travelled is fitted against time with a local straight line, which
    is a fair description over half a second and shrugs off a mistimed sample.
    The positions themselves are never altered: only where along the path the
    car is judged to be at each instant.
    """
    t, x, y = channel.t, channel.values["x"], channel.values["y"]
    if len(t) < 4:
        sampled = channel.at(times)
        return sampled["x"], sampled["y"]

    distance = np.concatenate([[0.0], np.cumsum(np.hypot(np.diff(x), np.diff(y)))])
    reach = 3 * bandwidth

    # Every output time gets the same-sized neighbourhood of samples, so the
    # fits run as one array operation rather than a loop over hundreds of
    # points: samples arrive at a steady 0.24 s, so a fixed width covers the
    # window, and anything outside it is masked out by weight.
    half = max(2, int(np.ceil(reach / max(1e-6, float(np.median(np.diff(t)))))))
    centre = np.searchsorted(t, times)
    offsets = np.arange(-half, half + 1)
    index = np.clip(centre[:, None] + offsets[None, :], 0, len(t) - 1)

    tw, dw = t[index], distance[index]
    weights = np.exp(-0.5 * ((tw - times[:, None]) / bandwidth) ** 2)
    weights[np.abs(tw - times[:, None]) > reach] = 0.0
    total = weights.sum(axis=1)
    usable = total > 1e-9
    weights[~usable] = 1.0
    total[~usable] = weights.shape[1]

    t_mean = (weights * tw).sum(axis=1) / total
    d_mean = (weights * dw).sum(axis=1) / total
    dt = tw - t_mean[:, None]
    variance = (weights * dt * dt).sum(axis=1) / total
    covariance = (weights * dt * (dw - d_mean[:, None])).sum(axis=1) / total
    slope = np.divide(covariance, variance, out=np.zeros_like(covariance), where=variance > 1e-12)
    at = d_mean + slope * (times - t_mean)
    at = np.where(usable, at, np.interp(times, t, distance))
    at = np.maximum.accumulate(at)          # a car only ever goes forward

    # Outside the samples there is nothing to stand on, so say so; nor inside a
    # gap longer than the feed ever leaves while a car is running (the garage,
    # a dropout), where it would otherwise slide across the circuit.
    after = np.clip(np.searchsorted(t, times, side="left"), 0, len(t) - 1)
    before = np.clip(after - 1, 0, len(t) - 1)
    in_gap = (t[after] - t[before] > MAX_INTERPOLATION_GAP_S) & (times > t[before]) & (times < t[after])
    stale = (times < t[0] - MAX_INTERPOLATION_GAP_S) | (times > t[-1] + MAX_INTERPOLATION_GAP_S) | in_gap
    xs = np.interp(at, distance, x)
    ys = np.interp(at, distance, y)
    return ([None if bad else v for bad, v in zip(stale, xs)],
            [None if bad else v for bad, v in zip(stale, ys)])


def _records(df: pd.DataFrame) -> list[dict]:
    return [{k: (None if pd.isna(v) else v) for k, v in row.items()} for row in df.to_dict("records")]


# Telemetry kept at the size it needs: speed, throttle and position to a
# hundredth or better in 32 bits; gear, brake and DRS are small whole numbers,
# one byte each. Time stays 64-bit: session seconds need the precision.
_FLOAT32 = {"speed", "throttle", "rpm", "x", "y", "z"}
_SMALL_INT = {"gear", "brake", "drs"}


def _compact(name: str, column) -> np.ndarray:
    """One telemetry column at the smallest dtype that holds it exactly enough."""
    masked = np.ma.isMaskedArray(column) and bool(np.ma.getmaskarray(column).any())
    if name in _SMALL_INT and not masked:
        data = np.asarray(column)
        if data.dtype == bool:
            return data.astype(np.uint8)
        if data.size and np.isfinite(data).all() and data.min() >= 0 and data.max() <= 255 and (data == np.round(data)).all():
            return data.astype(np.uint8)
    if name in _FLOAT32 or name in _SMALL_INT:
        return np.ma.filled(np.ma.asarray(column, dtype=np.float32), np.nan)
    return np.ma.filled(np.ma.asarray(column, dtype=np.float64), np.nan)


def _round(value, digits: int):
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    return round(float(value), digits)


def _int_or_none(value):
    return None if value is None or pd.isna(value) else int(value)
