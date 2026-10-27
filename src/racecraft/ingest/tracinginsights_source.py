"""
TracingInsights' public archive (github.com/TracingInsights/<season>, Apache-2.0): the tyre
history OpenF1 lacks, corners for circuits the lake has not seen, and a backup for OpenF1.

Its files are FastF1's own output, published by its authors after each session (the 2026 US
GP race was there about twelve hours later), one folder per event and session:
`<season>/<event>/<session>/session_laptimes.json`, `corners.json`, `rcm.json`, `weather.json`,
`drivers.json`, and telemetry per lap. Each file holds one list per field, "None" for a
missing value. Times are seconds on FastF1's session clock; a lap's start date less its
start time gives that clock's t0 in UTC. Race lap times are Jolpica's official ones.

Used three ways (D-012):
* corners and the circuit's rotation for the session itself;
* tyres: compound, stint, tyre life and fresh tyre over OpenF1's (OpenF1 restarts tyre age
  on a reused set), and laps whose times the two disagree on are counted;
* when OpenF1 has no session at all: laps, weather, race control and track status.
  shortcut: no telemetry then; its files are per lap, resampled and merged (about 1,200
  downloads a race, and not the raw samples the lake keeps). Read them if OpenF1 is ever
  down for good.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from urllib.parse import quote

import fastf1
import numpy as np
import pandas as pd
import requests

from racecraft.ingest import openf1_source
from racecraft.ingest.fastf1_source import _frame

log = logging.getLogger(__name__)

BASE = "https://raw.githubusercontent.com/TracingInsights/{season}/main/{event}/{session}/{file}"
SOURCE = "tracinginsights"
TYRES = ["compound", "stint", "tyre_life", "laps_in_stint", "fresh_tyre"]


def _get(season: int, event: str, session: str, file: str) -> dict | None:
    """One file from the archive, or None if it is not there (yet) or cannot be reached."""
    url = BASE.format(season=season, event=quote(event), session=quote(session), file=file)
    try:
        response = requests.get(url, timeout=60)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as error:     # a backup failing is not fatal
        log.warning("TracingInsights: no %s for %s %s: %s", file, event, session, error)
        return None


def _columns(body: dict) -> pd.DataFrame:
    """A file's lists as a frame, with its "None" strings missing."""
    df = pd.DataFrame({k: v for k, v in body.items() if isinstance(v, list)})
    return df.replace("None", None).infer_objects()


def _number(df: pd.DataFrame, name: str) -> pd.Series:
    return pd.to_numeric(df[name], errors="coerce") if name in df else pd.Series(np.nan, index=df.index)


def laps(body: dict | None, key: str) -> pd.DataFrame | None:
    """`session_laptimes.json` as the lake's laps table, on FastF1's session clock."""
    if not body:
        return None
    df = _columns(body)
    if df.empty:
        return None
    stint = _number(df, "stint")
    number = pd.to_numeric(df["dNum"])
    in_stint = df.groupby([number, stint.fillna(-1)]).cumcount() + 1     # as fastf1_source
    pit_in, pit_out = _number(df, "pin"), _number(df, "pout")
    return _frame({
        "session_key": key, "driver_number": number, "driver": df["drv"], "team": df["team"],
        "lap_number": pd.to_numeric(df["lap"]), "stint": stint, "compound": df["compound"],
        "tyre_life": _number(df, "life"), "laps_in_stint": in_stint.where(stint.notna()),
        "fresh_tyre": df["fresh"].astype("boolean"), "lap_time_s": _number(df, "time"),
        "sector1_s": _number(df, "s1"), "sector2_s": _number(df, "s2"), "sector3_s": _number(df, "s3"),
        "lap_start_t": _number(df, "lST"), "lap_end_t": _number(df, "sesT"),
        "pit_in_t": pit_in, "pit_out_t": pit_out,
        "is_pit_in_lap": pit_in.notna(), "is_pit_out_lap": pit_out.notna(),
        "speed_i1": _number(df, "vi1"), "speed_i2": _number(df, "vi2"), "speed_fl": _number(df, "vfl"),
        "speed_st": _number(df, "vst"), "position": _number(df, "pos"), "track_status": df["status"],
        "is_personal_best": df["pb"].astype("boolean"), "deleted": df["del"].astype("boolean"),
        "deleted_reason": df["delR"], "is_accurate": df["iacc"].astype("boolean"),
        "fastf1_generated": df["ff1G"].astype("boolean"),
    }, "laps")


def markers(body: dict | None, key: str) -> tuple[pd.DataFrame, float] | None:
    """`corners.json` as the lake's circuit markers, and the circuit's rotation."""
    if not body or not body.get("CornerNumber"):
        return None
    frames = []
    # Corners' fields are "X", "Y"...; marshal sectors' and lights' are "MarshalSectorX"...
    for kind, prefix in [("corner", ""), ("marshal_sector", "MarshalSector"), ("marshal_light", "MarshalLight")]:
        numbers = body.get(prefix + "Number" if prefix else "CornerNumber")
        if not numbers:
            continue
        part = pd.DataFrame({"number": numbers, **{f.lower(): body[prefix + f] for f in ("X", "Y", "Angle", "Distance")}})
        part["letter"] = pd.Series(body.get("CornerLetter")).replace("", None) if not prefix else None
        frames.append(part.assign(session_key=key, kind=kind))
    return _frame(pd.concat(frames, ignore_index=True), "circuit_markers"), float(body.get("Rotation") or 0.0)


