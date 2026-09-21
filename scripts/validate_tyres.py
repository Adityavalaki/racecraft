"""
How much does racing a car's own tyres change the answer?

The simulator used to give every stint a new set. It now starts each stint on
the set the car would really use, at the age that set already carries, and
drops plans it has no sets for. This asks what that is worth: for every race in
a season and several grid slots, the same study is run twice — once on the sets
that car actually had at the start, once on new ones — and the two are compared.

Both are held out: the sets come from the weekend's earlier sessions, so
everything here was knowable before the lights went out.

A ranking has noise on it, and at these run counts two plans a tenth of a place
apart cannot be told apart. So "the best plan changed" is not enough: a change
counts here only when following the new-tyre answer costs more, on the car's own
tyres, than the error bars on the two finishes together. Without that test the
figure mostly measures the simulator's own scatter.

    python scripts/validate_tyres.py            # 2025, three grid slots
    python scripts/validate_tyres.py 2024 --grids 8
"""

from __future__ import annotations

import argparse
import sys

import numpy as np

from racecraft.model import places, race_inputs
from racecraft.store.db import connect

RUNS = 120
PLANS = 8
DRAWS = 8


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("season", nargs="?", type=int, default=2025)
    ap.add_argument("--grids", type=int, nargs="+", default=[4, 10, 16])
    ap.add_argument("--runs", type=int, default=RUNS)
    args = ap.parse_args(argv)

    con = connect()
    races = con.sql(f"""select session_key, location, event_name from sessions
                        where year = {args.season} and "session" = 'R' order by round""").fetchall()

    rows, skipped = [], []
    for key, location, name in races:
        try:
            inputs = race_inputs.build(con, location, args.season, session_key=key)
        except race_inputs.NotEnoughData as error:
            skipped.append(f"{name}: {error}")
            continue
        for grid in args.grids:
            stock = race_inputs.tyre_stock(con, key, grid=grid)
            if stock is None:
                skipped.append(f"{name} P{grid}: nobody started there")
                continue
            own = places.study(inputs, grid, plans=PLANS, runs=args.runs, field_draws=DRAWS,
                               stock=stock.left)
            fresh = places.study(inputs, grid, plans=PLANS, runs=args.runs, field_draws=DRAWS)
            if not own.ranking or not fresh.ranking:
                skipped.append(f"{name} P{grid}: no plans to race")
                continue
            by_plan = {str(e.plan): e for e in fresh.ranking}
            best_own, best_fresh = str(own.ranking[0].plan), str(fresh.ranking[0].plan)
            # The new-tyre pick, raced on the tyres the car actually had.
            as_raced = next((e for e in own.ranking if str(e.plan) == best_fresh), None)
            noise = float(np.hypot(own.ranking[0].std_error,
                                   as_raced.std_error if as_raced else own.ranking[0].std_error))
            rows.append({
                "race": name, "grid": grid, "driver": stock.driver,
                "new_sets": sum(held["new"] for held in stock.left.values()),
                "changed": best_own != best_fresh,
                "dropped": len(own.dropped),
                "places_lost": own.ranking[0].mean_finish - fresh.ranking[0].mean_finish,
                # What following the ideal-tyre answer would have cost, on the
                # tyres the car actually had.
                "cost_of_ignoring": None if as_raced is None else as_raced.mean_finish,
                # Worse by more than the two error bars together, or not runnable at all.
                "changed_beyond_noise": (as_raced is None or
                                         as_raced.mean_finish - own.ranking[0].mean_finish > noise),
                "noise": noise,
                "best_own_finish": own.ranking[0].mean_finish,
                "worn": any(any(e.start_ages) for e in own.ranking),
                "tied_span": own.ranking[0].std_error,
                "fresh_has": best_fresh in {str(e.plan) for e in own.ranking},
            })
            print(f"  {name:<28} P{grid:<3} {stock.driver:<4} "
                  f"own {best_own:<22} new {best_fresh:<22} "
                  f"{'changed' if best_own != best_fresh else ''}")

    if not rows:
        print("nothing to compare")
        return 1

    changed = [r for r in rows if r["changed"]]
    worn = [r for r in rows if r["worn"]]
    costs = [r["cost_of_ignoring"] - r["best_own_finish"] for r in rows
             if r["cost_of_ignoring"] is not None]

    print(f"\n{len(rows)} car-races in {args.season}, each studied twice")
    print(f"  started on at least one used set        {len(worn)} ({len(worn) / len(rows):.0%})")
    print(f"  best plan changed with the real tyres   {len(changed)} ({len(changed) / len(rows):.0%})")
    real = [r for r in rows if r["changed_beyond_noise"]]
    print(f"  ...beyond the error bars on both          {len(real)} ({len(real) / len(rows):.0%})")
    print(f"  plans ruled out for want of a set       {sum(r['dropped'] for r in rows)}")
    print(f"  places given up to worn tyres, mean     {np.mean([r['places_lost'] for r in rows]):+.2f}")
    if costs:
        print(f"  cost of following the new-tyre answer   {np.mean(costs):+.2f} places, "
              f"worst {max(costs):+.2f}")
    print(f"  the new-tyre pick was not even runnable {sum(1 for r in rows if not r['fresh_has'])}")

    print("\nwhere the answer changed most:")
    for row in sorted(changed, key=lambda r: -(r["cost_of_ignoring"] or 0) + r["best_own_finish"])[:8]:
        gap = (row["cost_of_ignoring"] or row["best_own_finish"]) - row["best_own_finish"]
        print(f"  {row['race']:<28} P{row['grid']:<3} {row['driver']:<4} "
              f"{row['new_sets']} new sets, {gap:+.2f} places")

    if skipped:
        print(f"\nnot compared ({len(skipped)}):")
        for line in skipped[:10]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
