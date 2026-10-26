"""
The championships, played out to the end of the season.

From the standings at a moment, every Grand Prix and sprint still to run is
simulated many times and the points added up: each driver's chance of the
title, where they are likely to finish, and the most they can still score.

**Each driver's pace** is their recent race form (`weekend.form`, and last
season's early on), turned into a pace by the race prediction's calibration.

**How unsure that is comes in two parts, measured, not tuned** (`measure`).
How far a driver's race pace strays race to race around their own season
average (0.40 s a lap over 2023-2025), and how far form misses that average
(0.24 s, about half of what a single race's prediction allows for). The first
is drawn afresh every race; the second once per simulated season, so a driver
quicker than their form says stays quicker. Treating all of a single race's
uncertainty as lasting, as an earlier version did, hands a whole season to
whoever draws the better car, and was measurably worse.

**Each race** orders the field by that pace, with retirements at the season's
rate. No grid and no circuit: over the rest of a season they even out.

**Points** are F1's: the top ten in a Grand Prix, the top eight in a sprint,
no fastest-lap point (gone from 2025). Ties are broken on wins, then on
chance, close to the FIA's count-back.

`backtest` replays 2023 to 2025 from every round and scores the chance it gave
the eventual champion, beside a baseline that knows only the points.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from racecraft.model import predict, standings, weekend
from racecraft.store.db import has_table

log = logging.getLogger(__name__)

WEIGHTS_FILE = Path(__file__).with_name("title_weights.json")
DEFAULT_RUNS = 10_000
# Measuring the lasting part needs this many of a driver's races still to come.
MIN_RACES_LEFT = 5
# A sprint is about a third of a race, so a third of its chance of retiring.
SPRINT_SHARE = 1 / 3
RACE_POINTS = np.array(standings.RACE_POINTS, dtype=np.float32)
SPRINT_POINTS = np.array(standings.SPRINT_POINTS, dtype=np.float32)


# No form to read: an empty table, but of numbers, so filling it in is not a type change.
_NO_PACE = pd.DataFrame({"pace": pd.Series(dtype=float), "sd": pd.Series(dtype=float)})


class NoCalendar(LookupError):
    """What is left of the season cannot be known (offline, and not in the lake)."""


@dataclass
class Event:
    round: int
    event_name: str
    sprint: bool               # a sprint (True) or a Grand Prix


@dataclass
class TitleOdds:
    year: int
    drivers: list[dict]
    constructors: list[dict]
    remaining: list[dict]
    runs: int
    race_noise_s: float
    lasting_share: float
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"year": self.year, "drivers": self.drivers, "constructors": self.constructors,
                "remaining": self.remaining, "runs": self.runs, "race_noise_s": self.race_noise_s,
                "lasting_share": self.lasting_share, "notes": self.notes}


# ------------------------------------------------------------------ inputs

def load_uncertainty(path: Path = WEIGHTS_FILE) -> dict:
    """The measured split: `race_noise_s` (race to race) and `lasting_share` (of a race's stated sd)."""
    return json.loads(path.read_text(encoding="utf-8"))


def lake_events(con, year: int, after: pd.Timestamp | None) -> list[Event]:
    """Grands Prix and sprints of `year` in the lake that started at or after `after`."""
    df = con.execute("""select cast(round as integer) as round, event_name, "session", date_utc from sessions
                        where year = ? and "session" in ('R', 'S') order by date_utc""", [int(year)]).df()
    if after is not None and not df.empty:
        df = df[pd.to_datetime(df["date_utc"], utc=True) >= after]
    return [Event(int(r.round), str(r.event_name), r.session == "S") for r in df.itertuples()]


def calendar_events(year: int, after: pd.Timestamp) -> list[Event]:
    """Grands Prix and sprints of `year` from F1's schedule that start at or after `after`."""
    import fastf1

    from racecraft.live.feed import _use_project_cache

    _use_project_cache()
    schedule = fastf1.get_event_schedule(int(year), include_testing=False)
    out = []
    for _, event in schedule.iterrows():
        for i in range(1, 6):
            name = str(event.get(f"Session{i}", ""))
            when = event.get(f"Session{i}DateUtc")
            if name not in ("Sprint", "Race") or pd.isna(when):
                continue
            if pd.Timestamp(when).tz_localize("UTC") >= after:
                out.append(Event(int(event["RoundNumber"]), str(event["EventName"]), name == "Sprint"))
    return out


def remaining_events(con, year: int, after: pd.Timestamp) -> tuple[list[Event], list[str]]:
    """
    What is left of the season after `after`: what the lake holds, then the
    schedule for the rest. A past season is all in the lake and needs nothing
    else; the season in progress needs the schedule, which FastF1 caches.
    """
    known = lake_events(con, year, after)
    try:
        scheduled = calendar_events(year, after)
    except Exception as error:                       # noqa: BLE001 - offline is normal
        log.info("no schedule for %s: %s", year, error)
        scheduled = None
    if scheduled is None:
        if not _season_finished(con, year):
            raise NoCalendar(f"the rest of the {year} calendar is not known offline")
        return known, []
    seen = {(e.round, e.sprint) for e in known}
    merged = known + [e for e in scheduled if (e.round, e.sprint) not in seen]
    return sorted(merged, key=lambda e: (e.round, not e.sprint)), []


def _season_finished(con, year: int) -> bool:
    """A season whose next one has begun in the lake is over."""
    return bool(con.execute("select count(*) from sessions where year > ?", [int(year)]).fetchone()[0])


def field_pace(con, year: int, rnd: int, calibration: predict.Calibration) -> pd.DataFrame:
    """Each driver's pace and its uncertainty from the season's races before round `rnd`."""
    if not has_table(con, "laps"):                   # results alone: no form to read, everyone is the field
        return _NO_PACE.copy()
    form_s, _, _, _, carry_s, _ = weekend._form_and_carry(con, year, rnd)
    table = pd.DataFrame({"form_s": form_s, "carry_s": carry_s})
    for signal in predict.SIGNALS:
        if signal not in table:
            table[signal] = np.nan
    return predict.combine(table, calibration) if not table.empty else _NO_PACE.copy()


def entrants(con, year: int, before: pd.Timestamp | None) -> pd.DataFrame:
    """The current field: who started the latest Grand Prix, with their team."""
    df = standings.results(con, year)
    if before is not None and not df.empty:
        df = df[pd.to_datetime(df["date_utc"], utc=True) < before]
    races = df[df["code"] == "R"]
    if races.empty:
        return pd.DataFrame(columns=["driver_number", "abbreviation", "team_key", "team_name"])
    latest = races[races["session_key"] == races.sort_values("date_utc")["session_key"].iloc[-1]]
    return latest[["driver_number", "abbreviation", "team_key", "team_name"]].reset_index(drop=True)


# ------------------------------------------------------------------ simulation

def simulate_races(pace: np.ndarray, sd: np.ndarray, sprint: list[bool], noise: float, retire: float,
                   runs: int, rng: np.random.Generator) -> tuple[np.ndarray, np.ndarray]:
    """
    Points and Grand Prix wins per driver per simulated season, over the given
    events, as (runs x drivers) arrays. Single precision throughout: the
    answers are percentages, and it halves the memory.
    """
    n = len(pace)
    true = (pace[None, :] + rng.standard_normal((runs, n), dtype=np.float32) * sd[None, :]).astype(np.float32)
    points = np.zeros((runs, n), dtype=np.float32)
    wins = np.zeros((runs, n), dtype=np.int16)
    rows = np.arange(runs)[:, None]
    for is_sprint in sprint:
        perf = true + rng.standard_normal((runs, n), dtype=np.float32) * np.float32(noise)
        out = rng.random((runs, n), dtype=np.float32) < (retire * (SPRINT_SHARE if is_sprint else 1.0))
        perf[out] = np.inf
        order = np.argsort(perf, axis=1)                      # quickest first
        scale = SPRINT_POINTS if is_sprint else RACE_POINTS
        place_points = np.zeros(n, dtype=np.float32)
        place_points[:min(n, len(scale))] = scale[:n]
        earned = np.zeros((runs, n), dtype=np.float32)
        earned[rows, order] = place_points[None, :]
        earned[out] = 0.0
        points += earned
        if not is_sprint:
            finished_first = order[:, 0]
            valid = ~out[np.arange(runs), finished_first]
            wins[np.arange(runs)[valid], finished_first[valid]] += 1
    return points, wins


def champions(totals: np.ndarray, wins: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """The champion of each simulated season: most points, then most wins, then chance."""
    key = totals.astype(np.float64) * 1e4 + wins.astype(np.float64) + rng.random(totals.shape) * 0.5
    return np.argmax(key, axis=1)


# ------------------------------------------------------------------ the odds

def odds(con, year: int, as_of: pd.Timestamp | None = None, *, runs: int = DEFAULT_RUNS,
         uncertainty: dict | None = None, calibration: predict.Calibration | None = None,
         events: list[Event] | None = None, seed: int = 11) -> TitleOdds:
    """Each driver's and constructor's chance of the title, from the standings at `as_of`."""
    as_of = as_of if as_of is not None else pd.Timestamp.now(tz="UTC")
    table = standings.standings(con, year, as_of)
    notes = list(table.notes)
    if events is None:
        events, more = remaining_events(con, year, as_of)
        notes += more
    split = uncertainty or load_uncertainty()
    noise, share = float(split["race_noise_s"]), float(split["lasting_share"])
    cal = calibration or predict.load_calibration()
    field_now = entrants(con, year, as_of)
    next_round = events[0].round if events else (table.last["round"] + 1 if table.last else 1)
    known = field_pace(con, year, next_round, cal).reindex(field_now["driver_number"].astype(int))
    # A driver with no form yet (a stand-in, or the first race of a season) is the field, and as unsure.
    pace = known["pace"].fillna(0.0).to_numpy(np.float32)
    lasting = (known["sd"].fillna(cal.prior_sd) * share).to_numpy(np.float32)
    retire = predict.retire_rate(con, year, next_round)

    rng = np.random.default_rng(seed)
    if events and len(field_now):
        points, wins = simulate_races(pace, lasting, [e.sprint for e in events], noise, retire, runs, rng)
    else:
        points = np.zeros((runs, len(field_now)), dtype=np.float32)
        wins = np.zeros((runs, len(field_now)), dtype=np.int16)
    left = most_points_left(events)
    left_team = most_points_left(events, cars=2)
    remaining = [{"round": e.round, "event_name": e.event_name, "session": "sprint" if e.sprint else "Grand Prix"}
                 for e in events]
    drivers = _driver_odds(table, field_now, points, wins, left, rng)
    constructors = _constructor_odds(table, field_now, points, left, left_team, rng)
    if not events:
        notes.append("the season is over: these are the final standings")
    return TitleOdds(year=int(year), drivers=drivers, constructors=constructors, remaining=remaining,
                     runs=runs, race_noise_s=round(noise, 3), lasting_share=round(share, 3), notes=notes)


def _driver_odds(table: standings.Standings, field_now: pd.DataFrame, points: np.ndarray, wins: np.ndarray,
                 left: int, rng: np.random.Generator) -> list[dict]:
    # Everyone with points stays in the table; only the current field scores more.
    rows = {d["abbreviation"]: d for d in table.drivers}
    codes = list(rows) + [c for c in field_now["abbreviation"] if c not in rows]
    runs = points.shape[0]
    totals = np.zeros((runs, len(codes)), dtype=np.float32)
    all_wins = np.zeros((runs, len(codes)), dtype=np.int16)
    racing = {c: i for i, c in enumerate(field_now["abbreviation"])}
    for j, code in enumerate(codes):
        totals[:, j] = rows[code]["points"] if code in rows else 0
        all_wins[:, j] = rows[code]["wins"] if code in rows else 0
        if code in racing:
            totals[:, j] += points[:, racing[code]]
            all_wins[:, j] += wins[:, racing[code]]
    champion = champions(totals, all_wins, rng) if codes else np.array([], dtype=int)
    leader_now = max((rows[c]["points"] for c in rows), default=0)
    out = []
    for j, code in enumerate(codes):
        now = rows[code]["points"] if code in rows else 0
        most = now + (left if code in racing else 0)
        out.append({
            "abbreviation": code,
            "driver_number": rows[code]["driver_number"] if code in rows else int(
                field_now.loc[field_now["abbreviation"] == code, "driver_number"].iloc[0]),
            "points": now,
            "title": round(float((champion == j).mean()), 4) if len(champion) else 0.0,
            "expected_points": round(float(totals[:, j].mean()), 1),
            "p10": int(np.percentile(totals[:, j], 10)),
            "p90": int(np.percentile(totals[:, j], 90)),
            "max_points": most,
            # Can still at least draw level with today's leader: still in it, in arithmetic.
            "alive": bool(most >= leader_now),
        })
    out.sort(key=lambda d: (-d["title"], -d["points"]))
    return out


def _constructor_odds(table: standings.Standings, field_now: pd.DataFrame, points: np.ndarray, left: int,
                      left_team: int, rng: np.random.Generator) -> list[dict]:
    teams = {t["team"]: t for t in table.constructors}
    team_of = dict(zip(field_now["abbreviation"], field_now["team_name"]))
    names = list(teams) + [t for t in dict.fromkeys(field_now["team_name"]) if t not in teams]
    runs = points.shape[0]
    totals = np.zeros((runs, len(names)), dtype=np.float32)
    for j, name in enumerate(names):
        totals[:, j] = teams[name]["points"] if name in teams else 0
        for i, code in enumerate(field_now["abbreviation"]):
            if team_of[code] == name:
                totals[:, j] += points[:, i]
    winner = np.argmax(totals.astype(np.float64) + rng.random(totals.shape) * 0.5, axis=1) if names else np.array([])
    leader_now = max((t["points"] for t in teams.values()), default=0)
    cars = {name: sum(1 for t in team_of.values() if t == name) for name in names}
    out = []
    for j, name in enumerate(names):
        now = teams[name]["points"] if name in teams else 0
        most = now + (left_team if cars[name] >= 2 else left if cars[name] else 0)
        out.append({"team": name, "points": now, "title": round(float((winner == j).mean()), 4) if len(winner) else 0.0,
                    "expected_points": round(float(totals[:, j].mean()), 1), "max_points": int(most),
                    "alive": bool(most >= leader_now)})
    out.sort(key=lambda t: (-t["title"], -t["points"]))
    return out


# ------------------------------------------------------------------ fitting and replay

def measure(con, years: list[int], calibration: predict.Calibration | None = None) -> dict:
    """
    The two parts of a driver's pace uncertainty, from the races of `years`.

    * `race_noise_s`: a driver's race pace around their own average for the
      season, pooled over drivers with five races or more.
    * `lasting_share`: how far the form-based pace misses the driver's average
      over the rest of the season (the race-to-race part of that average taken
      out), as a share of the sd a single race's prediction states.
    """
    cal = calibration or predict.load_calibration()
    rows = predict.clipped(predict.training_rows(con, predict.race_keys(con, years))).reset_index()
    rows = rows.dropna(subset=["actual_s"])
    rows = rows[rows[["form_s", "carry_s"]].notna().any(axis=1)].copy()
    reading = rows[["form_s", "carry_s"]].assign(**{s: np.nan for s in predict.SIGNALS if s not in ("form_s", "carry_s")})
    est = predict.combine(reading, cal)
    rows["est"], rows["est_sd"] = est["pace"].to_numpy(), est["sd"].to_numpy()
    rows["round"] = rows["race_key"].str[5:7].astype(int)

    group = rows.groupby(["year", "driver_number"])["actual_s"]
    many = group.transform("size") >= MIN_RACES_LEFT
    spread = (rows["actual_s"] - group.transform("mean"))[many]
    dof = int((rows[many].groupby(["year", "driver_number"]).size() - 1).sum())
    race_sd = float(np.sqrt((spread ** 2).sum() / max(dof, 1)))

    misses, lefts = [], []
    for _, d in rows.sort_values("round").groupby(["year", "driver_number"]):
        actual = d["actual_s"].to_numpy()
        for i in range(len(d) - MIN_RACES_LEFT + 1):
            misses.append(d["est"].iloc[i] - actual[i:].mean())
            lefts.append(len(actual) - i)
    lasting_var = float(np.mean(np.square(misses)) - np.mean(race_sd ** 2 / np.array(lefts)))
    lasting_sd = float(np.sqrt(max(lasting_var, 0.0)))
    return {"race_noise_s": round(race_sd, 3), "lasting_share": round(lasting_sd / float(rows["est_sd"].mean()), 3),
            "lasting_sd_s": round(lasting_sd, 3), "stated_sd_s": round(float(rows["est_sd"].mean()), 3),
            "rows": int(len(rows)), "fitted_on": [str(y) for y in years]}


@dataclass
class Checkpoint:
    year: int
    after_round: int
    rounds: int
    champion: str
    model: float          # chance given to the eventual champion
    points_only: float    # the same with every driver's pace equal
    model_brier: float
    points_brier: float


def backtest(con, years: list[int], *, runs: int = 4_000, progress=None) -> tuple[list[Checkpoint], dict]:
    """
    Every season in `years` replayed from each round to the last: the title
    odds at that point, with the uncertainty measured on the other seasons,
    and the chance they gave the eventual champion, beside the same
    simulation with every driver's pace equal (what the points alone say).
    """
    cal = predict.load_calibration()
    noise_for = {year: measure(con, [y for y in years if y != year], cal) for year in years}
    out = []
    for year in years:
        sessions = con.execute("""select cast(round as integer) as round, min(date_utc) as start from sessions
                                  where year = ? and "session" in ('R', 'S') group by 1 order by 1""",
                               [int(year)]).df()
        final = standings.standings(con, year)
        champion = final.drivers[0]["abbreviation"]
        rounds = int(sessions["round"].max())
        for _, nxt in sessions.iloc[1:].iterrows():
            as_of = pd.Timestamp(nxt["start"]).tz_convert("UTC") if pd.Timestamp(nxt["start"]).tzinfo else \
                pd.Timestamp(nxt["start"]).tz_localize("UTC")
            events = lake_events(con, year, as_of)
            scored = []
            for flat in (False, True):
                o = odds(con, year, as_of, runs=runs, uncertainty=noise_for[year],
                         calibration=_flat(cal) if flat else cal, events=events)
                chance = {d["abbreviation"]: d["title"] for d in o.drivers}
                brier = sum((p - (code == champion)) ** 2 for code, p in chance.items())
                scored.append((chance.get(champion, 0.0), brier))
            out.append(Checkpoint(year, int(nxt["round"]) - 1, rounds, champion,
                                  scored[0][0], scored[1][0], scored[0][1], scored[1][1]))
            if progress:
                progress(year, int(nxt["round"]) - 1)
    return out, noise_for


def _flat(cal: predict.Calibration) -> predict.Calibration:
    """A calibration that reads nothing: every driver is the field's median, equally unsure."""
    return predict.Calibration(scale={}, noise_sd={}, prior_sd=cal.prior_sd, inflate=1.0)


def save_uncertainty(split: dict, path: Path = WEIGHTS_FILE) -> None:
    path.write_text(json.dumps(split, indent=2) + "\n", encoding="utf-8")


def most_points_left(events: list[Event], cars: int = 1) -> int:
    """The most one driver (or a team's `cars`) can still score: first (and second...) everywhere."""
    return int(sum((SPRINT_POINTS if e.sprint else RACE_POINTS)[:cars].sum() for e in events))
