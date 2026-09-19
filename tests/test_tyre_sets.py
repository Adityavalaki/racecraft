"""
Following tyre sets through a weekend.

The feed never numbers a set, so every rule here is an inference: which
earlier set a stint continues, which sets went back to Pirelli, whose car a
rookie drove. Each test pins one of them to a case built by hand, where the
right answer is known.
"""

import pandas as pd
import pytest

from racecraft.model import tyre_sets

STANDARD = ["FP1", "FP2", "FP3", "Q", "R"]
SPRINT = ["FP1", "SQ", "S", "Q", "R"]


def _stint(session, compound, age, laps, *, car=1, stint=1, fresh=None, driver="AAA",
           team="Team", start=0.0):
    """Lap rows for one stint: `age` is the feed's lap count on the set at its first lap."""
    fresh = (age == 1) if fresh is None else fresh
    return [{
        "session": session, "driver_number": car, "driver": driver, "team": team,
        "stint": stint, "compound": compound, "tyre_life": age + i, "fresh_tyre": fresh,
        "lap_number": i + 1, "lap_start_t": start + 90.0 * i, "lap_end_t": start + 90.0 * (i + 1),
    } for i in range(laps)]


def _weekend(*stints, order=STANDARD, regulars=None, sprint=False, q3=(), year=2025, rnd=1):
    """A weekend from stint specs: (session, compound, age, laps, {options})."""
    frames = []
    for n, spec in enumerate(stints):
        session, compound, age, laps, *rest = spec
        options = rest[0] if rest else {}
        rows = pd.DataFrame(_stint(session, compound, age, laps, stint=n + 1,
                                   start=1000.0 * n, **options))
        frames.append(tyre_sets.stints_from_laps(rows, session))
    stints_df = pd.concat(frames, ignore_index=True)
    cars = regulars if regulars is not None else set(stints_df["driver_number"])
    return tyre_sets.build(stints_df, order, cars, year=year, round_number=rnd,
                           event_name="Test Grand Prix", sprint=sprint, q3_cars=set(q3))


def _sets(weekend, car=1):
    return weekend.cars[car].sets


# ------------------------------------------------------------- which set is which

def test_a_used_set_carries_its_laps_from_qualifying_into_the_race():
    w = _weekend(("Q", "MEDIUM", 1, 4), ("R", "MEDIUM", 5, 20))
    assert len(_sets(w)) == 1
    assert _sets(w)[0].laps_before("R", STANDARD) == 4


def test_a_counter_that_did_not_tick_is_still_the_same_set():
    """Ends a stint at age 6, next starts at 6: an out-lap the feed did not count."""
    w = _weekend(("FP3", "SOFT", 1, 6), ("FP3", "SOFT", 6, 4))
    assert len(_sets(w)) == 1
    assert _sets(w)[0].link == "stalled"


def test_a_counter_two_laps_behind_is_the_same_set_but_five_is_another():
    w = _weekend(("FP2", "SOFT", 1, 8), ("FP2", "SOFT", 7, 3))
    assert len(_sets(w)) == 1 and _sets(w)[0].link == "counter slipped"

    w = _weekend(("FP2", "SOFT", 1, 10), ("FP2", "SOFT", 6, 3))
    assert len(_sets(w)) == 2
    assert _sets(w)[1].link == "unseen"


def test_two_sets_that_fit_equally_the_more_recent_is_raced():
    """A six-lap soft from FP3 and one from qualifying: the race used the one kept."""
    w = _weekend(("FP3", "SOFT", 1, 6), ("Q", "SOFT", 1, 6), ("R", "SOFT", 7, 10))
    fp3, quali = _sets(w)
    assert [run.session for run in quali.runs] == ["Q", "R"]
    assert [run.session for run in fp3.runs] == ["FP3"]


