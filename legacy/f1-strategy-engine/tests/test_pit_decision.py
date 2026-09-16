"""
Tests for the pit-decision framing.

Most of these exist to stop one specific mistake returning: letting the model
see something it could not have known when the call was made. That mistake has
been made twice in this project, in two different disguises, and both times the
scores looked excellent.

Run with:  python -m pytest tests -q
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.features.tyre_degradation import degradation_rate, summarize_degradation
from src.models.pit_decision import build_lap_decisions

PIT_LANE_COST = 21.0


def race(stint_lengths=(18, 20), base=95.0, degradation=0.08, drivers=("VER", "HAM"), grand_prix="Test GP"):
    """A race where every driver pits at the end of each stint."""
    rows = []
    for driver in drivers:
        lap_number = 1
        for stint, length in enumerate(stint_lengths, start=1):
            for age in range(1, length + 1):
                last_of_stint = age == length and stint < len(stint_lengths)
                rows.append({
                    "Year": 2024, "GrandPrix": grand_prix, "Driver": driver, "Team": "T",
                    "Stint": stint, "LapNumber": lap_number, "Compound": "HARD",
                    "TyreLife": age, "TrackStatus": "1",
                    # A lap on which the car pits carries the pit lane inside it.
                    "LapTime_s": base + degradation * age + (PIT_LANE_COST if last_of_stint else 0.0),
                    "PitInTime": 1.0 if last_of_stint else np.nan,
                    "PitOutTime": np.nan,
                })
                lap_number += 1
    return pd.DataFrame(rows)


class TestCausalFeatures:
    def test_the_lap_being_decided_is_not_in_its_own_features(self):
        # The giveaway: a pit lap is ~21 s slower than its neighbours. If that
        # time reaches the features, the model spots a stop that has already
        # happened and scores brilliantly for nothing.
        table = build_lap_decisions(race())
        stops = table[table.pits_this_lap]
        assert len(stops) > 0
        assert stops["pace_loss_vs_last_lap_s"].abs().max() < 1.0
        assert stops["pace_loss_vs_stint_best_s"].max() < 2.0

    def test_features_only_ever_describe_earlier_laps(self):
        table = build_lap_decisions(race(stint_lengths=(20, 20)))
        row = table[(table.Driver == "VER") & (table.Stint == 1)].iloc[5]
        # Degradation is fitted over the laps run so far, which is fewer than
        # the stint contains.
        assert row.laps_in_stint < 20
        assert row.deg_so_far_s_per_lap == pytest.approx(0.08, abs=0.02)

    def test_a_row_exists_for_every_lap_a_call_could_be_made_on(self):
        table = build_lap_decisions(race(stint_lengths=(18, 20)))
        per_driver = table[table.Driver == "VER"]
        assert len(per_driver) == (18 - 3) + (20 - 3)
        assert per_driver.pits_this_lap.sum() == 1      # only the end of stint 1 is a stop

    def test_stops_already_made_are_counted_but_not_future_ones(self):
        table = build_lap_decisions(race(stint_lengths=(15, 15, 15)))
        first = table[(table.Driver == "VER") & (table.Stint == 1)]
        third = table[(table.Driver == "VER") & (table.Stint == 3)]
        assert set(first.stops_so_far) == {0}
        assert set(third.stops_so_far) == {2}


class TestDegradationInRange:
    def test_measured_across_the_laps_actually_run(self):
        laps = pd.DataFrame([{
            "Driver": "VER", "GrandPrix": "Test GP", "Stint": 1, "Compound": "SOFT",
            "TyreLife": age, "LapTime_s": 95 + 0.1 * age,
            "PitInTime": np.nan, "PitOutTime": np.nan, "TrackStatus": "1",
        } for age in range(1, 7)])
        assert degradation_rate(laps) == pytest.approx(0.1, abs=0.01)

    def test_the_three_to_fifteen_delta_is_null_for_a_stint_that_never_got_there(self):
        # The old bug: a quadratic fitted to six laps, then read at lap 15.
        short = pd.DataFrame([{
            "Driver": "SHORT", "GrandPrix": "Test GP", "Stint": 1, "Compound": "SOFT",
            "TyreLife": age, "LapTime_s": 95 + 0.1 * age,
            "PitInTime": np.nan, "PitOutTime": np.nan, "TrackStatus": "1",
        } for age in range(1, 7)])
        summary = summarize_degradation(short)
        assert summary["deg_delta_3to15"].isna().all()
        assert summary["deg_s_per_lap"].iloc[0] == pytest.approx(0.1, abs=0.01)

    def test_a_long_stint_still_reports_both(self):
        long_stint = pd.DataFrame([{
            "Driver": "LONG", "GrandPrix": "Test GP", "Stint": 1, "Compound": "HARD",
            "TyreLife": age, "LapTime_s": 95 + 0.1 * age,
            "PitInTime": np.nan, "PitOutTime": np.nan, "TrackStatus": "1",
        } for age in range(1, 26)])
        summary = summarize_degradation(long_stint)
        assert summary["deg_s_per_lap"].iloc[0] == pytest.approx(0.1, abs=0.01)
        assert summary["deg_delta_3to15"].iloc[0] == pytest.approx(1.2, abs=0.1)


class TestGroupingAcrossRaces:
    def test_stints_from_different_races_are_never_merged(self):
        # The other fixed bug: grouping on (Driver, Stint) alone pooled "stint 1"
        # from every race in the training set into a single fit.
        one = race(grand_prix="Bahrain")
        two = race(grand_prix="Jeddah", base=83.0)     # a circuit 12 s a lap quicker
        summary = summarize_degradation(pd.concat([one, two], ignore_index=True))
        assert len(summary) == 8                        # 2 races x 2 drivers x 2 stints
        assert summary["deg_s_per_lap"].between(0.05, 0.11).all()
