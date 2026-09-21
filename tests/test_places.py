"""
Ranking strategies in places rather than seconds.

The point of the module is that the two disagree, so most of what is worth
testing is about not fooling yourself: that the ranking is reproducible, that
plans too close to separate are reported as tied rather than ordered, and that
the field is spread rather than uniform — because a field all on one plan
rewards a car for copying it, which looks like a finding and is an artefact.
"""

import numpy as np
import pytest

from racecraft.model import places
from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

TOTAL = 51
DEGRADATION = {"SOFT": 0.05, "MEDIUM": 0.054, "HARD": 0.065}
PIT_LOSS = 21.0
QUICKEST = 103.0
LADDER = [0.0 + 0.12 * i for i in range(20)]


def _stop(lap: int) -> Plan:
    return Plan((("MEDIUM", lap), ("HARD", TOTAL - lap)))


def _rank(candidates, *, grid=8, runs=150, draws=10, **kwargs):
    return places.rank_plans(
        candidates, _stop(24), grid=grid, ladder=LADDER, quickest_lap_s=QUICKEST,
        total_laps=TOTAL, degradation=DEGRADATION, pit_loss_s=PIT_LOSS,
        neutralisation=Neutralisation.for_circuit(1.0, TOTAL),
        passes_per_lap=0.12, runs=runs, field_draws=draws, **kwargs)


# ------------------------------------------------------------- the field

def test_the_field_is_spread_across_stop_laps_not_stacked_on_one():
    """
    Learned the hard way. Every rival on one identical plan produced a
    four-place cliff in favour of stopping on the lap they stopped, which is the
    simulation rewarding a car for copying a field that does not exist.
    """
    drawn = places._draw_field(_stop(24), cars=20, total_laps=TOTAL,
                               rng=np.random.default_rng(1))
    stops = [plan.stints[0][1] for plan in drawn]

    assert len(set(stops)) > 5, "a field on one stop lap is the artefact this exists to avoid"
    assert all(plan.laps == TOTAL for plan in drawn), "every rival still runs the full distance"


def test_the_spread_sits_around_what_the_field_is_doing():
    low, high = places.field_stop_window(TOTAL, _stop(24))
    assert low < 24 < high
    assert low >= 6 and high <= TOTAL - 6, "nobody stops on lap one or the last lap"

    stops = [p.stints[0][1] for p in places._draw_field(_stop(24), 20, TOTAL, np.random.default_rng(2))]
    assert all(low <= s <= high for s in stops)


def test_a_reference_with_no_stop_still_gives_a_usable_window():
    low, high = places.field_stop_window(TOTAL, Plan((("HARD", TOTAL),)))
    assert low < high


# ------------------------------------------------------------- the ranking

def test_a_plan_that_is_far_worse_finishes_worse():
    """Sanity: the model must agree with the seconds model where it is obviously right."""
    ranked = _rank([_stop(25), _stop(8)])
    by_stop = {r.plan.stints[0][1]: r for r in ranked}
    assert by_stop[25].mean_finish < by_stop[8].mean_finish, \
        "stopping on lap 8 of 51 throws away half a stint of tyre life"


def test_the_same_inputs_give_the_same_ranking():
    """Common random numbers, so a difference between plans is the plans."""
    first = _rank([_stop(22), _stop(28)])
    second = _rank([_stop(22), _stop(28)])
    assert [r.plan.stints[0][1] for r in first] == [r.plan.stints[0][1] for r in second]
    assert first[0].mean_finish == pytest.approx(second[0].mean_finish)


def test_every_candidate_meets_the_same_fields():
    """
    Otherwise one plan could win by drawing kinder rivals. Running a plan alone
    and in company must give it the same answer.
    """
    alone = _rank([_stop(22)])[0]
    in_company = next(r for r in _rank([_stop(22), _stop(28), _stop(34)])
                      if r.plan.stints[0][1] == 22)
    assert alone.mean_finish == pytest.approx(in_company.mean_finish)


def test_plans_too_close_to_separate_are_reported_as_tied():
    """
    A mean over a few hundred races carries a standard error, and a ranking
    printed without it manufactures a decision out of noise.
    """
    ranked = _rank([_stop(24), _stop(25)])
    assert ranked[0].within_noise, "the best plan is always within noise of itself"
    assert all(r.std_error > 0 for r in ranked)
    # These two differ by one lap of a shallow cost curve; they cannot be split.
    assert ranked[1].within_noise, f"separated by {ranked[1].behind_best:.2f} places"


def test_a_plan_far_enough_ahead_is_not_called_tied():
    ranked = _rank([_stop(25), _stop(8)])
    assert not ranked[1].within_noise, "lap 8 is not indistinguishable from lap 25"


def test_the_ranking_reports_what_a_decision_needs():
    ranked = _rank([_stop(22), _stop(28)])
    entry = ranked[0].as_dict()
    for key in ("plan", "stops", "stop_laps", "mean_finish", "std_error", "median_finish",
                "best", "worst", "podium_share", "points_share", "gained",
                "behind_best", "within_noise"):
        assert key in entry, key
    assert entry["stop_laps"] == places._stop_laps(ranked[0].plan)
    assert 1 <= entry["median_finish"] <= 20
    assert 0.0 <= entry["points_share"] <= 1.0
    assert entry["gained"] == pytest.approx(8 - entry["mean_finish"], abs=0.01)


