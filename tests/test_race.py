"""The race simulator: places rather than seconds."""

import numpy as np
import pytest

from racecraft.model import race
from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

DEG = {"SOFT": 0.05, "MEDIUM": 0.05, "HARD": 0.05}
PLAN = Plan((("MEDIUM", 25), ("SOFT", 25)))
LAPS = 50
QUIET = Neutralisation(per_lap=0.0)


def field(size=10, spread=0.25, fast_car_last=False):
    cars = [race.Car(i + 1, f"D{i+1}", 90.0 + spread * i, i + 1, PLAN) for i in range(size)]
    if fast_car_last:
        cars.append(race.Car(99, "FAST", 90.0 - 0.5, size + 1, PLAN))
    return cars


def run(cars, passes_per_lap=0.1, risk=QUIET, runs=60, seed=3):
    return race.simulate(cars, LAPS, DEG, 22.0, risk, passes_per_lap,
                         runs=runs, rng=np.random.default_rng(seed))


def test_following_costs_more_the_closer_you_are():
    assert race.following_penalty(0.2) > race.following_penalty(0.8) > race.following_penalty(2.0)
    assert race.following_penalty(10.0) == 0.0


def test_everyone_finishes_somewhere_and_nowhere_twice():
    cars = field()
    result = run(cars)
    for driver, positions in result.positions.items():
        assert len(positions) == 60
        assert positions.min() >= 1 and positions.max() <= len(cars)
    # Within a single race the finishing positions are a permutation.
    first_run = [result.positions[car.driver_number][0] for car in cars]
    assert sorted(first_run) == list(range(1, len(cars) + 1))


def test_a_quicker_car_finishes_ahead_when_passing_is_easy():
    result = run(field(fast_car_last=True), passes_per_lap=0.5)
    assert result.positions[99].mean() < 4


def test_the_same_car_is_stuck_when_passing_is_hard():
    # The only difference is the circuit. This is why Monaco is not Monza.
    easy = run(field(fast_car_last=True), passes_per_lap=0.5).positions[99].mean()
    hard = run(field(fast_car_last=True), passes_per_lap=0.01).positions[99].mean()
    assert hard > easy + 5


def test_a_safety_car_closes_the_field_up():
    elapsed = np.array([0.0, 30.0, 75.0, 130.0])
    bunched = race._bunch_up(elapsed)
    assert np.argsort(bunched).tolist() == np.argsort(elapsed).tolist()   # order is kept
    assert bunched.max() - bunched.min() < elapsed.max() - elapsed.min()


def test_blocking_holds_a_car_behind_one_it_cannot_pass():
    order = np.array([0, 1])                     # car 0 leads at the start of the lap
    elapsed = np.array([100.0, 100.1])           # car 1 has caught it
    never = race._apply_blocking(elapsed.copy(), order, passes_per_lap=0.0,
                                 rng=np.random.default_rng(0))
    assert never[1] == pytest.approx(never[0] + race.MIN_FOLLOWING_GAP_S)

    always = race._apply_blocking(elapsed.copy(), order, passes_per_lap=1.0,
                                  rng=np.random.default_rng(0))
    assert always[1] == pytest.approx(100.1)     # through, keeping its own time


def test_strategy_changes_where_a_car_finishes():
    # The question the simulator exists to answer: same car, same grid slot,
    # different plan.
    def finish(plan):
        cars = field(size=12)
        cars[7] = race.Car(8, "US", cars[7].pace_s, 8, plan)
        return run(cars, runs=120).positions[8].mean()

    sensible = finish(Plan((("MEDIUM", 25), ("SOFT", 25))))
    wasteful = finish(Plan((("SOFT", 12), ("MEDIUM", 13), ("SOFT", 12), ("MEDIUM", 13))))
    assert wasteful > sensible + 0.5             # three extra stops cost places


def test_results_repeat_with_the_same_seed():
    assert run(field(), seed=9).positions[1].mean() == run(field(), seed=9).positions[1].mean()


def test_passes_per_race_becomes_a_per_lap_chance():
    monaco = race.pass_probability(5.8, 78)
    vegas = race.pass_probability(48.3, 50)
    assert monaco < vegas
    assert 0 < monaco < 1 and 0 < vegas < 1


# ------------------------------------------------------------- used sets

def test_a_car_on_a_worn_set_loses_the_laps_that_set_already_did():
    """
    Two identical cars, identical plans, one starting its first stint on a set
    with twenty laps on it. Wear is counted from where the set already is, so it
    starts the race at the pace the other car will only reach twenty laps in.
    """
    cars = field(size=6)
    cars[0] = race.Car(1, "D1", 90.0, 1, PLAN, start_ages=(20, 0))
    result = run(cars, runs=80)
    assert result.positions[1].mean() > result.positions[2].mean()


def test_a_fresh_set_is_the_default_and_matches_zero_ages():
    cars = field(size=6)
    spelled_out = [race.Car(c.driver_number, c.abbreviation, c.pace_s, c.grid, c.plan,
                            start_ages=(0, 0)) for c in cars]
    assert (run(cars).positions[1] == run(spelled_out).positions[1]).all()


def test_the_age_a_stint_starts_on_is_read_per_stint():
    car = race.Car(1, "D1", 90.0, 1, PLAN, start_ages=(0, 9))
    assert car.age_at(0) == 0 and car.age_at(1) == 9
    assert car.age_at(5) == 0            # beyond the plan: a new set


def test_a_stop_is_due_when_the_plan_says_so_whatever_else_is_happening():
    assert race.stops_now(lap=25, total_laps=LAPS, due_lap=25, neutral=False, stint_laps=25)
    assert not race.stops_now(lap=24, total_laps=LAPS, due_lap=25, neutral=False, stint_laps=24)


def test_a_safety_car_stop_is_taken_only_after_a_stint_worth_ending():
    """
    Counted in laps run in the stint, not in the age of the set. Counting the
    set's age would send a car that started on a twenty-lap tyre into the pits
    on the first safety car of lap two, which is the model inventing a stop.
    """
    assert race.stops_now(lap=12, total_laps=LAPS, due_lap=25, neutral=True, stint_laps=12)
    assert not race.stops_now(lap=2, total_laps=LAPS, due_lap=25, neutral=True, stint_laps=2)
    # Nor with the flag out near the end, where the stop cannot be paid back.
    assert not race.stops_now(lap=LAPS - 2, total_laps=LAPS, due_lap=LAPS, neutral=True, stint_laps=30)
