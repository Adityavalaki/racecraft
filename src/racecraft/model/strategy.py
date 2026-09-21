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
                    min_stint: int = 8, step: int = 1) -> list[Plan]:
    """
    Every plan worth considering: each compound sequence, each split of the
    race into stints of at least `min_stint` laps.

    The rules require two different dry compounds in a dry race, so sequences
    using only one are dropped.
    """
    plans: list[Plan] = []
    for stops in range(0, max_stops + 1):
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
               compound_offset_s: dict[str, float] | None = None) -> list[PlanCost]:
    """The cheapest plans, best first."""
    compounds = tuple(degradation)
    costs = [cost(plan, degradation, pit_loss_s, curvature, compound_offset_s)
             for plan in enumerate_plans(total_laps, compounds, max_stops, min_stint, step)]
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
