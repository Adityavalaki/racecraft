"""
Sessions from OpenF1 (openf1.org), for when F1's archive will not serve them.

Since about 15 October 2026 F1's timing archive wants an F1 TV login (BUG-004, D-009).
OpenF1's free tier still serves every session since 2023 without one: laps, tyre stints,
pit stops, positions, race control, weather, results, car telemetry and positions. This
module turns one session from it into the tables `fastf1_source.extract` builds, so nothing
downstream can tell which source a session came from (`sessions.fastf1_version` says
"openf1", for whoever needs to know).

Time: the lake's `t` is seconds from the session's t0. Here t0 is an hour before the
scheduled start (`date_start`), close to where FastF1 puts it, so pre-session race control
and weather are kept and every `t` is positive. `start_t` is race control's "SESSION
STARTED". Samples before t0 or more than an hour after the end are dropped: OpenF1 carries
strays (one dated 11 October inside the 23 October 2026 Austin FP1).

What OpenF1 does not have, taken elsewhere:
* the event's name, location and country: FastF1's schedule, which still loads freely;
* corner positions and the circuit's rotation: the latest session at the same circuit;
* track status: rebuilt from race control's flags and safety car messages;
* the grid: OpenF1 files it under the qualifying session that set it.

Where OpenF1 differs from FastF1, it is made to match (checked on Singapore 2026 with
`scripts/compare_openf1.py`; every rule and what still differs: D-010). The main ones:
* a car starting from the pit lane gets a one-lap first stint and loses its real stop, so
  stints are re-cut at the pit stops when there is one fewer stop than stints;
* a pit stop's `date` is the exit; an out-lap from the garage is timed from the line;
* `is_accurate` copies FastF1's rule, less its timing-continuity check (OpenF1's lap starts
  are not that precise); a race's first lap, from a standing start, is never accurate.

Free tier: 30 requests a minute, so requests are spaced 2.1 s apart (a race with telemetry
took 209 s). Licence: personal, non-commercial use.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone

import fastf1
import numpy as np
import pandas as pd
import requests

from racecraft.ingest.fastf1_source import _frame
from racecraft.store.db import connect, has_table
from racecraft.store.schema import TABLES

log = logging.getLogger(__name__)
TABLE_COLUMNS = {name: schema.names for name, schema in TABLES.items()}

BASE = "https://api.openf1.org/v1"
SPACING_S = 2.1                      # 30 requests a minute on the free tier
MATCH_WITHIN = pd.Timedelta(hours=2)
BEFORE_START = pd.Timedelta(hours=1)          # t0, and the earliest sample kept
KEEP_AFTER = pd.Timedelta(hours=1)
SOURCE = "openf1"

_last_request = 0.0


class NotAvailable(LookupError):
    """OpenF1 has no such session, or would not serve it: the message says which."""


def _get(endpoint: str, **params) -> list[dict]:
    """One OpenF1 endpoint, spaced to the free tier's rate and retried when it says slow down."""
    global _last_request
    for attempt in range(4):
        wait = _last_request + SPACING_S - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request = time.monotonic()
        response = requests.get(f"{BASE}/{endpoint}", params=params, timeout=60)
        if response.status_code == 429:
            time.sleep(10 * (attempt + 1))
            continue
        if response.status_code == 404:           # OpenF1's answer for "no rows"
            return []
        response.raise_for_status()
        body = response.json()
        return body if isinstance(body, list) else []
    raise NotAvailable(f"OpenF1 kept refusing {endpoint}: too many requests")


def find_session(year: int, starts: pd.Timestamp) -> dict:
    """The OpenF1 session that starts closest to `starts` (UTC), within two hours."""
    sessions = _get("sessions", year=year)
    if not sessions:
        raise NotAvailable(f"OpenF1 lists no sessions for {year}")
    best = min(sessions, key=lambda s: abs(pd.Timestamp(s["date_start"]) - starts))
    if abs(pd.Timestamp(best["date_start"]) - starts) > MATCH_WITHIN:
        raise NotAvailable(f"OpenF1 has no session starting near {starts:%Y-%m-%d %H:%M} UTC")
    return best


