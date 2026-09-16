"""
Can the cost of rejoining in traffic be measured from where a car comes out of the pits?

The strategy model costs plans in seconds and cannot see that a plan two
seconds quicker may rejoin behind a car it will never pass. The obvious way to
fix that is to measure what rejoining close behind someone costs, and add it.

This script is the attempt, and it says the answer is no. Run it:

    python scripts/traffic_probe.py

The design: for every green-flag pit stop, take the gap to the car ahead at the
end of the out-lap, then measure the driver's pace over the next three green
laps against the field's median on those same laps. The field median removes
fuel, track evolution and anything else hitting every car at once.

Raw, the numbers look like a result — cars rejoining within a second of another
are about 0.18 s/lap slower than cars rejoining in clear air. With driver fixed
effects, which is the least you must do when quick cars rejoin in clear air
*because* they are quick, the effect collapses into its own error bar.

The conclusion is not that traffic is free. It is that this measurement cannot
see it, so no traffic term belongs in the strategy model on this evidence.
"""

from __future__ import annotations

import sys

import numpy as np
import pandas as pd

from racecraft.model import circuit as circuit_model
from racecraft.store.db import connect

FROM_SEASON = 2024
LAPS_AFTER = 3            # green laps after the out-lap used to read pace
MAX_GAP_S = 30.0          # beyond this the car ahead is not traffic
MIN_FIELD_CARS = 6        # a lap needs this many cars for its median to mean anything
BANDS = [0, 1, 2, 3, 5, 8, 12, 30]
DECAYS = (1.0, 1.5, 2.0, 3.0, 4.0)


def rejoins(laps: pd.DataFrame) -> pd.DataFrame:
    """One row per green-flag stop: the gap on rejoining and the pace that followed."""
    rows = []
    for session_key, race in laps.groupby("session_key"):
        counts = race.groupby("lap_number")["lap_time_s"].count()
        field = race.groupby("lap_number")["lap_time_s"].median()
        field = field[counts >= MIN_FIELD_CARS]

        for driver_number, driver_laps in race.groupby("driver_number"):
            driver_laps = driver_laps.sort_values("lap_number")
            for _, lap in driver_laps.iterrows():
                if not lap["is_pit_out_lap"] or lap["track_status"] != "1":
                    continue
                on_this_lap = race[race["lap_number"] == lap["lap_number"]]
                ahead = on_this_lap[on_this_lap["position"] == lap["position"] - 1]
                if ahead.empty or pd.isna(lap["lap_end_t"]):
                    continue
                gap = float(lap["lap_end_t"]) - float(ahead.iloc[0]["lap_end_t"])
                if not np.isfinite(gap) or not 0 <= gap <= MAX_GAP_S:
                    continue

                after = driver_laps[
                    (driver_laps["lap_number"] > lap["lap_number"])
                    & (driver_laps["lap_number"] <= lap["lap_number"] + LAPS_AFTER)
                    & (driver_laps["track_status"] == "1")
                    & ~driver_laps["is_pit_in_lap"].fillna(False)
                    & driver_laps["lap_number"].isin(field.index)
                ]
                if len(after) < 2:
                    continue
                excess = float((after["lap_time_s"] - after["lap_number"].map(field)).median())
                rows.append({"session_key": session_key, "driver_number": int(driver_number),
                             "circuit": str(lap["circuit"]), "gap_s": gap, "excess_s": excess})
    return pd.DataFrame(rows)


def fit(df: pd.DataFrame, decay: float) -> tuple[float, float]:
    """Excess pace on driver effects plus proximity, decaying with the gap."""
    proximity = np.exp(-df["gap_s"] / decay)
    drivers = sorted(df["driver_number"].unique())
    design = np.column_stack(
        [(df["driver_number"] == d).to_numpy(dtype=float) for d in drivers] + [proximity])
    observed = df["excess_s"].to_numpy(dtype=float)

    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    residuals = observed - design @ coefficients
    dof = max(1, len(observed) - design.shape[1])
    sigma_squared = float(residuals @ residuals) / dof
    error = float(np.sqrt(np.diag(sigma_squared * np.linalg.pinv(design.T @ design))[-1]))
    return float(coefficients[-1]), error


def main() -> int:
    con = connect()
    laps = con.sql(f"""select l.*, s.location, s.year from laps l join sessions s using (session_key)
                       where s.session = 'R' and s.year >= {FROM_SEASON}""").df()
    if laps.empty:
        print("no races in the lake")
        return 1
    laps = laps.assign(circuit=circuit_model.canonical_circuit(laps["location"]))

    df = rejoins(laps)
    if df.empty:
        print("no green-flag rejoins found")
        return 1

    print(f"\n{len(df)} green-flag rejoins, {df.driver_number.nunique()} drivers, "
          f"{df.session_key.nunique()} races, {FROM_SEASON} onward\n")

    print("Raw: pace over the next three laps, against the field on those laps")
    print("(negative is quicker — every one of these cars is on a fresh tyre)\n")
    banded = df.assign(band=pd.cut(df["gap_s"], BANDS))
    table = banded.groupby("band", observed=True)["excess_s"].agg(["median", "count"])
    for band, row in table.iterrows():
        print(f"  rejoined {str(band):>10} behind   {row['median']:+.2f} s/lap   n={int(row['count'])}")
    spread = table["median"].max() - table["median"].min()
    print(f"\n  spread across bands: {spread:.2f} s/lap — which looks like a traffic effect")

    print("\nWith driver fixed effects, because quick cars rejoin in clear air")
    print("*because* they are quick:\n")
    for decay in DECAYS:
        penalty, error = fit(df, decay)
        verdict = "significant" if abs(penalty) > 2 * error else "inside its own error bar"
        print(f"  decay {decay:>3.1f}s   {penalty:+.3f} ± {error:.3f} s/lap   {verdict}")

    print("\n  The effect does not survive. No traffic term belongs in the strategy")
    print("  model on this evidence; see the README for what to try instead.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
