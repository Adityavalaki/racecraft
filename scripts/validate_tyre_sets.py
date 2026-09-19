"""
How often the tyre-set tracker is right about what a car had for the race.

For every car in every race in the lake, take what the tracker says it held at
the start of the race — built only from the sessions before it — and check
every set the car then ran in the race against it:

* a set the race opened new must have been one of the new sets left, and
* a used set must have been one the tracker kept, not one it assumed was
  handed back to Pirelli after practice.

Anything else is the tracker being wrong, and it is counted.

    python scripts/validate_tyre_sets.py
"""

from __future__ import annotations

import collections
import sys

from racecraft.model import tyre_sets
from racecraft.store.db import connect


def main() -> int:
    con = connect()
    weekends = con.sql("""select distinct year, round from sessions where "session" = 'R'
                          order by 1, 2""").fetchall()
    counts = collections.Counter()
    wrong: list[str] = []
    by_format = collections.defaultdict(collections.Counter)

    for year, rnd in weekends:
        weekend = tyre_sets.from_lake(con, year, rnd)
        if "R" not in weekend.sessions:
            continue
        for number, car in weekend.cars.items():
            holding = weekend.holding(number, "R")
            counts["cars"] += 1
            by_format[weekend.allocation_name]["cars"] += 1
            rules = weekend.rules
            expected = (sum(weekend.allocation.values()) - sum(n for _, n, _ in rules.returns)
                        - (1 if rules.q3_returns_soft and number in weekend.q3_cars else 0))
            by_format[weekend.allocation_name][holding.total - expected] += 1
            kept = {s.number for s, _ in holding.used}
            returned = {r.set.number for r in holding.returned}
            opened = collections.Counter()
            for tyre in car.sets:
                if not any(run.session == "R" for run in tyre.runs):
                    continue
                counts["race sets"] += 1
                if tyre.first_session() == "R" and tyre.seen_new:
                    opened[tyre.compound] += 1
                    counts["opened new"] += 1
                elif tyre.number in kept:
                    counts["used, kept"] += 1
                elif tyre.number in returned:
                    counts["used, but assumed handed back"] += 1
                    wrong.append(f"{year} R{rnd:02d} {car.driver}: {tyre.compound.lower()} set "
                                 f"assumed handed back, then raced")
                else:
                    counts["used, not seen before"] += 1
            for compound, n in opened.items():
                if n > max(holding.new[compound], 0):
                    counts["opened more new than left"] += n - max(holding.new[compound], 0)
                    wrong.append(f"{year} R{rnd:02d} {car.driver}: opened {n} new "
                                 f"{compound.lower()}, tracker said {max(holding.new[compound], 0)}")

    print(f"{counts['cars']} cars at the start of {len(weekends)} races\n")
    print(f"sets raced                       {counts['race sets']}")
    for label in ("opened new", "used, kept", "used, but assumed handed back",
                  "used, not seen before", "opened more new than left"):
        print(f"  {label:<31}{counts[label]:>5}")
    bad = counts["used, but assumed handed back"] + counts["opened more new than left"]
    print(f"\nright about {1 - bad / counts['race sets']:.1%} of the sets raced")

    print("\nsets held at the start of the race:")
    for name, tally in by_format.items():
        cars = tally.pop("cars")
        spread = ", ".join(f"{k}: {v}" for k, v in sorted(tally.items()))
        print(f"  {name:<30} {cars} cars   {spread}")

    if wrong:
        print(f"\nwhere it was wrong (first 20 of {len(wrong)}):")
        for line in wrong[:20]:
            print("  " + line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
