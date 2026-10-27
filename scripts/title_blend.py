"""
Is the results-only title model worth showing, and is a blend of the two better than either?

Both models are replayed on 2023-2025, the seasons the lake has lap times for, at the
same checkpoints as `title.backtest` (the start of every Grand Prix and sprint after the
first). Each model's uncertainty is measured without the season being scored: the
lap-time model's on the other two lake seasons, the results-only model's on every other
f1db season. At each checkpoint every driver's chance is kept, so a blend
w x lap-time + (1 - w) x results-only can be scored for any w.

The blend's weight is chosen fairly: for each season, the w with the best Brier on the
other two, then scored on that one. A weight picked on the very seasons it is scored on
would only show how well it fits them.

    python scripts/title_blend.py [--runs 4000] [--out checkpoints.csv]
"""

from __future__ import annotations

import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from racecraft.model import predict, standings, title, title_history   # noqa: E402
from racecraft.store.db import connect                                  # noqa: E402

YEARS = [2023, 2024, 2025]
WEIGHTS = np.round(np.arange(0.0, 1.01, 0.1), 1)          # w on the lap-time model


def checkpoints(runs: int) -> pd.DataFrame:
    """One row per checkpoint and driver: both models' chances, and whether they became champion."""
    con = connect()
    cal = predict.load_calibration()
    lap_split = {y: title.measure(con, [x for x in YEARS if x != y], cal) for y in YEARS}
    history = title_history.seasons(list(range(1950, 2026)))
    stats = {s.year: title_history._season_stats(s) for s in history}
    res_split = {y: title_history.measure([v for k, v in stats.items() if k != y]) for y in YEARS}
    rows = []
    for year in YEARS:
        champion = standings.standings(con, year).drivers[0]["abbreviation"]
        starts = con.execute("""select cast(round as integer) as round, min(date_utc) as start from sessions
                                where year = ? and "session" in ('R', 'S') group by 1 order by 1""", [year]).df()
        rounds = int(starts["round"].max())
        for _, nxt in starts.iloc[1:].iterrows():
            at = pd.Timestamp(nxt["start"])
            at = at.tz_convert("UTC") if at.tzinfo else at.tz_localize("UTC")
            events = title.lake_events(con, year, at)
            lap = {d["abbreviation"]: d["title"] for d in
                   title.odds(con, year, at, runs=runs, uncertainty=lap_split[year], calibration=cal,
                              events=events).drivers}
            res = title_history.odds_now(con, year, at, events=events, split=res_split[year], runs=runs)
            for code in sorted(set(lap) | set(res)):
                rows.append({"year": year, "after_round": int(nxt["round"]) - 1, "rounds": rounds,
                             "driver": code, "champion": code == champion,
                             "lap": lap.get(code, 0.0), "results": res.get(code, 0.0)})
            print(f"  {year} after round {int(nxt['round']) - 1}", file=sys.stderr, flush=True)
    return pd.DataFrame(rows)


def score(table: pd.DataFrame, w: float) -> pd.DataFrame:
    """Per checkpoint: the chance the blend gave the champion, and its Brier over every driver."""
    p = w * table["lap"] + (1 - w) * table["results"]
    scored = table.assign(p=p, sq=(p - table["champion"]) ** 2)
    return scored.groupby(["year", "after_round", "rounds"]).apply(
        lambda g: pd.Series({"champion_chance": g.loc[g["champion"], "p"].sum(), "brier": g["sq"].sum()}),
        include_groups=False).reset_index()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=int, default=4_000)
    ap.add_argument("--out", help="write every checkpoint and driver here as CSV")
    args = ap.parse_args()
    table = checkpoints(args.runs)
    if args.out:
        table.to_csv(args.out, index=False)

    by_w = {w: score(table, w) for w in WEIGHTS}
    sweep = pd.DataFrame({w: s[["champion_chance", "brier"]].mean() for w, s in by_w.items()}).T
    sweep.index.name = "w (lap-time share)"
    print("\nEvery weight on all three seasons (w = 1 is the lap-time model alone, 0 the results-only)")
    print(sweep.round(3).to_string())

    # The fair blend: each season scored with the weight best on the other two.
    fair, chosen = [], {}
    for year in YEARS:
        others = {w: s.loc[s["year"] != year, "brier"].mean() for w, s in by_w.items()}
        chosen[year] = min(others, key=others.get)
        fair.append(by_w[chosen[year]].loc[lambda s: s["year"] == year])
    fair = pd.concat(fair)
    print("\nWeight chosen on the other two seasons:", chosen)

    summary = pd.DataFrame({
        "lap-time alone": by_w[1.0].groupby("year")[["champion_chance", "brier"]].mean().stack(),
        "results-only alone": by_w[0.0].groupby("year")[["champion_chance", "brier"]].mean().stack(),
        "50/50 blend": by_w[0.5].groupby("year")[["champion_chance", "brier"]].mean().stack(),
        "fair blend": fair.groupby("year")[["champion_chance", "brier"]].mean().stack(),
    })
    print("\nBy season: chance given to the champion (higher is better) and Brier (lower is better)")
    print(summary.round(3).to_string())
    overall = pd.DataFrame({name: s[["champion_chance", "brier"]].mean() for name, s in
                            {"lap-time alone": by_w[1.0], "results-only alone": by_w[0.0],
                             "50/50 blend": by_w[0.5], "fair blend": fair}.items()}).T
    print(f"\nAll {len(fair)} checkpoints")
    print(overall.round(3).to_string())

    # Where the two disagree, which was right more often?
    lap_b, res_b = by_w[1.0]["brier"].to_numpy(), by_w[0.0]["brier"].to_numpy()
    print(f"\nCheckpoints where results-only beat lap-time on Brier: {(res_b < lap_b).sum()}, "
          f"lap-time beat results-only: {(lap_b < res_b).sum()}, level: {(lap_b == res_b).sum()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
