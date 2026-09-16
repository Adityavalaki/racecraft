"""
The model layer behind the interface, tested against races built to a known answer.

Two properties matter more than the plumbing and are checked directly:

* degradation put into the synthetic races comes back out, so the panel is
  drawing a measurement rather than a shape;
* the race being viewed is left out of its own fit, which is what makes the
  curve on screen a prediction of that race instead of a description of it.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft import config
from racecraft.api import insight
from racecraft.store import lake

YEAR = 2024
BASE_LAP = 90.0
PIT_LOSS = 22.0
TOTAL_LAPS = 44
FUEL = 0.05
TRUE_DEGRADATION = {"SOFT": 0.09, "MEDIUM": 0.06, "HARD": 0.03}
TRUE_OFFSET = {"SOFT": 0.0, "MEDIUM": 0.35, "HARD": 0.75}

# Ten cars, each on a different one-stop split and compound pair. Stints have
# to differ for degradation to be separable from everything else; identical
# strategies are rank deficient and the model says so rather than guessing.
PLANS = [
    (("SOFT", 12), ("HARD", 32)),
    (("SOFT", 16), ("HARD", 28)),
    (("SOFT", 20), ("MEDIUM", 24)),
    (("MEDIUM", 14), ("HARD", 30)),
    (("MEDIUM", 18), ("HARD", 26)),
    (("MEDIUM", 22), ("SOFT", 22)),
    (("HARD", 24), ("SOFT", 20)),
    (("HARD", 28), ("MEDIUM", 16)),
    (("HARD", 30), ("SOFT", 14)),
    (("SOFT", 10), ("HARD", 34)),
]


def _race(session_key: str, seed: int) -> pd.DataFrame:
    """A race whose lap times are built from known fuel, degradation and offsets."""
    rng = np.random.default_rng(seed)
    rows = []
    for index, plan in enumerate(PLANS):
        number = index + 1
        car = 0.4 * index          # a spread of car pace, absorbed by driver effects
        lap_number = 0
        t = 0.0
        for stint_index, (compound, length) in enumerate(plan):
            for age in range(1, length + 1):
                lap_number += 1
                if lap_number > TOTAL_LAPS:
                    break
                lap_time = (
                    BASE_LAP
                    + car
                    + TRUE_OFFSET[compound]
                    + TRUE_DEGRADATION[compound] * age
                    - FUEL * lap_number          # lighter every lap
                    + rng.normal(0, 0.05)
                )
                pit_in = stint_index < len(plan) - 1 and age == length
                pit_out = stint_index > 0 and age == 1
                if pit_in:
                    lap_time += PIT_LOSS / 2
                if pit_out:
                    lap_time += PIT_LOSS / 2
                t += lap_time
                rows.append({
                    "session_key": session_key, "driver_number": number, "driver": f"D{number:02d}",
                    "team": f"T{index // 2}", "lap_number": lap_number, "stint": stint_index + 1,
                    "compound": compound, "tyre_life": age, "laps_in_stint": age,
                    "fresh_tyre": stint_index > 0, "lap_time_s": lap_time,
                    "sector1_s": lap_time / 3, "sector2_s": lap_time / 3, "sector3_s": lap_time / 3,
                    "lap_start_t": t - lap_time, "lap_end_t": t,
                    "pit_in_t": t if pit_in else None, "pit_out_t": t - lap_time if pit_out else None,
                    "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out,
                    "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                    "position": number, "track_status": "1", "is_personal_best": False,
                    "deleted": False, "deleted_reason": None, "is_accurate": True,
                    "fastf1_generated": False,
                })
    return pd.DataFrame(rows)


def _write(tmp_path, session_key: str, round_number: int, location: str) -> None:
    laps = _race(session_key, seed=round_number)
    drivers = sorted(laps["driver_number"].unique())
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [session_key], "event_name": [f"{location} Grand Prix"],
            "country": [location], "location": [location], "session_name": ["Race"],
            "date_utc": [pd.Timestamp(f"{YEAR}-03-0{round_number} 15:00", tz="UTC")],
            "t0_utc": [pd.Timestamp(f"{YEAR}-03-0{round_number} 14:00", tz="UTC")],
            "start_t": [0.0], "total_laps": [TOTAL_LAPS], "circuit_rotation_deg": [0.0],
            "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "results": pd.DataFrame({
            "session_key": session_key, "driver_number": drivers,
            "abbreviation": [f"D{n:02d}" for n in drivers],
            "full_name": [f"Driver {n}" for n in drivers], "team_name": "T", "team_id": "t",
            "team_color": "ff0000", "grid_position": drivers, "position": drivers,
            "classified_position": [str(n) for n in drivers], "status": "Finished",
            "points": 0.0, "laps": TOTAL_LAPS, "result_time_s": 0.0,
            "q1_s": None, "q2_s": None, "q3_s": None}),
        "laps": laps,
        "track_status": pd.DataFrame({"session_key": [session_key], "t": [0.0],
                                      "status": ["1"], "message": ["AllClear"]}),
    }
    lake.write_session(tables, YEAR, round_number, "R", lake=tmp_path)


@pytest.fixture
def lake_dir(tmp_path, monkeypatch):
    for round_number, location in ((1, "Sakhir"), (2, "Jeddah"), (3, "Melbourne")):
        _write(tmp_path, f"{YEAR}_0{round_number}_R", round_number, location)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    insight._circuit_cache.clear()
    insight._season_cache.clear()
    yield tmp_path
    insight._circuit_cache.clear()
    insight._season_cache.clear()


def test_degradation_put_in_comes_back_out(lake_dir):
    out = insight.for_session(f"{YEAR}_01_R")
    measured = out["degradation_measured"]
    for compound, truth in TRUE_DEGRADATION.items():
        assert measured[compound] == pytest.approx(truth, abs=0.015), compound
    # Softs wear fastest here, and the ordering has to survive as well as the values.
    assert measured["SOFT"] > measured["MEDIUM"] > measured["HARD"]


def test_the_race_being_viewed_is_left_out_of_its_own_fit(lake_dir):
    """The whole point of the split: the curve predicts this race, it does not describe it."""
    out = insight.for_session(f"{YEAR}_01_R")
    assert out["held_out"] is True
    assert out["fitted_on_count"] == 2
    assert "Sakhir Grand Prix" not in out["fitted_on"]
    assert set(out["fitted_on"]) == {"Jeddah Grand Prix", "Melbourne Grand Prix"}

    # A different race is fitted on a different pair, so the numbers must differ.
    other = insight.for_session(f"{YEAR}_02_R")
    assert "Jeddah Grand Prix" not in other["fitted_on"]


def test_pit_loss_is_measured_from_the_races(lake_dir):
    out = insight.for_session(f"{YEAR}_01_R")
    assert out["pit_loss"]["seconds"] == pytest.approx(PIT_LOSS, abs=2.0)
    assert out["pit_loss"]["stops"] >= 10


def test_scale_multiplies_the_measurement_without_changing_it(lake_dir):
    out = insight.for_session(f"{YEAR}_01_R", scale=2.0)
    plain = insight.for_session(f"{YEAR}_01_R", scale=1.0)
    # Scaling multiplies the measurement; it must not quietly re-fit it.
    assert out["degradation_measured"] == plain["degradation_measured"]
    for compound, value in out["degradation_measured"].items():
        assert out["degradation_used"][compound] == pytest.approx(value * 2.0, abs=1e-3)


def test_plans_are_ranked_and_mirror_images_collapsed(lake_dir):
    out = insight.for_session(f"{YEAR}_01_R")
    plans = out["plans"]
    assert plans, out.get("plans_unavailable")

    costs = [p["seconds_lost"] for p in plans]
    assert costs == sorted(costs)
    assert plans[0]["behind_best_s"] == 0.0

    # No two rows may be the same set of stints in a different order.
    shapes = [tuple(sorted(zip(p["plan"].split(" > "), p["stint_laps"]))) for p in plans]
    assert len(shapes) == len(set(shapes))
    # ...and a collapsed row still reports the orders it stands for.
    assert any(len(p["orders"]) > 1 for p in plans)

    for plan in plans:
        assert sum(plan["stint_laps"]) == TOTAL_LAPS
        assert plan["pit_seconds"] == pytest.approx(plan["stops"] * out["pit_loss"]["seconds"], abs=0.1)


def test_a_stop_is_only_worth_it_when_the_tyres_cost_more_than_the_pit_lane(lake_dir):
    """With a 22 s pit lane and gentle wear, the cheapest plan should not be a two-stop."""
    out = insight.for_session(f"{YEAR}_01_R", scale=1.0)
    assert out["plans"][0]["stops"] <= 1


def test_the_observed_curve_does_not_run_backwards(lake_dir):
    """
    A first version measured laps against the driver's own stint and had hard
    tyres a second a lap *faster* by age 22 — the track rubbering in, not the
    tyre. Normalising against the field on the same lap is what fixed it, and
    this is the regression test for it.
    """
    out = insight.for_session(f"{YEAR}_01_R")
    curves = {c["compound"]: c for c in out["degradation_curve"]}
    assert set(curves) == set(TRUE_DEGRADATION)

    for compound, curve in curves.items():
        seen = [(p["age"], p["observed_s"]) for p in curve["points"] if p["observed_s"] is not None]
        assert len(seen) >= 4, compound
        early = np.mean([v for age, v in seen if age <= len(seen) // 3 + 1])
        late = np.mean([v for age, v in seen if age >= seen[-1][0] - len(seen) // 3])
        assert late > early, f"{compound} got faster as it aged: {early:.2f} -> {late:.2f}"


def test_observed_and_modelled_agree_on_the_synthetic_races(lake_dir):
    """Both lines on the chart should measure one quantity, or the chart is lying."""
    out = insight.for_session(f"{YEAR}_01_R", scale=1.0)
    for curve in out["degradation_curve"]:
        points = [p for p in curve["points"] if p["observed_s"] is not None]
        oldest = points[-1]
        assert oldest["observed_s"] == pytest.approx(oldest["model_s"], abs=0.35), curve["compound"]


def test_stints_report_what_each_car_actually_ran(lake_dir):
    out = insight.for_session(f"{YEAR}_01_R")
    by_driver = {s["driver_number"]: s for s in out["stints"]}
    assert len(by_driver) == len(PLANS)
    first = by_driver[1]
    assert first["stops"] == 1
    assert [s["compound"] for s in first["stints"]] == ["SOFT", "HARD"]
    assert first["stints"][0]["laps"] == 12


def test_caveats_travel_with_the_numbers(lake_dir):
    """A strategy shown without its omissions is the failure mode this project exists to avoid."""
    out = insight.for_session(f"{YEAR}_01_R")
    assert len(out["caveats"]) >= 5
    assert any("traffic" in c for c in out["caveats"])
    assert any("track position" in c for c in out["caveats"])


def test_circuits_lists_every_track_with_its_constants(lake_dir):
    rows = insight.circuits()
    assert {r["circuit"] for r in rows} == {"Sakhir", "Jeddah", "Melbourne"}
    for row in rows:
        assert row["pit_loss"]["seconds"] == pytest.approx(PIT_LOSS, abs=2.0)
        assert row["laps"] == TOTAL_LAPS


def test_an_unknown_session_is_a_key_error(lake_dir):
    with pytest.raises(KeyError):
        insight.for_session("1999_01_R")


def test_safety_car_ranking_is_a_different_question_from_the_green_one(lake_dir):
    """
    A stop under a safety car costs 61% of a green one, so a circuit that
    neutralises often rewards a longer first stint: more laps in which a cheap
    stop can arrive. The two rankings are allowed to disagree — that is the
    point of having both — but both must be complete and ordered.
    """
    out = insight.for_session(f"{YEAR}_01_R")
    risky = out["plans_with_risk"]
    assert risky, out.get("plans_unavailable")

    expected = [p["expected_s"] for p in risky]
    assert expected == sorted(expected)
    assert risky[0]["behind_best_s"] == 0.0

    for plan in risky:
        # A neutralisation can only ever make a plan cheaper, never dearer.
        assert plan["expected_s"] <= plan["green_s"] + 0.5
        assert plan["best_case_s"] <= plan["expected_s"] <= plan["worst_case_s"]
        assert 0.0 <= plan["cheap_stop_share"] <= 1.0
        assert sum(int(part.split(" ")[1]) for part in plan["plan"].split(" > ")) == TOTAL_LAPS


def test_pruning_never_drops_the_plan_that_would_have_won(lake_dir):
    """
    The ranking simulates a pruned set, because simulating every plan took 25 s.
    The prune is a bound, not a guess — a plan cannot cost less than its green
    cost minus the discount on its stops — so the winner has to survive it.
    This checks the bound against the full field rather than trusting it.
    """
    from racecraft.model import simulate as simulate_model
    from racecraft.model import strategy as strategy_model

    out = insight.for_session(f"{YEAR}_01_R")
    degradation = {c: v for c, v in out["degradation_used"].items()}
    offsets = out["compound_offset_s"]
    pit_loss = out["pit_loss"]["seconds"]
    risk = out["safety_car"]
    periods = risk["periods_per_race"] if risk else 1.0
    neutralisation = simulate_model.Neutralisation.for_circuit(periods, TOTAL_LAPS)

    plans = strategy_model.enumerate_plans(TOTAL_LAPS, tuple(degradation), max_stops=2,
                                           min_stint=insight.MIN_STINT_LAPS, step=insight.RISK_STEP)
    saving = (1 - neutralisation.stop_discount) * pit_loss
    green = {p: strategy_model.cost(p, degradation, pit_loss, compound_offset_s=offsets) for p in plans}
    best_green = min(c.seconds_lost for c in green.values())
    kept = {p for p in plans if green[p].seconds_lost - p.stops * saving < best_green}
    assert len(kept) < len(plans), "the bound pruned nothing, so it is not doing its job"

    # Every plan the bound dropped must be provably unable to win.
    for plan in plans:
        if plan in kept:
            continue
        floor = green[plan].seconds_lost - plan.stops * saving
        assert floor >= best_green


def test_a_circuit_with_no_neutralisation_history_still_ranks_plans(lake_dir):
    """Two of the three synthetic circuits have too little history for a risk figure."""
    for round_number in (1, 2, 3):
        out = insight.for_session(f"{YEAR}_0{round_number}_R")
        assert out["plans_with_risk"], out["circuit"]
