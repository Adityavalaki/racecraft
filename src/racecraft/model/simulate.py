"""
Strategy under uncertainty: what a plan is worth when safety cars happen.

The plan costing in `strategy` assumes the race runs green from start to
finish. Real races do not. Across 2023-2026 a race is neutralised 1.27 times
on average, and a stop taken entirely under a full safety car costs 61% of a
green one — 13.7 s against 22.5 s, measured against the drivers who stayed
out on the same laps.

That changes what a plan is worth, and not evenly: a plan that still has a
stop in hand when the safety car comes gets it at a discount, while one that
has already stopped gains nothing. So a plan is not a number, it is a
distribution, and the right comparison is over many races rather than one.

The strategy simulated here is the one teams actually use: stop as planned,
unless the race is neutralised while a stop is still owed and the tyres have
done enough laps to be worth changing, in which case take it now.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from racecraft.model.strategy import Plan, stint_cost

# Measured across the lake; see the README for how.
NEUTRALISATION_PER_LAP = 0.021       # chance a neutralisation begins on a given lap
NEUTRALISATION_LAPS = 3.0            # how long one lasts, in laps
SAFETY_CAR_STOP_DISCOUNT = 0.61      # what a stop costs under one, against a green stop
MIN_STINT_BEFORE_OPPORTUNISTIC = 8   # laps before it is worth taking a cheap stop


@dataclass
class Neutralisation:
    """How often a race is interrupted here, and what that does to a stop."""
    per_lap: float = NEUTRALISATION_PER_LAP
    laps: float = NEUTRALISATION_LAPS
    stop_discount: float = SAFETY_CAR_STOP_DISCOUNT

    @classmethod
    def for_circuit(cls, periods_per_race: float, total_laps: int, laps: float = NEUTRALISATION_LAPS,
                    discount: float = SAFETY_CAR_STOP_DISCOUNT) -> "Neutralisation":
        return cls(per_lap=periods_per_race / max(1, total_laps), laps=laps, stop_discount=discount)


@dataclass
class RiskyCost:
    plan: Plan
    expected_s: float            # mean over simulated races
    green_s: float               # what it costs if the race stays green
    best_case_s: float           # 10th percentile: the safety car fell kindly
    worst_case_s: float          # 90th percentile
    cheap_stop_share: float      # how often at least one stop was taken under neutralisation

    def as_dict(self) -> dict:
        return {"plan": str(self.plan), "stops": self.plan.stops,
                "expected_s": round(self.expected_s, 1), "green_s": round(self.green_s, 1),
                "best_case_s": round(self.best_case_s, 1), "worst_case_s": round(self.worst_case_s, 1),
                "cheap_stop_share": round(self.cheap_stop_share, 3)}


def simulate_plan(plan: Plan, degradation: dict[str, float], pit_loss_s: float,
                  neutralisation: Neutralisation, curvature: dict[str, float] | None = None,
                  compound_offset_s: dict[str, float] | None = None,
                  runs: int = 2000, rng: np.random.Generator | None = None) -> RiskyCost:
    """
    Run one plan through many races and report what it costs.

    Each simulated race draws its own neutralisations. The driver follows the
    plan, except that a neutralisation arriving while a stop is still owed —
    and the current tyres have done enough laps — brings that stop forward to
    now, at the discount.
    """
    rng = rng or np.random.default_rng(0)
    offsets = compound_offset_s or {}
    total_laps = plan.laps
    planned_stops = [sum(length for _, length in plan.stints[:i + 1]) for i in range(plan.stops)]
    compounds = [compound for compound, _ in plan.stints]

    # The compound penalty does not depend on when stops happen, only on how
    # many laps run on each tyre, so it is the same in every simulated race.
    compound_seconds = sum(offsets.get(name, 0.0) * length for name, length in plan.stints)

    results = np.empty(runs)
    cheap = np.zeros(runs, dtype=bool)
    for run in range(runs):
        neutral_laps = _draw_neutral_laps(total_laps, neutralisation, rng)
        tyre_seconds, pit_seconds, took_cheap = _one_race(
            total_laps, planned_stops, compounds, neutral_laps,
            degradation, curvature, pit_loss_s, neutralisation.stop_discount)
        results[run] = tyre_seconds + pit_seconds + compound_seconds
        cheap[run] = took_cheap

    green_tyre, green_pit, _ = _one_race(total_laps, planned_stops, compounds, set(),
                                         degradation, curvature, pit_loss_s, neutralisation.stop_discount)
    return RiskyCost(
        plan=plan,
        expected_s=float(results.mean()),
        green_s=float(green_tyre + green_pit + compound_seconds),
        best_case_s=float(np.percentile(results, 10)),
        worst_case_s=float(np.percentile(results, 90)),
        cheap_stop_share=float(cheap.mean()),
    )


def _draw_neutral_laps(total_laps: int, neutralisation: Neutralisation, rng: np.random.Generator) -> set[int]:
    """Which laps of this race are run under a safety car or VSC."""
    starts = rng.random(total_laps) < neutralisation.per_lap
    neutral: set[int] = set()
    for lap in np.flatnonzero(starts) + 1:
        length = max(1, int(round(rng.exponential(neutralisation.laps))))
        neutral.update(range(int(lap), min(total_laps, int(lap) + length) + 1))
    return neutral


def _one_race(total_laps: int, planned_stops: list[int], compounds: list[str], neutral_laps: set[int],
              degradation: dict[str, float], curvature: dict[str, float] | None,
              pit_loss_s: float, discount: float) -> tuple[float, float, bool]:
    """Walk the race lap by lap, taking a cheap stop when one is offered."""
    stops_left = list(planned_stops)
    stint_start, stint_index = 0, 0
    tyre_seconds, pit_seconds, took_cheap = 0.0, 0.0, False

    lap = 1
    while lap <= total_laps and stops_left:
        age = lap - stint_start
        due = lap >= stops_left[0]
        opportunity = (lap in neutral_laps and age >= MIN_STINT_BEFORE_OPPORTUNISTIC
                       and total_laps - lap >= MIN_STINT_BEFORE_OPPORTUNISTIC)
        if due or opportunity:
            tyre_seconds += stint_cost(compounds[stint_index], age, degradation, curvature)
            cheap = lap in neutral_laps
            pit_seconds += pit_loss_s * (discount if cheap else 1.0)
            took_cheap = took_cheap or cheap
            stops_left.pop(0)
            stint_start, stint_index = lap, stint_index + 1
        lap += 1

    tyre_seconds += stint_cost(compounds[stint_index], total_laps - stint_start, degradation, curvature)
    return tyre_seconds, pit_seconds, took_cheap


def best_plans_with_risk(plans: list[Plan], degradation: dict[str, float], pit_loss_s: float,
                         neutralisation: Neutralisation, curvature: dict[str, float] | None = None,
                         compound_offset_s: dict[str, float] | None = None,
                         runs: int = 500, top: int = 5,
                         rng: np.random.Generator | None = None) -> list[RiskyCost]:
    """Simulate every plan and rank by what it is expected to cost."""
    rng = rng or np.random.default_rng(0)
    costs = [simulate_plan(plan, degradation, pit_loss_s, neutralisation, curvature,
                           compound_offset_s, runs=runs, rng=rng) for plan in plans]
    return sorted(costs, key=lambda c: c.expected_s)[:top]


# How the plan space is swept when safety cars are simulated: in threes rather
# than ones, because the cost curve is a shallow bowl and neighbouring stop laps
# differ by a tenth. Then two passes: a cheap screen over everything that survives
# the bound below, and an accurate run over the leaders.
RISK_STEP = 3
SCREEN_RUNS = 120
SCREEN_KEEP = 24
RISK_RUNS = 1500


def rank_with_risk(total_laps: int, degradation: dict[str, float], pit_loss_s: float,
                   neutralisation: Neutralisation, compound_offset_s: dict[str, float] | None = None,
                   *, keep: int = 8, min_stint: int = 10, max_stops: int = 2,
                   allow=None) -> list[RiskyCost]:
    """
    The best plans over races that can be neutralised, one per shape.

    This is a different question from the green-flag ranking, not a refinement
    of it. A stop under a safety car costs about 61% of a green one, so the best
    plan on a circuit that neutralises often is usually a *later* first stop — a
    longer first stint leaves more laps in which a cheap stop can arrive. It is
    also the better description of what teams actually do: across the fourteen
    2026 races it is 0.43 stops off the field's median, against 0.57 for the
    green ranking.

    Simulating every plan took 12 seconds for an answer settled by a handful of
    them, so the hopeless ones are dropped first, by a bound rather than a guess.
    A neutralisation can only ever save the discount on a stop, so no plan costs
    less than `green - stops x (1 - discount) x pit loss`; if even that floor is
    above the best plan's green cost, the plan cannot win. The bound is exact but
    loose for two-stop plans — at Zandvoort 3054 survived it — so the survivors
    are screened on few runs and only the leaders re-run properly.

    Mirror images — soft then medium against medium then soft — cost the same
    here, so the ranking keeps one of each and the caller is not handed the same
    answer twice.

    `allow` filters the plans before any of that, and is how a car's own tyres
    reach the shortlist: ranking first and filtering after would leave a car
    that cannot run any of the best plans with nothing at all, which is what
    happened to Verstappen at Monaco 2025 — one new medium, one new hard, four
    used softs, and every two-stop plan in the shortlist calling for two hards.
    The right answer there is the best plan he could run, not silence.
    """
    from racecraft.model import strategy as strategy_model

    offsets = compound_offset_s or {}
    plans = strategy_model.enumerate_plans(total_laps, tuple(degradation), max_stops=max_stops,
                                           min_stint=min_stint, step=RISK_STEP)
    if allow is not None:
        plans = [plan for plan in plans if allow(plan)]
    if not plans:
        return []

    saving_per_stop = (1 - neutralisation.stop_discount) * pit_loss_s
    green = {plan: strategy_model.cost(plan, degradation, pit_loss_s, compound_offset_s=offsets)
             for plan in plans}
    best_green = min(c.seconds_lost for c in green.values())
    contenders = [plan for plan in plans
                  if green[plan].seconds_lost - plan.stops * saving_per_stop < best_green]

    screened = best_plans_with_risk(contenders, degradation, pit_loss_s, neutralisation,
                                    compound_offset_s=offsets, runs=SCREEN_RUNS, top=SCREEN_KEEP)
    ranked = best_plans_with_risk([c.plan for c in screened], degradation, pit_loss_s,
                                  neutralisation, compound_offset_s=offsets,
                                  runs=RISK_RUNS, top=SCREEN_KEEP)

    out, seen = [], set()
    for costed in ranked:
        shape = tuple(sorted(costed.plan.stints))
        if shape in seen:
            continue
        seen.add(shape)
        out.append(costed)
        if len(out) == keep:
            break
    return out
