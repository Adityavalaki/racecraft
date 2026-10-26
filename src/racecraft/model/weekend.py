"""
What a race weekend says about each driver before Sunday.

A prediction made on Saturday night can only use what was known on Saturday
night: that weekend's practice and qualifying (and, on a sprint weekend, the
sprint), and the races already run. Everything here keeps to that. The race
itself is read for one purpose only — `actual_pace`, the answer the blend is
fitted against — and never feeds a prediction.

Four signals, each a pace relative to the field's median, in seconds a lap
(positive is slower):

* `quali_gap_s` — best qualifying lap against pole. One lap, low fuel, new
  tyres: the cleanest measure of car and driver, but not of race pace.
* `long_run_s` — practice long runs: stints of at least LONG_RUN_LAPS clean
  laps on one set, each lap corrected for tyre age and compound with the
  season's own wear model. Fuel loads in practice are unknown, which is the
  noise this signal carries; the blend measures how much it is worth.
* `sprint_s` — the sprint's own race pace, fitted the same way a race is.
  Race fuel, race tyres, wheel to wheel: the closest thing to Sunday there is.
* `form_s` — race pace in the season's earlier races, the newest counting most.

Each comes from data the lake already holds, through the same cleaning and
fits the rest of the models use.

`sprint_evidence` is the same for a sprint, as known once sprint qualifying is
in: its gap stands for qualifying's, FP1 is the only practice there is, and
the sprint's own pace is the answer rather than a signal. Only sessions run
before the sprint are read: in 2023 the Grand Prix's qualifying came first,
and from 2024 it comes after.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racecraft.model import pace as pace_model
from racecraft.model import race_inputs
from racecraft.store.db import partition

log = logging.getLogger(__name__)

SIGNALS = ("quali_gap_s", "long_run_s", "sprint_s", "form_s", "carry_s")

# A practice stint this long, on one set, is a long run rather than a quick
# lap with a cool-down either side.
LONG_RUN_LAPS = 6
# A lap this much slower than its own stint's median is traffic or a cool-down.
LONG_RUN_OUTLIER = 1.04
# Friday's second session is when teams run race fuel; FP1 is set-up work and
# FP3 is qualifying preparation. A lap counts this much toward a driver's
# long-run figure.
PRACTICE_WEIGHT = {"FP1": 0.5, "FP2": 1.0, "FP3": 0.5}
# Each earlier race counts this much less than the one after it.
FORM_DECAY = 0.7
FORM_RACES = 6
# Where a pit-lane start or a missing grid slot is put.
BACK_OF_GRID = 99
# Until a season has this many races behind it, last season's closing form is
# read too, as a signal of its own: the calibration measures how much a winter
# of development (or a new rulebook) erodes it.
CARRY_UNTIL = 3
# Sprint qualifying's codes: the "sprint shootout" of 2023, "sprint qualifying" since.
SPRINT_QUALIFYING = ("SQ", "SS")
# A sprint lap is compared with the field's only where this many cars set a
# clean one, and a driver's sprint pace needs this many such laps.
SPRINT_PACE_CARS = 5
SPRINT_PACE_LAPS = 5
# Seasons that start a new rulebook: the cars are new, and last season's order
# says little about this one. Known in advance, so it is not hindsight; but it
# was added after the replay showed 2026 openers predicted worse with it.
NEW_RULES = {2026}


@dataclass
class Evidence:
    """One race's weekend, as a table with a row per driver, and where it came from."""
    race_key: str
    year: int
    round: int
    event_name: str
    location: str
    table: pd.DataFrame
    sessions_used: list[str] = field(default_factory=list)
    form_races: list[str] = field(default_factory=list)
    grid_source: str = "race"
    notes: list[str] = field(default_factory=list)
    race_in_lake: bool = True       # False on Saturday night: the race has not been run


def _weekend(con, race_key: str) -> pd.DataFrame:
    """Every session of the race's weekend, the race included."""
    row = con.execute("""select year, round from sessions where session_key = ?""", [race_key]).fetchone()
    if row is None:
        raise KeyError(race_key)
    year, rnd = int(row[0]), int(row[1])
    return con.execute("""select session_key, "session", event_name, location, date_utc
                          from sessions where year = ? and round = ?""", [year, rnd]).df().assign(year=year, round=rnd)


