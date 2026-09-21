"""
Does knowing *when* safety cars arrive make the ranking better?

The safety-car ranking treats a neutralisation as equally likely on every lap.
It is not: across the lake a quarter of them begin in the opening tenth of a
race, where a car has run too few laps for a cheap stop to be worth taking. A
flat rate therefore promises a discount that the early ones cannot deliver, and
that should show up as overvaluing a long first stint.

This scores three rankings against what the field actually did — how many times
the cars stopped, and the lap they first stopped on — for every race that can be
studied held out:

* green      tyres and pit lane only, no luck
* flat       safety cars at one rate for the whole race
* measured   the same rate, shaped by when they really arrive

    python scripts/validate_safety_car_timing.py            # 2025 and 2026
"""

from __future__ import annotations

import argparse
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from racecraft.model import race_inputs, simulate, strategy            # noqa: E402
from racecraft.store.db import connect                                 # noqa: E402

KEEP = 4
MIN_STINT = 10


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seasons", type=int, nargs="+", default=[2025, 2026])
    args = ap.parse_args(argv)

    con = connect()
    rows, wet = [], []
    for season in args.seasons:
        races = con.sql(f"""select session_key, location, event_name from sessions
                            where year = {season} and "session" = 'R' order by round""").fetchall()
        for key, location, name in races:
            try:
                inputs = race_inputs.build(con, location, season, session_key=key)
            except race_inputs.NotEnoughData:
                continue
            # A wet race is scored on a different sport: the stops it ran say
            # nothing about a dry plan, for any of the three rankings.
            if race_inputs._wet_share(con, key) >= race_inputs.WET_SHARE:
                wet.append(name)
                continue
            ran = con.sql(f"""select median(stops) from (
                                select driver_number, max(stint) - 1 as stops from laps
                                where session_key = '{key}'
                                  and compound in ('SOFT', 'MEDIUM', 'HARD')
                                group by driver_number)""").fetchone()[0]
            if ran is None:
                continue
            # The lap the field actually first stopped on: the length of each
            # car's opening stint, taken as a median over the cars that stopped.
            stopped_on = con.sql(f"""select median(first_stint) from (
                                       select driver_number, count(*) as first_stint from laps
                                       where session_key = '{key}' and stint = 1
                                         and compound in ('SOFT', 'MEDIUM', 'HARD')
                                       group by driver_number
                                       having max(stint) is not null)""").fetchone()[0]

            green = strategy.best_plans(inputs.total_laps, inputs.degradation, inputs.pit_loss_s,
                                        max_stops=2, min_stint=MIN_STINT, step=3, top=1,
                                        compound_offset_s=inputs.compound_offset_s,
                                        min_stops=inputs.min_stops)
            flat = simulate.Neutralisation.for_circuit(inputs.periods_per_race, inputs.total_laps)
            ranked = {}
            for label, neutralisation in (("flat", flat), ("measured", inputs.neutralisation)):
                best = simulate.rank_with_risk(inputs.total_laps, inputs.degradation,
                                               inputs.pit_loss_s, neutralisation,
                                               inputs.compound_offset_s, keep=KEEP,
                                               min_stint=MIN_STINT, min_stops=inputs.min_stops)
                ranked[label] = best[0].plan if best else None
            if not green or ranked["flat"] is None or ranked["measured"] is None:
                continue
            first = {label: plan.stints[0][1] for label, plan in ranked.items()}
            rows.append({"season": season, "race": name, "ran": float(ran),
                         "green": green[0].plan.stops,
                         "flat": ranked["flat"].stops, "measured": ranked["measured"].stops,
                         "flat_stop": first["flat"], "measured_stop": first["measured"],
                         "stopped_on": None if stopped_on is None else float(stopped_on),
                         "laps": inputs.total_laps})
            print(f"  {name:<28} ran {ran:>4.1f}   green {green[0].plan.stops}   "
                  f"flat {ranked['flat']} | measured {ranked['measured']}")

    if wet:
        print()
        print(f"not scored, ran wet: {', '.join(wet)}")
    df = pd.DataFrame(rows)
    if df.empty:
        print("nothing to score")
        return 1

    print(f"\n{len(df)} races scored against the stops the field actually ran\n")
    print("mean error in stops (lower is better):")
    for column in ("green", "flat", "measured"):
        error = (df[column] - df.ran).abs()
        bias = (df[column] - df.ran).mean()
        print(f"  {column:<9} {error.mean():.3f}   bias {bias:+.3f}   "
              f"exact {(error < 0.5).sum()}/{len(df)}")
    moved = (df.flat != df.measured).sum()
    print()
    print(f"the timing changed the stop count in {moved} of {len(df)} races")

    # Where it should show, if anywhere: a flat rate promises a discount the
    # early neutralisations cannot deliver, so it should stop later than it ought.
    shift = df.measured_stop - df.flat_stop
    print(f"first stop lap, measured against flat: {shift.mean():+.1f} laps on average, "
          f"moved in {(shift != 0).sum()} of {len(df)} races")

    # The test that decides it: which is closer to the lap the field stopped on.
    scored = df[df.stopped_on.notna()]
    if not scored.empty:
        print(f"\nagainst the lap the field actually first stopped ({len(scored)} races):")
        for column in ("flat_stop", "measured_stop"):
            error = (scored[column] - scored.stopped_on).abs()
            bias = (scored[column] - scored.stopped_on).mean()
            print(f"  {column.replace('_stop', ''):<9} {error.mean():.1f} laps out   "
                  f"bias {bias:+.1f}")
    if (shift != 0).any():
        print(df[shift != 0][["season", "race", "laps", "flat_stop", "measured_stop"]]
              .to_string(index=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
