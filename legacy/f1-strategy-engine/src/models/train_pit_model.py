"""
Trains a model to predict the optimal pit lap given tyre age, degradation
rate, gap to competitors, and compound.

Framing choice, worth defending in your write-up: this is set up as a
REGRESSION problem (predict optimal pit lap number) rather than a per-lap
binary classifier ("pit now: yes/no"), because pit timing is fundamentally
a continuous optimization — when do cumulative degradation losses exceed
the fixed pit loss cost. A classifier version is easy to add later for
comparison, but don't present both without explaining why you chose one.
"""

import os
import sys
import json
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.metrics import mean_absolute_error
import joblib

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src import config


def build_training_table(laps: pd.DataFrame, degradation: pd.DataFrame,
                          pit_loss: pd.DataFrame) -> pd.DataFrame:
    """
    Joins lap data, degradation rates, and pit loss into one training table.
    Label = the tyre age at which the driver ACTUALLY pitted (their real
    strategy call). This lets you later compare model predictions against
    what the team really did — the backtest that makes this project credible.
    """
    race_keys = [c for c in ("Year", "GrandPrix") if c in laps.columns]
    pit_events = laps[laps["PitInTime"].notna()][
        list(dict.fromkeys(race_keys + ["Driver", "Stint", "Team", "GrandPrix", "TyreLife", "Compound"]))
    ].rename(columns={"TyreLife": "actual_pit_tyre_age"})

    # Join on the race as well as driver and stint, or every driver's stint 1
    # matches the stint-1 degradation row from every other race too.
    merged = pit_events.merge(degradation, on=race_keys + ["Driver", "Stint", "Compound"], how="left")
    merged = merged.merge(pit_loss, on=["Team", "GrandPrix"], how="left")
    return merged.dropna(subset=["deg_delta_3to15", "estimated_pit_loss_s"])


def _prepare_features(training_table: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """
    Builds the feature matrix, including one-hot encoded Compound.
    Compound matters a lot for pit timing (softs wear faster, get pitted
    earlier, than hards) — leaving it out understates the model's real
    predictive power and hides a variable race engineers actively use.
    """
    numeric_features = ["deg_delta_3to15", "estimated_pit_loss_s", "n_laps", "fit_r2"]
    compound_dummies = pd.get_dummies(training_table["Compound"], prefix="compound")

    X = pd.concat([training_table[numeric_features], compound_dummies], axis=1)
    y = training_table["actual_pit_tyre_age"]
    return X, y


def train(training_table: pd.DataFrame):
    X, y = _prepare_features(training_table)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=config.TEST_SIZE, random_state=config.RANDOM_STATE
    )

    model = RandomForestRegressor(
        n_estimators=config.RF_N_ESTIMATORS,
        max_depth=config.RF_MAX_DEPTH,
        random_state=config.RANDOM_STATE,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_test)
    test_mae = mean_absolute_error(y_test, preds)

    # Cross-validation on top of the single split — with a dataset this
    # small (a handful of races), a single train/test split can be
    # misleadingly good or bad depending on the random draw. CV gives a
    # more honest read of how stable the MAE actually is.
    cv_folds = max(2, min(config.CV_FOLDS, len(X) // 3))
    cv_scores = cross_val_score(
        model, X, y, cv=cv_folds, scoring="neg_mean_absolute_error",
    )
    cv_mae_mean = -cv_scores.mean()
    cv_mae_std = cv_scores.std()

    importances = dict(zip(X.columns, model.feature_importances_))
    importances = dict(sorted(importances.items(), key=lambda kv: -kv[1]))

    print(f"Test-split MAE: {test_mae:.2f} laps")
    print(f"Cross-val MAE ({cv_folds}-fold): {cv_mae_mean:.2f} \u00b1 {cv_mae_std:.2f} laps "
          f"(this is the more trustworthy number with a small dataset)")
    print("Feature importances:")
    for feat, imp in importances.items():
        print(f"  {feat}: {imp:.3f}")
    print("A model off by ~1-2 laps is genuinely competitive with real strategy calls. "
          "If CV std is large relative to the mean, you don't have enough training "
          "data yet to trust this number — that's a signal to expand DEFAULT_RACES "
          "in src/config.py, not to tune hyperparameters harder.")

    metrics = {
        "test_mae_laps": round(float(test_mae), 3),
        "cv_mae_mean_laps": round(float(cv_mae_mean), 3),
        "cv_mae_std_laps": round(float(cv_mae_std), 3),
        "n_training_rows": len(X),
        "feature_importances": {k: round(float(v), 4) for k, v in importances.items()},
    }
    with open(config.METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    joblib.dump({"model": model, "feature_columns": list(X.columns)}, config.MODEL_PATH)
    print(f"Saved model to {config.MODEL_PATH}")
    print(f"Saved metrics to {config.METRICS_PATH}")
    return model, metrics



LEAKAGE_NOTICE = """
This module is kept only to reproduce a mistake, and its numbers must not be
quoted. It predicts the tyre age a stint ends at from features computed over
that same stint - the stint's own length among them, which correlates 0.964
with the answer. It scores an MAE of 1.22 laps and knows nothing: given only
what a strategist has before the call, the same approach scores 6.83, worse
than guessing the average.

Use src/models/pit_decision.py, which asks whether a car stops at the end of
each lap using only the laps before it. See the README.
"""

if __name__ == "__main__":
    print(LEAKAGE_NOTICE)
    sys.exit(1)


def _superseded_main():
    from src.features.tyre_degradation import summarize_degradation
    from src.features.pit_loss import compute_pit_loss

    if not os.path.exists(config.TRAINING_LAPS_CSV):
        print(f"No training data at {config.TRAINING_LAPS_CSV}. "
              f"Run src/data/fastf1_loader.py first, or use run_pipeline.py.")
        sys.exit(1)

    laps = pd.read_csv(config.TRAINING_LAPS_CSV)
    degradation = summarize_degradation(laps)
    pit_loss = compute_pit_loss(laps)
    table = build_training_table(laps, degradation, pit_loss)

    if len(table) < 10:
        print(f"Only {len(table)} training rows after joins — too few to train "
              f"a meaningful model. Expand DEFAULT_RACES in src/config.py and "
              f"reload data before proceeding.")
        sys.exit(1)

    train(table)
