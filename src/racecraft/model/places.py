"""
Ranking strategies by where they finish, not by how many seconds they lose.

`strategy.py` costs a plan in seconds: tyre wear, compound, pit lane. It is
arithmetic and it is exact, and it is answering the wrong question. A plan two
seconds quicker that rejoins behind a car it cannot pass has lost, and a model
counting seconds in a vacuum cannot see that because it never looks at anyone
else.

`race.py` can see it — it puts the whole field on track, makes cars lose time in
each other's wake, and only lets them past as often as the circuit allows. What
was missing was the join: `race.py` was only ever used to compare four
hand-written plans, while the seconds model swept hundreds.

This is that join. It takes the plans the seconds model likes, runs each one as
a whole race many times over, and ranks them by finishing position.

Three things it does deliberately.

*It only simulates plans worth simulating.* A race is three milliseconds and a
sweep is thousands of plans, so the candidates come from the seconds ranking
first. That is a real assumption and not a safe one in general: the seconds
model is exactly the thing being corrected. It holds here because the two
disagree about *which* of several close plans is best, not about whether a plan
that loses half a minute is in contention.

*It uses the same random races for every plan.* Each plan is run against an
identically-seeded field, so a comparison between two plans differs only by the
plans themselves and not by which safety car each happened to draw. This is
what makes differences of a tenth of a place mean anything at these run counts.

*It varies what the rest of the field does.* This one was learned the hard way.
Running every rival on one identical plan produced a four-place cliff in favour
of stopping on the lap they stopped — which is not a strategy insight, it is the
simulation rewarding a car for copying a field that does not exist. Spread the
field's stop laps instead and the ordering inverts: the seconds-optimal lap is
no longer the best place to stop. So the field is drawn fresh several times per
plan and the results pooled, and what comes out is a plan's expected finish
against a *plausible* field rather than against one particular guess.

*It says when two plans are indistinguishable.* The mean finishing position of a
few hundred simulated races carries a standard error, and most plans in a sweep
sit inside each other's. Reporting a ranking without that would manufacture a
decision out of noise, which is the failure this project keeps finding in its
own work.

What it inherits from `race.py` and cannot fix: the rest of the field runs a
fixed plan and never reacts. Real rivals cover a stop. That makes this a model
of racing against a field, not against a strategist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from racecraft.model import race as race_model
from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

log = logging.getLogger(__name__)

DEFAULT_RUNS = 300
DEFAULT_CARS = 20
# How many different fields each plan is run against. The rest of the field's
# stop laps are redrawn for each, and the finishes pooled, so no single guess
# about what rivals do decides the ranking.
DEFAULT_FIELD_DRAWS = 15
# Plans whose mean finish is within this many standard errors of the best are
# reported as tied rather than ranked against each other.
NOISE_SIGMAS = 1.0


@dataclass
class PlaceRanking:
    """One plan, judged over many simulated races."""
    plan: Plan
    mean_finish: float
    std_error: float
    median_finish: int
    best: int
    worst: int
    podium_share: float
    points_share: float
    gained: float                 # places against the grid slot started from
    behind_best: float            # places behind the best plan here
    within_noise: bool            # indistinguishable from the best

    def as_dict(self) -> dict:
        return {
            "plan": str(self.plan),
            "stops": self.plan.stops,
            "stop_laps": _stop_laps(self.plan),
            "mean_finish": round(self.mean_finish, 2),
            "std_error": round(self.std_error, 3),
            "median_finish": self.median_finish,
            "best": self.best,
            "worst": self.worst,
            "podium_share": round(self.podium_share, 3),
            "points_share": round(self.points_share, 3),
            "gained": round(self.gained, 2),
            "behind_best": round(self.behind_best, 2),
            "within_noise": self.within_noise,
        }


def pace_ladder(baselines: list[float], cars: int) -> list[float]:
    """
    How far apart the field is, quickest first.

    Taken from fitted driver effects rather than assumed, and padded by
    repeating the slowest gap when a season has fitted fewer cars than the race
    has entries — which happens when someone's every stint was identical and
    their pace was not separable.
    """
    ordered = sorted(baselines)
    if not ordered:
        raise ValueError("no fitted driver pace to build a ladder from")
    while len(ordered) < cars:
        step = ordered[-1] - ordered[-2] if len(ordered) > 1 else 0.1
        ordered.append(ordered[-1] + max(step, 0.05))
    return ordered[:cars]


def field_stop_window(total_laps: int, reference: Plan) -> tuple[int, int]:
    """
    The laps a rival might plausibly stop on: the reference stop, give or take.

    Wide enough that the field is not all on one lap, narrow enough to stay a
    field running the same race. Real spreads at Baku ran nine laps wide.
    """
    reference_stop = _stop_laps(reference)
    middle = reference_stop[0] if reference_stop else total_laps // 2
    return max(6, middle - 5), min(total_laps - 6, middle + 6)


def _draw_field(reference: Plan, cars: int, total_laps: int,
                rng: np.random.Generator) -> list[Plan]:
    """One plausible field: the reference plan, with stop laps spread around it."""
    low, high = field_stop_window(total_laps, reference)
    compounds = [compound for compound, _ in reference.stints]
    out = []
    for _ in range(cars):
        stop = int(rng.integers(low, high + 1))
        out.append(Plan(stints=((compounds[0], stop), (compounds[-1], total_laps - stop))))
    return out


def rank_plans(candidates: list[Plan], field_plan: Plan, *, grid: int, ladder: list[float],
               quickest_lap_s: float, total_laps: int, degradation: dict[str, float],
               pit_loss_s: float, neutralisation: Neutralisation, passes_per_lap: float,
               compound_offset_s: dict[str, float] | None = None,
               runs: int = DEFAULT_RUNS, cars: int = DEFAULT_CARS,
               field_draws: int = DEFAULT_FIELD_DRAWS, seed: int = 11) -> list[PlaceRanking]:
    """
    Every candidate plan, run as a whole race, ranked by where it finishes.

    `grid` is the slot the car being advised starts from. `field_plan` is what
    the rest of the field is doing on average; their stop laps are spread around
    it and redrawn `field_draws` times, because a field all on one lap rewards
    copying it and that is an artefact rather than a finding.

    The same seed is used for every candidate, so two plans are compared over
    the same races and the same fields rather than over different luck.
    """
    if not candidates:
        return []
    if not 1 <= grid <= cars:
        raise ValueError(f"grid {grid} is outside a field of {cars}")
    ladder = pace_ladder(ladder, cars)
    draws = max(1, field_draws)
    per_draw = max(1, runs // draws)

    ranked: list[PlaceRanking] = []
    for plan in candidates:
        collected: list[np.ndarray] = []
        for draw in range(draws):
            # Same seed per draw index across plans: every candidate meets the
            # same set of fields, so the comparison is of plans and not of luck.
            field_rng = np.random.default_rng(seed * 1000 + draw)
            rivals = _draw_field(field_plan, cars, total_laps, field_rng)
            field = [
                race_model.Car(driver_number=index + 1, abbreviation=f"P{index + 1}",
                               pace_s=quickest_lap_s + ladder[index], grid=index + 1,
                               plan=plan if index + 1 == grid else rivals[index])
                for index in range(cars)
            ]
            result = race_model.simulate(
                field, total_laps, degradation, pit_loss_s, neutralisation, passes_per_lap,
                compound_offset_s=compound_offset_s or {}, runs=per_draw,
                rng=np.random.default_rng(seed * 1000 + draw))
            collected.append(result.positions[grid])
        finishes = np.concatenate(collected)
        ranked.append(PlaceRanking(
            plan=plan,
            mean_finish=float(finishes.mean()),
            std_error=float(finishes.std(ddof=1) / np.sqrt(len(finishes))) if len(finishes) > 1 else 0.0,
            median_finish=int(np.median(finishes)),
            best=int(finishes.min()),
            worst=int(finishes.max()),
            podium_share=float((finishes <= 3).mean()),
            points_share=float((finishes <= 10).mean()),
            gained=float(grid - finishes.mean()),
            behind_best=0.0,
            within_noise=False,
        ))

    ranked.sort(key=lambda r: r.mean_finish)
    best = ranked[0]
    for entry in ranked:
        entry.behind_best = entry.mean_finish - best.mean_finish
        # Two means this close, at these run counts, are one answer with noise
        # on it rather than two answers.
        spread = float(np.hypot(entry.std_error, best.std_error))
        entry.within_noise = entry.behind_best <= NOISE_SIGMAS * spread
    return ranked


def _stop_laps(plan: Plan) -> list[int]:
    laps, running = [], 0
    for _, length in plan.stints[:-1]:
        running += length
        laps.append(running)
    return laps
