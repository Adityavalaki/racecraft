"""
The running order and gaps at any instant, from lap data alone.

The public feed carries no interval field, so gaps are derived the way
broadcast timing derives them: from the moment each car crosses the line.
A driver's gap to the leader is the difference between the two cars'
crossing times for the same lap, which is exact at the crossing and holds
until the next one. Cars a full lap or more behind are shown in laps, as
timing screens do, because a time gap across different laps is meaningless.

Everything here is a pure function of a lap table plus a time, so the whole
running order can be tested without a server or a database.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

RACE_SESSIONS = ("Race", "Sprint")


@dataclass
class DriverTiming:
    driver_number: int
    abbreviation: str | None
    team_name: str | None
    team_color: str | None
    position: int
    status: str                      # racing | out | finished | not_started
    laps_completed: int = 0
    gap_to_leader_s: float | None = None
    gap_text: str = ""
    interval_s: float | None = None
    interval_text: str = ""
    laps_down: int = 0
    last_lap_s: float | None = None
    best_lap_s: float | None = None
    is_session_best: bool = False
    is_personal_best: bool = False
    compound: str | None = None
    tyre_life: int | None = None
    laps_in_stint: int | None = None
    stops: int = 0
    # Last lap's sectors, each with how it stands: 'session_best' (purple),
    # 'personal_best' (green) or 'normal', the way a timing screen shows them.
    sectors: list[dict] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {k: (None if isinstance(v, float) and np.isnan(v) else v) for k, v in self.__dict__.items()}


@dataclass
class Classification:
    t: float
    leader_lap: int
    drivers: list[DriverTiming] = field(default_factory=list)
    # Who holds each sector, and the lap that would result from stringing the
    # three fastest together - a lap nobody has driven but everyone is chasing.
    best_sectors: list[dict] = field(default_factory=list)
    ideal_lap_s: float | None = None

    def as_dict(self) -> dict:
        return {"t": self.t, "leader_lap": self.leader_lap,
                "drivers": [d.as_dict() for d in self.drivers],
                "best_sectors": self.best_sectors, "ideal_lap_s": self.ideal_lap_s}


SECTOR_COLUMNS = ("sector1_s", "sector2_s", "sector3_s")


def _sector_bests(done: pd.DataFrame) -> list[dict]:
    """The quickest time set in each sector so far, and who set it."""
    out = []
    for index, column in enumerate(SECTOR_COLUMNS, start=1):
        if column not in done.columns or done[column].notna().sum() == 0:
            out.append({"sector": index, "seconds": None, "driver_number": None, "driver": None})
            continue
        row = done.loc[done[column].idxmin()]
        out.append({"sector": index, "seconds": float(row[column]),
                    "driver_number": int(row["driver_number"]),
                    "driver": row.get("driver")})
    return out


def _driver_sectors(last_lap: pd.Series, driver_laps: pd.DataFrame, session_best: list[dict]) -> list[dict]:
    """This driver's last sectors, marked against their own best and the session's."""
    out = []
    for index, column in enumerate(SECTOR_COLUMNS, start=1):
        value = last_lap.get(column)
        if pd.isna(value):
            out.append({"sector": index, "seconds": None, "state": "none"})
            continue
        value = float(value)
        personal = driver_laps[column].min(skipna=True)
        overall = session_best[index - 1]["seconds"]
        if overall is not None and value <= overall + 1e-9:
            state = "session_best"
        elif pd.notna(personal) and value <= personal + 1e-9:
            state = "personal_best"
        else:
            state = "normal"
        out.append({"sector": index, "seconds": value, "state": state})
    return out


def _format_gap(seconds: float | None, laps_down: int) -> str:
    if laps_down >= 1:
        return f"+{laps_down} LAP" if laps_down == 1 else f"+{laps_down} LAPS"
    if seconds is None:
        return ""
    return "" if seconds == 0 else f"+{seconds:.3f}"


def classify(laps: pd.DataFrame, drivers: pd.DataFrame, t: float, session_name: str) -> Classification:
    """
    Running order at session time `t`.

    laps: one session's lap table. drivers: one row per driver, carrying
    abbreviation, team_name, team_color, grid_position and status.
    """
    if session_name in RACE_SESSIONS:
        return _classify_race(laps, drivers, t)
    return _classify_by_best_lap(laps, drivers, t)


def _completed(laps: pd.DataFrame, t: float) -> pd.DataFrame:
    done = laps[laps["lap_end_t"].notna() & (laps["lap_end_t"] <= t)]
    return done.sort_values(["driver_number", "lap_number"])


def _driver_meta(drivers: pd.DataFrame, number: int) -> dict:
    row = drivers.loc[drivers["driver_number"] == number]
    if row.empty:
        return {"abbreviation": None, "team_name": None, "team_color": None, "grid_position": None, "status": None}
    return row.iloc[0].to_dict()


def _classify_race(laps: pd.DataFrame, drivers: pd.DataFrame, t: float) -> Classification:
    done = _completed(laps, t)
    all_numbers = sorted(set(laps["driver_number"]) | set(drivers["driver_number"]))

    if done.empty:  # before anyone has crossed the line: grid order
        out = []
        for pos, number in enumerate(sorted(all_numbers, key=lambda n: _grid_or_last(drivers, n)), start=1):
            meta = _driver_meta(drivers, number)
            out.append(DriverTiming(driver_number=int(number), abbreviation=meta["abbreviation"],
                                    team_name=meta["team_name"], team_color=meta["team_color"],
                                    position=pos, status="not_started"))
        return Classification(t=t, leader_lap=0, drivers=out)

    last = done.groupby("driver_number").tail(1).set_index("driver_number")
    order = last.sort_values(["lap_number", "lap_end_t"], ascending=[False, True])
    leader_number = order.index[0]
    leader_laps = done[done["driver_number"] == leader_number].set_index("lap_number")["lap_end_t"]
    leader_lap = int(last.loc[leader_number, "lap_number"])
    leader_crossings = np.sort(leader_laps.to_numpy())

    session_best = done["lap_time_s"].min(skipna=True)
    finished = _finished_drivers(laps, t)
    sector_bests = _sector_bests(done)

    rows: list[DriverTiming] = []
    for number in order.index:
        row = last.loc[number]
        meta = _driver_meta(drivers, number)
        lap_number = int(row["lap_number"])
        # Lapped or not is judged at the driver's own crossing, not now: how
        # many laps had the leader completed at that moment? Comparing current
        # lap counts instead would call every car "+1 LAP" for most of a lap,
        # because the leader crosses first and the rest are still circulating.
        leader_laps_then = int(np.searchsorted(leader_crossings, row["lap_end_t"], side="right"))
        laps_down = max(0, leader_laps_then - lap_number)

        gap = None
        if laps_down < 1 and lap_number in leader_laps.index:
            gap = float(row["lap_end_t"] - leader_laps.loc[lap_number])

        driver_laps = done[done["driver_number"] == number]
        best = driver_laps["lap_time_s"].min(skipna=True)
        rows.append(DriverTiming(
            driver_number=int(number),
            abbreviation=meta["abbreviation"], team_name=meta["team_name"], team_color=meta["team_color"],
            position=len(rows) + 1,
            status=_status(number, finished, meta),
            laps_completed=lap_number,
            gap_to_leader_s=gap, gap_text=_format_gap(gap, laps_down), laps_down=max(0, laps_down),
            last_lap_s=_float_or_none(row["lap_time_s"]),
            best_lap_s=_float_or_none(best),
            is_session_best=bool(pd.notna(best) and pd.notna(session_best) and best <= session_best),
            is_personal_best=bool(pd.notna(row["lap_time_s"]) and pd.notna(best) and row["lap_time_s"] <= best),
            compound=row["compound"] if pd.notna(row["compound"]) else None,
            tyre_life=_int_or_none(row["tyre_life"]),
            laps_in_stint=_int_or_none(row["laps_in_stint"]),
            stops=int(driver_laps["is_pit_in_lap"].sum()),
            sectors=_driver_sectors(row, driver_laps, sector_bests),
        ))

    # Drivers with no completed lap yet (retired on lap 1, or never started).
    for number in all_numbers:
        if number in last.index:
            continue
        meta = _driver_meta(drivers, number)
        rows.append(DriverTiming(driver_number=int(number), abbreviation=meta["abbreviation"],
                                 team_name=meta["team_name"], team_color=meta["team_color"],
                                 position=len(rows) + 1, status="out"))

    _fill_intervals(rows)
    return Classification(t=t, leader_lap=leader_lap, drivers=rows,
                          best_sectors=sector_bests, ideal_lap_s=_ideal_lap(sector_bests))


def _classify_by_best_lap(laps: pd.DataFrame, drivers: pd.DataFrame, t: float) -> Classification:
    """Practice and qualifying: ordered by best lap set so far, not by track position."""
    done = _completed(laps, t)
    timed = done[done["lap_time_s"].notna() & ~done["deleted"].fillna(False)]
    best = (timed.sort_values("lap_time_s").groupby("driver_number").head(1)
            .sort_values("lap_time_s").set_index("driver_number"))

    rows: list[DriverTiming] = []
    sector_bests = _sector_bests(timed)
    fastest = float(best["lap_time_s"].iloc[0]) if len(best) else None
    for number in best.index:
        row = best.loc[number]
        meta = _driver_meta(drivers, number)
        driver_laps = done[done["driver_number"] == number]
        gap = float(row["lap_time_s"] - fastest)
        rows.append(DriverTiming(
            driver_number=int(number),
            abbreviation=meta["abbreviation"], team_name=meta["team_name"], team_color=meta["team_color"],
            position=len(rows) + 1, status="racing",
            laps_completed=int(len(driver_laps)),
            gap_to_leader_s=gap, gap_text=_format_gap(gap, 0),
            last_lap_s=_float_or_none(driver_laps["lap_time_s"].iloc[-1]) if len(driver_laps) else None,
            best_lap_s=float(row["lap_time_s"]),
            is_session_best=bool(gap == 0),
            compound=row["compound"] if pd.notna(row["compound"]) else None,
            tyre_life=_int_or_none(row["tyre_life"]),
            laps_in_stint=_int_or_none(row["laps_in_stint"]),
            stops=int(driver_laps["is_pit_in_lap"].sum()),
            sectors=_driver_sectors(row, driver_laps, sector_bests),
        ))

    for number in sorted(set(laps["driver_number"]) | set(drivers["driver_number"])):
        if number in best.index:
            continue
        meta = _driver_meta(drivers, number)
        ran = len(done[done["driver_number"] == number])
        rows.append(DriverTiming(driver_number=int(number), abbreviation=meta["abbreviation"],
                                 team_name=meta["team_name"], team_color=meta["team_color"],
                                 position=len(rows) + 1, status="racing" if ran else "not_started",
                                 laps_completed=ran))

    _fill_intervals(rows)
    return Classification(t=t, leader_lap=int(done["lap_number"].max()) if len(done) else 0, drivers=rows,
                          best_sectors=sector_bests, ideal_lap_s=_ideal_lap(sector_bests))


def _fill_intervals(rows: list[DriverTiming]) -> None:
    for i, row in enumerate(rows):
        if i == 0:
            row.interval_s, row.interval_text = None, ""
            continue
        ahead = rows[i - 1]
        laps_between = row.laps_down - ahead.laps_down
        if laps_between >= 1:
            row.interval_text = _format_gap(None, laps_between)
        elif row.gap_to_leader_s is not None and ahead.gap_to_leader_s is not None:
            row.interval_s = row.gap_to_leader_s - ahead.gap_to_leader_s
            row.interval_text = _format_gap(row.interval_s, 0)


def _finished_drivers(laps: pd.DataFrame, t: float) -> set[int]:
    """Drivers whose last lap of the whole session is already behind us."""
    last_of_session = laps.groupby("driver_number")["lap_end_t"].max()
    return set(last_of_session[last_of_session <= t].index)


def _status(number: int, finished: set[int], meta: dict) -> str:
    """
    A driver still on track is racing; one whose last lap is behind us either
    finished or retired. Classified position decides which: it is a number for
    anyone classified and a letter otherwise (R retired, D disqualified). The
    status text alone is not enough, since a lapped finisher reads "Lapped".
    """
    if number not in finished:
        return "racing"
    classified = str(meta.get("classified_position") or "").strip()
    return "finished" if classified.isdigit() else "out"


def _ideal_lap(sector_bests: list[dict]) -> float | None:
    """The three fastest sectors added together."""
    times = [entry["seconds"] for entry in sector_bests]
    return float(sum(times)) if times and all(t is not None for t in times) else None


def _float_or_none(value) -> float | None:
    return None if pd.isna(value) else float(value)


def _int_or_none(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _grid_or_last(drivers: pd.DataFrame, number: int) -> float:
    meta = _driver_meta(drivers, number)
    grid = meta.get("grid_position")
    return float(grid) if grid is not None and pd.notna(grid) and grid > 0 else 99.0
