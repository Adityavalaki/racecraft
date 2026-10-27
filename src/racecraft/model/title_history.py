"""
The title odds from results alone, for seasons the lake does not hold (D-017).

`title` reads each driver's pace from lap times, which the lake has only from 2023. f1db
(D-016) has every championship since 1950 but only results, so here a driver's form is
their average finishing place so far that season. Its uncertainty is measured the way
`title.measure` measures it, in places rather than seconds: how far a finish strays race to
race around the driver's season average, and how far the early average misses the rest of
the season (beyond what that sampling alone explains). The races are `title.simulate_races`
with the season's own points; the champion is `title.champions`.

shortcut: no dropped scores (best-N results counted until 1990), no fastest-lap or shared-
drive points. The champion scored against is still the official one, so a season settled by
dropped scores counts against the model; upgrade if those seasons score badly.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from racecraft.ingest import f1db_source
from racecraft.model import title

MIN_RACES_LEFT = title.MIN_RACES_LEFT


@dataclass
class Season:
    year: int
    rounds: list[int]                  # in order
    sprint: dict[int, bool]            # round -> had a sprint
    results: pd.DataFrame              # round, kind ('R'|'S'), driver, place (NaN if not classified), points
    standings: pd.DataFrame            # round, driver, points: after that round, as published
    champion: str
    race_points: np.ndarray            # this season's points for 1st, 2nd, ...
    sprint_points: np.ndarray


def _scale(results: pd.DataFrame) -> np.ndarray:
    """The season's points by place: the most common award for each place, up to the last that scored."""
    scored = results[results["place"].notna() & (results["points"] > 0)]
    if scored.empty:
        return np.zeros(0, dtype=np.float32)
    by_place = scored.groupby("place")["points"].agg(lambda p: p.mode().iloc[0])
    last = int(by_place.index.max())
    return np.array([by_place.get(float(i), 0.0) for i in range(1, last + 1)], dtype=np.float32)


def seasons(years: list[int] | None = None, into=None) -> list[Season]:
    """Each season in f1db (or those in `years`) with a known champion, ready to replay."""
    races = f1db_source.load("races", into)
    results = []
    for kind, name in (("R", "race_results"), ("S", "sprint_results")):
        df = f1db_source.load(name, into)
        # A shared drive splits one car's result; keep each driver's own line, its points as given.
        results.append(pd.DataFrame({"year": df["year"], "round": df["round"], "kind": kind, "driver": df["driverId"],
                                     "place": pd.to_numeric(df["positionNumber"], errors="coerce"),
                                     "points": df["points"].fillna(0.0)}))
    results = pd.concat(results, ignore_index=True)
    standings = f1db_source.load("standings", into)
    final = f1db_source.load("season_standings", into)
    champions = final[final["championshipWon"].astype(bool)].set_index("year")["driverId"]
    out = []
    for year, mine in races.groupby("year"):
        if years is not None and year not in years or year not in champions.index:
            continue
        r = results[results["year"] == year]
        st = standings[standings["year"] == year]
        out.append(Season(
            year=int(year), rounds=sorted(int(x) for x in mine["round"]),
            sprint={int(x.round): bool(x.has_sprint) for x in mine.itertuples()},
            results=r.drop(columns="year").reset_index(drop=True),
            standings=pd.DataFrame({"round": st["round"], "driver": st["driverId"], "points": st["points"]}),
            champion=str(champions[year]),
            race_points=_scale(r[r["kind"] == "R"]), sprint_points=_scale(r[r["kind"] == "S"])))
    return out


# ------------------------------------------------------------------ uncertainty

def _season_stats(season: Season) -> dict:
    """Sums for the two measurements, so leaving a season out is a subtraction."""
    gp = season.results[(season.results["kind"] == "R") & season.results["place"].notna()]
    by_driver = [g.sort_values("round")["place"].to_numpy(float) for _, g in gp.groupby("driver")]
    spread = [(p - p.mean()) ** 2 for p in by_driver if len(p) >= MIN_RACES_LEFT]
    stats = {"ss": float(sum(s.sum() for s in spread)), "dof": int(sum(len(s) - 1 for s in spread)),
             "miss2": [], "so_far": [], "left": []}
    for p in by_driver:
        for k in range(1, len(p) - MIN_RACES_LEFT + 1):
            stats["miss2"].append((p[:k].mean() - p[k:].mean()) ** 2)
            stats["so_far"].append(k)
            stats["left"].append(len(p) - k)
    return stats


