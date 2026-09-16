"""
Backtest: compares the trained model's predicted pit lap against what the
team actually did. This is the piece that makes the project credible rather
than just "a model that runs" — anyone can train a regressor, the useful
question is whether it's actually close to real strategist decisions.
"""

import os
import sys
import pandas as pd
import numpy as np
import joblib

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src import config
from src.features.tyre_degradation import summarize_degradation
from src.features.pit_loss import compute_pit_loss
from src.models.train_pit_model import build_training_table, _prepare_features


def load_model():
    if not os.path.exists(config.MODEL_PATH):
        raise FileNotFoundError(
            f"No trained model at {config.MODEL_PATH}. Run train_pit_model.py first."
        )
    saved = joblib.load(config.MODEL_PATH)
    return saved["model"], saved["feature_columns"]


def run_backtest(laps: pd.DataFrame) -> pd.DataFrame:
    """
    Returns one row per real pit stop: predicted tyre age vs. actual,
    the error, and whether the model's call falls within +/-2 laps of
    what the team really did.

    Note on what this DOESN'T tell you: agreeing with what the team did
    only proves the model learned to imitate real strategists, not that
    either the team or the model made the OPTIMAL call. A team can pit at
    the wrong time and the model will learn to imitate that mistake too.
    Real validation would need race outcome data (did the strategy gain or
    lose positions), which is a further step beyond this backtest.
    """
    model, feature_columns = load_model()

    degradation = summarize_degradation(laps)
    pit_loss = compute_pit_loss(laps)
    table = build_training_table(laps, degradation, pit_loss)

    X, y_actual = _prepare_features(table)
    # Align columns with what the model was trained on — a compound that
    # didn't appear in this race's data would otherwise silently break
    # the feature alignment.
    X = X.reindex(columns=feature_columns, fill_value=0)

    predictions = model.predict(X)

    result = table[["Driver", "Team", "GrandPrix", "Stint", "Compound"]].copy()
    result["actual_pit_tyre_age"] = y_actual.values
    result["predicted_pit_tyre_age"] = np.round(predictions, 1)
    result["error_laps"] = result["predicted_pit_tyre_age"] - result["actual_pit_tyre_age"]
    result["within_2_laps"] = result["error_laps"].abs() <= 2

    return result.reset_index(drop=True)


def summarize_backtest(backtest_df: pd.DataFrame) -> dict:
    return {
        "n_pit_stops": len(backtest_df),
        "mean_absolute_error_laps": round(backtest_df["error_laps"].abs().mean(), 2),
        "pct_within_2_laps": round(100 * backtest_df["within_2_laps"].mean(), 1),
        "worst_miss": backtest_df.loc[backtest_df["error_laps"].abs().idxmax()].to_dict()
            if len(backtest_df) else None,
    }



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
    if not os.path.exists(config.TRAINING_LAPS_CSV):
        print(f"No data at {config.TRAINING_LAPS_CSV}. Run the pipeline first.")
        sys.exit(1)

    print(
        "WARNING: this script runs the backtest against the SAME races the "
        "model was trained on (config.TRAINING_LAPS_CSV), so these numbers "
        "are optimistic — the model has already seen this data. For a real "
        "backtest, load a race that was NOT in DEFAULT_RACES when the model "
        "was trained (pull a new race with fastf1_loader.py and pass that "
        "DataFrame to run_backtest() instead). Report cross-val MAE from "
        "training, not this number, as your headline metric.\n"
    )

    laps = pd.read_csv(config.TRAINING_LAPS_CSV)
    backtest = run_backtest(laps)
    summary = summarize_backtest(backtest)

    print(backtest.to_string(index=False))
    print("\nSummary:")
    for k, v in summary.items():
        print(f"  {k}: {v}")
