"""
What it costs to run in another car's wake, measured rather than assumed.

The race simulator needs one number per gap: how much slower a car goes when it
is this close behind another. It used to carry a hard-coded table — 0.55 s a lap
inside half a second — with a comment saying it had been measured, and nothing
in the repository measuring it. This is the measurement, and it disagreed.

The method is the pace model's own residual. Fit driver, lap, compound and wear
to a race's clean laps; what is left on each lap is whatever happened to that car
and no other, and the gap to the car ahead as the lap began is one such thing.
Bin the residuals by that gap and read each bin against clear air, over four
seconds back.

The subtle part is which laps to use, and getting it wrong doubles the answer.
A car close behind another loses time for two reasons: the disturbed air, and
being held up by a slower car it cannot pass. The simulator already models the
second — a car behind one it cannot pass is held at the minimum gap — so a
following penalty measured on every lap counts it twice. Measured on all laps,
2026 inside half a second is +0.39 s; on laps where the follower is *slower*
than the car ahead, who therefore cannot be holding it up, it is +0.28 s. The
second is the wake alone and is what the simulator wants. The old 0.55 was
roughly double it.

Measured this way, 2026 cars lose less in the wake than 2025 cars at every
distance, which is what the regulations set out to do and what the all-laps
measurement, contaminated by the holding-up, failed to show.

    racecraft-analyse following --season 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racecraft.model import pace as pace_model

log = logging.getLogger(__name__)

# Bin edges, matching the lookup in race.py: a gap under the first edge takes the
# first penalty, and so on. Over the last edge the car is in clear air.
EDGES = (0.5, 1.0, 1.5, 2.5, 4.0)
CLEAR_AIR_S = 4.0
# The closest bin has the fewest laps and the largest effect, so it decides
# whether a season has enough to measure at all.
MIN_CLOSE_LAPS = 100


@dataclass
class FollowingTable:
    """Seconds a lap lost in another car's wake, by gap, and how it was measured."""
    penalties: tuple[tuple[float, float], ...]      # ((edge, seconds), ...), the shape race.py reads
    errors: tuple[float, ...] = ()
    laps: tuple[int, ...] = ()
    races: int = 0
    measured: bool = True
    detail: str = ""
    all_laps: tuple[float, ...] = field(default_factory=tuple)   # held-up included, for comparison

    def as_dict(self) -> dict:
        return {
            "penalties": [{"under_s": edge, "seconds": round(value, 3)} for edge, value in self.penalties],
            "errors": [round(e, 3) for e in self.errors],
            "laps": list(self.laps),
            "races": self.races,
            "measured": self.measured,
            "detail": self.detail,
        }


def gaps_ahead(laps: pd.DataFrame) -> pd.DataFrame:
    """
    Each car's gap to the one ahead as each lap began, and who that was.

    Taken at the end of the previous lap: that is the gap the car spent the lap
    in. Only cars on the same lap are compared, so a car being lapped is not
    counted as the one ahead of the leader.
    """
    ends = (laps[["driver_number", "lap_number", "lap_end_t"]]
            .dropna().sort_values(["lap_number", "lap_end_t"]))
    ends["gap_ahead"] = ends.groupby("lap_number")["lap_end_t"].diff()
    ends["ahead"] = ends.groupby("lap_number")["driver_number"].shift()
    ends["lap_number"] = ends["lap_number"] + 1
    return ends[["driver_number", "lap_number", "gap_ahead", "ahead"]]


def race_residuals(laps: pd.DataFrame) -> pd.DataFrame | None:
    """One race's residuals, with each lap's gap and whether the follower was slower."""
    clean = pace_model.clean_race_laps(laps)
    if len(clean) < 200:
        return None
    try:
        residuals = pace_model.partial_residuals(clean)
        pace = pace_model.fit_lap_effects(clean).driver_baseline_s
    except (pace_model.Confounded, ValueError):
        return None
    merged = residuals.merge(gaps_ahead(laps), on=["driver_number", "lap_number"])
    merged = merged[merged["ahead"].notna() & (merged["gap_ahead"] > 0)]
    merged["own_pace"] = merged["driver_number"].map(pace)
    merged["their_pace"] = merged["ahead"].astype(int).map(pace)
    return merged.dropna(subset=["own_pace", "their_pace"])


def _bin(gap: pd.Series) -> pd.Series:
    labels = [f"<{e}" for e in EDGES] + ["clear"]
    return pd.cut(gap, [0, *EDGES, np.inf], labels=labels, right=False)


def measure(races: list[pd.DataFrame]) -> FollowingTable:
    """
    The wake penalty from a set of races' laps.

    Each element is one race's raw laps; residuals are taken per race because
    driver and lap effects belong to a race, then pooled across them.
    """
    return summarise([_race_residuals(laps) for laps in races])


# Kept so tests and older callers that patch the private name still work.
_race_residuals = race_residuals


def summarise(per_race: list[pd.DataFrame | None]) -> FollowingTable:
    """The wake penalty from residuals already taken per race by `race_residuals`."""
    frames = [r for r in per_race if r is not None]
    if not frames:
        return FollowingTable(penalties=(), measured=False, detail="no fittable races")

    everything = pd.concat(frames, ignore_index=True)
    everything["bin"] = _bin(everything["gap_ahead"])
    # Only followers slower than the car ahead: they cannot be being held up, so
    # what they lose is the air and nothing else. See the module docstring.
    wake = everything[everything["own_pace"] > everything["their_pace"]]

    labels = [f"<{e}" for e in EDGES]
    medians = wake.groupby("bin", observed=True)["residual_s"].median()
    counts = wake.groupby("bin", observed=True).size()
    close = int(counts.get(labels[0], 0))
    if close < MIN_CLOSE_LAPS or "clear" not in medians.index:
        return FollowingTable(penalties=(), measured=False, races=len(frames),
                              detail=f"only {close} laps within {EDGES[0]}s of a quicker car")

    clear = float(medians["clear"])
    # Standard error of a median, from the spread of each bin.
    spread = wake.groupby("bin", observed=True)["residual_s"].std()

    values, errors, laps = [], [], []
    ceiling = np.inf
    for label in labels:
        raw = float(medians.get(label, clear)) - clear
        # A wake cannot make a car quicker, and cannot cost more further back
        # than closer in; noise can suggest either, and neither is physics.
        value = min(max(raw, 0.0), ceiling)
        ceiling = value
        n = int(counts.get(label, 0))
        values.append(value)
        errors.append(float(1.2533 * spread.get(label, 0.0) / np.sqrt(n)) if n else float("nan"))
        laps.append(n)

    held_up = everything.groupby("bin", observed=True)["residual_s"].median()
    all_laps = tuple(float(held_up.get(label, clear)) - float(held_up.get("clear", clear))
                     for label in labels)

    return FollowingTable(
        penalties=tuple(zip(EDGES, values)),
        errors=tuple(errors),
        laps=tuple(laps),
        races=len(frames),
        measured=True,
        detail=f"{len(wake)} laps where the follower was slower, {len(frames)} races",
        all_laps=all_laps,
    )
