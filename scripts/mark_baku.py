"""Mark the Baku pre-race call against the race that actually happened.

The five predictions were published on 16 September 2026, ten days before the
race, at https://claude.ai/artifact/5NhEPAp4H71HzDzPtU8CXX

Run this once the 2026 Azerbaijan Grand Prix is in the lake:

    racecraft-ingest --season 2026
    python scripts/mark_baku.py

It prints each call, what the race did, and whether the call was right. It does
not decide anything; every threshold below is quoted from the published page and
must not be edited after the fact. If a call needs reinterpreting to pass, it
failed.
"""

from __future__ import annotations

import sys

from racecraft.store.db import connect

YEAR = 2026
LOCATION = "Baku"

# Quoted verbatim from the published page. Do not tune.
WINDOW = (21, 30)
NEUTRALISED_SHARE_MIN = 0.20
EARLY_SC_MEDIAN_MAX = 21

# A neutralisation only offers a cheap stop once cars have run long enough to
# want one. A lap-1 safety car does not — everyone is on fresh tyres and one
# lap of fuel has burned — so it neither voids call 2 nor triggers call 5.
# Fixed before the race, on the 2025 dry run, not after seeing the result.
EARLY_SC_RANGE = (8, 26)


def green(status: str | None) -> bool:
    """FastF1 track status '1' is green; null means the feed said nothing."""
    return status is None or status == "1"


def main() -> int:
    con = connect()

    race = con.sql(
        """
        select year, round from sessions
        where session = 'R' and year = ? and location = ?
        """,
        params=[YEAR, LOCATION],
    ).df()
    if race.empty:
        print(f"{YEAR} {LOCATION} race is not in the lake yet. Ingest it first:")
        print(f"  racecraft-ingest --season {YEAR}")
        return 1

    rnd = int(race.iloc[0]["round"])

    laps = con.sql(
        """
        select driver, lap_number, track_status, is_pit_in_lap
        from laps
        where year = ? and round = ? and session = 'R'
        """,
        params=[YEAR, rnd],
    ).df()

    stops = laps[laps["is_pit_in_lap"].fillna(False)]
    if stops.empty:
        print("No pit stops found — check the ingest before reading anything into this.")
        return 1

    per_driver = stops.groupby("driver").size()
    # Drivers who ran but never stopped still count as zero stops.
    ran = set(laps["driver"].unique())
    counts = [int(per_driver.get(d, 0)) for d in sorted(ran)]
    median_stops = sorted(counts)[len(counts) // 2]

    is_green = stops["track_status"].map(green)
    green_stops = stops[is_green]
    neutralised_share = float((~is_green).sum()) / len(stops)

    median_green_lap = (
        float(green_stops["lap_number"].median()) if not green_stops.empty else None
    )
    median_any_lap = float(stops["lap_number"].median())

    neutral_laps = laps[~laps["track_status"].map(green)]["lap_number"]
    first_neutral = int(neutral_laps.min()) if not neutral_laps.empty else None

    lo, hi = EARLY_SC_RANGE
    usable = neutral_laps[(neutral_laps >= lo) & (neutral_laps <= hi)]
    cheap_stop_lap = int(usable.min()) if not usable.empty else None

    results: list[tuple[str, bool | None, str]] = []

    results.append((
        "1  median finisher stops once",
        median_stops == 1,
        f"median {median_stops} stops across {len(counts)} drivers",
    ))

    if cheap_stop_lap is not None:
        results.append((
            f"2  median green stop in laps {WINDOW[0]}-{WINDOW[1]}",
            None,
            f"void — cheap stop available on lap {cheap_stop_lap}",
        ))
    elif median_green_lap is None:
        results.append(("2  median green stop in window", None, "void — no green stops"))
    else:
        results.append((
            f"2  median green stop in laps {WINDOW[0]}-{WINDOW[1]}",
            WINDOW[0] <= median_green_lap <= WINDOW[1],
            f"median green stop lap {median_green_lap:.1f}",
        ))

    results.append((
        "3  at least one SC or VSC",
        first_neutral is not None,
        f"first neutralised lap {first_neutral}" if first_neutral else "race ran green throughout",
    ))

    results.append((
        f"4  >= {NEUTRALISED_SHARE_MIN:.0%} of stops under neutralisation",
        neutralised_share >= NEUTRALISED_SHARE_MIN,
        f"{neutralised_share:.0%} of {len(stops)} stops",
    ))

    if cheap_stop_lap is None:
        results.append((
            f"5  early SC pulls median stop below {EARLY_SC_MEDIAN_MAX}",
            None,
            f"not marked — no neutralisation in laps {lo}-{hi}",
        ))
    else:
        results.append((
            f"5  early SC pulls median stop below {EARLY_SC_MEDIAN_MAX}",
            median_any_lap < EARLY_SC_MEDIAN_MAX,
            f"cheap stop on lap {cheap_stop_lap}, median stop lap {median_any_lap:.1f}",
        ))

    print(f"\nBaku pre-race call, marked against {YEAR} round {rnd}\n")
    marked = 0
    right = 0
    for name, ok, detail in results:
        if ok is None:
            mark = "void"
        else:
            marked += 1
            right += int(ok)
            mark = "RIGHT" if ok else "WRONG"
        print(f"  {mark:<5}  {name:<48}  {detail}")

    print(f"\n  {right} of {marked} marked calls correct\n")
    print("  Write down why the wrong ones were wrong before reading anyone")
    print("  else's account of the race.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