def extract(season: int, rnd: int, ident: str, session_name: str, key: str,
            telemetry: bool = True) -> dict[str, pd.DataFrame]:
    """All lake tables for one session, from OpenF1."""
    schedule = fastf1.get_session(season, rnd, session_name)       # schedule only: no download
    starts = pd.Timestamp(schedule.date).tz_localize("UTC")
    session = find_session(season, starts)
    sk = session["session_key"]
    t0 = pd.Timestamp(session["date_start"]) - BEFORE_START
    window = (t0, pd.Timestamp(session["date_end"]) + KEEP_AFTER)
    race = ident in ("R", "S")

    drivers = pd.DataFrame(_get("drivers", session_key=sk))
    if drivers.empty:
        raise NotAvailable(f"OpenF1 has no drivers for {key} yet")
    drivers = drivers.drop_duplicates("driver_number", keep="last").set_index("driver_number")
    rc = _timed(pd.DataFrame(_get("race_control", session_key=sk)), t0, window)
    status = track_status(rc, key)
    started = rc.loc[rc.get("message", pd.Series(dtype=object)).astype(str).str.upper() == "SESSION STARTED", "t"]
    tables = {
        "sessions": _sessions(schedule, key, t0, started.min() if len(started) else BEFORE_START.total_seconds()),
        "results": _results(_get("session_result", session_key=sk), _grid(session) if race else [],
                            drivers, key, ident),
        "laps": _laps(_get("laps", session_key=sk), _get("stints", session_key=sk), _get("pit", session_key=sk),
                      _get("position", session_key=sk), rc, status, drivers, t0, key, race),
        "weather": _weather(_timed(pd.DataFrame(_get("weather", session_key=sk)), t0, window), key),
        "race_control": _race_control(rc, key),
        "track_status": status,
        "session_status": _frame({n: [] for n in TABLE_COLUMNS["session_status"]}, "session_status"),
    }
    markers, rotation = _circuit(schedule.event["Location"], key)
    tables["circuit_markers"] = markers
    tables["sessions"]["circuit_rotation_deg"] = rotation
    if race and not tables["results"].empty:
        tables["sessions"]["total_laps"] = tables["results"]["laps"].max()
    if telemetry:
        car, pos = [], []
        for number in drivers.index:
            car.append(_car(_timed(pd.DataFrame(_get("car_data", session_key=sk, driver_number=number)),
                                   t0, window), key))
            pos.append(_pos(_timed(pd.DataFrame(_get("location", session_key=sk, driver_number=number)),
                                   t0, window), key))
        tables["car_data"] = pd.concat(car, ignore_index=True)
        tables["pos_data"] = pd.concat(pos, ignore_index=True)
    return tables


# ---------------------------------------------------------------- shaping

def _timed(df: pd.DataFrame, t0: pd.Timestamp, window: tuple) -> pd.DataFrame:
    """Rows inside the session's window, with `t` in seconds from t0."""
    if df.empty or "date" not in df:
        return df.assign(t=pd.Series(dtype=float))
    when = pd.to_datetime(df["date"], utc=True, format="ISO8601")
    keep = (when >= window[0]) & (when <= window[1])
    df = df[keep].copy()
    df["t"] = (when[keep] - t0).dt.total_seconds()
    return df.sort_values("t", kind="stable").reset_index(drop=True)


def _grid(session: dict) -> list[dict]:
    """A race's grid: OpenF1 files it under the last qualifying session before the race."""
    earlier = [s for s in _get("sessions", meeting_key=session["meeting_key"])
               if s.get("session_type") == "Qualifying" and s["date_start"] < session["date_start"]]
    if not earlier:
        return []
    return _get("starting_grid", session_key=max(earlier, key=lambda s: s["date_start"])["session_key"])


def _sessions(schedule, key: str, t0: pd.Timestamp, start_t: float) -> pd.DataFrame:
    event = schedule.event
    return _frame({
        "session_key": [key], "event_name": [str(event["EventName"])], "country": [str(event["Country"])],
        "location": [str(event["Location"])], "session_name": [str(schedule.name)],
        "date_utc": [t0], "t0_utc": [t0], "start_t": [float(start_t)], "total_laps": [None],
        "circuit_rotation_deg": [0.0], "fastf1_version": [SOURCE],
        "ingested_at": [pd.Timestamp(datetime.now(timezone.utc))],
    }, "sessions")


