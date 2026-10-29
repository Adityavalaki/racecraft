"""
Qualifying laps: how much time each driver left on the table.

A driver's ideal lap is their own three best sectors of the session added
together; the time left is their best lap minus it. It measures execution, not
car speed: against the session's best sectors the slowest car would always look
worst. Deleted laps (track limits) count for neither, as they do not count for
the grid.

The best sectors can come from different runs (Q1 and Q3) on a track that was
getting quicker, so the ideal is a little optimistic for drivers who ran on.
"""

from __future__ import annotations

import pandas as pd

SECTORS = ("sector1_s", "sector2_s", "sector3_s")


def latest(con, year: int, as_of: pd.Timestamp | None = None, code: str = "Q") -> dict:
    """The last `code` session (Q or SQ) of `year` that started before `as_of`: each driver's time left in it, and their season average."""
    laps = con.execute(f"""
        select l.session_key, s.event_name, s.date_utc, l.driver, l.lap_time_s, {", ".join(f"l.{c}" for c in SECTORS)}
        from laps l join sessions s using (session_key)
        where s.year = ? and s."session" = ? and not coalesce(l.deleted, false)""", [int(year), code]).df()
    if not laps.empty and as_of is not None:
        laps = laps[pd.to_datetime(laps["date_utc"], utc=True) < pd.Timestamp(as_of).tz_convert("UTC")]
    if laps.empty:
        return {"year": int(year), "session_key": None, "event_name": None, "sessions": 0, "drivers": [],
                "notes": ["no qualifying has been run yet this season"]}

    per = pd.DataFrame([_driver(key, driver, mine) for (key, driver), mine in laps.groupby(["session_key", "driver"])])
    key = laps.sort_values("date_utc")["session_key"].iloc[-1]
    season = per.groupby("driver")["left_s"].agg(["mean", "count"])
    results = con.execute("""
        select abbreviation, full_name, team_name, team_color, position from results where session_key = ?""", [key]).df()
    rows = per[per["session_key"] == key].merge(results, left_on="driver", right_on="abbreviation", how="left")
    rows = rows.sort_values(["position", "driver"], na_position="last")

    drivers, notes = [], []
    for row in rows.itertuples():
        if pd.isna(row.best_s):
            notes.append(f"{row.driver} set no lap time that counted")
        mean, count = season.loc[row.driver]
        drivers.append({
            "abbreviation": row.driver, "full_name": _text(row.full_name), "team": _text(row.team_name),
            "team_color": _text(row.team_color), "position": None if pd.isna(row.position) else int(row.position),
            "best_s": _num(row.best_s), "ideal_s": _num(row.ideal_s), "left_s": _num(row.left_s),
            "sectors_left": row.sectors_left if isinstance(row.sectors_left, list) else None,
            "season_left_s": None if pd.isna(mean) else round(float(mean), 3), "season_sessions": int(count),
        })
    return {"year": int(year), "session_key": key, "event_name": laps.loc[laps["session_key"] == key, "event_name"].iloc[0],
            "sessions": int(per["session_key"].nunique()), "drivers": drivers, "notes": notes}


def _driver(key: str, driver: str, laps: pd.DataFrame) -> dict:
    """One driver's best lap, own ideal lap, the gap, and that gap sector by sector (the three add up to it)."""
    timed = laps.dropna(subset=["lap_time_s"])
    bests = [laps[c].min() for c in SECTORS]
    if timed.empty or any(pd.isna(b) for b in bests):
        return {"session_key": key, "driver": driver, "best_s": None, "ideal_s": None, "left_s": None, "sectors_left": None}
    lap = timed.loc[timed["lap_time_s"].idxmin()]
    ideal = float(sum(bests))
    split = None if any(pd.isna(lap[c]) for c in SECTORS) else [round(max(float(lap[c] - b), 0.0), 3) for c, b in zip(SECTORS, bests)]
    return {"session_key": key, "driver": driver, "best_s": round(float(lap["lap_time_s"]), 3), "ideal_s": round(ideal, 3),
            # max(): a best lap made of the best sectors comes out a hair below 0 in floating point
            "left_s": round(max(float(lap["lap_time_s"]) - ideal, 0.0), 3), "sectors_left": split}


def _num(value) -> float | None:
    return None if pd.isna(value) else float(value)


def _text(value) -> str | None:
    return None if pd.isna(value) else str(value)
