"""
Fits per-stint tyre degradation curves.

Key insight (this is the domain knowledge that separates a real strategy
model from a generic regression): degradation is NOT linear. It's usually
flat-ish early, then degrades faster (cliff effect), and varies a lot by
compound and track. A linear fit is a fine baseline but say so explicitly
in your write-up — don't present it as if it were the real physics.
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import PolynomialFeatures
from sklearn.pipeline import make_pipeline

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src import config


def _ensure_laptime_seconds(df: pd.DataFrame) -> pd.DataFrame:
    """
    Guarantees a numeric LapTime_s column regardless of where the data
    came from. Bug this fixes: fastf1_loader now writes LapTime_s
    directly at load time, but if this DataFrame instead arrived via
    `pd.read_csv(...)`, LapTime survives as a string ("0 days 00:01:32...")
    and the old `.dt.total_seconds()` call throws — pandas' .dt accessor
    only works on an actual datetime/timedelta dtype, not its string repr.
    """
    if "LapTime_s" in df.columns and df["LapTime_s"].notna().any():
        return df  # already numeric, from fastf1_loader or a prior run

    if "LapTime" not in df.columns:
        raise ValueError("No LapTime or LapTime_s column found in laps data.")

    if pd.api.types.is_timedelta64_dtype(df["LapTime"]):
        df["LapTime_s"] = df["LapTime"].dt.total_seconds()
    else:
        # Came back from CSV as a string — parse it back to timedelta first.
        df["LapTime_s"] = pd.to_timedelta(df["LapTime"]).dt.total_seconds()
    return df


def stint_keys(df: pd.DataFrame) -> list[str]:
    """
    Columns that identify one physical stint. Bug this fixes: grouping by
    only (Driver, Stint) merged "VER stint 1" from every race in the training
    set into a single fit, so a 12 s pace difference between tracks became
    noise in the degradation curve (fit_r2 fell from 0.91 to 0.004 on a
    two-race synthetic test) and each driver got one degradation row instead
    of one per race.
    """
    return [c for c in ("Year", "GrandPrix") if c in df.columns] + ["Driver", "Stint"]


def clean_lap_times(laps: pd.DataFrame) -> pd.DataFrame:
    """
    Drop laps that don't represent clean pace: in/out laps, laps under
    yellow/safety car (TrackStatus != '1'), and obvious outliers.
    """
    df = _ensure_laptime_seconds(laps.copy())

    df = df[df["PitInTime"].isna() & df["PitOutTime"].isna()]
    if "TrackStatus" in df.columns:
        # Compare as string explicitly. Bug this fixes: TrackStatus is a
        # string in FastF1 (e.g. '1', '12' for combined flags), but after a
        # CSV round-trip pandas infers it as int64 when every value in the
        # file happens to be single-digit, and `== "1"` (str) then silently
        # matches ZERO rows instead of raising — the whole downstream
        # pipeline just goes empty with no error. Found by running this
        # against synthetic data; verify it doesn't recur with real FastF1
        # output, which may have multi-character TrackStatus values.
        df = df[df["TrackStatus"].astype(str) == "1"]

    # Remove statistical outliers per driver/stint (e.g. traffic, mistakes)
    df["z"] = df.groupby(stint_keys(df))["LapTime_s"].transform(
        lambda x: (x - x.mean()) / x.std(ddof=0) if x.std(ddof=0) > 0 else 0
    )
    df = df[df["z"].abs() < config.OUTLIER_Z_THRESHOLD]
    return df.drop(columns=["z"])


def fit_degradation_curve(stint_laps: pd.DataFrame, degree: int = None):
    """
    Fits lap time as a function of tyre age for a single stint.
    degree=2 (default) captures the "cliff" better than a straight line.
    Returns the fitted model and the R^2 to flag stints where the fit is weak.

    KNOWN GAP, be upfront about this in your write-up: this fits tyre age
    against raw lap time, but lap time also falls across a stint because the
    car gets LIGHTER as fuel burns off (~0.03-0.06s/lap depending on car and
    track, non-trivial over a 20+ lap stint). Right now that fuel effect is
    baked into the "degradation" number, which means deg_delta_3to15 is
    actually (tyre degradation - fuel burn improvement), not pure tyre
    degradation. A real fuel-load correction needs either FastF1's fuel
    estimate (not always reliable) or a per-track linear fuel-effect
    assumption applied before fitting. Until you add that, describe this
    metric as "net stint pace change," not "tyre degradation," if you want
    to be accurate.
    """
    degree = degree or config.DEGRADATION_POLY_DEGREE
    x = stint_laps[["TyreLife"]].values
    y = stint_laps["LapTime_s"].values
    if len(x) < config.MIN_LAPS_FOR_STINT_FIT:
        return None, None  # not enough laps to fit reliably

    model = make_pipeline(PolynomialFeatures(degree), LinearRegression())
    model.fit(x, y)
    r2 = model.score(x, y)
    return model, r2


def degradation_rate(stint_laps: pd.DataFrame) -> float:
    """
    Seconds lost per lap of tyre age, measured only over the laps actually run.

    Bug this fixes: the old `deg_delta_3to15` evaluated a fitted quadratic at
    tyre ages 3 and 15 for every stint, including stints that never reached
    lap 15. A quadratic extrapolated past its data goes wherever its curvature
    points - a 6-lap stint with a true +1.20 s of degradation came back as
    +0.41 s - so the number described the fit rather than the tyre. A straight
    line across the observed ages cannot leave the data it was fitted to.
    """
    if len(stint_laps) < config.MIN_LAPS_FOR_STINT_FIT:
        return float("nan")
    ages = stint_laps["TyreLife"].to_numpy(dtype=float)
    times = stint_laps["LapTime_s"].to_numpy(dtype=float)
    if np.ptp(ages) < 2:
        return float("nan")          # too narrow a range of ages to see a trend
    slope, _ = np.polyfit(ages, times, 1)
    return float(slope)


def predict_lap_time(model, tyre_age: int) -> float:
    """
    Predicts lap time (seconds) at a given tyre age from a fitted
    degradation model. Used by the undercut calculator to estimate the
    pace delta between a fresh tyre and a rival's current worn tyre,
    instead of requiring that number to be typed in by hand.
    """
    if model is None:
        raise ValueError("No fitted model provided — check fit_r2 before calling this.")
    return float(model.predict([[tyre_age]])[0])


def summarize_degradation(laps: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (driver, stint, compound) with fitted degradation slope
    and quality of fit — this table feeds the pit-window model.
    """
    clean = clean_lap_times(laps)
    keys = stint_keys(clean)
    rows = []
    for key_values, group in clean.groupby(keys):
        ids = dict(zip(keys, key_values))
        driver, stint = ids["Driver"], ids["Stint"]
        model, r2 = fit_degradation_curve(group)
        if model is None:
            continue
        compound = group["Compound"].iloc[0]
        ages = group["TyreLife"]
        covers_window = ages.min() <= 3 and ages.max() >= 15
        # Only quote the lap 3 to lap 15 delta when the stint actually ran
        # those laps; otherwise it is extrapolation, not measurement.
        try:
            # .item() not float(): NumPy >=2.0 raises TypeError converting
            # a size-1 array via float() (this used to silently work in
            # NumPy 1.x). Found by actually running this against synthetic
            # data — every single row was silently going NaN here and the
            # broad `except Exception` was swallowing it without a trace,
            # which is its own lesson: don't catch bare Exception around a
            # calculation you actually need to trust.
            delta = (model.predict([[15]]) - model.predict([[3]])).item() if covers_window else np.nan
        except Exception as e:
            print(f"  [degradation] fit delta failed for {driver} stint {stint}: {e}")
            delta = np.nan
        rows.append({
            **ids, "Compound": compound,
            "n_laps": len(group), "fit_r2": r2,
            "deg_s_per_lap": degradation_rate(group),   # measured over the laps actually run
            "deg_delta_3to15": delta,                   # null unless the stint covered ages 3-15
            "tyre_age_min": int(ages.min()), "tyre_age_max": int(ages.max()),
        })
    return pd.DataFrame(rows)
