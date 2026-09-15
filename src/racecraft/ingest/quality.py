"""
Sanity checks run on every session before it is written to the lake.

Two severities. An ERROR means the data is structurally wrong (duplicate
laps, time running backwards) and the session is not written. A WARN means
something is unusual but plausibly real (a red-flagged race whose winner
didn't complete the scheduled distance) and is reported, not blocked.

The cross-checks between independent fields are the valuable ones: summing
the winner's lap times and comparing against the official race time tests
the whole timedelta -> seconds conversion at once, which no single-column
range check can do.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

ERROR, WARN, OK = "ERROR", "WARN", "OK"


@dataclass
class Finding:
    severity: str
    check: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.severity}] {self.check}: {self.detail}"


def check_session(tables: dict[str, pd.DataFrame]) -> list[Finding]:
    out: list[Finding] = []
    laps, results, sessions = tables["laps"], tables["results"], tables["sessions"]

    # -- structure -------------------------------------------------------
    if laps.empty:
        out.append(Finding(ERROR, "laps.nonempty", "no laps"))
        return out
    if len(results) < 10:
        out.append(Finding(ERROR, "results.drivers", f"only {len(results)} drivers in results"))
    if results["driver_number"].duplicated().any():
        out.append(Finding(ERROR, "results.unique_driver", "duplicate driver_number in results"))

    dup = laps.duplicated(["driver_number", "lap_number"])
    if dup.any():
        out.append(Finding(ERROR, "laps.unique_lap", f"{int(dup.sum())} duplicate (driver, lap) rows"))

    unknown = set(laps["driver_number"]) - set(results["driver_number"])
    if unknown:
        out.append(Finding(WARN, "laps.drivers_in_results", f"laps for drivers not in results: {sorted(unknown)}"))

    by_driver = laps.sort_values(["driver_number", "lap_number"]).groupby("driver_number")
    stint_back = by_driver["stint"].diff() < 0
    if stint_back.any():
        out.append(Finding(ERROR, "laps.stint_monotonic", f"stint number decreases on {int(stint_back.sum())} laps"))

    life_back = laps.sort_values(["driver_number", "lap_number"]).groupby(["driver_number", "stint"])["tyre_life"].diff() < 0
    if life_back.any():
        out.append(Finding(ERROR, "laps.tyre_life_monotonic", f"tyre_life decreases within a stint on {int(life_back.sum())} laps"))

    end_back = by_driver["lap_end_t"].diff() <= 0
    if end_back.any():
        out.append(Finding(ERROR, "laps.time_monotonic", f"lap_end_t does not increase on {int(end_back.sum())} laps"))

    # -- ranges ----------------------------------------------------------
    green = laps[(laps["track_status"] == "1") & ~laps["is_pit_in_lap"] & ~laps["is_pit_out_lap"]
                 & (laps["lap_number"] > 1) & laps["lap_time_s"].notna()]
    bad = green[(green["lap_time_s"] < 55) | (green["lap_time_s"] > 180)]
    if len(bad):
        out.append(Finding(WARN, "laps.green_lap_range",
                           f"{len(bad)} green-flag laps outside 55-180 s, e.g. {bad['lap_time_s'].head(3).round(1).tolist()}"))

    missing = laps["lap_time_s"].isna().mean()
    if missing > 0.05:
        out.append(Finding(WARN, "laps.lap_time_coverage", f"{missing:.1%} of laps have no lap time"))

    if "car_data" in tables and not tables["car_data"].empty:
        cd = tables["car_data"]
        if (cd["speed"] > 400).any() or (cd["speed"] < 0).any():
            out.append(Finding(ERROR, "car_data.speed_range", f"speed outside 0-400 km/h (max {cd['speed'].max()})"))
        back = cd.groupby("driver_number")["t"].diff() < 0
        if back.any():
            out.append(Finding(ERROR, "car_data.time_monotonic", f"t goes backwards on {int(back.sum())} samples"))
        # Position and car data arrive at the same rate, so their row counts
        # track each other (median ratio 1.02 across 2023-2026). 2026 Monaco
        # had 0.18: the position feed stopped before the race while car data
        # continued, which leaves the track map empty for the whole race.
        if "pos_data" in tables:
            ratio = len(tables["pos_data"]) / len(cd)
            if ratio < 0.5:
                out.append(Finding(WARN, "pos_data.coverage",
                                   f"only {ratio:.0%} as many position samples as car samples; track map will have gaps"))
        # Out-of-domain readings are nulled at ingest; report how much was lost.
        for col in ("gear", "throttle"):
            share = cd[col].isna().mean()
            if share > 0:
                out.append(Finding(WARN if share > 0.25 else OK, f"car_data.{col}_coverage",
                                   f"{share:.2%} of samples null after removing invalid readings"))

    # -- cross-checks against the official result ------------------------
    total_laps = sessions["total_laps"].iloc[0]
    winner = results[results["position"] == 1]
    if len(winner) == 1:
        w = winner.iloc[0]
        if pd.notna(total_laps) and pd.notna(w["laps"]) and int(w["laps"]) != int(total_laps):
            out.append(Finding(WARN, "results.winner_distance",
                               f"winner completed {int(w['laps'])} of {int(total_laps)} scheduled laps"))

        # Span from the winner's first lap start to their last lap end, not the
        # sum of lap times: the feed drops lap times under safety cars and red
        # flags, so a sum only works for uneventful races. The span also has to
        # absorb a red-flag stoppage, which the official time includes.
        # Expect about +0.25 s: lap 1 starts at the session 'Started' status,
        # slightly before lights out (consistent across all of 2024 rounds 1-5).
        wl = laps[laps["driver_number"] == w["driver_number"]]
        if pd.isna(w["result_time_s"]) or wl["lap_end_t"].isna().all():
            out.append(Finding(WARN, "results.winner_time_reconciles", "skipped: no official time or no lap timestamps"))
        else:
            span = wl["lap_end_t"].max() - wl["lap_start_t"].min()
            diff = span - w["result_time_s"]
            detail = f"winner's lap span {span:.3f}s vs official {w['result_time_s']:.3f}s (diff {diff:+.3f}s)"
            out.append(Finding(WARN if abs(diff) > 2.0 else OK, "results.winner_time_reconciles", detail))
    return out


def has_errors(findings: list[Finding]) -> bool:
    return any(f.severity == ERROR for f in findings)