def measure(stats: list[dict]) -> dict:
    """
    Race-to-race noise (places), and the lasting part of how far a driver's
    early average misses the rest of their season, both pooled over `stats`.
    The early average's own sampling (noise² / races so far) is left in the
    model as such, so only what is beyond it and the rest's sampling is lasting.
    """
    noise = float(np.sqrt(sum(s["ss"] for s in stats) / max(sum(s["dof"] for s in stats), 1)))
    miss2 = np.concatenate([np.asarray(s["miss2"], float) for s in stats])
    so_far = np.concatenate([np.asarray(s["so_far"], float) for s in stats])
    left = np.concatenate([np.asarray(s["left"], float) for s in stats])
    lasting2 = float(np.mean(miss2 - noise ** 2 / so_far - noise ** 2 / left))
    return {"race_noise": round(noise, 3), "lasting_sd": round(float(np.sqrt(max(lasting2, 0.0))), 3)}


# ------------------------------------------------------------------ the odds

def odds_after(season: Season, after: int, split: dict, *, flat: bool = False, runs: int = 4_000,
               seed: int = 11) -> dict[str, float]:
    """Each driver's chance of the title after round `after`: published points, the rest simulated.
    `flat` gives every driver the same form: what the points alone say."""
    rng = np.random.default_rng(seed)
    done = season.results[season.results["round"] <= after]
    gp_done = done[done["kind"] == "R"]
    field = list(dict.fromkeys(gp_done.loc[gp_done["round"] == after, "driver"]))
    now = season.standings[season.standings["round"] == after].set_index("driver")["points"]
    drivers = list(dict.fromkeys(list(now.index) + field))

    finishes = gp_done[gp_done["place"].notna()].groupby("driver")["place"]
    mean, count = finishes.mean(), finishes.size()
    noise, base = float(split["race_noise"]), float(split["lasting_sd"])
    form = pd.Series(mean, index=field).fillna(mean.median() if len(mean) else 0.0)
    known = pd.Series(count, index=field).fillna(0.0)
    pace = np.zeros(len(field), np.float32) if flat else form.to_numpy(np.float32)
    # The lasting doubt, plus the early average's own sampling (none known: as unsure as one race).
    sd = np.sqrt(base ** 2 + noise ** 2 / np.maximum(known.to_numpy(float), 1.0)).astype(np.float32)
    retire = float(gp_done["place"].isna().mean()) if len(gp_done) else 0.0

    events = []
    for rnd in (r for r in season.rounds if r > after):
        events += ([True] if season.sprint.get(rnd) else []) + [False]
    points = np.zeros((runs, len(field)), np.float32)
    wins = np.zeros((runs, len(field)), np.int16)
    if events and field:
        points, wins = title.simulate_races(pace, sd, events, noise, retire, runs, rng,
                                            race_points=season.race_points, sprint_points=season.sprint_points)
    totals = np.zeros((runs, len(drivers)), np.float32)
    all_wins = np.zeros((runs, len(drivers)), np.int16)
    won = gp_done[gp_done["place"] == 1].groupby("driver").size()
    column = {d: i for i, d in enumerate(field)}
    for j, driver in enumerate(drivers):
        totals[:, j] = float(now.get(driver, 0.0))
        all_wins[:, j] = int(won.get(driver, 0))
        if driver in column:
            totals[:, j] += points[:, column[driver]]
            all_wins[:, j] += wins[:, column[driver]]
    champion = title.champions(totals, all_wins, rng)
    return {driver: float((champion == j).mean()) for j, driver in enumerate(drivers)}


def backtest(all_seasons: list[Season], *, runs: int = 2_000, progress=None) -> tuple[list[title.Checkpoint], dict]:
    """
    Every season replayed from each round to the last, as `title.backtest` does,
    with the uncertainty measured on every other season: the chance given to the
    official champion, beside what the points alone say.
    """
    stats = {s.year: _season_stats(s) for s in all_seasons}
    out, split_for = [], {}
    for season in all_seasons:
        split = split_for[season.year] = measure([v for y, v in stats.items() if y != season.year])
        last = season.rounds[-1]
        for after in season.rounds[:-1]:
            scored = []
            for flat in (False, True):
                chance = odds_after(season, after, split, flat=flat, runs=runs)
                brier = sum((p - (d == season.champion)) ** 2 for d, p in chance.items())
                scored.append((chance.get(season.champion, 0.0), brier))
            out.append(title.Checkpoint(season.year, after, last, season.champion,
                                        scored[0][0], scored[1][0], scored[0][1], scored[1][1]))
        if progress:
            progress(season.year)
    return out, split_for