def test_age_one_is_a_new_set_whatever_the_flag_says():
    w = _weekend(("FP1", "HARD", 1, 5), ("FP2", "HARD", 1, 4, {"fresh": False}))
    assert len(_sets(w)) == 2
    assert all(s.seen_new for s in _sets(w))


def test_a_worn_set_never_seen_before_counts_as_used():
    """Run in laps the feed did not time: it is from the allocation and not new."""
    w = _weekend(("R", "HARD", 9, 20))
    held = w.holding(1, "R")
    assert held.new["HARD"] == 1
    assert [laps for s, laps in held.used] == [8]


# ------------------------------------------------------------- what goes back

def test_the_most_worn_sets_go_back_after_practice():
    w = _weekend(("FP1", "MEDIUM", 1, 18), ("FP1", "SOFT", 1, 4), ("FP1", "HARD", 1, 9))
    held = w.holding(1, "FP2")
    assert sorted(r.laps for r in held.returned) == [9, 18]
    assert [(s.compound, laps) for s, laps in held.used] == [("SOFT", 4)]


def test_a_set_run_again_later_was_not_handed_back():
    """The FP1 medium comes back out in qualifying, so the soft went back instead."""
    w = _weekend(("FP1", "MEDIUM", 1, 18), ("FP1", "SOFT", 1, 4), ("FP1", "HARD", 1, 9),
                 ("Q", "MEDIUM", 19, 2))
    held = w.holding(1, "R")
    assert "MEDIUM" not in {r.set.compound for r in held.returned if r.after == "FP1"}


def test_with_no_used_set_to_give_a_new_one_goes_back_and_the_guess_is_named():
    w = _weekend(("FP1", "SOFT", 1, 3))
    held = w.holding(1, "FP2")
    assert held.new_returned == {"SOFT": 1}
    assert held.new["SOFT"] == 8 - 1 - 1
    assert any("guess" in note for note in held.notes)


def test_the_race_starts_with_seven_sets_or_six_after_q3():
    runs = [("FP1", "SOFT", 1, 5), ("FP1", "MEDIUM", 1, 5), ("FP2", "SOFT", 1, 5),
            ("FP2", "HARD", 1, 5), ("FP3", "SOFT", 1, 5), ("FP3", "SOFT", 1, 5),
            ("Q", "SOFT", 1, 3), ("Q", "SOFT", 1, 3)]
    assert _weekend(*runs).holding(1, "R").total == 7
    q3 = _weekend(*runs, q3={1}).holding(1, "R")
    assert q3.total == 6
    assert [r.set.compound for r in q3.returned if r.after == "Q"] == ["SOFT"]


def test_one_hard_and_one_medium_are_never_handed_back_before_the_race():
    """Both hards run in practice: the more worn goes back, the other must stay."""
    w = _weekend(("FP1", "HARD", 1, 20), ("FP1", "HARD", 1, 18), ("FP1", "SOFT", 1, 2))
    held = w.holding(1, "FP2")
    hards = [laps for s, laps in held.used if s.compound == "HARD"]
    assert hards == [18]


def test_after_a_sprint_the_set_with_most_sprint_laps_goes_back():
    w = _weekend(("FP1", "MEDIUM", 1, 3), ("SQ", "MEDIUM", 1, 3), ("S", "MEDIUM", 4, 19),
                 ("S", "HARD", 1, 2), order=SPRINT, sprint=True)
    held = w.holding(1, "Q")
    after_sprint = [r for r in held.returned if r.after == "S"]
    assert len(after_sprint) == 1
    assert after_sprint[0].set.runs[-1].session == "S" and after_sprint[0].laps == 22


# ------------------------------------------------------------- whose car

