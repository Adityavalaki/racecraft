"""
Separating fuel burn from tyre wear.

A car gets faster through a stint as fuel burns off and slower as the tyre
wears. Both are roughly linear in laps and they pull in opposite directions,
so a lap time on its own cannot tell them apart. Worse, *within a stint* they
are perfectly confounded: one more lap of tyre age is always exactly one less
lap of fuel, so no amount of data from a single stint can separate them.

The separation comes from comparing stints. A driver runs a fresh tyre early
with a heavy car and again later with a light one; the same tyre age at two
fuel loads is what identifies the two effects. So the model is fitted across
a whole session at once:

    lap_time = driver_baseline + compound_offset
               + fuel * laps_remaining
               + degradation[compound] * tyre_age

with a baseline per driver, which absorbs car pace, and separate degradation
slopes per compound. It is deliberately a transparent linear model: a race
engineer can read every coefficient, which a gradient-boosted anything does
not allow.

One honest caveat, stated because it cannot be removed from this data: the
track rubbers in and gets faster through a session, and that improvement also
grows with race progress. It is therefore absorbed into the fuel coefficient,
which will read slightly high. Calling it "fuel and track evolution" would be
more accurate than calling it fuel alone.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")

# A lap this much slower than the driver's own median is traffic, a mistake or
# a slow zone, not pace. Kept loose so real degradation is never trimmed away.
OUTLIER_MULTIPLE = 1.07
MIN_LAPS_PER_STINT = 4
MIN_LAPS_TO_FIT = 40


class Confounded(ValueError):
    """Raised when the laps cannot separate fuel burn from tyre wear."""


@dataclass
class PaceModel:
    """Fitted coefficients, in seconds."""
    fuel_s_per_lap: float
    degradation_s_per_lap: dict[str, float]
    compound_offset_s: dict[str, float]
    driver_baseline_s: dict[int, float]
    n_laps: int
    n_drivers: int
    residual_std_s: float
    r_squared: float
    standard_errors: dict[str, float] = field(default_factory=dict)
    curvature_s_per_lap2: dict[str, float] = field(default_factory=dict)
    condition_number: float = float("nan")

    @property
    def is_weakly_identified(self) -> bool:
        """Stints varied enough to fit, but barely. Treat the split with suspicion."""
        return not np.isfinite(self.condition_number) or self.condition_number > 1e4

    def as_dict(self) -> dict:
        return {
            "fuel_s_per_lap": round(self.fuel_s_per_lap, 4),
            "degradation_s_per_lap": {k: round(v, 4) for k, v in self.degradation_s_per_lap.items()},
            "compound_offset_s": {k: round(v, 3) for k, v in self.compound_offset_s.items()},
            "n_laps": self.n_laps,
            "n_drivers": self.n_drivers,
            "residual_std_s": round(self.residual_std_s, 3),
            "r_squared": round(self.r_squared, 3),
            "standard_errors": {k: round(v, 4) for k, v in self.standard_errors.items()},
            "condition_number": round(self.condition_number, 1),
            "weakly_identified": self.is_weakly_identified,
        }


def clean_race_laps(laps: pd.DataFrame, compounds: tuple[str, ...] = DRY_COMPOUNDS) -> pd.DataFrame:
    """
    Laps that represent pace: green flag, dry tyres, no pit lane, no traffic.

    Anything else describes something other than the car and the tyre. Safety
    car laps, in and out laps, the first lap from a standing start, deleted
    laps and laps the timing feed itself marks inaccurate are all removed,
    then each driver's slowest laps go too: a lap 7% off their own median is
    traffic or a mistake.
    """
    df = laps.copy()
    keep = (
        df["lap_time_s"].notna()
        & (df["track_status"] == "1")
        & ~df["is_pit_in_lap"].fillna(False)
        & ~df["is_pit_out_lap"].fillna(False)
        & (df["lap_number"] > 1)
        & ~df["deleted"].fillna(False)
        & df["is_accurate"].fillna(True)
        & df["compound"].isin(compounds)
        & df["tyre_life"].notna()
    )
    df = df[keep]
    if df.empty:
        return df

    median = df.groupby("driver_number")["lap_time_s"].transform("median")
    df = df[df["lap_time_s"] <= median * OUTLIER_MULTIPLE]

    # A stint needs a few laps before its shape means anything.
    counts = df.groupby(["driver_number", "stint"])["lap_number"].transform("size")
    return df[counts >= MIN_LAPS_PER_STINT]


def fit(laps: pd.DataFrame, total_laps: int | None = None) -> PaceModel:
    """
    Fit fuel and per-compound degradation over one session's clean laps.

    `laps` should already be clean (see clean_race_laps).
    """
    df = laps
    if len(df) < MIN_LAPS_TO_FIT:
        raise ValueError(f"only {len(df)} clean laps; need at least {MIN_LAPS_TO_FIT} to separate fuel from wear")

    final_lap = total_laps or int(df["lap_number"].max())
    laps_remaining = (final_lap - df["lap_number"]).to_numpy(dtype=float)
    tyre_age = df["tyre_life"].to_numpy(dtype=float)

    drivers = sorted(df["driver_number"].unique())
    compounds = [c for c in DRY_COMPOUNDS if c in set(df["compound"])]

    # Design: a baseline per driver, a compound offset (first compound is the
    # reference), one fuel slope, and a degradation slope per compound.
    columns: list[np.ndarray] = []
    names: list[str] = []
    for driver in drivers:
        columns.append((df["driver_number"] == driver).to_numpy(dtype=float))
        names.append(f"driver_{driver}")
    for compound in compounds[1:]:
        columns.append((df["compound"] == compound).to_numpy(dtype=float))
        names.append(f"offset_{compound}")
    columns.append(laps_remaining)
    names.append("fuel")
    for compound in compounds:
        columns.append(np.where(df["compound"] == compound, tyre_age, 0.0))
        names.append(f"deg_{compound}")

    design = np.column_stack(columns)
    observed = df["lap_time_s"].to_numpy(dtype=float)

    # Refuse rather than answer badly. If every driver pits on the same laps,
    # tyre age and fuel stay perfectly confounded and the design is rank
    # deficient: least squares still returns a solution, splitting the effect
    # arbitrarily between them, and the fit looks excellent while both
    # coefficients are meaningless. Separation needs stints that differ.
    rank = np.linalg.matrix_rank(design)
    if rank < design.shape[1]:
        raise Confounded(
            f"fuel and tyre wear cannot be separated from these {len(df)} laps: the design has rank "
            f"{rank} of {design.shape[1]}. Drivers need to run the same compound at different points "
            f"in the race for the two to be told apart."
        )
    condition = float(np.linalg.cond(design))

    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    fitted = design @ coefficients
    residuals = observed - fitted

    dof = max(1, len(observed) - design.shape[1])
    sigma_squared = float(residuals @ residuals) / dof
    try:
        covariance = sigma_squared * np.linalg.pinv(design.T @ design)
        errors = np.sqrt(np.clip(np.diag(covariance), 0, None))
    except np.linalg.LinAlgError:
        errors = np.full(len(coefficients), np.nan)

    by_name = dict(zip(names, coefficients))
    error_by_name = dict(zip(names, errors))
    total_variance = float(((observed - observed.mean()) ** 2).sum())

    return PaceModel(
        fuel_s_per_lap=float(by_name["fuel"]),
        degradation_s_per_lap={c: float(by_name[f"deg_{c}"]) for c in compounds},
        compound_offset_s={c: float(by_name.get(f"offset_{c}", 0.0)) for c in compounds},
        driver_baseline_s={int(d): float(by_name[f"driver_{d}"]) for d in drivers},
        n_laps=len(df),
        n_drivers=len(drivers),
        residual_std_s=float(np.sqrt(sigma_squared)),
        r_squared=float(1 - (residuals @ residuals) / total_variance) if total_variance > 0 else float("nan"),
        standard_errors={
            "fuel": float(error_by_name["fuel"]),
            **{f"deg_{c}": float(error_by_name[f"deg_{c}"]) for c in compounds},
        },
        condition_number=condition,
    )


def fuel_corrected_lap_time(laps: pd.DataFrame, model: PaceModel, total_laps: int | None = None) -> pd.Series:
    """
    Lap times with the fuel effect removed, as if every lap were run on the
    same (end-of-race) fuel load. This is the number to compare across a race;
    raw lap times flatter the end of it.
    """
    final_lap = total_laps or int(laps["lap_number"].max())
    laps_remaining = final_lap - laps["lap_number"]
    return laps["lap_time_s"] - model.fuel_s_per_lap * laps_remaining


def fit_pooled(laps_by_session: dict[str, pd.DataFrame], total_laps: dict[str, int] | None = None) -> PaceModel:
    """
    One degradation figure per compound, fitted across many races at once.

    A single race cannot pin degradation down: the scatter in clean lap times
    is 0.5-1.1 s while the effect being measured is around 0.05 s per lap, so
    individual races come back noisy and occasionally negative, which would
    mean tyres getting faster as they wear. Pooling fixes that without
    pretending every circuit is the same: each race keeps its own baseline per
    driver and its own fuel slope (fuel per lap depends on the circuit), while
    the degradation slopes are shared, which is what the extra data buys.

    The result is the season-level tyre behaviour a strategy model needs.
    """
    total_laps = total_laps or {}
    frames, keys = [], []
    for key, laps in laps_by_session.items():
        if laps.empty:
            continue
        frame = laps.copy()
        frame["_session"] = key
        final_lap = total_laps.get(key) or int(frame["lap_number"].max())
        frame["_remaining"] = final_lap - frame["lap_number"]
        frames.append(frame)
        keys.append(key)
    if not frames:
        raise ValueError("no laps to fit")

    df = pd.concat(frames, ignore_index=True)
    if len(df) < MIN_LAPS_TO_FIT:
        raise ValueError(f"only {len(df)} clean laps across {len(keys)} sessions")

    compounds = [c for c in DRY_COMPOUNDS if c in set(df["compound"])]
    baseline = df["_session"] + "|" + df["driver_number"].astype(str)
    offset = df["_session"] + "|" + df["compound"]

    columns, names = [], []
    for group in sorted(baseline.unique()):
        columns.append((baseline == group).to_numpy(dtype=float))
        names.append(f"base_{group}")
    # One compound offset per race: the pace gap between compounds is a
    # property of the circuit, not a constant.
    for group in sorted(offset.unique())[1:]:
        columns.append((offset == group).to_numpy(dtype=float))
        names.append(f"offset_{group}")
    for key in keys:
        columns.append(np.where(df["_session"] == key, df["_remaining"], 0.0).astype(float))
        names.append(f"fuel_{key}")
    for compound in compounds:
        columns.append(np.where(df["compound"] == compound, df["tyre_life"], 0.0).astype(float))
        names.append(f"deg_{compound}")

    design = np.column_stack(columns)
    observed = df["lap_time_s"].to_numpy(dtype=float)
    rank = np.linalg.matrix_rank(design)
    if rank < design.shape[1]:
        # Drop the columns least able to carry information rather than refuse
        # outright: with many races, one uniform race should not sink the fit.
        keep = _independent_columns(design)
        design = design[:, keep]
        names = [n for n, k in zip(names, keep) if k]

    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    residuals = observed - design @ coefficients
    dof = max(1, len(observed) - design.shape[1])
    sigma_squared = float(residuals @ residuals) / dof
    errors = np.sqrt(np.clip(np.diag(sigma_squared * np.linalg.pinv(design.T @ design)), 0, None))
    by_name = dict(zip(names, coefficients))
    error_by_name = dict(zip(names, errors))
    total_variance = float(((observed - observed.mean()) ** 2).sum())

    fuels = [by_name[f"fuel_{k}"] for k in keys if f"fuel_{k}" in by_name]
    return PaceModel(
        fuel_s_per_lap=float(np.median(fuels)) if fuels else float("nan"),
        degradation_s_per_lap={c: float(by_name[f"deg_{c}"]) for c in compounds if f"deg_{c}" in by_name},
        compound_offset_s={},
        driver_baseline_s={},
        n_laps=len(df),
        n_drivers=int(df["driver_number"].nunique()),
        residual_std_s=float(np.sqrt(sigma_squared)),
        r_squared=float(1 - (residuals @ residuals) / total_variance) if total_variance > 0 else float("nan"),
        standard_errors={f"deg_{c}": float(error_by_name.get(f"deg_{c}", np.nan)) for c in compounds},
        condition_number=float(np.linalg.cond(design)),
    )


def _independent_columns(design: np.ndarray) -> np.ndarray:
    """A mask of columns that add rank, found by QR with column pivoting."""
    _, r, pivots = _qr_pivot(design)
    rank = int((np.abs(np.diag(r)) > 1e-9 * abs(r[0, 0])).sum()) if r.size else 0
    keep = np.zeros(design.shape[1], dtype=bool)
    keep[pivots[:rank]] = True
    return keep


def _qr_pivot(a: np.ndarray):
    from scipy.linalg import qr
    q, r, p = qr(a, mode="economic", pivoting=True)
    return q, r, p


def fit_lap_effects(laps: pd.DataFrame, curved: bool = False) -> PaceModel:
    """
    Degradation measured by comparing drivers at the same lap.

    The fuel model above has to assume a shape for everything that changes as
    a race runs: fuel burning away, and the track rubbering in. It fits one
    straight line to both, and any error in that assumption lands on whichever
    compound is used when the assumption is worst.

    This avoids the problem instead of modelling it. Give every lap of the race
    its own effect, and everything shared by the whole field on that lap —
    fuel load, track state, wind, a damp patch — is absorbed, whatever its
    shape. What remains is what differs between cars on that same lap, and the
    thing that differs is tyre age, because drivers stop at different times.

    The cost is that fuel can no longer be read off: it is inside the lap
    effects. Use `fit` when the fuel number is wanted and this when the
    degradation number is.
    """
    df = laps
    if len(df) < MIN_LAPS_TO_FIT:
        raise ValueError(f"only {len(df)} clean laps; need at least {MIN_LAPS_TO_FIT}")

    drivers = sorted(df["driver_number"].unique())
    lap_numbers = sorted(df["lap_number"].unique())
    compounds = [c for c in DRY_COMPOUNDS if c in set(df["compound"])]
    tyre_age = df["tyre_life"].to_numpy(dtype=float)

    columns, names = [], []
    for driver in drivers:
        columns.append((df["driver_number"] == driver).to_numpy(dtype=float))
        names.append(f"driver_{driver}")
    for lap in lap_numbers[1:]:                      # first lap is the reference
        columns.append((df["lap_number"] == lap).to_numpy(dtype=float))
        names.append(f"lap_{lap}")
    for compound in compounds[1:]:
        columns.append((df["compound"] == compound).to_numpy(dtype=float))
        names.append(f"offset_{compound}")
    for compound in compounds:
        columns.append(np.where(df["compound"] == compound, tyre_age, 0.0))
        names.append(f"deg_{compound}")
    if curved:
        # A tyre rarely wears in a straight line: it holds on, then falls away.
        # The squared term is that bend, so `deg_` becomes the slope when the
        # tyre is new and `curve_` how fast the drop-off accelerates.
        for compound in compounds:
            columns.append(np.where(df["compound"] == compound, tyre_age**2, 0.0))
            names.append(f"curve_{compound}")

    design = np.column_stack(columns)
    observed = df["lap_time_s"].to_numpy(dtype=float)
    if np.linalg.matrix_rank(design) < design.shape[1]:
        keep = _independent_columns(design)
        design, names = design[:, keep], [n for n, k in zip(names, keep) if k]
        if not any(n.startswith("deg_") for n in names):
            raise Confounded("no degradation slope survives: every driver is on the same tyre age each lap")

    coefficients, *_ = np.linalg.lstsq(design, observed, rcond=None)
    residuals = observed - design @ coefficients
    dof = max(1, len(observed) - design.shape[1])
    sigma_squared = float(residuals @ residuals) / dof
    errors = np.sqrt(np.clip(np.diag(sigma_squared * np.linalg.pinv(design.T @ design)), 0, None))
    by_name = dict(zip(names, coefficients))
    error_by_name = dict(zip(names, errors))
    total_variance = float(((observed - observed.mean()) ** 2).sum())

    reference = compounds[0]
    return PaceModel(
        fuel_s_per_lap=float("nan"),        # absorbed into the lap effects, by design
        degradation_s_per_lap={c: float(by_name[f"deg_{c}"]) for c in compounds if f"deg_{c}" in by_name},
        # Pace at the same tyre age, relative to the softest compound present:
        # how much slower a harder tyre is before wear enters at all.
        compound_offset_s={reference: 0.0,
                           **{c: float(by_name.get(f"offset_{c}", 0.0)) for c in compounds[1:]}},
        driver_baseline_s={},
        n_laps=len(df),
        n_drivers=len(drivers),
        residual_std_s=float(np.sqrt(sigma_squared)),
        r_squared=float(1 - (residuals @ residuals) / total_variance) if total_variance > 0 else float("nan"),
        standard_errors={
            **{f"deg_{c}": float(error_by_name.get(f"deg_{c}", np.nan)) for c in compounds},
            **({f"curve_{c}": float(error_by_name.get(f"curve_{c}", np.nan)) for c in compounds} if curved else {}),
        },
        curvature_s_per_lap2={c: float(by_name[f"curve_{c}"]) for c in compounds if f"curve_{c}" in by_name},
        condition_number=float(np.linalg.cond(design)),
    )


def combine(models: list[PaceModel]) -> dict[str, tuple[float, float]]:
    """
    Pool per-race degradation estimates, weighting each by its precision.

    A race that pinned the number down counts for more than one that barely
    did. Returns {compound: (estimate, standard error)}.
    """
    out: dict[str, tuple[float, float]] = {}
    for compound in DRY_COMPOUNDS:
        weights, values = [], []
        for model in models:
            value = model.degradation_s_per_lap.get(compound)
            error = model.standard_errors.get(f"deg_{compound}")
            if value is None or error is None or not np.isfinite(error) or error <= 0:
                continue
            weights.append(1 / error**2)
            values.append(value)
        if weights:
            weight_total = float(np.sum(weights))
            out[compound] = (float(np.dot(weights, values) / weight_total), float(np.sqrt(1 / weight_total)))
    return out
