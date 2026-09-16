"""
Pit-window model, framed so it cannot cheat.

This replaces the framing in `train_pit_model.py`, which asked a regressor to
predict the tyre age a stint would end at, using features computed over that
same stint. Two of those features - how many laps the stint contained, and a
degradation curve fitted across all of them - are only knowable once the stop
has happened. On 166 real pit stops the lap count correlated 0.964 with the
answer, and the model scored 1.22 laps of error while a strategist armed only
with what is knowable beforehand would score 6.83, worse than guessing the
average. The model was reading the stint length back, not predicting a call.

The question is therefore re-asked the way a pit wall asks it. On every lap:
given the laps run so far, does this car stop at the end of this one? Each lap
is one row and every feature is built from *earlier* laps only.

Excluding the lap itself matters more than it looks. A lap on which a car pits
contains the pit lane, so its lap time is some twenty seconds slower than the
ones around it. A model allowed to see that time scores an average precision
of 0.76, twenty-three times the base rate, and leans almost entirely on "this
lap was slow" - which is not a prediction of a stop but an observation of one
that has already happened. The call is made before the car reaches the pit
entry, so the model is given only what the pit wall had.

That reframing costs accuracy, and should. The honest score is in the README;
what matters is that it is a score for the question actually being asked.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src import config
from src.features.pit_loss import get_pit_loss_for
from src.features.tyre_degradation import _ensure_laptime_seconds, stint_keys

# A stint needs a few laps before its shape says anything, and the model
# should not be asked about laps where no team would consider stopping.
MIN_LAPS_BEFORE_DECIDING = 3

FEATURES = [
    "tyre_life",
    "laps_in_stint",
    "deg_so_far_s_per_lap",
    "pace_loss_vs_stint_best_s",
    "pace_loss_vs_last_lap_s",
    "race_progress",
    "stops_so_far",
    "estimated_pit_loss_s",
]


def build_lap_decisions(laps: pd.DataFrame, pit_loss: pd.DataFrame | None = None) -> pd.DataFrame:
    """
    One row per lap: what was known before it, and whether the car stopped at
    the end of it.

    Every feature comes from earlier laps only - the lap being decided is
    excluded, because a lap on which a car pits carries the pit lane inside its
    own lap time. The degradation figure is fitted across just the laps already
    run in this stint, which is what a race engineer has on the pit wall.
    """
    df = _ensure_laptime_seconds(laps.copy())
    df["is_pit_lap"] = df["PitInTime"].notna()
    keys = stint_keys(df)
    race_keys = [k for k in keys if k not in ("Driver", "Stint")]

    rows = []
    for key_values, stint in df.sort_values("LapNumber").groupby(keys):
        ids = dict(zip(keys, key_values))
        race_laps = df
        for race_key in race_keys:
            race_laps = race_laps[race_laps[race_key] == ids[race_key]]
        total_laps = float(race_laps["LapNumber"].max())
        driver_laps = race_laps[race_laps["Driver"] == ids["Driver"]].sort_values("LapNumber")

        green = stint[stint["LapTime_s"].notna()]
        if len(green) <= MIN_LAPS_BEFORE_DECIDING:
            continue

        ages = green["TyreLife"].to_numpy(dtype=float)
        times = green["LapTime_s"].to_numpy(dtype=float)
        for position in range(MIN_LAPS_BEFORE_DECIDING, len(green)):
            lap = green.iloc[position]
            # Laps before this one only: this lap's time would contain the very
            # stop the model is being asked to predict.
            seen_ages, seen_times = ages[:position], times[:position]
            rows.append({
                **ids,
                "Compound": lap["Compound"],
                "LapNumber": lap["LapNumber"],
                "tyre_life": float(lap["TyreLife"]),
                "laps_in_stint": position,
                "deg_so_far_s_per_lap": _slope(seen_ages, seen_times),
                "pace_loss_vs_stint_best_s": float(seen_times[-1] - seen_times.min()),
                "pace_loss_vs_last_lap_s": float(seen_times[-1] - seen_times[-2]),
                "race_progress": float(lap["LapNumber"]) / total_laps if total_laps else np.nan,
                "stops_so_far": int(driver_laps[driver_laps["LapNumber"] < lap["LapNumber"]]["is_pit_lap"].sum()),
                "Team": lap.get("Team"),
                "pits_this_lap": bool(lap["is_pit_lap"]),
            })

    table = pd.DataFrame(rows)
    if table.empty:
        return table

    if pit_loss is not None and "GrandPrix" in table.columns:
        # Looked up once per team and race, not once per lap, so the fallback
        # notice appears once rather than for every lap of that race.
        pairs = table[["Team", "GrandPrix"]].drop_duplicates()
        pairs["estimated_pit_loss_s"] = [
            get_pit_loss_for(row.Team, row.GrandPrix, pit_loss) for row in pairs.itertuples()
        ]
        return table.merge(pairs, on=["Team", "GrandPrix"], how="left")

    table["estimated_pit_loss_s"] = np.nan
    return table


def _slope(ages: np.ndarray, times: np.ndarray) -> float:
    """Degradation measured from the laps run so far in this stint."""
    if len(ages) < 3 or np.ptp(ages) < 2:
        return np.nan
    slope, _ = np.polyfit(ages, times, 1)
    return float(slope)


def prepare(table: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Feature matrix, label, and the race each row came from (for splitting)."""
    compounds = pd.get_dummies(table["Compound"], prefix="compound")
    features = table[FEATURES].astype(float)
    X = pd.concat([features, compounds], axis=1).fillna(0.0)
    y = table["pits_this_lap"].astype(int)
    groups = table["GrandPrix"] if "GrandPrix" in table.columns else pd.Series("all", index=table.index)
    return X, y, groups


