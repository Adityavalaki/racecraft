"""
Fuel and degradation, checked against data whose answer is known.

The point of these tests is that the estimator either recovers the truth or
says it cannot. A model that quietly splits an unidentifiable effect between
two coefficients and reports a high R-squared is worse than one that refuses.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft.model import pace

TRUE_FUEL = 0.055
TRUE_DEG = {"SOFT": 0.110, "MEDIUM": 0.070, "HARD": 0.040}
TOTAL_LAPS = 60

VARIED = {
    1: [("SOFT", 1, 14), ("HARD", 15, 38), ("MEDIUM", 39, 60)],
    11: [("MEDIUM", 1, 22), ("HARD", 23, 60)],
    16: [("SOFT", 1, 10), ("MEDIUM", 11, 32), ("HARD", 33, 60)],
    55: [("HARD", 1, 28), ("SOFT", 29, 44), ("MEDIUM", 45, 60)],
    44: [("MEDIUM", 1, 18), ("SOFT", 19, 30), ("HARD", 31, 60)],
}
IDENTICAL = {d: [("SOFT", 1, 18), ("HARD", 19, 40), ("MEDIUM", 41, 60)] for d in VARIED}


def build(plans, seed=7, noise=0.15, base_pace=90.0, session_key="2026_01_R"):
    rng = np.random.default_rng(seed)
    rows = []
    for offset, (driver, plan) in enumerate(plans.items()):
        for stint, (compound, first, last) in enumerate(plan, start=1):
            for age, lap in enumerate(range(first, last + 1), start=1):
                lap_time = (base_pace + offset * 0.2
                            + TRUE_FUEL * (TOTAL_LAPS - lap)
                            + TRUE_DEG[compound] * age
                            + rng.normal(0, noise))
                rows.append({
                    "session_key": session_key, "driver_number": driver, "lap_number": lap,
                    "stint": stint, "compound": compound, "tyre_life": age, "lap_time_s": lap_time,
                    "track_status": "1", "is_pit_in_lap": False, "is_pit_out_lap": False,
                    "deleted": False, "is_accurate": True,
                })
    return pd.DataFrame(rows)


def test_recovers_fuel_and_degradation_from_varied_strategies():
    model = pace.fit(pace.clean_race_laps(build(VARIED)), total_laps=TOTAL_LAPS)
    assert model.fuel_s_per_lap == pytest.approx(TRUE_FUEL, abs=0.01)
    for compound, truth in TRUE_DEG.items():
        assert model.degradation_s_per_lap[compound] == pytest.approx(truth, abs=0.015), compound
    assert not model.is_weakly_identified


def test_refuses_when_every_driver_runs_the_same_strategy():
    # Tyre age and fuel move together for everyone, so no split is knowable.
    # Least squares would still answer, and the answer would be nonsense.
    with pytest.raises(pace.Confounded, match="cannot be separated"):
        pace.fit(pace.clean_race_laps(build(IDENTICAL)), total_laps=TOTAL_LAPS)


def test_pooling_sharpens_degradation_across_races():
    races = {f"2026_{round:02d}_R": pace.clean_race_laps(build(VARIED, seed=round, session_key=f"2026_{round:02d}_R"))
             for round in range(1, 6)}
    pooled = pace.fit_pooled(races, {key: TOTAL_LAPS for key in races})
    single = pace.fit(races["2026_01_R"], total_laps=TOTAL_LAPS)

    for compound, truth in TRUE_DEG.items():
        assert pooled.degradation_s_per_lap[compound] == pytest.approx(truth, abs=0.01), compound
        assert pooled.standard_errors[f"deg_{compound}"] < single.standard_errors[f"deg_{compound}"]


def test_fuel_correction_removes_the_race_long_trend():
    laps = pace.clean_race_laps(build(VARIED))
    model = pace.fit(laps, total_laps=TOTAL_LAPS)
    corrected = pace.fuel_corrected_lap_time(laps, model, total_laps=TOTAL_LAPS)

    # Raw times fall through the race as fuel burns; corrected ones should not.
    raw_trend = np.polyfit(laps["lap_number"], laps["lap_time_s"], 1)[0]
    corrected_trend = np.polyfit(laps["lap_number"], corrected, 1)[0]
    assert raw_trend < -0.03
    assert abs(corrected_trend) < abs(raw_trend) / 3


class TestCleanRaceLaps:
    """Each case marks a few mid-stint laps, which the baseline keeps, and checks they go."""

    MARKED = [20, 21, 22]      # laps well inside driver 1's second stint

    def _marked(self, **overrides):
        laps = build(VARIED)
        rows = (laps.driver_number == 1) & laps.lap_number.isin(self.MARKED)
        assert rows.sum() == len(self.MARKED)
        for column, value in overrides.items():
            laps.loc[rows, column] = value
        return laps

    def _survivors(self, laps):
        cleaned = pace.clean_race_laps(laps)
        return set(cleaned[cleaned.driver_number == 1].lap_number) & set(self.MARKED)

    def test_keeps_ordinary_green_laps(self):
        assert self._survivors(build(VARIED)) == set(self.MARKED)

    @pytest.mark.parametrize("column,value", [
        ("track_status", "4"),          # safety car
        ("is_pit_in_lap", True),
        ("is_pit_out_lap", True),
        ("deleted", True),
        ("is_accurate", False),
        ("compound", "INTERMEDIATE"),   # wet tyres tell you nothing about dry pace
    ])
    def test_drops_laps_that_do_not_represent_pace(self, column, value):
        assert self._survivors(self._marked(**{column: value})) == set()

    def test_drops_traffic_laps_far_off_a_driver_own_median(self):
        laps = build(VARIED)
        rows = (laps.driver_number == 1) & laps.lap_number.isin(self.MARKED)
        laps.loc[rows, "lap_time_s"] += 20      # stuck behind a slower car
        assert self._survivors(laps) == set()

    def test_drops_the_first_lap(self):
        assert (pace.clean_race_laps(build(VARIED))["lap_number"] > 1).all()

    def test_drops_stints_too_short_to_show_a_shape(self):
        laps = build(VARIED)
        short = (laps.driver_number == 1) & (laps.stint == 1) & (laps.tyre_life > 2)
        cleaned = pace.clean_race_laps(laps[~short])
        assert cleaned[(cleaned.driver_number == 1) & (cleaned.stint == 1)].empty


class TestLapEffects:
    """Degradation from comparing drivers at the same lap, rather than modelling fuel."""

    def test_recovers_degradation_without_modelling_fuel_at_all(self):
        model = pace.fit_lap_effects(pace.clean_race_laps(build(VARIED)))
        for compound, truth in TRUE_DEG.items():
            assert model.degradation_s_per_lap[compound] == pytest.approx(truth, abs=0.015), compound
        assert np.isnan(model.fuel_s_per_lap)      # absorbed into the lap effects, by design

    def test_survives_track_evolution_that_the_fuel_model_assumes_away(self):
        # The fuel model fits one straight line to fuel and track evolution
        # together. When the track improves non-linearly, the error lands on
        # whichever compound runs when the straight line fits worst.
        rng = np.random.default_rng(3)
        rows = []
        for driver, plan in VARIED.items():
            for stint, (compound, first, last) in enumerate(plan, start=1):
                for age, lap in enumerate(range(first, last + 1), start=1):
                    evolution = -1.2 * (1 - np.exp(-lap / 12))
                    rows.append({
                        "driver_number": driver, "lap_number": lap, "stint": stint, "compound": compound,
                        "tyre_life": age, "track_status": "1", "is_pit_in_lap": False, "is_pit_out_lap": False,
                        "deleted": False, "is_accurate": True,
                        "lap_time_s": (90 + TRUE_FUEL * (TOTAL_LAPS - lap) + TRUE_DEG[compound] * age
                                       + evolution + rng.normal(0, 0.15)),
                    })
        laps = pace.clean_race_laps(pd.DataFrame(rows))
        lap_effects = pace.fit_lap_effects(laps)
        fuel_model = pace.fit(laps, total_laps=TOTAL_LAPS)

        for compound, truth in TRUE_DEG.items():
            assert lap_effects.degradation_s_per_lap[compound] == pytest.approx(truth, abs=0.015), compound
        # The gap between compounds is what a strategy turns on, and the fuel
        # model compresses it here while the lap-effects model does not.
        true_spread = TRUE_DEG["SOFT"] - TRUE_DEG["HARD"]
        fuel_spread = fuel_model.degradation_s_per_lap["SOFT"] - fuel_model.degradation_s_per_lap["HARD"]
        lap_spread = lap_effects.degradation_s_per_lap["SOFT"] - lap_effects.degradation_s_per_lap["HARD"]
        assert abs(lap_spread - true_spread) < abs(fuel_spread - true_spread)

    def test_can_let_degradation_bend(self):
        model = pace.fit_lap_effects(pace.clean_race_laps(build(VARIED)), curved=True)
        assert set(model.curvature_s_per_lap2) == set(TRUE_DEG)
        # The synthetic tyres wear in a straight line, so the bend should be tiny.
        assert all(abs(v) < 0.002 for v in model.curvature_s_per_lap2.values())


def test_combine_weights_precise_races_more_heavily():
    def model(value, error):
        return pace.PaceModel(fuel_s_per_lap=0.05, degradation_s_per_lap={"SOFT": value},
                              compound_offset_s={}, driver_baseline_s={}, n_laps=100, n_drivers=20,
                              residual_std_s=0.5, r_squared=0.9, standard_errors={"deg_SOFT": error})

    combined = pace.combine([model(0.10, 0.001), model(0.30, 0.10)])
    estimate, error = combined["SOFT"]
    assert estimate == pytest.approx(0.10, abs=0.005)   # the vague race barely moves it
    assert error < 0.001                                # and pooling is tighter than either alone
