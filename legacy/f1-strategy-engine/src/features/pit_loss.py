"""
Computes real pit stop time loss per team/track — this is the number that
makes undercut/overcut math correct instead of guessed. Generic "pit stop
costs ~20s" assumptions are wrong track-to-track (pit lane length/speed
limit varies a lot) and team-to-team (crew performance varies).
"""

import pandas as pd

from src.features.tyre_degradation import _ensure_laptime_seconds


def compute_pit_loss(laps: pd.DataFrame) -> pd.DataFrame:
    """
    Estimates time lost in the pits by comparing the in-lap/out-lap time
    to the driver's median clean lap time in that stint window.

    Returns one row per (team, track) with an estimated pit loss in seconds.
    Requires PitInTime/PitOutTime and Team/GrandPrix columns from FastF1 laps.
    """
    df = _ensure_laptime_seconds(laps.copy())

    baseline = (
        df[df["PitInTime"].isna() & df["PitOutTime"].isna()]
        .groupby(["Team", "GrandPrix"])["LapTime_s"]
        .median()
        .rename("baseline_lap_s")
    )

    pit_laps = df[df["PitInTime"].notna() | df["PitOutTime"].notna()]
    pit_avg = (
        pit_laps.groupby(["Team", "GrandPrix"])["LapTime_s"]
        .mean()
        .rename("pit_lap_avg_s")
    )

    result = pd.concat([baseline, pit_avg], axis=1).dropna()
    result["estimated_pit_loss_s"] = result["pit_lap_avg_s"] - result["baseline_lap_s"]
    return result.reset_index()


def get_pit_loss_for(team: str, gp: str, pit_loss_df: pd.DataFrame,
                      fallback_s: float = 22.0) -> float:
    """
    Looks up the estimated pit loss for a given team/track from a
    precomputed pit_loss_df (output of compute_pit_loss). Falls back to a
    generic ~22s estimate if no data exists for that combination — this
    happens for GPs/teams not in your training set, or new tracks.

    The fallback is a rough average across tracks and should NOT be trusted
    for anything you're presenting as precise — it exists so the pipeline
    doesn't crash on a lookup miss, not because 22s is a good universal
    number. Log when it's used so you notice how often you're relying on it.
    """
    match = pit_loss_df[
        (pit_loss_df["Team"] == team) & (pit_loss_df["GrandPrix"] == gp)
    ]
    if match.empty:
        print(f"[pit_loss] No data for {team} at {gp} — using fallback {fallback_s}s")
        return fallback_s
    return float(match["estimated_pit_loss_s"].iloc[0])