def test_where_a_car_starts_changes_where_it_finishes():
    front = _rank([_stop(24)], grid=2)[0]
    back = _rank([_stop(24)], grid=16)[0]
    assert front.mean_finish < back.mean_finish
    assert front.podium_share > back.podium_share


# ------------------------------------------------------------- the edges

def test_no_candidates_is_an_empty_ranking_not_a_crash():
    assert _rank([]) == []


def test_a_grid_slot_outside_the_field_is_refused():
    with pytest.raises(ValueError, match="outside a field"):
        _rank([_stop(24)], grid=25)


def test_a_short_pace_ladder_is_padded_rather_than_failing():
    """A season can fit fewer cars than a race enters: someone's pace was not separable."""
    padded = places.pace_ladder([0.0, 0.2, 0.5], cars=20)
    assert len(padded) == 20
    assert padded == sorted(padded), "a ladder runs quickest first"
    assert padded[-1] > padded[2]


def test_an_empty_ladder_is_refused_rather_than_invented():
    with pytest.raises(ValueError, match="no fitted driver pace"):
        places.pace_ladder([], cars=20)


def test_a_long_ladder_is_cut_to_the_field():
    assert len(places.pace_ladder([0.1 * i for i in range(30)], cars=20)) == 20


# ------------------------------------------------------------- the car's own tyres

STOCK_NEW = {"SOFT": {"new": 2, "used": []}, "MEDIUM": {"new": 2, "used": []},
             "HARD": {"new": 2, "used": []}}
STOCK_WORN = {"SOFT": {"new": 0, "used": []}, "MEDIUM": {"new": 0, "used": [4]},
              "HARD": {"new": 1, "used": [12]}}


def test_a_plan_starts_on_the_sets_the_car_would_actually_use():
    ages = places.start_ages(_stop(24), STOCK_WORN, DEGRADATION)
    assert ages == (4, 0)                 # the 4-lap medium, then the new hard


def test_without_a_stock_every_stint_starts_new():
    assert places.start_ages(_stop(24), None, DEGRADATION) == (0, 0)


def test_a_plan_the_car_has_no_sets_for_is_refused_with_a_reason():
    ok, reason = places.runnable(Plan((("HARD", 25), ("HARD", 26))), STOCK_WORN, DEGRADATION)
    assert ok is True                     # one new hard and one with 12 laps: it can
    ok, reason = places.runnable(Plan((("SOFT", 25), ("SOFT", 26))), STOCK_WORN, DEGRADATION)
    assert not ok and reason == "no soft sets left"


def test_worn_tyres_finish_behind_the_same_plan_on_new_ones():
    """The whole point of the join: the same plan is not the same race."""
    fresh = _rank([_stop(24)], stock=STOCK_NEW)[0]
    worn = _rank([_stop(24)], stock={"SOFT": {"new": 0, "used": []},
                                     "MEDIUM": {"new": 0, "used": [15]},
                                     "HARD": {"new": 1, "used": []}})[0]
    assert worn.start_ages == (15, 0)
    assert worn.mean_finish > fresh.mean_finish


def test_the_ranking_can_change_when_the_tyres_do():
    """
    A car with one worn medium is better off running it short. On new sets the
    two plans are the other way round.
    """
    plans = [_stop(18), _stop(30)]
    fresh = {str(r.plan): r.mean_finish for r in _rank(plans, stock=STOCK_NEW)}
    worn = {str(r.plan): r.mean_finish for r in
            _rank(plans, stock={"SOFT": {"new": 0, "used": []},
                                "MEDIUM": {"new": 0, "used": [18]},
                                "HARD": {"new": 2, "used": []}})}
    long_stint, short_stint = str(_stop(30)), str(_stop(18))
    assert worn[long_stint] - worn[short_stint] > fresh[long_stint] - fresh[short_stint]


def test_a_rival_runs_its_own_tyres_when_its_drawn_plan_fits_them():
    plan = _stop(24)                              # medium then hard
    held = {"SOFT": {"new": 0, "used": []}, "MEDIUM": {"new": 0, "used": [6]},
            "HARD": {"new": 1, "used": []}}
    assert places._rival_ages(plan, 5, {5: held}, DEGRADATION) == (6, 0)


def test_a_rival_whose_drawn_plan_it_could_not_have_run_keeps_new_tyres():
    """
    Their plans are drawn rather than read, so a drawn plan can call for sets
    the real car never had. Inventing a different plan for a rival would be
    modelling a strategist; leaving it on new tyres is the honest fallback.
    """
    plan = _stop(24)
    without_hards = {"SOFT": {"new": 2, "used": []}, "MEDIUM": {"new": 2, "used": []},
                     "HARD": {"new": 0, "used": []}}
    assert places._rival_ages(plan, 5, {5: without_hards}, DEGRADATION) == ()
    assert places._rival_ages(plan, 9, {5: without_hards}, DEGRADATION) == ()   # unknown slot