def _laps(con, session_key: str) -> pd.DataFrame:
    return con.sql(f"select * from laps where session_key = '{race_inputs._safe(session_key)}'"
                   f"{partition(session_key)}").df()


def quali_gap(con, quali_key: str) -> pd.Series:
    """Each driver's best qualifying lap, as seconds behind pole."""
    df = con.execute("""select driver_number, q1_s, q2_s, q3_s from results where session_key = ?""",
                     [quali_key]).df()
    if df.empty:
        return pd.Series(dtype=float)
    best = df[["q1_s", "q2_s", "q3_s"]].min(axis=1, skipna=True)
    best.index = df["driver_number"].astype(int)
    best = best.dropna()
    return (best - best.min()) if len(best) else best


def long_runs(practice: dict[str, pd.DataFrame], degradation: dict[str, float],
              offsets: dict[str, float]) -> pd.DataFrame:
    """
    Each driver's long-run pace in practice, relative to the field's median,
    and how many laps it rests on (weighted by session).
    """
    rows = []
    for name, laps in practice.items():
        if laps.empty:
            continue
        keep = (
            laps["lap_time_s"].notna()
            & (laps["track_status"] == "1")
            & ~laps["is_pit_in_lap"].fillna(False)
            & ~laps["is_pit_out_lap"].fillna(False)
            & ~laps["deleted"].fillna(False)
            & laps["is_accurate"].fillna(True)
            & laps["compound"].isin(pace_model.DRY_COMPOUNDS)
            & laps["tyre_life"].notna()
        )
        clean = laps[keep]
        if clean.empty:
            continue
        median = clean.groupby(["driver_number", "stint"])["lap_time_s"].transform("median")
        clean = clean[clean["lap_time_s"] <= median * LONG_RUN_OUTLIER]
        size = clean.groupby(["driver_number", "stint"])["lap_number"].transform("size")
        runs = clean[size >= LONG_RUN_LAPS]
        if runs.empty:
            continue
        corrected = (runs["lap_time_s"]
                     - runs["compound"].map(degradation).fillna(0.0) * runs["tyre_life"]
                     - runs["compound"].map(offsets).fillna(0.0))
        weight = PRACTICE_WEIGHT.get(name, 0.5)
        for driver, values in corrected.groupby(runs["driver_number"]):
            rows.append({"driver_number": int(driver), "pace": float(values.median()),
                         "laps": float(len(values) * weight), "session": name})
    if not rows:
        return pd.DataFrame(columns=["long_run_s", "long_run_laps"])
    per = pd.DataFrame(rows)
    # Each session is its own fuel and track state: make each relative to its
    # own field before combining, so a quick FP3 does not flatter its runners.
    per["pace"] = per["pace"] - per.groupby("session")["pace"].transform("median")
    combined = per.groupby("driver_number").apply(
        lambda g: pd.Series({"long_run_s": float(np.average(g["pace"], weights=g["laps"])),
                             "long_run_laps": float(g["laps"].sum())}), include_groups=False)
    combined["long_run_s"] -= combined["long_run_s"].median()
    return combined


def race_pace(laps: pd.DataFrame) -> pd.Series:
    """
    One race's (or sprint's) pace per driver, relative to the field's median,
    from the lap-effects fit the rest of the models use. Empty if it cannot be fitted.
    """
    clean = pace_model.clean_race_laps(laps)
    if len(clean) < pace_model.MIN_LAPS_TO_FIT:
        return pd.Series(dtype=float)
    try:
        model = pace_model.fit_lap_effects(clean)
    except (pace_model.Confounded, ValueError, np.linalg.LinAlgError):
        return pd.Series(dtype=float)
    baseline = pd.Series(model.driver_baseline_s, dtype=float)
    return baseline - baseline.median()


def _earlier_races(con, year: int, rnd: int) -> pd.DataFrame:
    return con.execute("""select session_key, round, event_name from sessions
                          where "session" = 'R' and year = ? and round < ? order by round""",
                       [year, rnd]).df()


