"""Strategy under safety cars: a plan is a distribution, not a number."""

import numpy as np
import pytest

from racecraft.model import simulate, strategy
from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

DEG = {"SOFT": 0.09, "MEDIUM": 0.06, "HARD": 0.04}
PIT = 22.0
NEVER = Neutralisation(per_lap=0.0)
OFTEN = Neutralisation(per_lap=0.05, laps=3.0, stop_discount=0.6)


def simulate_plan(plan, risk=OFTEN, runs=600, seed=1, **kwargs):
    return simulate.simulate_plan(plan, DEG, PIT, risk, runs=runs,
                                  rng=np.random.default_rng(seed), **kwargs)


def test_a_race_that_stays_green_costs_what_the_simple_model_says():
    plan = Plan((("SOFT", 25), ("HARD", 25)))
    simulated = simulate_plan(plan, risk=NEVER, runs=20)
    plain = strategy.cost(plan, DEG, PIT)
    assert simulated.expected_s == pytest.approx(plain.seconds_lost, abs=0.01)
    assert simulated.green_s == pytest.approx(plain.seconds_lost, abs=0.01)
    assert simulated.cheap_stop_share == 0.0


def test_safety_cars_make_a_plan_cheaper_on_average():
    plan = Plan((("SOFT", 25), ("HARD", 25)))
    assert simulate_plan(plan).expected_s < simulate_plan(plan, risk=NEVER, runs=20).green_s


def test_stopping_later_catches_more_safety_cars():
    # A stop still owed late in the race is a stop that can be taken cheaply.
    early = simulate_plan(Plan((("SOFT", 14), ("HARD", 36))))
    late = simulate_plan(Plan((("SOFT", 36), ("HARD", 14))))
    assert late.cheap_stop_share > early.cheap_stop_share


def test_the_downside_of_a_plan_is_its_green_race():
    # Nothing worse than a green race can happen: a neutralisation only ever
    # makes a stop cheaper, never dearer.
    plan = Plan((("SOFT", 30), ("MEDIUM", 20)))
    result = simulate_plan(plan)
    assert result.worst_case_s <= result.green_s + 0.01
    assert result.best_case_s < result.expected_s < result.green_s


def test_a_deeper_discount_is_worth_more():
    plan = Plan((("SOFT", 25), ("HARD", 25)))
    shallow = simulate_plan(plan, risk=Neutralisation(per_lap=0.05, laps=3.0, stop_discount=0.9))
    deep = simulate_plan(plan, risk=Neutralisation(per_lap=0.05, laps=3.0, stop_discount=0.3))
    assert deep.expected_s < shallow.expected_s


def test_results_repeat_with_the_same_seed():
    plan = Plan((("SOFT", 25), ("HARD", 25)))
    assert simulate_plan(plan, seed=7).expected_s == simulate_plan(plan, seed=7).expected_s


def test_risk_can_reorder_plans_that_look_equal_when_green():
    # The whole point: ranking on a green race alone misses this.
    plans = strategy.enumerate_plans(50, ("SOFT", "MEDIUM"), max_stops=1, min_stint=12, step=6)
    ranked = simulate.best_plans_with_risk(plans, DEG, PIT, OFTEN, runs=400,
                                           rng=np.random.default_rng(3), top=len(plans))
    assert ranked[0].expected_s <= ranked[-1].expected_s
    assert any(a.green_s > b.green_s for a, b in zip(ranked, ranked[1:]))


def test_circuit_rate_converts_periods_per_race_into_a_per_lap_chance():
    risk = Neutralisation.for_circuit(periods_per_race=1.5, total_laps=50)
    assert risk.per_lap == pytest.approx(0.03)


def test_the_ranking_can_be_asked_for_plans_of_a_certain_shape_only():
    """
    How a car's own tyres reach the shortlist. Filtering after the ranking would
    leave a car that cannot run any of the best plans with nothing at all.
    """
    from racecraft.model import simulate as simulate_model

    common = dict(total_laps=50, degradation={"SOFT": 0.10, "MEDIUM": 0.06, "HARD": 0.04},
                  pit_loss_s=22.0, neutralisation=Neutralisation(per_lap=0.02), keep=5)
    everything = simulate_model.rank_with_risk(**common)
    one_stop_only = simulate_model.rank_with_risk(**common, allow=lambda plan: plan.stops == 1)

    assert everything, "nothing to compare"
    assert one_stop_only, "the filter left nothing at all"
    assert all(cost.plan.stops == 1 for cost in one_stop_only)
    # And the filtered ranking is still a ranking: cheapest first.
    assert [c.expected_s for c in one_stop_only] == sorted(c.expected_s for c in one_stop_only)


def test_a_filter_that_allows_nothing_returns_nothing_rather_than_failing():
    from racecraft.model import simulate as simulate_model

    assert simulate_model.rank_with_risk(
        50, {"SOFT": 0.1, "MEDIUM": 0.06, "HARD": 0.04}, 22.0, Neutralisation(),
        allow=lambda plan: False) == []