def improve(tables: dict[str, pd.DataFrame], season: int, event: str, session: str, key: str) -> dict:
    """An OpenF1 session with this session's corners and FastF1's tyre history, where published."""
    found = markers(_get(season, event, session, "corners.json"), key)
    if found is not None:
        tables["circuit_markers"], rotation = found
        tables["sessions"]["circuit_rotation_deg"] = rotation
    ti = laps(_get(season, event, session, "session_laptimes.json"), key)
    if ti is not None:
        tables["laps"], differ = tyres_over(tables["laps"], ti)
        if differ:
            log.info("%s: OpenF1 and TracingInsights lap times differ by over 10 ms on %d laps", key, differ)
    return tables


def tyres_over(openf1: pd.DataFrame, ti: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """OpenF1's laps with FastF1's tyre fields over them, lap by lap; and how many laps'
    times the two disagree on. Laps the archive does not have keep OpenF1's tyres."""
    on = ["driver_number", "lap_number"]
    theirs = ti.set_index(on)
    out = openf1.set_index(on)
    shared = out.index.intersection(theirs.index[theirs["compound"].notna()])
    for column in TYRES:
        out.loc[shared, column] = theirs.loc[shared, column]
    both = out.index.intersection(theirs.index)
    gap = (out.loc[both, "lap_time_s"] - theirs.loc[both, "lap_time_s"]).abs()
    return _frame(out.reset_index()[openf1.columns], "laps"), int((gap > 0.01).sum())


def extract(season: int, rnd: int, ident: str, session_name: str, key: str) -> dict[str, pd.DataFrame] | None:
    """A session's tables from the archive alone (no telemetry), or None if it is not there."""
    schedule = fastf1.get_session(season, rnd, session_name)       # schedule only: no download
    event = str(schedule.event["EventName"])
    body = _get(season, event, session_name, "session_laptimes.json")
    lap_table = laps(body, key)
    if lap_table is None:
        return None
    # FastF1's t0 in UTC: each lap's start date less its start time on the session clock.
    starts = pd.to_datetime(pd.Series(body["lSD"]).replace("None", None), utc=True)
    t0 = (starts - pd.to_timedelta(lap_table["lap_start_t"], unit="s")).median().round("ms")   # ms-precise sources

    rc = _columns(_get(season, event, session_name, "rcm.json") or {"time": []})
    if not rc.empty:
        rc = pd.DataFrame({"t": (pd.to_datetime(rc["time"], utc=True) - t0).dt.total_seconds(),
                           "lap": rc.get("lap"), "category": rc.get("cat"), "flag": rc.get("flag"),
                           "scope": rc.get("scope"), "sector": rc.get("sector"),
                           "racing_number": pd.to_numeric(rc.get("dNum"), errors="coerce"),
                           "status": rc.get("status"), "message": rc.get("msg")}).sort_values("t", kind="stable")
    weather = _columns(_get(season, event, session_name, "weather.json") or {"wT": []})
    drivers = (_get(season, event, session_name, "drivers.json") or {}).get("drivers") or []
    sessions = openf1_source._sessions(schedule, key, t0, float(lap_table["lap_start_t"].min()))
    sessions["fastf1_version"] = SOURCE
    sessions["ingested_at"] = pd.Timestamp(datetime.now(timezone.utc))
    tables = {
        "sessions": sessions,
        "results": _frame(pd.DataFrame([{
            "session_key": key, "driver_number": int(d["dn"]), "abbreviation": d.get("driver"),
            "full_name": f"{d.get('fn')} {d.get('ln')}", "team_name": d.get("team"), "team_color": d.get("tc"),
        } for d in drivers]).reindex(columns=openf1_source.TABLE_COLUMNS["results"]), "results"),
        "laps": lap_table,
        "weather": _frame({"session_key": key, "t": weather.get("wT"), "air_temp": weather.get("wAT"),
                           "track_temp": weather.get("wTT"), "humidity": weather.get("wH"),
                           "pressure": weather.get("wP"), "wind_speed": weather.get("wWS"),
                           "wind_direction": weather.get("wWD"), "rainfall": weather.get("wR")}, "weather"),
        "race_control": _frame(rc.assign(session_key=key) if not rc.empty else
                               {n: [] for n in openf1_source.TABLE_COLUMNS["race_control"]}, "race_control"),
        "track_status": openf1_source.track_status(rc if not rc.empty else pd.DataFrame(), key),
        "session_status": _frame({n: [] for n in openf1_source.TABLE_COLUMNS["session_status"]}, "session_status"),
    }
    found = markers(_get(season, event, session_name, "corners.json"), key)
    tables["circuit_markers"], tables["sessions"]["circuit_rotation_deg"] = found if found is not None else (
        _frame({n: [] for n in openf1_source.TABLE_COLUMNS["circuit_markers"]}, "circuit_markers"), 0.0)
    if ident in ("R", "S"):
        tables["sessions"]["total_laps"] = lap_table["lap_number"].max()
    return tables