def form(con, year: int, rnd: int) -> tuple[pd.Series, list[str], dict, dict]:
    """
    Race pace in the season's earlier races, newest counting most, and the
    season's tyre wear and compound offsets measured from the same fits.
    """
    earlier = _earlier_races(con, year, rnd).tail(FORM_RACES)
    paces, names, models = [], [], []
    for _, race in earlier.iterrows():
        laps = _laps(con, str(race["session_key"]))
        if laps.empty:
            continue
        model, _ = race_inputs._race_fit(str(race["session_key"]), laps)
        if model is None or len(model.driver_baseline_s) < 5:
            continue
        baseline = pd.Series(model.driver_baseline_s, dtype=float)
        paces.append(baseline - baseline.median())
        names.append(str(race["event_name"]))
        models.append(model)
    degradation = {c: v[0] for c, v in pace_model.combine(models).items()} if models else {}
    offsets = {c: float(np.median([m.compound_offset_s[c] for m in models if c in m.compound_offset_s]))
               for c in pace_model.DRY_COMPOUNDS if any(c in m.compound_offset_s for m in models)}
    if not paces:
        return pd.Series(dtype=float), names, degradation, offsets
    weights = [FORM_DECAY ** (len(paces) - 1 - i) for i in range(len(paces))]   # newest last
    table = pd.concat(paces, axis=1)
    w = pd.DataFrame(np.tile(weights, (len(table), 1)), index=table.index).where(table.notna().values)
    value = (table.fillna(0.0).values * w.fillna(0.0).values).sum(axis=1) / w.sum(axis=1).replace(0, np.nan)
    series = pd.Series(value, index=table.index).dropna()
    return series - series.median(), names, degradation, offsets


def grid(con, race_key: str, quali_key: str | None) -> tuple[pd.Series, str]:
    """
    The starting grid: the race's own, when the lake has it (penalties are set
    before the start, so this is not hindsight), else qualifying's order.
    """
    # Ties are never broken by row order: results are stored in finishing
    # order, so that would hand the answer to anything ranked on the grid.
    # Qualifying breaks them, then the car number.
    quali = pd.Series(dtype=float)
    if quali_key:
        q = con.execute("""select driver_number, position from results where session_key = ?""", [quali_key]).df()
        quali = pd.Series(q["position"].values, index=q["driver_number"].astype(int).values, dtype=float)

    def ranked(slots: pd.Series) -> pd.Series:
        tie = quali.reindex(slots.index).fillna(BACK_OF_GRID)
        key = pd.DataFrame({"slot": slots, "tie": tie, "number": slots.index}, index=slots.index)
        order = key.sort_values(["slot", "tie", "number"]).index
        return pd.Series(range(1, len(order) + 1), index=order).reindex(slots.index).astype(int)

    rows = con.execute("""select driver_number, grid_position from results where session_key = ?""",
                       [race_key]).df()
    # A grid the feed did not publish comes through as -1 or empty for every
    # car; one or two cars at 0 are pit-lane starts.
    known = rows["grid_position"].fillna(0) > 0 if not rows.empty else pd.Series(dtype=bool)
    if not rows.empty and known.mean() > 0.5:
        slots = rows.set_index(rows["driver_number"].astype(int))["grid_position"]
        slots = slots.where(slots > 0, BACK_OF_GRID).astype(float)  # pit-lane starts
        return ranked(slots), "race"
    if not quali.empty:
        return ranked(quali.fillna(BACK_OF_GRID)), "qualifying"
    return pd.Series(dtype=int), "none"


def race_key_of(year: int, rnd: int) -> str:
    return f"{int(year)}_{int(rnd):02d}_R"


def sprint_key_of(year: int, rnd: int) -> str:
    return f"{int(year)}_{int(rnd):02d}_S"


class NotSprintWeekend(LookupError):
    """The weekend has no sprint."""


def sessions_of(con, session_key: str) -> list[str]:
    """The weekend's sessions in the lake, in the order they ran."""
    return _weekend(con, session_key).sort_values("date_utc")["session"].astype(str).tolist()