def _classification(r: dict) -> tuple[str | None, str | None]:
    """A race result's classified position and status, as FastF1 writes them."""
    place = r.get("position")
    if r.get("dsq"):
        return "D", "Disqualified"
    if r.get("dns"):
        return "W", "Did not start"
    if r.get("dnf"):                           # retired, but classified if it ran 90% of the race
        return (str(int(place)) if place is not None else "R"), "Retired"
    if place is None:
        return None, None
    return str(int(place)), "Lapped" if "LAP" in str(r.get("gap_to_leader")).upper() else "Finished"


def _results(rows: list[dict], grid: list[dict], drivers: pd.DataFrame, key: str, ident: str) -> pd.DataFrame:
    """One row per driver: classification from session_result, names and colours from drivers.

    As FastF1 does: classification, status, laps and time (the winner's total, everyone else's
    gap) only for a race or sprint; no places in practice; and cars without a place (OpenF1
    writes "RT") numbered after the rest, most laps first.
    """
    race, practice = ident in ("R", "S"), ident.startswith("FP")
    res = rows or [{"driver_number": n} for n in drivers.index]
    starts = {g["driver_number"]: g.get("position") for g in grid}
    out = []
    for r in res:
        n = int(r["driver_number"])
        d = drivers.loc[n] if n in drivers.index else pd.Series(dtype=object)
        duration = r.get("duration")
        # Qualifying gives one time per part (Q1, Q2, Q3), a race one total time.
        parts = (list(duration) + [None] * 3)[:3] if isinstance(duration, list) else [None] * 3
        place = r.get("position") if isinstance(r.get("position"), (int, float)) else None
        r = {**r, "position": place}
        code, status = _classification(r) if race else (None, None)
        gap = r.get("gap_to_leader")
        out.append({
            "session_key": key, "driver_number": n, "abbreviation": d.get("name_acronym"),
            "full_name": d.get("full_name"), "team_name": d.get("team_name"), "team_id": None,
            "team_color": d.get("team_colour"), "grid_position": starts.get(n),
            "position": None if practice else place, "classified_position": code, "status": status,
            "points": r.get("points"), "laps": r.get("number_of_laps") if race else None,
            "result_time_s": None if not race else duration if place == 1 else
            gap if isinstance(gap, (int, float)) else None,
            "q1_s": parts[0], "q2_s": parts[1], "q3_s": parts[2],
        })
    out = pd.DataFrame(out)
    unplaced = out["position"].isna()
    if unplaced.any() and not practice:
        order = out.loc[unplaced, "laps"].astype(float).fillna(0).rank(ascending=False, method="first")
        out.loc[unplaced, "position"] = out["position"].max(skipna=True) if (~unplaced).any() else 0
        out.loc[unplaced, "position"] += order
    return _frame(out, "results")


