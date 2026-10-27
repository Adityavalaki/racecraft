"""
Does a session built from OpenF1 match the one FastF1 built?

`ingest/openf1_source.py` stands in for FastF1 when F1's archive wants an F1 TV
login (D-009). Models filter on fields the two sources fill differently, so each
rule in it was checked against a session the lake already has from FastF1
(Singapore 2026, D-010). This builds that session again as ingest would, from
OpenF1 without telemetry, with TracingInsights' corners and tyres (D-012) and
Jolpica's results (D-011) over it, and prints every lap and result field where
the two disagree. `--openf1-only` leaves out the other two. The lake is only read.

    python scripts/compare_openf1.py 2026_17_R 2026_17_FP1 [--openf1-only]
"""

from __future__ import annotations

import sys

import pandas as pd

from racecraft.ingest import jolpica_source, openf1_source, quality, tracinginsights_source
from racecraft.store.db import connect

NAMES = {"FP1": "Practice 1", "FP2": "Practice 2", "FP3": "Practice 3", "SQ": "Sprint Qualifying",
         "Q": "Qualifying", "S": "Sprint", "R": "Race"}
LAP_FIELDS = ["compound", "stint", "tyre_life", "laps_in_stint", "fresh_tyre", "is_pit_in_lap", "is_pit_out_lap",
              "position", "track_status", "deleted", "is_accurate", "is_personal_best"]
RESULT_FIELDS = ["abbreviation", "team_name", "grid_position", "position", "classified_position", "status",
                 "points", "laps", "result_time_s", "q1_s", "q2_s", "q3_s"]


def same(a: pd.Series, b: pd.Series) -> pd.Series:
    """Equal, both missing, or (numbers) within 10 ms."""
    both_missing = a.isna() & b.isna()
    try:
        return both_missing | ((pd.to_numeric(a) - pd.to_numeric(b)).abs() < 0.01)
    except (ValueError, TypeError):
        return both_missing | (a.astype(str) == b.astype(str))


def main(key: str, openf1_only: bool) -> None:
    season, rnd, ident = key.split("_")
    new = openf1_source.extract(int(season), int(rnd), ident, NAMES[ident], key, telemetry=False)
    if not openf1_only:            # what ingest writes (D-011, D-012)
        new = tracinginsights_source.improve(new, int(season), str(new["sessions"]["event_name"][0]), NAMES[ident], key)
        new["results"], differ = jolpica_source.overlay(new["results"], jolpica_source.official(
            int(season), int(rnd), ident), ident)
        print("OpenF1 and Jolpica place differently:", differ)
    con = connect()
    old = {t: con.execute(f"select * from {t} where session_key = ?", [key]).df() for t in new}
    if old["sessions"].empty:
        sys.exit(f"{key} is not in the lake: nothing to compare against")

    # The two put t0 in different places: move FastF1's times onto OpenF1's clock.
    shift = (pd.Timestamp(old["sessions"]["t0_utc"][0]).tz_convert("UTC")
             - new["sessions"]["t0_utc"][0]).total_seconds()
    print("rows (FastF1, OpenF1):", {t: (len(old[t]), len(new[t])) for t in new})
    print("quality:", [(f.severity, f.check, f.detail) for f in quality.check_session(new) if f.severity != "OK"])

    laps = old["laps"].merge(new["laps"], on=["driver_number", "lap_number"], how="outer",
                             suffixes=("_f", "_o"), indicator=True)
    print("laps in:", laps["_merge"].value_counts().to_dict())
    laps = laps[laps["_merge"] == "both"]
    for name in ["lap_time_s", "lap_start_t", "lap_end_t", "pit_in_t", "pit_out_t"]:
        f = laps[name + "_f"] + (0 if name == "lap_time_s" else shift)
        gap = (f - laps[name + "_o"]).abs()
        print(f"{name:16s} max |diff| {gap.max():8.2f} s; only FastF1 {(f.notna() & laps[name + '_o'].isna()).sum()}, "
              f"only OpenF1 {(f.isna() & laps[name + '_o'].notna()).sum()}")
    for name in LAP_FIELDS:
        bad = ~same(laps[name + "_f"], laps[name + "_o"])
        print(f"{name:16s} differs on {bad.sum():4d} laps (driver, lap, FastF1, OpenF1):",
              laps.loc[bad, ["driver_number", "lap_number", name + "_f", name + "_o"]].head(5).values.tolist())

    res = old["results"].merge(new["results"], on="driver_number", suffixes=("_f", "_o"))
    for name in RESULT_FIELDS:
        bad = ~same(res[name + "_f"], res[name + "_o"])
        if bad.any():
            print(f"results.{name} differs for {bad.sum()}:",
                  res.loc[bad, ["driver_number", name + "_f", name + "_o"]].head(5).values.tolist())

    print("track status, FastF1:", old["track_status"].assign(t=lambda d: d["t"] + shift)[["t", "status"]]
          .round(0).values.tolist())
    print("track status, OpenF1:", new["track_status"][["t", "status"]].round(0).values.tolist())


if __name__ == "__main__":
    keys = [a for a in sys.argv[1:] if not a.startswith("--")] or ["2026_17_R"]
    for key in keys:
        main(key, "--openf1-only" in sys.argv)
