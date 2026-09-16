"""
Lap data shaped like FastF1's, for exercising the pipeline without a network.

This builds fixtures; it does not check anything, despite the name it has
carried since the start. Running it prints a frame and exits successfully
whatever the pipeline does, so it should never be taken as evidence that
anything works. The real checks are in `tests/`:

    python -m pytest tests -q

Note also what synthetic data cannot show. Every stint here is the same
length, so the model's old leakage - predicting stint length from stint
length - scored a perfect 0.00 MAE against it and looked flawless. It took
real races, where drivers stop at different times, to expose that.
"""

import numpy as np
import pandas as pd

np.random.seed(42)


def make_synthetic_laps(n_races=2, drivers=("VER", "HAM", "LEC"), laps_per_stint=18):
    rows = []
    teams = {"VER": "Red Bull", "HAM": "Mercedes", "LEC": "Ferrari"}
    compounds = ["SOFT", "MEDIUM", "HARD"]
    gps = [f"TestGP{i}" for i in range(n_races)]

    for gp in gps:
        for driver in drivers:
            team = teams[driver]
            lap_number = 1
            for stint_idx, compound in enumerate(compounds[:2]):  # 2 stints per race
                base_pace = 90 + np.random.normal(0, 0.5)
                deg_rate = {"SOFT": 0.15, "MEDIUM": 0.08, "HARD": 0.04}[compound]
                for tyre_age in range(1, laps_per_stint + 1):
                    # quadratic-ish degradation + noise
                    lap_time = base_pace + deg_rate * tyre_age + 0.01 * tyre_age**1.5 \
                        + np.random.normal(0, 0.15)
                    is_pit_in = (tyre_age == laps_per_stint)
                    rows.append({
                        "Driver": driver, "Team": team, "GrandPrix": gp,
                        "LapNumber": lap_number, "Stint": stint_idx + 1,
                        "Compound": compound, "TyreLife": tyre_age,
                        "LapTime_s": lap_time,
                        "LapTime": pd.to_timedelta(lap_time, unit="s"),
                        "PitInTime": lap_time if is_pit_in else np.nan,
                        "PitOutTime": np.nan,
                        "TrackStatus": "1",
                        "Position": np.random.randint(1, 20),
                        "AirTemp": 28.0, "TrackTemp": 42.0, "Rainfall": False,
                    })
                    lap_number += 1
                # add an explicit pit-in row transition marker for the last lap of stint
    df = pd.DataFrame(rows)
    return df


if __name__ == "__main__":
    df = make_synthetic_laps()
    print(df.shape)
    print(df.head())
    df.to_csv("data/synthetic_laps.csv", index=False)
