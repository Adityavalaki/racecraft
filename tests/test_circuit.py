"""Circuit-owned quantities: pit lane cost and how often a race is neutralised."""

import pandas as pd
import pytest

from racecraft.model import circuit

LAP = 90.0
PIT_COST = 21.0


def race_laps(session_key="2024_01_R", location="Baku", drivers=(1, 11, 16, 55, 44, 63),
              stop_lap=20, laps=40, under_safety_car=False):
    """One race where every driver loses exactly PIT_COST seconds stopping."""
    rows = []
    for driver in drivers:
        for lap in range(1, laps + 1):
            pit_in, pit_out = lap == stop_lap, lap == stop_lap + 1
            lap_time = LAP + (PIT_COST if pit_in or pit_out else 0.0) / 2
            status = "4" if under_safety_car and abs(lap - stop_lap) <= 1 else "1"
            rows.append({
                "session_key": session_key, "location": location, "driver_number": driver,
                "lap_number": lap, "lap_time_s": lap_time, "track_status": status,
                "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out,
            })
    return pd.DataFrame(rows)


class TestPitLoss:
    def test_measures_the_cost_of_a_stop(self):
        [result] = circuit.pit_loss(race_laps())
        assert result.circuit == "Baku"
        assert result.seconds == pytest.approx(PIT_COST, abs=0.2)
        assert result.stops == 6

    def test_ignores_stops_made_under_a_safety_car(self):
        # They are far cheaper, and counting them understates a green-flag stop.
        assert circuit.pit_loss(race_laps(under_safety_car=True)) == []

    def test_pools_a_circuit_across_seasons_despite_renaming(self):
        # FastF1 called Monaco "Monte Carlo" from 2026.
        old = race_laps(session_key="2025_08_R", location="Monaco")
        new = race_laps(session_key="2026_06_R", location="Monte Carlo")
        [result] = circuit.pit_loss(pd.concat([old, new], ignore_index=True))
        assert result.circuit == "Monaco"
        assert result.stops == 12
        assert result.seasons == 2

    def test_needs_several_stops_before_reporting(self):
        assert circuit.pit_loss(race_laps(drivers=(1,))) == []


class TestSafetyCarRisk:
    def _inputs(self, statuses: dict[str, list[tuple[float, str]]], location="Baku"):
        laps = pd.concat([race_laps(session_key=key, location=location) for key in statuses], ignore_index=True)
        sessions = pd.DataFrame({"session_key": list(statuses), "location": location})
        track_status = pd.DataFrame(
            [{"session_key": key, "t": t, "status": s} for key, rows in statuses.items() for t, s in rows])
        return track_status, sessions, laps

    def test_counts_races_that_were_neutralised(self):
        quiet = [(0.0, "1")]
        neutralised = [(0.0, "1"), (500.0, "4"), (900.0, "1")]
        [risk] = circuit.safety_car_risk(*self._inputs({
            "2023_01_R": neutralised, "2024_01_R": neutralised, "2025_01_R": quiet}))
        assert risk.races == 3
        assert risk.share_of_races == pytest.approx(2 / 3)
        assert risk.median_laps_lost == pytest.approx(400 / LAP, abs=0.1)

    def test_a_virtual_safety_car_counts_too(self):
        [risk] = circuit.safety_car_risk(*self._inputs({
            "2023_01_R": [(0.0, "1"), (500.0, "6"), (700.0, "1")],
            "2024_01_R": [(0.0, "1")]}))
        assert risk.share_of_races == pytest.approx(0.5)

    def test_a_short_history_is_pulled_toward_the_league_average(self):
        # Three from three is not certainty, and one from four is not a rule.
        always = {f"202{i}_01_R": [(0.0, "1"), (500.0, "4"), (900.0, "1")] for i in range(3)}
        never = {f"202{i}_02_R": [(0.0, "1")] for i in range(4)}
        track_status, sessions, laps = self._inputs(always)
        calm_status, calm_sessions, calm_laps = self._inputs(never, location="Monza")
        risks = {r.circuit: r for r in circuit.safety_car_risk(
            pd.concat([track_status, calm_status]), pd.concat([sessions, calm_sessions]),
            pd.concat([laps, calm_laps]))}

        assert risks["Baku"].share_of_races == 1.0
        assert 0.5 < risks["Baku"].probability < 1.0
        assert risks["Monza"].share_of_races == 0.0
        assert 0.0 < risks["Monza"].probability < 0.5
        assert risks["Baku"].probability > risks["Monza"].probability
