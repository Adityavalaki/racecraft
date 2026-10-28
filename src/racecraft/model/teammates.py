"""
Teammates, head to head: each team's two drivers, compared in the same car.

The car is the biggest thing in a lap time and teammates share it, so the gap
between them is the closest this data gets to the driver alone. For each pair,
over the rounds they drove together, and as of a moment like the standings:

* Qualifying: who qualified ahead, and the gap in the last part both set a
  time in (Q3 if both reached it, else Q2, else Q1), in seconds and percent.
* Race pace, Grand Prix and sprint: clean laps only (`pace.clean_race_laps`:
  green flag, no pit lane, no lap 1, no traffic outliers), and only laps where
  both ran the same lap number on the same compound. The race's gap is the
  median of those differences, over at least MIN_SHARED_LAPS laps: traffic,
  strategy and luck mostly fall away.
* Practice: each session's best lap on the softest dry compound both set a
  lap on. Programmes and fuel loads differ and are not known, so it is the
  noisiest of the lines.
* Results: who finished ahead when both were classified, retirements counted
  apart, and points (sprints included) as the championship counts them.

A pair is the two drivers a team ran in a round's qualifying, sprint or Grand
Prix. A round where a team ran any other number (a stand-in mid-weekend) is
left out with a note, so a stand-in is only compared with the driver they
raced beside, over the rounds they did. A round with only practice run so far
counts if the team's latest pair both drove in it (an FP1 rookie does not
start a pair).

Gaps are first driver minus second: negative means the first was quicker.
The first driver is the one with more points between them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from racecraft.model import pace, standings
from racecraft.store.db import has_table

PRACTICE = ("FP1", "FP2", "FP3")
QUALIFYING = ("Q",)
SPRINT_QUALIFYING = ("SQ", "SS")
RACES = ("R", "S")
# The sessions that say who a team's drivers were that round; practice does not (FP1 rookies).
ENTRY = QUALIFYING + SPRINT_QUALIFYING + RACES
# A race gap needs this many laps where both were clean on the same compound.
MIN_SHARED_LAPS = 5
LAP_COLUMNS = ('session_key, "session" as code, driver_number, lap_number, stint, compound, tyre_life, lap_time_s, '
               'track_status, is_pit_in_lap, is_pit_out_lap, deleted, is_accurate')


@dataclass
class Teammates:
    year: int
    pairs: list[dict]
    rounds: int                                  # rounds with any session counted
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"year": self.year, "pairs": self.pairs, "rounds": self.rounds, "notes": self.notes}


def head_to_head(con, year: int, as_of: pd.Timestamp | None = None) -> Teammates:
    """Every team's pairing of `year`, from sessions that started before `as_of` (all, if None)."""
    df = standings.results(con, year, codes=PRACTICE + ENTRY)
    if not df.empty and as_of is not None:
        df = df[pd.to_datetime(df["date_utc"], utc=True) < pd.Timestamp(as_of).tz_convert("UTC")]
    if df.empty:
        return Teammates(year=int(year), pairs=[], rounds=0, notes=["nothing has been run yet this season"])
    points, _ = standings.counted(df[df["code"].isin(RACES)])
    team_points = points.groupby("team_key")["points"].sum()
    clean, best = _lap_tables(_laps(con, year, set(df["session_key"])))

    pairs, notes = _pairs(df)
    out = []
    for (team, a, b), rounds in pairs.items():
        mine = points[(points["team_key"] == team) & points["round"].isin(rounds)]
        scored = mine.groupby("abbreviation")["points"].sum()
        if scored.get(b, 0) > scored.get(a, 0):
            a, b = b, a
        out.append((team, _pair(df[df["round"].isin(rounds)], clean, best, team, a, b, scored)))
    out.sort(key=lambda item: (-team_points.get(item[0], 0), item[1]["team"], -item[1]["rounds_together"]))
    return Teammates(year=int(year), pairs=[pair for _, pair in out], rounds=int(df["round"].nunique()), notes=notes)


def _laps(con, year: int, keys: set[str]) -> pd.DataFrame:
    if not has_table(con, "laps"):
        return pd.DataFrame()
    laps = con.execute(f"""select {LAP_COLUMNS} from laps where year = ? and list_contains(?, "session")""",
                       [int(year), list(PRACTICE + RACES)]).df()
    return laps[laps["session_key"].isin(keys)]


