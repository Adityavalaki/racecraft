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

*It races the tyres the car actually has.* A plan is a sequence of compounds,
and a car cannot run one it has no sets for. Given a `stock` — what the car held
at the start of the race, from `tyre_sets` — plans it cannot run are dropped
with the reason, and every stint starts on the set it would really use, at the
age that set already carries. A car whose mediums all ran in qualifying is not
racing the same plan as one with three new sets, and before this both got the
same answer.

What it inherits from `race.py` and cannot fix: the rest of the field runs a
fixed plan and never reacts. Real rivals cover a stop. That makes this a model
of racing against a field, not against a strategist.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from racecraft.model import race as race_model
from racecraft.model import tyre_sets as tyre_sets_model
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
    # Laps already on the set each stint starts on, when the car's own tyres
    # were used. All zeros means it ran the plan on new sets.
    start_ages: tuple[int, ...] = ()

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
            "start_ages": list(self.start_ages),
            "on_used_sets": any(self.start_ages),
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
    opening = compounds[0]
    # The first compound that is not the opening one: a two-stop reference such
    # as soft > medium > soft would otherwise hand rivals soft > soft, which the
    # rules do not allow in a dry race.
    closing = next((c for c in compounds[1:] if c != opening), compounds[-1])
    out = []
    for _ in range(cars):
        stop = int(rng.integers(low, high + 1))
        out.append(Plan(stints=((opening, stop), (closing, total_laps - stop))))
    return out


def start_ages(plan: Plan, stock: dict | None, degradation: dict[str, float]) -> tuple[int, ...]:
    """
    Laps already on the set each stint of `plan` would start on.

    The assignment is `tyre_sets.check_plan`: new sets first, then the least
    worn, with the oldest set on the shortest stint. All zeros without a stock,
    which is the same as assuming new tyres throughout.
    """
    if not stock:
        return tuple(0 for _ in plan.stints)
    check = tyre_sets_model.check_plan([(c, laps) for c, laps in plan.stints], stock, degradation)
    if not check.feasible:
        return tuple(0 for _ in plan.stints)
    return tuple(age for _, _, age in check.stints)


def runnable(plan: Plan, stock: dict | None, degradation: dict[str, float]) -> tuple[bool, str | None]:
    """Whether the car has the sets for this plan, and why not when it does not."""
    if not stock:
        return True, None
    check = tyre_sets_model.check_plan([(c, laps) for c, laps in plan.stints], stock, degradation)
    return check.feasible, check.reason


