"""
Single entry point chaining the whole pipeline:
load -> clean/feature-engineer -> train -> save artifacts.

Run: python run_pipeline.py
Optionally: python run_pipeline.py --year 2024 --races Bahrain "Saudi Arabia" Australia

Requires internet access to api.formula1.com (via FastF1). Will NOT work
in a network-restricted sandbox — run this locally.
"""

import argparse
import json
import os
import sys

import joblib
import pandas as pd

from src import config
from src.data.fastf1_loader import load_multiple_races
from src.features.tyre_degradation import summarize_degradation
from src.features.pit_loss import compute_pit_loss
from src.models.pit_decision import build_lap_decisions, train


def main(year: int, races: list[str], session: str, reuse_cached_laps: bool = False):
    if reuse_cached_laps and os.path.exists(config.TRAINING_LAPS_CSV):
        print(f"Step 1/4: Reusing laps already downloaded to {config.TRAINING_LAPS_CSV}")
        laps = pd.read_csv(config.TRAINING_LAPS_CSV)
    else:
        print(f"Step 1/4: Loading {len(races)} races from {year}...")
        laps = load_multiple_races(year, races, session)
    if laps.empty:
        print("No races loaded — check internet access and GP names. Aborting.")
        sys.exit(1)
    if not reuse_cached_laps:
        laps.to_csv(config.TRAINING_LAPS_CSV, index=False)
    print(f"  {len(laps)} laps -> {config.TRAINING_LAPS_CSV}")

    print("Step 2/4: Fitting tyre degradation curves...")
    degradation = summarize_degradation(laps)
    degradation.to_csv(config.DEGRADATION_CSV, index=False)
    print(f"  {len(degradation)} stint fits -> {config.DEGRADATION_CSV}")
    weak_fits = degradation[degradation["fit_r2"] < 0.3]
    if len(weak_fits) > 0:
        print(f"  NOTE: {len(weak_fits)} stints have fit_r2 < 0.3 (poor fit) — "
              f"likely short stints or noisy laps (traffic, mistakes). "
              f"These still get used downstream; consider filtering them out "
              f"if the model's MAE looks worse than expected.")

    print("Step 3/4: Computing pit loss estimates...")
    pit_loss = compute_pit_loss(laps)
    pit_loss.to_csv(config.PIT_LOSS_CSV, index=False)
    print(f"  {len(pit_loss)} team/track combinations -> {config.PIT_LOSS_CSV}")
    out_of_range = pit_loss[
        (pit_loss["estimated_pit_loss_s"] < 15) | (pit_loss["estimated_pit_loss_s"] > 35)
    ]
    if len(out_of_range) > 0:
        print(f"  NOTE: {len(out_of_range)} pit loss estimates fall outside the "
              f"typical 15-35s range — inspect these manually before trusting "
              f"them, they may indicate a data quality issue (e.g. a safety "
              f"car pit stop mixed in with a normal one).")

    print("Step 4/4: Building lap-by-lap decisions and training the pit model...")
    table = build_lap_decisions(laps, pit_loss)
    stops = int(table["pits_this_lap"].sum()) if len(table) else 0
    print(f"  {len(table)} laps a call could be made on, {stops} of them stops")
    if len(table) < 200:
        print("  Too few laps to train on. Add more races to config.DEFAULT_RACES and rerun.")
        sys.exit(1)

    decisions_path = os.path.join(config.DATA_DIR, "lap_decisions.csv")
    table.to_csv(decisions_path, index=False)
    model, metrics = train(table)
    joblib.dump(model, config.MODEL_PATH)
    with open(config.METRICS_PATH, "w") as handle:
        json.dump(metrics, handle, indent=2)
    print(f"  base rate {metrics['base_rate']:.3f} | average precision "
          f"{metrics['average_precision']:.3f} +/- {metrics['average_precision_std']:.3f} | "
          f"{metrics['lift_over_base_rate']}x better than guessing")
    print("  Scored with whole races held out. The base rate is what guessing scores,")
    print("  so the lift is what the model adds.")

    print("\nPipeline complete. Artifacts written to data/:")
    print(f"  {config.TRAINING_LAPS_CSV}")
    print(f"  {config.DEGRADATION_CSV}")
    print(f"  {config.PIT_LOSS_CSV}")
    print(f"  {config.MODEL_PATH}")
    print(f"  {config.METRICS_PATH}")
    print(f"  {decisions_path}")
    print("\nNext: streamlit run app/app.py")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the F1 strategy engine pipeline end-to-end.")
    parser.add_argument("--year", type=int, default=config.DEFAULT_YEAR)
    parser.add_argument("--races", nargs="+", default=config.DEFAULT_RACES)
    parser.add_argument("--session", type=str, default=config.DEFAULT_SESSION)
    parser.add_argument("--reuse-laps", action="store_true",
                        help="use the laps already downloaded instead of fetching again")
    args = parser.parse_args()

    main(args.year, args.races, args.session, reuse_cached_laps=args.reuse_laps)