def _stints(stints: list[dict], pits: list[dict], laps: pd.DataFrame) -> pd.DataFrame:
    """Each car's stints, re-cut at its pit stops when OpenF1 puts the boundaries elsewhere.

    A car starting from the pit lane gets a one-lap first stint and its real stop is lost
    (Singapore 2026: HAD on mediums for laps 1-33, OpenF1 says lap 1 only). With one fewer
    stop than stints, stint k ends on stop k's lap. The last stint runs to the car's last lap.
    """
    out = []
    for n, mine in pd.DataFrame(stints).groupby("driver_number") if stints else []:
        mine = mine.sort_values("stint_number").reset_index(drop=True)
        stops = sorted(p["lap_number"] for p in pits if p["driver_number"] == n)
        # FastF1 counts a pit-lane start as a pit exit; OpenF1 shows one as a lap-1 stint end.
        mine["pit_lane_start"] = (mine.index == 0) & (mine["lap_end"] == 1) & (1 not in stops)
        if len(stops) == len(mine) - 1 and stops != list(mine["lap_end"][:-1]):
            mine["lap_end"] = stops + [mine["lap_end"].iloc[-1]]
            mine["lap_start"] = [1] + [s + 1 for s in stops]
        last = laps.loc[laps["driver_number"] == n, "lap_number"].max()
        mine.loc[mine.index[-1], "lap_end"] = max(mine["lap_end"].iloc[-1], last if pd.notna(last) else 0)
        out.append(mine)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _laps(rows, stints, pits, positions, rc, status, drivers, t0, key, race) -> pd.DataFrame:
    laps = pd.DataFrame(rows)
    if laps.empty:
        return _frame({n: [] for n in TABLE_COLUMNS["laps"]}, "laps")
    laps = laps.sort_values(["driver_number", "lap_number"]).reset_index(drop=True)
    laps["is_pit_out_lap"] = laps["is_pit_out_lap"].fillna(False).astype(bool)
    start = pd.to_datetime(laps["date_start"], utc=True, format="ISO8601")
    raw_start = (start - t0).dt.total_seconds()
    duration = pd.to_numeric(laps["lap_duration"], errors="coerce")
    # Out of the garage, OpenF1 starts the lap when the car leaves it but times it from the
    # line, as FastF1 does: such a lap starts where the last one ended, and has no lap time.
    # Some out-laps start right but count the garage stay in their duration: they end where
    # the next lap starts, and have no lap time either.
    prev_end = (raw_start + duration).groupby(laps["driver_number"]).shift()
    garage = laps["is_pit_out_lap"] & (raw_start > prev_end + 1)
    laps["lap_start_t"] = raw_start.where(~garage, prev_end)
    following = laps.groupby("driver_number")["lap_start_t"].shift(-1)
    overrun = laps["lap_start_t"] + duration > following + 1
    laps["lap_time_s"] = duration.where(~garage & ~overrun)
    laps["lap_end_t"] = (laps["lap_start_t"] + duration).where(~overrun, following).fillna(following)

    # Pit stops: OpenF1's `date` is when the car left the pit lane (or garage), so the lap it
    # was then on is the out-lap, the one before it the in-lap, and it went in `pit_duration`
    # earlier (FastF1's entry and exit times, to 0.25 s, on Singapore 2026). A stop without a
    # duration is a car leaving the garage at the start of a session: an out-lap only.
    laps["pit_in_t"], laps["pit_out_t"], laps["is_pit_in_lap"] = np.nan, np.nan, False
    stops = []
    for p in pits:
        left = (pd.Timestamp(p["date"]) - t0).total_seconds()
        on = laps.index[(laps["driver_number"] == p["driver_number"]) & (raw_start <= left + 0.5)]
        if len(on) == 0:
            continue
        laps.loc[on[-1], ["pit_out_t", "is_pit_out_lap"]] = [left, True]
        if p.get("pit_duration") is not None and len(on) > 1:
            laps.loc[on[-2], ["pit_in_t", "is_pit_in_lap"]] = [left - float(p["pit_duration"]), True]
            stops.append({"driver_number": p["driver_number"], "lap_number": laps.at[on[-2], "lap_number"]})
    if not race:                        # back to the garage after the flag, as FastF1 has it
        laps.loc[laps.groupby("driver_number")["lap_number"].idxmax(), "is_pit_in_lap"] = True

    # Tyres: each stint covers laps lap_start..lap_end on one set, which may have run before.
    laps["stint"], laps["tyre_life"], laps["laps_in_stint"] = np.nan, np.nan, np.nan
    laps["compound"], laps["fresh_tyre"] = None, False
    for s in _stints(stints, stops, laps).to_dict("records"):
        mine = (laps["driver_number"] == s["driver_number"]) & \
            laps["lap_number"].between(s["lap_start"], s["lap_end"])
        into = laps.loc[mine, "lap_number"] - s["lap_start"] + 1
        age = s.get("tyre_age_at_start") or 0
        laps.loc[mine, "stint"] = s["stint_number"]
        laps.loc[mine, "compound"] = str(s.get("compound") or "").upper() or None
        laps.loc[mine, "laps_in_stint"] = into
        laps.loc[mine, "tyre_life"] = into + age
        laps.loc[mine, "fresh_tyre"] = age == 0
        if s["pit_lane_start"]:
            laps.loc[mine & (laps["lap_number"] == 1), "is_pit_out_lap"] = True

    laps["track_status"] = [_statuses_between(status, a, b) for a, b in zip(laps["lap_start_t"], laps["lap_end_t"])]
    standing_start = race & (laps["lap_number"] == 1)
    deleted = _deleted_laps(rc, laps, race)
    which = list(zip(laps["driver_number"].astype(int), laps["lap_number"].astype(int)))
    laps["deleted"] = [w in deleted for w in which]
    # A personal best beats every earlier counted lap; equalling one is not a new best. As in
    # FastF1, a race's first lap (from a standing start) is never one.
    counted = laps["lap_time_s"].where(~laps["deleted"] & ~standing_start)
    before = counted.groupby(laps["driver_number"]).transform(lambda s: s.cummin().ffill().shift())
    return _frame({
        "session_key": key, "driver_number": laps["driver_number"],
        "driver": laps["driver_number"].map(drivers["name_acronym"]),
        "team": laps["driver_number"].map(drivers["team_name"]),
        "lap_number": laps["lap_number"], "stint": laps["stint"], "compound": laps["compound"],
        "tyre_life": laps["tyre_life"], "laps_in_stint": laps["laps_in_stint"], "fresh_tyre": laps["fresh_tyre"],
        "lap_time_s": laps["lap_time_s"], "sector1_s": laps["duration_sector_1"],
        "sector2_s": laps["duration_sector_2"], "sector3_s": laps["duration_sector_3"],
        "lap_start_t": laps["lap_start_t"], "lap_end_t": laps["lap_end_t"],
        "pit_in_t": laps["pit_in_t"], "pit_out_t": laps["pit_out_t"],
        "is_pit_in_lap": laps["is_pit_in_lap"].astype(bool), "is_pit_out_lap": laps["is_pit_out_lap"],
        "speed_i1": laps["i1_speed"], "speed_i2": laps["i2_speed"], "speed_fl": np.nan,
        "speed_st": laps["st_speed"],
        "position": _position_at_lap_end(laps, positions, t0),
        "track_status": laps["track_status"],
        "is_personal_best": counted.notna() & (before.isna() | (counted < before)),
        "deleted": laps["deleted"], "deleted_reason": [deleted.get(w) for w in which],
        "is_accurate": _accurate(laps) & ~standing_start,
        "fastf1_generated": False,
    }, "laps")


