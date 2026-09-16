"""Costing a race plan: the trade between stopping and wearing tyres out."""

import pytest

from racecraft.model import strategy
from racecraft.model.strategy import Plan

DEG = {"SOFT": 0.10, "MEDIUM": 0.06, "HARD": 0.04}
OFFSETS = {"SOFT": 0.0, "MEDIUM": 0.35, "HARD": 0.70}     # harder tyres are slower at the same age


def test_wear_grows_with_the_square_of_stint_length():
    # Lap n costs n * degradation, so a stint costs the triangular sum. Twice
    # the laps is roughly four times the loss, which is why stopping pays.
    ten = strategy.stint_cost("SOFT", 10, DEG)
    twenty = strategy.stint_cost("SOFT", 20, DEG)
    assert ten == pytest.approx(0.10 * 55)
    assert twenty / ten == pytest.approx(3.8, abs=0.1)


def test_a_plan_costs_its_tyres_its_compounds_and_its_stops():
    plan = Plan((("SOFT", 20), ("HARD", 20)))
    costed = strategy.cost(plan, DEG, pit_loss_s=22.0, compound_offset_s=OFFSETS)
    assert costed.pit_seconds == 22.0
    assert costed.compound_seconds == pytest.approx(0.70 * 20)      # 20 laps on hards
    assert costed.tyre_seconds == pytest.approx(strategy.stint_cost("SOFT", 20, DEG)
                                                + strategy.stint_cost("HARD", 20, DEG))
    assert costed.seconds_lost == pytest.approx(costed.tyre_seconds + costed.compound_seconds + 22.0)


def test_cheap_tyres_and_dear_stops_mean_stopping_less():
    gentle = {c: v / 4 for c, v in DEG.items()}
    assert strategy.best_stop_count(50, gentle, pit_loss_s=30.0) == 1


def test_harsh_tyres_and_cheap_stops_mean_stopping_more():
    harsh = {c: v * 3 for c, v in DEG.items()}
    assert strategy.best_stop_count(50, harsh, pit_loss_s=16.0) >= 2


def test_every_plan_uses_two_compounds_as_the_rules_require():
    plans = strategy.enumerate_plans(50, ("SOFT", "MEDIUM", "HARD"), max_stops=2, min_stint=10, step=5)
    assert plans
    assert all(len({compound for compound, _ in plan.stints}) >= 2 for plan in plans)


def test_plans_always_cover_the_full_race():
    plans = strategy.enumerate_plans(57, ("SOFT", "HARD"), max_stops=3, min_stint=8, step=4)
    assert all(plan.laps == 57 for plan in plans)


def test_compound_pace_changes_which_tyre_is_chosen():
    # Hard wears least, so ignoring pace picks it; counting pace does not.
    ignoring_pace = strategy.best_plans(50, DEG, 22.0, top=1, step=5)[0]
    counting_pace = strategy.best_plans(50, DEG, 22.0, top=1, step=5, compound_offset_s=OFFSETS)[0]
    hard_laps = lambda plan: sum(laps for compound, laps in plan.stints if compound == "HARD")
    assert hard_laps(ignoring_pace.plan) > hard_laps(counting_pace.plan)


def test_the_models_limits_are_stated_alongside_it():
    # A number this simple should not travel without them.
    assert any("safety car" in omission for omission in strategy.KNOWN_OMISSIONS)
    assert any("traffic" in omission for omission in strategy.KNOWN_OMISSIONS)