def train(table: pd.DataFrame, random_state: int = config.RANDOM_STATE):
    """
    Fit the model and score it by leaving whole races out.

    Splitting at random would put laps from the same stint on both sides,
    which leaks almost as effectively as the features did. Races are held out
    whole, which is the only split that answers "would this have worked at the
    next race".
    """
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.metrics import average_precision_score
    from sklearn.model_selection import GroupKFold

    X, y, groups = prepare(table)
    base_rate = float(y.mean())

    folds = min(5, max(2, groups.nunique()))
    scores = []
    for train_index, test_index in GroupKFold(n_splits=folds).split(X, y, groups):
        model = RandomForestClassifier(
            n_estimators=config.RF_N_ESTIMATORS, max_depth=config.RF_MAX_DEPTH,
            class_weight="balanced", random_state=random_state,
        )
        model.fit(X.iloc[train_index], y.iloc[train_index])
        predicted = model.predict_proba(X.iloc[test_index])[:, 1]
        scores.append(average_precision_score(y.iloc[test_index], predicted))

    model = RandomForestClassifier(
        n_estimators=config.RF_N_ESTIMATORS, max_depth=config.RF_MAX_DEPTH,
        class_weight="balanced", random_state=random_state,
    )
    model.fit(X, y)

    metrics = {
        "laps": int(len(X)),
        "stops": int(y.sum()),
        "base_rate": round(base_rate, 4),
        "average_precision": round(float(np.mean(scores)), 4),
        "average_precision_std": round(float(np.std(scores)), 4),
        "lift_over_base_rate": round(float(np.mean(scores)) / base_rate, 2) if base_rate else float("nan"),
        "feature_importances": dict(sorted(
            ((name, round(float(value), 4)) for name, value in zip(X.columns, model.feature_importances_)),
            key=lambda item: -item[1])),
    }
    return model, metrics


if __name__ == "__main__":
    import json

    from src.features.pit_loss import compute_pit_loss

    if not os.path.exists(config.TRAINING_LAPS_CSV):
        print(f"No training data at {config.TRAINING_LAPS_CSV}. Run run_pipeline.py first.")
        sys.exit(1)

    laps = pd.read_csv(config.TRAINING_LAPS_CSV)
    table = build_lap_decisions(laps, compute_pit_loss(laps))
    if table.empty:
        print("No usable laps.")
        sys.exit(1)
    model, metrics = train(table)
    print(json.dumps(metrics, indent=2))
    print("\nAverage precision against the base rate is the number that matters: the base rate")
    print("is what guessing at random would score, so the lift is what the model actually adds.")