def _accurate(laps: pd.DataFrame) -> pd.Series:
    """FastF1's `IsAccurate`, less its timing-continuity check: a timed lap with all three
    sectors summing to it (3 ms), no pit stop, green or yellow only, and not the lap after
    a safety car."""
    sectors = laps[["duration_sector_1", "duration_sector_2", "duration_sector_3"]].astype(float)
    sums = (sectors.sum(axis=1, min_count=3) - laps["lap_time_s"]).abs() <= 0.003
    after_sc = laps.groupby("driver_number")["track_status"].shift() == "4"
    return (sums & ~laps["is_pit_in_lap"].astype(bool) & ~laps["is_pit_out_lap"]
            & laps["track_status"].isin(["1", "2", "12", "21"]) & ~after_sc)


def _position_at_lap_end(laps: pd.DataFrame, positions: list[dict], t0: pd.Timestamp) -> pd.Series:
    """Each lap's running position: the latest position OpenF1 reported by the lap's end."""
    pos = pd.DataFrame(positions)
    if pos.empty:
        return pd.Series(np.nan, index=laps.index)
    pos["t"] = (pd.to_datetime(pos["date"], utc=True, format="ISO8601") - t0).dt.total_seconds()
    ends = laps[["driver_number", "lap_end_t"]].reset_index()
    ends = ends[ends["lap_end_t"].notna()].sort_values("lap_end_t")
    merged = pd.merge_asof(ends, pos.sort_values("t")[["t", "driver_number", "position"]],
                           left_on="lap_end_t", right_on="t", by="driver_number", direction="backward")
    return merged.set_index("index")["position"].reindex(laps.index)