def is_sprint_weekend(codes) -> bool:
    return any(code in codes for code in (*SPRINT_QUALIFYING, "S"))


def _form_and_carry(con, year: int, rnd: int):
    """Recent form, and last season's for a season's first races; the notes say which."""
    form_s, form_races, degradation, offsets = form(con, year, rnd)
    carry_s = pd.Series(dtype=float)
    notes: list[str] = []
    if len(form_races) < CARRY_UNTIL and year not in NEW_RULES:
        carry_s, carried, _, _ = form(con, year - 1, 99)
        if carried:
            notes.append(f"early in the season: the end of {year - 1} is read too")
    if form_s.empty:
        notes.append("first race of the season: no earlier races to judge form or tyre wear from")
    return form_s, form_races, degradation, offsets, carry_s, notes


def _driver_table(con, result_keys: list[str], slots: pd.Series, columns: dict) -> pd.DataFrame:
    """A row per driver: who they are, their grid slot, and each signal (missing where unread)."""
    marks = ", ".join("?" for _ in result_keys)
    drivers = con.execute(f"""select driver_number, abbreviation, team_name, team_color from results
                              where session_key in ({marks})""", result_keys).df()
    drivers = drivers.drop_duplicates("driver_number")
    drivers = drivers.set_index(drivers["driver_number"].astype(int).values)
    table = pd.DataFrame(index=sorted(set(drivers.index) | set(slots.index)))
    table.index.name = "driver_number"
    table["abbreviation"] = drivers["abbreviation"]
    table["team_name"] = drivers["team_name"]
    table["team_color"] = drivers["team_color"]
    table["grid"] = slots
    for name, values in columns.items():
        table[name] = values
    table["grid"] = table["grid"].fillna(BACK_OF_GRID)
    # Qualifying gaps are one-lap times; relative to the field like the rest.
    table["quali_gap_s"] = table["quali_gap_s"] - table["quali_gap_s"].median()
    return table


def evidence(con, session_key: str) -> Evidence:
    """
    Everything known about each driver before the race starts. `session_key`
    is any session of the weekend: on Saturday night the race is not in the
    lake yet, and qualifying is what there is to ask about.
    """
    weekend = _weekend(con, session_key)
    year, rnd = int(weekend["year"].iloc[0]), int(weekend["round"].iloc[0])
    by_code = dict(zip(weekend["session"], weekend["session_key"]))
    race_key = race_key_of(year, rnd)
    event = weekend.loc[weekend["session"] == "R"]
    notes: list[str] = []

    form_s, form_races, degradation, offsets, carry_s, early = _form_and_carry(con, year, rnd)
    notes += early

    quali_key = by_code.get("Q")
    quali = quali_gap(con, quali_key) if quali_key else pd.Series(dtype=float)
    practice = {code: _laps(con, key) for code, key in by_code.items() if code in PRACTICE_WEIGHT}
    runs = long_runs(practice, degradation, offsets)
    sprint = race_pace(_laps(con, by_code["S"])) if "S" in by_code else pd.Series(dtype=float)
    slots, grid_source = grid(con, race_key, quali_key)
    if grid_source == "qualifying":
        notes.append("grid taken from qualifying: penalties not applied")

    table = _driver_table(con, [race_key, quali_key or race_key], slots, {
        "quali_gap_s": quali,
        "long_run_s": runs["long_run_s"] if "long_run_s" in runs else np.nan,
        "long_run_laps": runs["long_run_laps"] if "long_run_laps" in runs else 0.0,
        "sprint_s": sprint,
        "form_s": form_s,
        "carry_s": carry_s,
    })
    used = [code for code in ("FP1", "FP2", "FP3", "SQ", "S", "Q") if code in by_code]
    return Evidence(
        race_key=race_key, year=year, round=rnd,
        event_name=str(event["event_name"].iloc[0]) if not event.empty else str(weekend["event_name"].iloc[0]),
        location=str(event["location"].iloc[0]) if not event.empty else str(weekend["location"].iloc[0]),
        table=table, sessions_used=used, form_races=form_races, grid_source=grid_source, notes=notes,
        race_in_lake="R" in by_code,
    )


