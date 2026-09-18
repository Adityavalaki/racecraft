"""
Turns a loaded FastF1 Session into lake tables.

Everything here is a pure DataFrame transform except `load_session`, so the
normalisation rules can be tested without touching the network.

The one rule that matters most: every timestamp leaves this module as `t`,
float seconds since the session's t0. FastF1 is inconsistent about this —
laps, weather and track status use timedeltas from t0, but race control
messages arrive as absolute datetimes — and a panel reading one of each
would be silently misaligned.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import fastf1
import pandas as pd

from racecraft.store.schema import TABLES

log = logging.getLogger(__name__)


def make_session_key(year: int, round_number: int, session: str) -> str:
    return f"{year}_{round_number:02d}_{session}"


def load_session(year: int, round_number: int, session_name: str, telemetry: bool = True) -> fastf1.core.Session:
    """Load by FastF1 schedule name ("Practice 2", "Sprint Shootout"), not by code."""
    ses = fastf1.get_session(year, round_number, session_name)
    ses.load(laps=True, telemetry=telemetry, weather=True, messages=True)
    return ses


# ---------------------------------------------------------------- helpers

def seconds(td: pd.Series) -> pd.Series:
    """Timedelta series -> float seconds, NaT -> NaN."""
    return td.dt.total_seconds()


def seconds_since(ts: pd.Series, t0: pd.Timestamp) -> pd.Series:
    """Absolute datetime series -> float seconds since t0."""
    return (ts - t0).dt.total_seconds()


def _nullable_str(s: pd.Series) -> pd.Series:
    """Object column -> str with None for missing/blank. Keeps '12' as '12', never 12."""
    out = s.astype("object").where(s.notna(), None)
    return out.map(lambda v: None if v is None or (isinstance(v, str) and v.strip() == "") else str(v))


def _as_utc(ts) -> datetime | None:
    if ts is None or pd.isna(ts):
        return None
    ts = pd.Timestamp(ts)
    return (ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")).to_pydatetime()


def _frame(rows: dict[str, object], table: str) -> pd.DataFrame:
    """Build a DataFrame with exactly the schema's columns, in schema order."""
    df = pd.DataFrame(rows)
    missing = [n for n in TABLES[table].names if n not in df.columns]
    if missing:
        raise KeyError(f"{table}: transform did not produce columns {missing}")
    return df[TABLES[table].names]


# ---------------------------------------------------------------- tables

def session_t0(ses, fallback: pd.Timestamp | None = None) -> pd.Timestamp | None:
    """
    Wall-clock time of session time zero.

    FastF1 derives `t0_date` from the telemetry stream, so a session loaded
    without telemetry raises rather than returning it — which live mode does by
    choice, and which would otherwise make a recording unparseable for want of
    a number every lap already carries.

    Every lap holds both its absolute start (`LapStartDate`) and its start in
    session time (`LapStartTime`), and the difference between them is t0. The
    median across laps is used rather than the first, because one lap with a
    mistimed date should not move it.

    In a live recording even that is unavailable: `LapStartDate` is filled from
    telemetry too, and comes back entirely null. There the caller supplies a
    `fallback` — for a recording, the timestamp of its first message, which is
    the zero every session time in it was measured against.
    """
    try:
        t0 = ses.t0_date
        if t0 is not None and pd.notna(t0):
            return t0
    except Exception:
        pass                    # not loaded; derive it from the laps instead

    try:
        laps = ses.laps
    except Exception:
        return fallback
    if laps is None or laps.empty:
        return fallback
    if "LapStartDate" not in laps or "LapStartTime" not in laps:
        return fallback

    offsets = (laps["LapStartDate"] - laps["LapStartTime"]).dropna()
    if offsets.empty:
        return fallback
    derived = pd.Timestamp(offsets.median())
    log.info("%s: t0 derived from laps (%s), telemetry not loaded", ses.name, derived)
    return derived


def build_sessions(ses, key: str, t0: pd.Timestamp | None = None) -> pd.DataFrame:
    ci_rotation = None
    try:
        ci_rotation = float(ses.get_circuit_info().rotation)
    except Exception as e:  # circuit info is a nice-to-have, never worth failing an ingest
        log.warning("%s: no circuit info (%s)", key, e)
    try:
        total_laps = ses.total_laps
    except Exception:  # practice and qualifying have no scheduled distance; FastF1 raises
        total_laps = None
    try:
        start_t = ses.session_start_time
        start_t = start_t.total_seconds() if pd.notna(start_t) else None
    except Exception:  # same reason: not every session carries one
        start_t = None
    return _frame({
        "session_key": [key],
        "event_name": [ses.event["EventName"]],
        "country": [ses.event["Country"]],
        "location": [ses.event["Location"]],
        "session_name": [ses.name],
        "date_utc": [_as_utc(ses.date)],
        "t0_utc": [_as_utc(t0 if t0 is not None else session_t0(ses))],
        "start_t": [start_t],
        "total_laps": [int(total_laps) if total_laps is not None and pd.notna(total_laps) else None],
        "circuit_rotation_deg": [ci_rotation],
        "fastf1_version": [fastf1.__version__],
        "ingested_at": [datetime.now(timezone.utc)],
    }, "sessions")