# Race control's messages as the feed's track status codes. Order matters: "VIRTUAL SAFETY
# CAR DEPLOYED" also contains "SAFETY CAR DEPLOYED". Singapore 2026 writes "VSC DEPLOYED".
_STATUS_RULES = (
    (re.compile(r"\b(?:VIRTUAL SAFETY CAR|VSC) DEPLOYED"), "6"),
    (re.compile(r"\b(?:VIRTUAL SAFETY CAR|VSC) ENDING"), "7"),
    (re.compile(r"SAFETY CAR DEPLOYED"), "4"),
    (re.compile(r"\bRED FLAG\b"), "5"),
    (re.compile(r"\bGREEN LIGHT\b|\bTRACK CLEAR\b"), "1"),
)


def track_status(rc: pd.DataFrame, key: str) -> pd.DataFrame:
    """The session's track status over time, from race control, in the feed's codes.

    1 green, 2 a yellow anywhere, 4 safety car, 5 red flag, 6 VSC, 7 VSC ending. A safety car,
    VSC or red flag holds until the track is declared clear or green; under none of them, the
    track is yellow while any sector's yellow is still out.
    """
    rows = [{"t": 0.0, "status": "1", "message": "AllClear"}]
    neutralised, yellows = None, set()
    for r in rc.to_dict("records"):
        text = str(r.get("message") or "").upper()
        flag, scope = str(r.get("flag") or "").upper(), str(r.get("scope") or "").upper()
        code = next((c for pattern, c in _STATUS_RULES if pattern.search(text)), None)
        if code is None and flag == "RED":
            code = "5"
        if code is None and flag in ("GREEN", "CLEAR") and scope == "TRACK":
            code = "1"
        if code == "1":
            neutralised, yellows = None, set()
        elif code is not None:
            neutralised = code
        elif flag in ("YELLOW", "DOUBLE YELLOW"):
            yellows.add(r.get("sector") if scope == "SECTOR" else "track")
        elif flag == "CLEAR" and scope == "SECTOR":
            yellows.discard(r.get("sector"))
        status = neutralised or ("2" if yellows else "1")
        if status != rows[-1]["status"]:
            rows.append({"t": float(r["t"]), "status": status, "message": _STATUS_TEXT[status]})
    return _frame(pd.DataFrame(rows).assign(session_key=key), "track_status")


# The feed's own words for each code, as FastF1 stores them.
_STATUS_TEXT = {"1": "AllClear", "2": "Yellow", "4": "SCDeployed", "5": "Red", "6": "VSCDeployed",
                "7": "VSCEnding"}


def _statuses_between(status: pd.DataFrame, start: float, end: float) -> str:
    """Every status in force during a lap, in order, as the feed writes them ('14')."""
    if pd.isna(start):
        return "1"
    end = start if pd.isna(end) else end
    t, codes = status["t"].to_numpy(), status["status"].to_numpy()
    first = max(int(np.searchsorted(t, start, side="right")) - 1, 0)
    last = max(int(np.searchsorted(t, end, side="right")) - 1, 0)
    return "".join(dict.fromkeys(codes[first:last + 1]))


# "CAR 44 (HAM) TIME 1:35.123 DELETED - TRACK LIMITS AT TURN 4 LAP 12 15:04:23"
_CAR, _LAP = re.compile(r"\bCAR (\d+)"), re.compile(r"\bLAP (\d+)")
_TIME = re.compile(r"\bTIME (\d+):(\d+\.\d+)")