def _lap_tables(laps: pd.DataFrame) -> tuple[dict, dict]:
    """
    Each race's clean laps as (lap time, compound) tables, a row per lap and a
    column per car, and each practice session's best lap by (session, compound,
    car). Worked out once for the whole field: the cleaning is per driver, so it
    comes out the same as for each pair alone.
    """
    if laps.empty:
        return {}, {}
    clean = {}
    for key, race in laps[laps["code"].isin(RACES)].groupby("session_key"):
        race = pace.clean_race_laps(race)
        clean[key] = (race.pivot(index="lap_number", columns="driver_number", values="lap_time_s"),
                      race.pivot(index="lap_number", columns="driver_number", values="compound"))
    ok = laps[laps["code"].isin(PRACTICE)
              & laps["lap_time_s"].notna()
              & (laps["track_status"] == "1")
              & ~laps["is_pit_in_lap"].fillna(False)
              & ~laps["is_pit_out_lap"].fillna(False)
              & ~laps["deleted"].fillna(False)
              & laps["is_accurate"].fillna(True)
              & laps["compound"].isin(pace.DRY_COMPOUNDS)]
    return clean, ok.groupby(["session_key", "compound", "driver_number"])["lap_time_s"].min().to_dict()


def _pairs(df: pd.DataFrame) -> tuple[dict, list[str]]:
    """{(team, driver, driver): [rounds]}, drivers in alphabetical order, and a note for each round left out."""
    pairs: dict[tuple, list[int]] = {}
    latest: dict[str, tuple[str, str]] = {}
    notes = []
    for rnd, weekend in df.groupby("round", sort=True):
        entry = weekend[weekend["code"].isin(ENTRY)]
        for team, rows in weekend.groupby("team_key"):
            drivers = sorted(set(entry.loc[entry["team_key"] == team, "abbreviation"]))
            if not drivers and team in latest and set(latest[team]) <= set(rows["abbreviation"]):
                drivers = list(latest[team])
            if not drivers:
                continue
            if len(drivers) != 2:
                notes.append(f"{weekend['event_name'].iloc[0]}: {rows['team_name'].iloc[-1]} ran {'only ' if len(drivers) == 1 else ''}"
                             f"{', '.join(drivers)}, so the round is left out for them")
                continue
            latest[team] = (drivers[0], drivers[1])
            pairs.setdefault((team, drivers[0], drivers[1]), []).append(int(rnd))
    return pairs, notes


def _pair(df: pd.DataFrame, clean: dict, best: dict, team: str, a: str, b: str, scored: pd.Series) -> dict:
    # Plain records from here: a few hundred rows, looked up thousands of times.
    mine = df[(df["team_key"] == team) & df["abbreviation"].isin([a, b])].to_dict("records")
    sessions: dict[int, dict[str, dict]] = {}           # round -> session key -> driver -> result, in running order
    for row in mine:
        sessions.setdefault(int(row["round"]), {}).setdefault(row["session_key"], {})[row["abbreviation"]] = row
    rounds, quali, sprint_quali, race, sprint, practice, finish, sprint_finish = [], [], [], [], [], [], [], []
    for rnd in sorted(sessions):
        weekend = sessions[rnd]
        first = next(iter(weekend.values()))
        number = {code: int(row["driver_number"]) for rows in weekend.values() for code, row in rows.items()}
        na, nb = number[a], number[b]
        entry = {"round": rnd, "event_name": str(next(iter(first.values()))["event_name"]),
                 "quali_gap_s": None, "quali_pct": None, "race_gap_s": None, "sprint_gap_s": None,
                 "practice_gap_s": None}
        week_practice = []
        for key, rows in weekend.items():
            if a not in rows or b not in rows:
                continue
            ra, rb = rows[a], rows[b]
            code = ra["code"]
            if code in QUALIFYING + SPRINT_QUALIFYING:
                q = _quali(ra, rb)
                (quali if code in QUALIFYING else sprint_quali).append(q)
                if code in QUALIFYING:
                    entry["quali_gap_s"], entry["quali_pct"] = q["gap_s"], q["pct"]
            elif code in RACES:
                (finish if code == "R" else sprint_finish).append(_finish(ra, rb))
                gap = _race_gap(clean, key, na, nb)
                if gap is not None:
                    (race if code == "R" else sprint).append(gap)
                    entry["race_gap_s" if code == "R" else "sprint_gap_s"] = gap["gap_s"]
            else:
                gap = _practice_gap(best, key, na, nb)
                if gap is not None:
                    practice.append(gap)
                    week_practice.append(gap["gap_s"])
        if week_practice:
            entry["practice_gap_s"] = _r(pd.Series(week_practice).median())
        rounds.append(entry)

    latest = mine[-1]
    return {
        "team": str(latest["team_name"]),
        "team_color": None if pd.isna(latest["team_color"]) else str(latest["team_color"]),
        "drivers": [_driver([r for r in mine if r["abbreviation"] == code][-1]) for code in (a, b)],
        "rounds_together": len(rounds),
        "qualifying": _quali_summary(quali),
        "race_pace": _gap_summary(race),
        "practice": _gap_summary(practice),
        "results": {**_finish_summary(finish),
                    "points": [standings._number(scored.get(a, 0)), standings._number(scored.get(b, 0))]},
        "sprint": {"qualifying": _quali_summary(sprint_quali), "pace": _gap_summary(sprint),
                   **_finish_summary(sprint_finish)},
        "rounds": rounds,
    }