def rank_plans(candidates: list[Plan], field_plan: Plan, *, grid: int, ladder: list[float],
               quickest_lap_s: float, total_laps: int, degradation: dict[str, float],
               pit_loss_s: float, neutralisation: Neutralisation, passes_per_lap: float,
               compound_offset_s: dict[str, float] | None = None,
               runs: int = DEFAULT_RUNS, cars: int = DEFAULT_CARS,
               field_draws: int = DEFAULT_FIELD_DRAWS, seed: int = 11,
               following=None, stock: dict | None = None) -> list[PlaceRanking]:
    """
    Every candidate plan, run as a whole race, ranked by where it finishes.

    `grid` is the slot the car being advised starts from. `field_plan` is what
    the rest of the field is doing on average; their stop laps are spread around
    it and redrawn `field_draws` times, because a field all on one lap rewards
    copying it and that is an artefact rather than a finding.

    `stock` is what the car being advised has in its garage: `{compound: {"new":
    n, "used": [laps, ...]}}`, as `tyre_sets` reconstructs it. With one, its
    stints start on the sets it would really use and carry the laps those sets
    already have; without, every stint starts on a new tyre. The rest of the
    field always runs new sets, because what they have is not knowable from
    their own plans.

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
        ages = start_ages(plan, stock, degradation)
        collected: list[np.ndarray] = []
        for draw in range(draws):
            # Same seed per draw index across plans: every candidate meets the
            # same set of fields, so the comparison is of plans and not of luck.
            field_rng = np.random.default_rng(seed * 1000 + draw)
            rivals = _draw_field(field_plan, cars, total_laps, field_rng)
            field = [
                race_model.Car(driver_number=index + 1, abbreviation=f"P{index + 1}",
                               pace_s=quickest_lap_s + ladder[index], grid=index + 1,
                               plan=plan if index + 1 == grid else rivals[index],
                               start_ages=ages if index + 1 == grid else ())
                for index in range(cars)
            ]
            result = race_model.simulate(
                field, total_laps, degradation, pit_loss_s, neutralisation, passes_per_lap,
                compound_offset_s=compound_offset_s or {}, runs=per_draw,
                rng=np.random.default_rng(seed * 1000 + draw), following=following)
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
            start_ages=ages,
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


@dataclass
class RaceStudy:
    """A shortlist of plans and how each one finishes, for one car on one grid slot."""
    grid: int
    shortlist: list            # simulate.RiskyCost, best expected seconds first
    ranking: list[PlaceRanking]
    field_plan: Plan
    # What the car had in the garage, and the plans it ruled out.
    stock: dict | None = None
    dropped: list[dict] = None            # {"plan", "reason"}

    def as_dict(self) -> dict:
        seconds = {str(c.plan): c for c in self.shortlist}
        rows = []
        for entry in self.ranking:
            record = entry.as_dict()
            costed = seconds.get(str(entry.plan))
            if costed is not None:
                record["expected_s"] = round(costed.expected_s, 1)
                record["green_s"] = round(costed.green_s, 1)
            rows.append(record)
        cheapest = str(self.shortlist[0].plan) if self.shortlist else None
        low, high = field_stop_window(self.field_plan.laps, self.field_plan)
        return {
            "grid": self.grid,
            "plans": rows,
            "stock": None if self.stock is None else {
                compound: {"new": held["new"], "used": list(held["used"])}
                for compound, held in self.stock.items()
            },
            "dropped": list(self.dropped or []),
            "cheapest_in_seconds": cheapest,
            "best_in_places": str(self.ranking[0].plan) if self.ranking else None,
            "field_plan": str(self.field_plan),
            "field_stop_window": [low, high],
            "field_draws": DEFAULT_FIELD_DRAWS,
        }


def study(inputs, grid: int, *, plans: int = 10, runs: int = DEFAULT_RUNS,
          field_draws: int = DEFAULT_FIELD_DRAWS, stock: dict | None = None) -> RaceStudy:
    """
    Shortlist plans for one car, then race each against the field.

    The shortlist comes from the ranking that allows for safety cars rather than
    the green-flag one, because it is the better description of what teams do —
    0.43 stops off the field's median across the 2026 races, against 0.57 — and
    the shortlist decides which plans ever get raced. The field, on average,
    runs the best of them.

    With a `stock`, the shortlist is cut to the plans the car has the sets for,
    and each stint starts on the set it would use. The field plan is chosen
    before that cut: the rest of the field is not short of tyres because this
    car is.

    `inputs` is a `race_inputs.RaceInputs`, so everything here was measured only
    from races that had finished before the one being studied.
    """
    from racecraft.model import simulate as simulate_model

    shortlist = simulate_model.rank_with_risk(
        inputs.total_laps, inputs.degradation, inputs.pit_loss_s, inputs.neutralisation,
        inputs.compound_offset_s, keep=plans)
    if not shortlist:
        return RaceStudy(grid=grid, shortlist=[], ranking=[], field_plan=Plan(()),
                         stock=stock, dropped=[])

    field_plan = shortlist[0].plan
    dropped = []
    if stock:
        kept = []
        for costed in shortlist:
            ok, reason = runnable(costed.plan, stock, inputs.degradation)
            (kept if ok else dropped).append(costed if ok else
                                             {"plan": str(costed.plan), "reason": reason})
        shortlist = kept
    if not shortlist:
        return RaceStudy(grid=grid, shortlist=[], ranking=[], field_plan=field_plan,
                         stock=stock, dropped=dropped)

    ranking = rank_plans(
        [c.plan for c in shortlist], field_plan, grid=grid, ladder=inputs.ladder,
        quickest_lap_s=inputs.quickest_lap_s, total_laps=inputs.total_laps,
        degradation=inputs.degradation, pit_loss_s=inputs.pit_loss_s,
        neutralisation=inputs.neutralisation, passes_per_lap=inputs.passes_per_lap,
        compound_offset_s=inputs.compound_offset_s, runs=runs, cars=inputs.cars,
        field_draws=field_draws, following=inputs.following_table, stock=stock)
    return RaceStudy(grid=grid, shortlist=shortlist, ranking=ranking, field_plan=field_plan,
                     stock=stock, dropped=dropped)


# What the places model cannot see, shown beside its ranking. Traffic and track
# position are the two the seconds model leaves out and this one models; what is
# left, and the new limit this one brings, belong here instead.
OMISSIONS = (
    "rivals: the rest of the field runs a fixed plan and never covers a stop",
    "the field's tyres: rivals run new sets, because what they have left cannot "
    "be read from their plans",
    "the cliff: degradation past the point teams actually pit is unmeasured",
    "warm-up: an out-lap on cold tyres is slower than the model's fresh pace",
    "car pace on the day: the field's order comes from earlier races, and that is "
    "most of what decides where anyone finishes",
)


def verdict(result: RaceStudy) -> dict:
    """
    What the ranking says, in the terms a decision needs.

    Kept here rather than in the terminal command or the interface, so the two
    cannot end up saying different things about the same numbers.

    The honest price of track position is the cheapest plan that is as good as
    the best in places, not the best itself: when several tie for the lead, the
    best by a hair can cost seconds that a tied plan does not. Measuring against
    the best alone once reported 3.3 s where the real price was 0.1 s.
    """
    if not result.ranking or not result.shortlist:
        return {"agree": None, "tied": [], "price": None, "bad_plan": None}

    expected = {str(c.plan): c.expected_s for c in result.shortlist}
    cheapest = str(result.shortlist[0].plan)
    best = str(result.ranking[0].plan)
    by_name = {str(e.plan): e for e in result.ranking}
    cheapest_entry = by_name[cheapest]
    tied = [str(e.plan) for e in result.ranking if e.within_noise]

    price = None
    if cheapest != best and not cheapest_entry.within_noise:
        contenders = [e for e in result.ranking if e.within_noise]
        buy = min(contenders, key=lambda e: expected[str(e.plan)])
        price = {
            "plan": str(buy.plan),
            "instead_of": cheapest,
            "extra_seconds": round(expected[str(buy.plan)] - expected[cheapest], 1),
            "places_gained": round(cheapest_entry.mean_finish - buy.mean_finish, 2),
        }

    worst = result.ranking[-1]
    bad_plan = None
    if not worst.within_noise:
        bad_plan = {
            "plan": str(worst.plan),
            "extra_seconds": round(expected[str(worst.plan)] - expected[cheapest], 1),
            "places_lost": round(worst.behind_best, 2),
        }

    return {
        "cheapest_in_seconds": cheapest,
        "best_in_places": best,
        # "agree" is true when the two pick the same plan or the seconds pick is
        # inside the places pick's error bar: a different top line within noise
        # is the same answer, and saying otherwise would be selling a decision.
        "agree": cheapest == best or cheapest_entry.within_noise,
        "tied": tied,
        "price": price,
        "bad_plan": bad_plan,
    }