def _deleted_laps(rc: pd.DataFrame, laps: pd.DataFrame, race: bool) -> dict[tuple[int, int], str]:
    """Laps race control deleted, by (car, lap), with its message; reinstated ones put back.

    The lap is the car's lap with the time the message quotes. Only without one (a "LAP
    DELETED" message) is the message's lap number used, and outside a race it runs one ahead
    of the timing's (Singapore 2026: FP1's "TIME 1:38.239 ... LAP 3" is lap 2; qualifying's
    "LAP 16 ... (PIT)" was timed on lap 15, the in-lap).
    """
    out: dict[tuple[int, int], str] = {}
    for message in rc.get("message", pd.Series(dtype=object)):
        text = str(message).upper()
        car, lap, quoted = _CAR.search(text), _LAP.search(text), _TIME.search(text)
        if car is None or lap is None:
            continue
        which = (int(car.group(1)), int(lap.group(1)) - (0 if race else 1))
        if quoted is not None:
            seconds = 60 * int(quoted.group(1)) + float(quoted.group(2))
            timed = laps[(laps["driver_number"] == which[0]) & ((laps["lap_time_s"] - seconds).abs() < 0.0015)]
            if not timed.empty:
                which = (which[0], int(timed["lap_number"].iloc[0]))
        if "REINSTATED" in text:              # checked first: "...REINSTATED, DELETED IN ERROR"
            out.pop(which, None)
        elif "DELETED" in text:
            out[which] = str(message)
    return out


def _weather(w: pd.DataFrame, key: str) -> pd.DataFrame:
    if w.empty:
        return _frame({n: [] for n in TABLE_COLUMNS["weather"]}, "weather")
    return _frame({
        "session_key": key, "t": w["t"], "air_temp": w["air_temperature"], "track_temp": w["track_temperature"],
        "humidity": w["humidity"], "pressure": w["pressure"], "wind_speed": w["wind_speed"],
        "wind_direction": w["wind_direction"], "rainfall": w["rainfall"].fillna(0).astype(bool),
    }, "weather")


def _race_control(rc: pd.DataFrame, key: str) -> pd.DataFrame:
    if rc.empty:
        return _frame({n: [] for n in TABLE_COLUMNS["race_control"]}, "race_control")
    column = lambda name: rc[name] if name in rc else None                          # noqa: E731
    return _frame({
        "session_key": key, "t": rc["t"], "lap": column("lap_number"), "category": column("category"),
        "flag": column("flag"), "scope": column("scope"), "sector": column("sector"),
        "racing_number": column("driver_number"), "status": None, "message": column("message"),
    }, "race_control")


def _car(c: pd.DataFrame, key: str) -> pd.DataFrame:
    if c.empty:
        return _frame({n: [] for n in TABLE_COLUMNS["car_data"]}, "car_data")
    return _frame({
        "session_key": key, "driver_number": c["driver_number"], "t": c["t"], "rpm": c["rpm"],
        "speed": c["speed"], "gear": c["n_gear"], "throttle": c["throttle"],
        "brake": pd.to_numeric(c["brake"]).fillna(0) > 0,
        "drs": pd.to_numeric(c["drs"]).fillna(0) if "drs" in c else 0,
    }, "car_data")


def _pos(p: pd.DataFrame, key: str) -> pd.DataFrame:
    if p.empty:
        return _frame({n: [] for n in TABLE_COLUMNS["pos_data"]}, "pos_data")
    return _frame({"session_key": key, "driver_number": p["driver_number"], "t": p["t"],
                   "x": p["x"], "y": p["y"], "z": p["z"], "status": "OnTrack"}, "pos_data")


def _circuit(location: str, key: str) -> tuple[pd.DataFrame, float]:
    """Corner markers and rotation from the latest session at this circuit already in the lake."""
    empty = _frame({n: [] for n in TABLE_COLUMNS["circuit_markers"]}, "circuit_markers")
    con = connect()
    if not (has_table(con, "sessions") and has_table(con, "circuit_markers")):
        return empty, 0.0
    latest = con.execute("""select s.session_key, s.circuit_rotation_deg from sessions s
                            where s.location = ? and exists (select 1 from circuit_markers m
                                                             where m.session_key = s.session_key)
                            order by s.date_utc desc limit 1""", [location]).fetchone()
    if latest is None:
        log.info("%s: no earlier session at %s to take corners from", key, location)
        return empty, 0.0
    markers = con.execute("select * from circuit_markers where session_key = ?", [latest[0]]).df()
    return _frame(markers.assign(session_key=key), "circuit_markers"), float(latest[1] or 0.0)