def _driver(row: dict) -> dict:
    return {"abbreviation": row["abbreviation"], "driver_number": int(row["driver_number"]),
            "full_name": None if pd.isna(row["full_name"]) else str(row["full_name"])}


def _quali(ra, rb) -> dict:
    """Who qualified ahead, and the gap in the last part both set a time in."""
    out = {"ahead": _ahead(ra["position"], rb["position"]), "gap_s": None, "pct": None}
    for part in ("q3_s", "q2_s", "q1_s"):
        if pd.notna(ra[part]) and pd.notna(rb[part]):
            gap = float(ra[part]) - float(rb[part])
            return {**out, "gap_s": _r(gap), "pct": round(100 * gap / float(rb[part]), 3)}
    return out


def _race_gap(clean: dict, key: str, na: int, nb: int) -> dict | None:
    """The median gap over laps both ran clean, on the same lap and compound; None if too few."""
    times, tyres = clean.get(key, (pd.DataFrame(), None))
    if na not in times or nb not in times:
        return None
    gap = (times[na] - times[nb])[tyres[na] == tyres[nb]].dropna()
    if len(gap) < MIN_SHARED_LAPS:
        return None
    return {"gap_s": _r(gap.median()), "laps": int(len(gap))}


def _practice_gap(best: dict, key: str, na: int, nb: int) -> dict | None:
    """Best lap against best lap, on the softest dry compound both set a lap on; None if they shared none."""
    for compound in pace.DRY_COMPOUNDS:                 # softest first
        if (key, compound, na) in best and (key, compound, nb) in best:
            return {"gap_s": _r(best[(key, compound, na)] - best[(key, compound, nb)]), "compound": compound}
    return None


def _finish(ra, rb) -> dict:
    places = [pd.to_numeric(r["classified_position"], errors="coerce") for r in (ra, rb)]
    return {"ahead": _ahead(*places), "retired": [bool(pd.isna(p)) for p in places]}


def _ahead(pa, pb) -> int | None:
    """0 if the first driver placed ahead, 1 if the second, None if either has no place."""
    if pd.isna(pa) or pd.isna(pb) or pa == pb:
        return None
    return 0 if pa < pb else 1


def _count(items: list[dict]) -> list[int]:
    return [sum(1 for i in items if i["ahead"] == side) for side in (0, 1)]


def _quali_summary(sessions: list[dict]) -> dict:
    timed = [s for s in sessions if s["gap_s"] is not None]
    return {"ahead": _count(sessions), "sessions": len(sessions),
            "gap_s": _r(pd.Series([s["gap_s"] for s in timed]).median()) if timed else None,
            "pct": round(float(pd.Series([s["pct"] for s in timed]).median()), 3) if timed else None}


def _gap_summary(sessions: list[dict]) -> dict:
    """How many sessions each was quicker in, and the median gap: each session counts once."""
    return {"faster": [sum(1 for s in sessions if s["gap_s"] < 0), sum(1 for s in sessions if s["gap_s"] > 0)],
            "sessions": len(sessions),
            "gap_s": _r(pd.Series([s["gap_s"] for s in sessions]).median()) if sessions else None}


def _finish_summary(finishes: list[dict]) -> dict:
    return {"ahead": _count(finishes), "races": len(finishes),
            "retired": [sum(f["retired"][side] for f in finishes) for side in (0, 1)]}


def _r(value) -> float:
    return round(float(value), 3)
