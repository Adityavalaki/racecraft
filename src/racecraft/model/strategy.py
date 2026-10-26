"""
What a strategy costs, and which one is cheapest.

A race plan is a trade between two things that both cost time. Stopping costs
the pit lane; not stopping costs tyre wear, which grows with every lap on the
same set. Fresh tyres are quick but the lane is dear, so the answer is
whichever balance loses least in total.

The model here is deliberately the simplest thing that captures that trade:

    race time = base pace x laps
              + compound pace penalty for every lap run on a harder tyre
              + degradation accumulated in each stint
              + pit loss for each stop

The compound penalty matters as much as wear: a hard tyre is slower than a
soft at the same age, before wear enters at all. Leaving it out makes the
model prefer whichever compound wears slowest and ignore that it is also the
slowest to drive, which is not a trade a strategist would recognise.

Everything it leaves out is listed in `KNOWN_OMISSIONS` below, because a
number produced by a model this simple should arrive with its limits attached.
What it is good for is comparing plans at the same circuit, where the missing
pieces are largely common to both and cancel.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

KNOWN_OMISSIONS = (
    "traffic: a car released into a queue loses time this does not count",
    "safety cars: a stop under one costs roughly half, which can flip the answer",
    "track position: this counts seconds, not places, and races are scored in places",
    "the cliff: degradation past the point teams actually pit is unmeasured",
    "warm-up: an out-lap on cold tyres is slower than the model's fresh pace",
    "allocation: this ranking assumes new tyres for every stint; the tyre sets "
    "panel checks a plan against what a car actually has left",
)


@dataclass(frozen=True)
class Plan:
    """A sequence of stints: compound and length in laps."""
    stints: tuple[tuple[str, int], ...]

    @property
    def stops(self) -> int:
        return len(self.stints) - 1

    @property
    def laps(self) -> int:
        return sum(length for _, length in self.stints)

    def __str__(self) -> str:
        return " > ".join(f"{compound.lower()} {length}" for compound, length in self.stints)


@dataclass
class PlanCost:
    plan: Plan
    seconds_lost: float          # to tyres, compound choice and stops, above a fresh-soft race
    tyre_seconds: float
    pit_seconds: float
    compound_seconds: float = 0.0

    def as_dict(self) -> dict:
        return {"plan": str(self.plan), "stops": self.plan.stops,
                "seconds_lost": round(self.seconds_lost, 1),
                "tyre_seconds": round(self.tyre_seconds, 1),
                "compound_seconds": round(self.compound_seconds, 1),
                "pit_seconds": round(self.pit_seconds, 1)}


def stint_cost(compound: str, laps: int, degradation: dict[str, float],
               curvature: dict[str, float] | None = None) -> float:
    """
    Time lost to wear over a stint, relative to running it all on fresh tyres.

    Lap n of a stint loses `degradation * n`, so the stint loses the sum of
    that over its length. A curvature term, when supplied, bends the line.
    """
    slope = degradation[compound]
    bend = (curvature or {}).get(compound, 0.0)
    return sum(slope * n + bend * n * n for n in range(1, laps + 1))


def cost(plan: Plan, degradation: dict[str, float], pit_loss_s: float,
         curvature: dict[str, float] | None = None,
         compound_offset_s: dict[str, float] | None = None) -> PlanCost:
    offsets = compound_offset_s or {}
    tyre = sum(stint_cost(compound, laps, degradation, curvature) for compound, laps in plan.stints)
    compound = sum(offsets.get(name, 0.0) * laps for name, laps in plan.stints)
    pit = plan.stops * pit_loss_s
    return PlanCost(plan=plan, seconds_lost=tyre + compound + pit,
                    tyre_seconds=tyre, compound_seconds=compound, pit_seconds=pit)


def enumerate_plans(total_laps: int, compounds: tuple[str, ...], max_stops: int = 3,
                    min_stint: int = 8, step: int = 1, min_stops: int = 0) -> list[Plan]:
    """
    Every plan worth considering: each compound sequence, each split of the
    race into stints of at least `min_stint` laps.

    The rules require two different dry compounds in a dry race, so sequences
    using only one are dropped. `min_stops` is for the race that requires more:
    Monaco has demanded three sets, and so two stops, since 2025.
    """
    plans: list[Plan] = []
    for stops in range(max(0, min_stops), max_stops + 1):
        for sequence in itertools.product(compounds, repeat=stops + 1):
            if len(set(sequence)) < 2:
                continue                      # a dry race must use two compounds
            for lengths in _splits(total_laps, stops + 1, min_stint, step):
                plans.append(Plan(stints=tuple(zip(sequence, lengths))))
    return plans


def _splits(total: int, parts: int, minimum: int, step: int) -> list[tuple[int, ...]]:
    if parts == 1:
        return [(total,)] if total >= minimum else []
    out = []
    for first in range(minimum, total - minimum * (parts - 1) + 1, step):
        for rest in _splits(total - first, parts - 1, minimum, step):
            out.append((first, *rest))
    return out


def best_plans(total_laps: int, degradation: dict[str, float], pit_loss_s: float,
               curvature: dict[str, float] | None = None, max_stops: int = 3,
               min_stint: int = 8, step: int = 1, top: int = 5,
               compound_offset_s: dict[str, float] | None = None,
               min_stops: int = 0) -> list[PlanCost]:
    """The cheapest plans, best first."""
    compounds = tuple(degradation)
    costs = [cost(plan, degradation, pit_loss_s, curvature, compound_offset_s)
             for plan in enumerate_plans(total_laps, compounds, max_stops, min_stint, step,
                                         min_stops=min_stops)]
    return sorted(costs, key=lambda c: c.seconds_lost)[:top]


def best_stop_count(total_laps: int, degradation: dict[str, float], pit_loss_s: float,
                    curvature: dict[str, float] | None = None, max_stops: int = 3,
                    compound_offset_s: dict[str, float] | None = None, step: int = 3) -> int:
    """
    How many stops the cheapest plan makes.

    Stint lengths are swept in steps of `step` laps rather than one at a time:
    a stop count does not hinge on a single lap, and the coarser sweep is an
    order of magnitude faster over a whole season.
    """
    return best_plans(total_laps, degradation, pit_loss_s, curvature, max_stops,
                      step=step, top=1, compound_offset_s=compound_offset_s)[0].plan.stops


# ------------------------------------------------------------- in the race

# Stop laps within this many seconds of the cheapest are the window: the model
# cannot tell them apart, and a team picks among them on traffic.
WINDOW_TOLERANCE_S = 2.0
# Lap-to-lap scatter of a car's pace in clean air, for the undercut's odds.
LAP_NOISE_S = 0.25
# A median absolute deviation is this many standard deviations, for a normal spread.
MAD_TO_SD = 1.4826


@dataclass
class StopWindow:
    """When a car running on `compound` at `age` is best off stopping, from lap `lap`."""
    laps_until: int                 # from now to the cheapest stop
    first_lap: int
    last_lap: int
    most_likely_lap: int
    next_compound: str
    no_stop: bool = False           # running to the flag is as cheap as any stop

    def as_dict(self) -> dict:
        return {"laps_until": self.laps_until, "window": [self.first_lap, self.last_lap],
                "most_likely_lap": self.most_likely_lap, "next_compound": self.next_compound,
                "no_stop": self.no_stop}


def _finish_cost(laps: int, degradation: dict[str, float], offsets: dict[str, float], pit_loss_s: float,
                 allowed: set[str], min_stint: int) -> tuple[float, str] | None:
    """The cheapest way to run the last `laps` from fresh tyres: one stint, or two with one more stop."""
    best: tuple[float, str] | None = None
    for compound in allowed:
        one = stint_cost(compound, laps, degradation) + offsets.get(compound, 0.0) * laps
        if best is None or one < best[0]:
            best = (one, compound)
    # A second stop, where the rest of the race is too long for one set.
    for first in allowed:
        for second in degradation:
            for split in range(min_stint, laps - min_stint + 1):
                two = (stint_cost(first, split, degradation) + offsets.get(first, 0.0) * split
                       + stint_cost(second, laps - split, degradation) + offsets.get(second, 0.0) * (laps - split)
                       + pit_loss_s)
                if best is None or two < best[0]:
                    best = (two, first)
    return best


def stop_window(total_laps: int, lap: int, compound: str, age: int, degradation: dict[str, float],
                pit_loss_s: float, compound_offset_s: dict[str, float] | None = None,
                used: set[str] | frozenset = frozenset(), tolerance_s: float = WINDOW_TOLERANCE_S,
                min_stint: int = 5) -> StopWindow | None:
    """
    The stop lap that loses least over the rest of the race, and every lap
    within `tolerance_s` of it.

    From lap `lap`, a car on `compound` at `age` can stop after k more laps:
    those k laps on the old set, the pit lane, then the cheapest finish on
    fresh tyres. A dry race must use two compounds, so a car that has run only
    one leaves the pit on a different one. None when there is nothing to decide:
    too few laps left, or a compound the model has no wear for.
    """
    offsets = compound_offset_s or {}
    remaining = total_laps - lap
    if remaining < min_stint or compound not in degradation:
        return None
    ran = set(used) | {compound}
    allowed = {c for c in degradation if len(ran) >= 2 or c not in ran}
    if not allowed:
        return None

    def keep(k: int) -> float:
        return sum(degradation[compound] * (age + n) for n in range(1, k + 1)) + offsets.get(compound, 0.0) * k

    costs: list[tuple[float, int, str]] = []
    for k in range(0, remaining - min_stint + 1):
        finish = _finish_cost(remaining - k, degradation, offsets, pit_loss_s, allowed, min_stint)
        if finish is not None:
            costs.append((keep(k) + pit_loss_s + finish[0], k, finish[1]))
    if not costs:
        return None
    cheapest = min(costs)
    # Running to the flag is an option only once the rules are met.
    if len(ran) >= 2 and keep(remaining) <= cheapest[0]:
        return StopWindow(laps_until=remaining, first_lap=total_laps, last_lap=total_laps,
                          most_likely_lap=total_laps, next_compound=compound, no_stop=True)
    near = [k for cost_s, k, _ in costs if cost_s <= cheapest[0] + tolerance_s]
    return StopWindow(laps_until=cheapest[1], first_lap=lap + min(near), last_lap=lap + max(near),
                      most_likely_lap=lap + cheapest[1], next_compound=cheapest[2])


def undercut_gain(target_compound: str, target_age: int, fresh_compound: str, degradation: dict[str, float],
                  compound_offset_s: dict[str, float] | None = None) -> float:
    """
    Seconds the chasing car gains by stopping a lap before the car ahead: one
    lap on a fresh `fresh_compound` set against the target's old one, a lap
    older still. Both then lose the same pit lane. The out-lap's cold tyres are
    not in it, which flatters the undercut a little.
    """
    offsets = compound_offset_s or {}
    old = degradation.get(target_compound, 0.0) * (target_age + 1) + offsets.get(target_compound, 0.0)
    new = degradation.get(fresh_compound, 0.0) * 1 + offsets.get(fresh_compound, 0.0)
    return old - new


def undercut_chance(gap_s: float, gain_s: float, pit_spread_s: float, lap_noise_s: float = LAP_NOISE_S) -> float:
    """
    The chance the gain beats the gap. Two pit stops, each with the lane's own
    scatter (`pit_spread_s` is its median absolute deviation), and a lap of
    noise either way decide it as much as the tyres do.
    """
    from math import erf, sqrt

    sigma = sqrt(2 * (pit_spread_s * MAD_TO_SD) ** 2 + 2 * lap_noise_s ** 2) or 1e-6
    return 0.5 * (1 + erf((gain_s - gap_s) / (sigma * sqrt(2))))