def sprint_evidence(con, session_key: str) -> Evidence:
    """
    Everything known about each driver before the sprint starts, from any
    session of a sprint weekend. Raises `NotSprintWeekend` on any other.
    """
    weekend = _weekend(con, session_key).sort_values("date_utc")
    year, rnd = int(weekend["year"].iloc[0]), int(weekend["round"].iloc[0])
    by_code = dict(zip(weekend["session"], weekend["session_key"]))
    if not is_sprint_weekend(by_code):
        raise NotSprintWeekend(f"{weekend['event_name'].iloc[0]} {year} has no sprint")
    sprint_key = sprint_key_of(year, rnd)
    # What had run by the sprint's start; with the sprint not in the lake yet,
    # everything but the race, which always comes after it.
    if "S" in by_code:
        start = weekend.loc[weekend["session"] == "S", "date_utc"].iloc[0]
        before = weekend[weekend["date_utc"] < start]["session"].tolist()
    else:
        before = [code for code in by_code if code != "R"]
    notes: list[str] = []

    form_s, form_races, degradation, offsets, carry_s, early = _form_and_carry(con, year, rnd)
    notes += early
    sq_code = next((code for code in SPRINT_QUALIFYING if code in before), None)
    sq_key = by_code.get(sq_code) if sq_code else None
    quali = quali_gap(con, sq_key) if sq_key else pd.Series(dtype=float)
    practice = {code: _laps(con, by_code[code]) for code in before if code in PRACTICE_WEIGHT}
    runs = long_runs(practice, degradation, offsets)
    slots, grid_source = grid(con, sprint_key, sq_key)
    if grid_source == "qualifying":
        notes.append("grid taken from sprint qualifying: penalties not applied")

    table = _driver_table(con, [sprint_key, sq_key or sprint_key], slots, {
        "quali_gap_s": quali,
        "long_run_s": runs["long_run_s"] if "long_run_s" in runs else np.nan,
        "long_run_laps": runs["long_run_laps"] if "long_run_laps" in runs else 0.0,
        "sprint_s": np.nan,                         # the sprint is what is being predicted
        "form_s": form_s,
        "carry_s": carry_s,
    })
    used = [code for code in before if code in PRACTICE_WEIGHT] + ([sq_code] if sq_code else [])
    event = weekend.iloc[0]
    return Evidence(
        race_key=sprint_key, year=year, round=rnd, event_name=str(event["event_name"]),
        location=str(event["location"]), table=table, sessions_used=used, form_races=form_races,
        grid_source=grid_source, notes=notes, race_in_lake="S" in by_code,
    )


def sprint_pace(laps: pd.DataFrame) -> pd.Series:
    """
    A sprint's pace per driver, relative to the field's median: each clean lap
    against the field's median on that same lap (which takes out fuel and the
    track), the driver's median of those, over at least SPRINT_PACE_LAPS laps.

    Not the lap-effects fit `race_pace` uses: nobody stops in a sprint, so a
    driver alone on a compound has nothing to separate the tyre from the
    driver, and the fit puts them a hundred seconds a lap off (Russell on the
    only softs, China 2024). The tyre a driver chose is part of their sprint.
    """
    clean = pace_model.clean_race_laps(laps)
    if clean.empty:
        return pd.Series(dtype=float)
    field = clean.groupby("lap_number")["lap_time_s"].transform("median")
    cars = clean.groupby("lap_number")["lap_time_s"].transform("size")
    delta = (clean["lap_time_s"] - field)[cars >= SPRINT_PACE_CARS]
    by_driver = delta.groupby(clean.loc[delta.index, "driver_number"].astype(int))
    pace = by_driver.median()[by_driver.size() >= SPRINT_PACE_LAPS]
    return (pace - pace.median()) if len(pace) else pace


def actual_pace(con, race_key: str) -> pd.Series:
    """
    What the race (or the sprint) showed each driver's pace to be: the answer
    the blend is fitted against. Never an input to a prediction.
    """
    laps = _laps(con, race_key)
    return sprint_pace(laps) if race_key.endswith("_S") else race_pace(laps)
