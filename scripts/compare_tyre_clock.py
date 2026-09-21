"""
Does a set's whole life explain lap times, or only the laps of this stint?

Everything the simulator does with used tyres rests on one choice: wear is
counted against `tyre_life`, the laps a set has done across the whole weekend,
rather than `laps_in_stint`, the laps it has done since it was fitted. If the
second clock fitted the data better, a set from qualifying would behave like a
new one, and charging a car for the laps already on it would be inventing a
penalty.

So both clocks are fitted, to the same races, with the same model and the same
number of terms — lap times against driver, lap of the race, compound and age —
and scored on what is left over.

    python scripts/compare_tyre_clock.py
"""

from __future__ import annotations

import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from racecraft.model import pace                      # noqa: E402
from racecraft.store.db import connect                # noqa: E402

MIN_LAPS = 200


def main() -> int:
    con = connect()
    races = con.sql("""select session_key, year, event_name from sessions
                       where "session" = 'R' order by year, round""").df()
    rows = []
    for race in races.itertuples(index=False):
        laps = con.sql(f"select * from laps where session_key = '{race.session_key}'").df()
        clean = pace.clean_race_laps(laps)
        if len(clean) < MIN_LAPS:
            continue
        # How much of the difference there is to find: a stint on a used set is
        # the only place the two clocks disagree.
        carried = clean["tyre_life"] - clean["laps_in_stint"]
        if carried.max() <= 0:
            continue
        try:
            whole_life = pace.fit_lap_effects(clean)
            this_stint = pace.fit_lap_effects(clean.assign(tyre_life=clean["laps_in_stint"]))
        except (pace.Confounded, ValueError):
            continue
        rows.append({
            "year": race.year, "race": race.event_name,
            "laps_carried_in": float(carried[carried > 0].mean()),
            "share_carried": float((carried > 0).mean()),
            "whole_life": whole_life.residual_std_s,
            "this_stint": this_stint.residual_std_s,
            "whole_life_r2": whole_life.r_squared,
            "this_stint_r2": this_stint.r_squared,
        })

    df = pd.DataFrame(rows)
    if df.empty:
        print("no races with any laps carried into a stint")
        return 1

    wins = (df.whole_life < df.this_stint).sum()
    print(f"{len(df)} races, {df.share_carried.mean():.0%} of laps run on a set that had "
          f"laps on it already ({df.laps_carried_in.mean():.1f} laps carried in on average)\n")
    print("what is left over after the fit, seconds a lap (lower is the better clock):")
    print(f"  the set's whole life   {df.whole_life.mean():.4f}   R2 {df.whole_life_r2.mean():.3f}")
    print(f"  laps in this stint     {df.this_stint.mean():.4f}   R2 {df.this_stint_r2.mean():.3f}")
    print(f"\nthe set's whole life fits better in {wins} of {len(df)} races")
    print("\nby season:")
    print(df.groupby("year")[["whole_life", "this_stint"]].mean().round(4).to_string())
    gap = (df.this_stint - df.whole_life)
    print(f"\ngap per race: mean {gap.mean():+.4f}s, worst against it {gap.min():+.4f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