def build_results(results: pd.DataFrame, key: str) -> pd.DataFrame:
    r = results
    return _frame({
        "session_key": key,
        "driver_number": pd.to_numeric(r["DriverNumber"]),
        "abbreviation": _nullable_str(r["Abbreviation"]),
        "full_name": _nullable_str(r["FullName"]),
        "team_name": _nullable_str(r["TeamName"]),
        "team_id": _nullable_str(r["TeamId"]),
        "team_color": _nullable_str(r["TeamColor"]),
        "grid_position": r["GridPosition"],
        "position": r["Position"],
        "classified_position": _nullable_str(r["ClassifiedPosition"]),
        "status": _nullable_str(r["Status"]),
        "points": r["Points"],
        "laps": r["Laps"],
        "result_time_s": seconds(r["Time"]),
        "q1_s": _optional_seconds(r, "Q1"),
        "q2_s": _optional_seconds(r, "Q2"),
        "q3_s": _optional_seconds(r, "Q3"),
    }, "results")


def _optional_seconds(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(float("nan"), index=df.index)
    return seconds(pd.to_timedelta(df[col]))


def build_laps(laps: pd.DataFrame, key: str) -> pd.DataFrame:
    lp = laps.sort_values(["DriverNumber", "LapNumber"]).reset_index(drop=True)
    stint = lp["Stint"]
    # Count laps within each stint. Distinct from TyreLife: a driver can start
    # a stint on a used set (VER, Bahrain 2024: lap 1 on 4-lap-old softs).
    laps_in_stint = lp.groupby(["DriverNumber", stint.fillna(-1)]).cumcount() + 1
    return _frame({
        "session_key": key,
        "driver_number": pd.to_numeric(lp["DriverNumber"]),
        "driver": _nullable_str(lp["Driver"]),
        "team": _nullable_str(lp["Team"]),
        "lap_number": lp["LapNumber"],
        "stint": stint,
        "compound": _nullable_str(lp["Compound"]),
        "tyre_life": lp["TyreLife"],
        "laps_in_stint": laps_in_stint.where(stint.notna()),
        "fresh_tyre": lp["FreshTyre"].astype("boolean"),
        "lap_time_s": seconds(lp["LapTime"]),
        "sector1_s": seconds(lp["Sector1Time"]),
        "sector2_s": seconds(lp["Sector2Time"]),
        "sector3_s": seconds(lp["Sector3Time"]),
        "lap_start_t": seconds(lp["LapStartTime"]),
        "lap_end_t": seconds(lp["Time"]),
        "pit_in_t": seconds(lp["PitInTime"]),
        "pit_out_t": seconds(lp["PitOutTime"]),
        "is_pit_in_lap": lp["PitInTime"].notna(),
        "is_pit_out_lap": lp["PitOutTime"].notna(),
        "speed_i1": lp["SpeedI1"],
        "speed_i2": lp["SpeedI2"],
        "speed_fl": lp["SpeedFL"],
        "speed_st": lp["SpeedST"],
        "position": lp["Position"],
        "track_status": _nullable_str(lp["TrackStatus"]),
        "is_personal_best": lp["IsPersonalBest"].astype("boolean"),
        "deleted": lp["Deleted"].astype("boolean"),
        "deleted_reason": _nullable_str(lp["DeletedReason"]),
        "is_accurate": lp["IsAccurate"].astype("boolean"),
        "fastf1_generated": lp["FastF1Generated"].astype("boolean"),
    }, "laps")


MAX_GEAR = 8
THROTTLE_MISSING = 104.0


def clean_gear(gear: pd.Series) -> pd.Series:
    """
    Gears outside 0-8 become null. The feed emits values up to 128, almost
    always while the car is stationary (2024 Japan: 168 samples, pre-session
    and after the flag). Only the ones above 127 overflow the column type;
    the rest would sit in the lake silently looking like real gears.
    """
    g = pd.to_numeric(gear, errors="coerce")
    return g.where(g.between(0, MAX_GEAR))


def clean_throttle(throttle: pd.Series) -> pd.Series:
    """104 is the feed's 'no reading' sentinel (13% of samples in 2024 Japan); anything above 100 is not a throttle position."""
    t = pd.to_numeric(throttle, errors="coerce")
    return t.where(t <= 100.0)


def build_car_data(car_data: dict, key: str) -> pd.DataFrame:
    frames = []
    for drv, cd in car_data.items():
        if cd is None or len(cd) == 0:
            continue
        frames.append(pd.DataFrame({
            "session_key": key,
            "driver_number": int(drv),
            "t": seconds(cd["SessionTime"]).to_numpy(),
            "rpm": cd["RPM"].to_numpy(),
            "speed": cd["Speed"].to_numpy(),
            "gear": clean_gear(cd["nGear"]).to_numpy(),
            "throttle": clean_throttle(cd["Throttle"]).to_numpy(),
            "brake": cd["Brake"].astype(bool).to_numpy(),
            "drs": cd["DRS"].to_numpy(),
        }))
    return _concat(frames, "car_data")


def build_pos_data(pos_data: dict, key: str) -> pd.DataFrame:
    frames = []
    for drv, pdat in pos_data.items():
        if pdat is None or len(pdat) == 0:
            continue
        frames.append(pd.DataFrame({
            "session_key": key,
            "driver_number": int(drv),
            "t": seconds(pdat["SessionTime"]),
            "x": pdat["X"].to_numpy(),
            "y": pdat["Y"].to_numpy(),
            "z": pdat["Z"].to_numpy(),
            "status": _nullable_str(pdat["Status"]),
        }))
    return _concat(frames, "pos_data")


def build_weather(w: pd.DataFrame, key: str) -> pd.DataFrame:
    return _frame({
        "session_key": key,
        "t": seconds(w["Time"]),
        "air_temp": w["AirTemp"],
        "track_temp": w["TrackTemp"],
        "humidity": w["Humidity"],
        "pressure": w["Pressure"],
        "wind_speed": w["WindSpeed"],
        "wind_direction": w["WindDirection"],
        "rainfall": w["Rainfall"].astype("boolean"),
    }, "weather")


def build_race_control(rc: pd.DataFrame, t0: pd.Timestamp | None, key: str) -> pd.DataFrame:
    # Absolute datetimes, unlike every other FastF1 table. Also only
    # second-resolution, so ordering against 4 Hz telemetry is approximate.
    absolute = pd.api.types.is_datetime64_any_dtype(rc["Time"])
    if absolute and t0 is None:
        # Without a zero these cannot be placed on the clock. Better to carry
        # the messages with no time than to fail the whole session for them.
        log.warning("%s: race control messages have no session t0; times left empty", key)
        t = pd.Series([float("nan")] * len(rc), index=rc.index)
    else:
        t = seconds_since(rc["Time"], t0) if absolute else seconds(rc["Time"])
    return _frame({
        "session_key": key,
        "t": t,
        "lap": rc["Lap"],
        "category": _nullable_str(rc["Category"]),
        "flag": _nullable_str(rc["Flag"]),
        "scope": _nullable_str(rc["Scope"]),
        "sector": rc["Sector"],
        "racing_number": pd.to_numeric(rc["RacingNumber"], errors="coerce"),
        "status": _nullable_str(rc["Status"]),
        "message": _nullable_str(rc["Message"]),
    }, "race_control")


def build_track_status(ts: pd.DataFrame, key: str) -> pd.DataFrame:
    return _frame({
        "session_key": key,
        "t": seconds(ts["Time"]),
        "status": _nullable_str(ts["Status"]),
        "message": _nullable_str(ts["Message"]),
    }, "track_status")


def build_session_status(ss: pd.DataFrame, key: str) -> pd.DataFrame:
    return _frame({
        "session_key": key,
        "t": seconds(ss["Time"]),
        "status": _nullable_str(ss["Status"]),
    }, "session_status")


def build_circuit_markers(ses, key: str) -> pd.DataFrame:
    try:
        ci = ses.get_circuit_info()
    except Exception as e:
        log.warning("%s: no circuit markers (%s)", key, e)
        return _concat([], "circuit_markers")
    frames = []
    for kind, df in [("corner", ci.corners), ("marshal_sector", ci.marshal_sectors), ("marshal_light", ci.marshal_lights)]:
        if df is None or df.empty:
            continue
        frames.append(pd.DataFrame({
            "session_key": key,
            "kind": kind,
            "number": df["Number"].to_numpy(),
            "letter": _nullable_str(df["Letter"]),
            "x": df["X"].to_numpy(),
            "y": df["Y"].to_numpy(),
            "angle": df["Angle"].to_numpy(),
            "distance": df["Distance"].to_numpy(),
        }))
    return _concat(frames, "circuit_markers")


def _concat(frames: list[pd.DataFrame], table: str) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame({n: pd.Series(dtype="object") for n in TABLES[table].names})
    return pd.concat(frames, ignore_index=True)[TABLES[table].names]


def extract(ses, key: str, telemetry: bool = True,
            t0: pd.Timestamp | None = None) -> dict[str, pd.DataFrame]:
    """
    All lake tables for one loaded session.

    `t0` is only needed when the session was loaded without telemetry, because
    FastF1 derives session time zero from the telemetry stream. Live recordings
    supply their first message's timestamp, which is the same instant.
    """
    t0 = session_t0(ses, fallback=t0)
    tables = {
        "sessions": build_sessions(ses, key, t0),
        "results": build_results(ses.results, key),
        "laps": build_laps(ses.laps, key),
        "weather": build_weather(ses.weather_data, key),
        "race_control": build_race_control(ses.race_control_messages, t0, key),
        "track_status": build_track_status(ses.track_status, key),
        "session_status": build_session_status(ses.session_status, key),
        "circuit_markers": build_circuit_markers(ses, key),
    }
    if telemetry:
        tables["car_data"] = build_car_data(ses.car_data, key)
        tables["pos_data"] = build_pos_data(ses.pos_data, key)
    return tables
