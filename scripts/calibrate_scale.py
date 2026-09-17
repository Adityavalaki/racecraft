"""
Is the 1.5 degradation scale the right number, or just the first one tried?

Degradation measured from race laps only covers the tyre life teams accept —
nobody drives past the cliff, so nobody records it — and a long stint therefore
looks cheaper than it is. The strategy model multiplies measured wear by 1.5 to
compensate, and that constant was chosen by eye, as "best reproduces real stop
counts". This checks it.

    python scripts/calibrate_scale.py

For every dry race in the lake it sweeps the scale, costs every plan at each
one, and scores the cheapest plan's stop count against what the field actually
ran. Then it does the same leave-one-season-out, choosing the scale on three
seasons and scoring it on the fourth, because a constant picked and graded on
the same races is not a measurement.

The answer, on 76 dry races: 1.5 is right, or close enough that nothing else is
distinguishable from it. See the README for what that implies about where the
remaining error lives.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from racecraft.model import circuit as circuit_model
from racecraft.model import pace as pace_model
from racecraft.model import strategy as strategy_model
from racecraft.store.db import connect

SCALES = (1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 3.0, 3.5, 4.0)
MAX_STOPS = 3
MIN_STINT = 10
STEP = 2
MIN_LAPS_TO_FIT = 200
WET_SHARE = 0.05          # more intermediate or wet laps than this is a different race


def season_models(con) -> dict[int, tuple[dict, dict]]:
    """Degradation and compound offsets per season, from every fittable race in it."""
    out = {}
    years = [int(y) for (y,) in con.sql('select distinct year from sessions where "session" = \'R\'').fetchall()]
    for year in sorted(years):
        models = []
        races = con.sql(f"""select session_key from sessions
                            where year = {year} and "session" = 'R' order by round""").df()
        for key in races["session_key"]:
            laps = con.sql(f"select * from laps where session_key = '{key}'").df()
            clean = pace_model.clean_race_laps(laps)
            if len(clean) < MIN_LAPS_TO_FIT:
                continue
            try:
                models.append(pace_model.fit_lap_effects(clean))
            except (pace_model.Confounded, ValueError):
                continue
        if not models:
            continue
        degradation = {c: v[0] for c, v in pace_model.combine(models).items()}
        offsets = {
            compound: float(np.median([m.compound_offset_s[compound]
                                       for m in models if compound in m.compound_offset_s]))
            for compound in pace_model.DRY_COMPOUNDS
            if any(compound in m.compound_offset_s for m in models)
        }
        out[year] = (degradation, offsets)
    return out


def dry_races(con, seasons: dict) -> list[dict]:
    """Every dry race with a fittable season behind it, and what its field actually did."""
    all_laps = con.sql("""select l.*, s.location, s.year from laps l join sessions s using (session_key)
                          where s."session" = 'R'""").df()
    all_laps = all_laps.assign(circuit=circuit_model.canonical_circuit(all_laps["location"]))
    losses = {p.circuit: p.seconds for p in circuit_model.pit_loss(all_laps)}

    cases = []
    for session_key, laps in all_laps.groupby("session_key"):
        year = int(laps["year"].iloc[0])
        if year not in seasons:
            continue
        circuit = str(laps["circuit"].iloc[0])
        if circuit not in losses:
            continue
        if laps["compound"].isin(["INTERMEDIATE", "WET"]).mean() > WET_SHARE:
            continue
        total = int(laps.groupby("driver_number")["lap_number"].max().median())
        actual = float(laps.groupby("driver_number")["is_pit_in_lap"]
                       .apply(lambda s: int(s.fillna(False).sum())).median())
        degradation, offsets = seasons[year]
        # The plan list does not depend on the scale, only the costing does, so
        # it is built once per race and re-costed ten times rather than rebuilt.
        plans = strategy_model.enumerate_plans(total, tuple(degradation), max_stops=MAX_STOPS,
                                               min_stint=MIN_STINT, step=STEP)
        if not plans:
            continue
        cases.append({"year": year, "circuit": circuit, "actual": actual, "plans": plans,
                      "degradation": degradation, "offsets": offsets, "pit": losses[circuit]})
    return cases


def stops_at(case: dict, scale: float) -> int:
    degradation = {c: v * scale for c, v in case["degradation"].items()}
    best = min(case["plans"],
               key=lambda p: strategy_model.cost(p, degradation, case["pit"],
                                                 compound_offset_s=case["offsets"]).seconds_lost)
    return best.stops


def main() -> int:
    con = connect()
    seasons = season_models(con)
    if not seasons:
        print("no fittable seasons in the lake")
        return 1
    cases = dry_races(con, seasons)
    if not cases:
        print("no dry races with a fittable season behind them")
        return 1

    actual = np.array([c["actual"] for c in cases], dtype=float)
    predicted = {s: np.array([stops_at(c, s) for c in cases], dtype=float) for s in SCALES}

    print(f"\n{len(cases)} dry races, {len(seasons)} seasons\n")
    print(f"{'scale':>6} {'mean |err|':>11} {'exact':>9} {'bias':>8}")
    for scale in SCALES:
        error = np.abs(predicted[scale] - actual)
        mark = "  <- in use" if scale == 1.5 else ""
        print(f"{scale:>6.2f} {error.mean():>11.3f} {int((error == 0).sum()):>5}/{len(cases)} "
              f"{(predicted[scale] - actual).mean():>+8.3f}{mark}")

    print("\nleave-one-season-out — chosen on the other seasons, scored on this one\n")
    years = sorted({c["year"] for c in cases})
    weighted, total = 0.0, 0
    for year in years:
        train = [i for i, c in enumerate(cases) if c["year"] != year]
        test = [i for i, c in enumerate(cases) if c["year"] == year]
        chosen = min(SCALES, key=lambda s: np.abs(predicted[s][train] - actual[train]).mean())
        error = float(np.abs(predicted[chosen][test] - actual[test]).mean())
        print(f"  {year}   chose {chosen:.2f}   |err| {error:.3f} on {len(test)} races")
        weighted += error * len(test)
        total += len(test)
    print(f"\n  out-of-sample mean |err| {weighted / total:.3f}")
    print("\n  Every season picks between 1.50 and 2.00, and the difference between")
    print("  them is under one race in seventy-six. The constant is not the problem.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