def test_a_rookie_in_first_practice_uses_the_car_they_stood_in_for():
    frames = []
    for session, number, driver in (("FP1", 99, "ROO"), ("FP2", 1, "AAA"), ("R", 1, "AAA"),
                                    ("FP1", 2, "BBB"), ("R", 2, "BBB")):
        rows = pd.DataFrame(_stint(session, "SOFT", 1, 5, car=number, driver=driver))
        frames.append(tyre_sets.stints_from_laps(rows, session))
    stints = pd.concat(frames, ignore_index=True)
    w = tyre_sets.build(stints, STANDARD, {1, 2}, year=2025, round_number=1,
                        event_name="Test Grand Prix", sprint=False)
    assert w.cars[1].stand_ins == ["ROO (FP1)"]
    assert w.cars[1].driver == "AAA"
    assert [s.first_session() for s in w.cars[1].sets] == ["FP1", "FP2", "R"]
    assert 99 not in w.cars


def test_a_car_that_ran_more_sets_than_exist_is_reported_not_hidden():
    w = _weekend(*[("FP1", "HARD", 1, 3)] * 3)
    assert w.over_allocation() == {1: {"HARD": 1}}
    assert any("counted twice" in note for note in w.notes)


def test_an_extra_set_most_of_the_field_ran_was_allocated():
    """Qatar 2025: half the field ran a third hard. That is the weekend, not a miscount."""
    frames = []
    for car in range(1, 9):
        for n in range(3):
            rows = pd.DataFrame(_stint("FP1", "HARD", 1, 3, car=car, stint=n + 1, start=1000.0 * n))
            frames.append(tyre_sets.stints_from_laps(rows, "FP1"))
    w = tyre_sets.build(pd.concat(frames, ignore_index=True), STANDARD, set(range(1, 9)),
                        year=2025, round_number=23, event_name="Qatar", sprint=False)
    assert w.extra == {"HARD": 1}
    assert w.over_allocation() == {}


def test_the_2023_test_weekends_kept_eight_softs():
    assert _weekend(("FP1", "SOFT", 1, 3), year=2023).rules.allocation["SOFT"] == 8
    w = _weekend(("FP1", "SOFT", 1, 3), year=2024)
    w.test_tyres = True
    assert w.rules.allocation["SOFT"] == 7


# ------------------------------------------------------------- plans

DEGRADATION = {"SOFT": 0.10, "MEDIUM": 0.06, "HARD": 0.04}


def test_a_plan_on_new_sets_costs_nothing_extra():
    left = {"SOFT": {"new": 1, "used": []}, "MEDIUM": {"new": 1, "used": []},
            "HARD": {"new": 1, "used": []}}
    check = tyre_sets.check_plan([("MEDIUM", 20), ("HARD", 31)], left, DEGRADATION)
    assert check.feasible and check.extra_s == 0.0


def test_a_used_set_costs_its_age_on_every_lap_it_runs():
    left = {"SOFT": {"new": 0, "used": []}, "MEDIUM": {"new": 0, "used": [4]},
            "HARD": {"new": 1, "used": []}}
    check = tyre_sets.check_plan([("MEDIUM", 20), ("HARD", 31)], left, DEGRADATION)
    assert check.feasible
    assert check.extra_s == pytest.approx(0.06 * 4 * 20)
    assert check.stints[0] == ("MEDIUM", 20, 4)


def test_the_older_set_goes_on_the_shorter_stint():
    left = {"SOFT": {"new": 0, "used": []}, "MEDIUM": {"new": 0, "used": []},
            "HARD": {"new": 1, "used": [10]}}
    check = tyre_sets.check_plan([("HARD", 30), ("HARD", 12)], left, DEGRADATION)
    assert check.stints == [("HARD", 30, 0), ("HARD", 12, 10)]


def test_a_plan_the_car_has_no_tyres_for_says_so():
    left = {"SOFT": {"new": 2, "used": []}, "MEDIUM": {"new": 1, "used": []},
            "HARD": {"new": 0, "used": []}}
    check = tyre_sets.check_plan([("MEDIUM", 20), ("HARD", 31)], left, DEGRADATION)
    assert not check.feasible
    assert check.reason == "no hard sets left"
