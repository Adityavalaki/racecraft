"""
Race review: overtakes made and lost, and places lost at each pit stop.

Both are counts read off the timing positions at the end of each lap (D-023).

* **An overtake** is a pair of cars that swapped places between two laps, both
  green for both cars, with neither in the pit lane: the rule
  `circuit.passes_per_race` counts per race, here counted per driver. A car
  slowing with damage still counts as passed. Lap 1 is the Starts screen's.
* **Places lost at a stop**: cars that stayed out over the in-lap and out-lap,
  and were behind before the in-lap and ahead after the out-lap. A green-flag
  stop costs a median 3 places, one under a safety car 0 (D-023), so this is
  where a lucky safety car shows. Stops on lap 1, and stops the car retired at,
  are left out.

Consistency and "pitted on the wrong lap" were tried and left out: see D-023.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from racecraft.api.penalties import penalised_stops_in


def latest(con, year: int, as_of: pd.Timestamp | None = None) -> dict:
    """The last Grand Prix of `year` that started before `as_of` (the last of all, if None), reviewed driver by driver."""
    races = con.execute("""select session_key, event_name, date_utc from sessions
                           where year = ? and "session" = 'R' order by date_utc""", [int(year)]).df()
    if not races.empty and as_of is not None:
        races = races[pd.to_datetime(races["date_utc"], utc=True) < pd.Timestamp(as_of).tz_convert("UTC")]
    laps = pd.DataFrame()
    if not races.empty:
        key = races["session_key"].iloc[-1]
        laps = con.execute("select * from laps where session_key = ?", [key]).df()
    if laps.empty:
        return {"year": int(year), "session_key": None, "event_name": None, "drivers": [], "green_stop_places": None,
                "notes": ["no Grand Prix has been run yet this season"]}

    made, lost = passes(laps)
    stop_list = stops(laps, penalised_stops_in(con, laps))
    results = con.execute("""select driver_number, abbreviation, full_name, team_name, team_color, position, classified_position
                             from results where session_key = ? order by position nulls last""", [key]).df()
    green = [s["places"] for s in stop_list if s["kind"] == "green"]
    drivers = []
    for row in results.itertuples():
        mine = [{k: v for k, v in s.items() if k != "driver_number"} for s in stop_list if s["driver_number"] == row.driver_number]
        drivers.append({
            "abbreviation": row.abbreviation, "full_name": row.full_name, "team": row.team_name, "team_color": row.team_color,
            "position": row.classified_position if str(row.classified_position).isdigit() else None,
            "status": None if str(row.classified_position).isdigit() else str(row.classified_position),
            "passes_made": made.get(row.driver_number, 0), "passes_lost": lost.get(row.driver_number, 0),
            "stops": mine, "pit_places": sum(s["places"] for s in mine),
        })
    return {"year": int(year), "session_key": key, "event_name": races["event_name"].iloc[-1], "drivers": drivers,
            "green_stop_places": float(np.median(green)) if green else None, "notes": []}


def passes(laps: pd.DataFrame) -> tuple[dict[int, int], dict[int, int]]:
    """({driver: passes made}, {driver: times passed}) on track, between green laps, neither car in the pit lane."""
    usable = (laps["track_status"].astype(str) == "1") & ~laps["is_pit_in_lap"].fillna(False) & ~laps["is_pit_out_lap"].fillna(False)
    pos = _grid(laps, "position")
    ok = _grid(laps.assign(ok=usable), "ok").eq(True)                  # a missing lap is not usable
    made: dict[int, int] = {}
    lost: dict[int, int] = {}
    for lap in pos.index[1:]:
        if lap - 1 not in pos.index:
            continue
        before, after = pos.loc[lap - 1].to_numpy(float), pos.loc[lap].to_numpy(float)
        # Both laps clean for the car: the lap before ends where the comparison starts.
        running = ok.loc[lap].to_numpy() & ok.loc[lap - 1].to_numpy() & ~np.isnan(before) & ~np.isnan(after)
        cars = pos.columns[running]
        b, a = before[running], after[running]
        swapped = (b[:, None] > b[None, :]) & (a[:, None] < a[None, :])     # row car passed column car
        for i, j in zip(*np.nonzero(swapped)):
            made[int(cars[i])] = made.get(int(cars[i]), 0) + 1
            lost[int(cars[j])] = lost.get(int(cars[j]), 0) + 1
    return made, lost


def stops(laps: pd.DataFrame, penalised: frozenset = frozenset()) -> list[dict]:
    """Each stop: lap, what the track was doing, and the places lost to cars that stayed out."""
    pos = _grid(laps, "position")
    last = laps.groupby("driver_number")["lap_number"].max()
    in_pits = laps["is_pit_in_lap"].fillna(False) | laps["is_pit_out_lap"].fillna(False)
    pitting = laps[in_pits].groupby("lap_number")["driver_number"].apply(set)
    status = laps.set_index(["driver_number", "lap_number"])["track_status"].astype(str)
    out = []
    for row in laps[laps["is_pit_in_lap"].fillna(False)].itertuples():
        lap, car = int(row.lap_number), row.driver_number
        if lap == 1 or lap >= last[car] or lap - 1 not in pos.index or lap + 1 not in pos.index:
            continue                                   # lap-1 stop, or the car retired at it
        before, after = pos.loc[lap - 1], pos.loc[lap + 1]
        if pd.isna(before.get(car)) or pd.isna(after.get(car)):
            continue
        busy = pitting.get(lap, set()) | pitting.get(lap + 1, set())
        places = sum(1 for c in pos.columns if c not in busy and pd.notna(before[c]) and pd.notna(after[c])
                     and before[c] > before[car] and after[c] < after[car])
        flags = status.get((car, lap), "") + status.get((car, lap + 1), "")
        kind = ("red flag" if "5" in flags else "penalty" if (row.session_key, car, lap) in penalised
                else "safety car" if "4" in flags else "VSC" if set(flags) & set("67") else "green")
        out.append({"driver_number": int(car), "lap": lap, "kind": kind, "places": places})
    return out


def _grid(laps: pd.DataFrame, column: str) -> pd.DataFrame:
    """`column` as lap by car, every lap and car present (pivot_table drops all-empty ones)."""
    return (laps.pivot_table(index="lap_number", columns="driver_number", values=column, aggfunc="first")
            .reindex(index=sorted(laps["lap_number"].unique()), columns=sorted(laps["driver_number"].unique())))
