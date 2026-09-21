"""
The simulator's inputs, taken only from races that had finished.

For a race that has happened, the simulator used to be told the answer: tyre
wear fitted on that race, a pace ladder from races after it, pit loss measured
from its own stops. These tests build a lake with a race *after* the one being
simulated and assert that nothing from it, or from the race itself, gets in.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft import config
from racecraft.model import places, race_inputs
from racecraft.store import lake
from racecraft.store.db import connect

TOTAL_LAPS = 44
PIT_LOSS = 22.0
DEGRADATION = {"SOFT": 0.09, "MEDIUM": 0.06, "HARD": 0.03}
OFFSET = {"SOFT": 0.0, "MEDIUM": 0.35, "HARD": 0.75}
PLANS = [
    (("SOFT", 12), ("HARD", 32)), (("SOFT", 16), ("HARD", 28)), (("SOFT", 20), ("MEDIUM", 24)),
    (("MEDIUM", 14), ("HARD", 30)), (("MEDIUM", 18), ("HARD", 26)), (("MEDIUM", 22), ("SOFT", 22)),
    (("HARD", 24), ("SOFT", 20)), (("HARD", 28), ("MEDIUM", 16)), (("HARD", 30), ("SOFT", 14)),
    (("SOFT", 10), ("HARD", 34)),
]
# Two seasons, Baku in both, and a race after the 2024 Baku that must never be seen.
RACES = [
    (2023, 1, "Baku", "2023-04-30"),
    (2023, 2, "Monza", "2023-09-03"),
    (2024, 1, "Sakhir", "2024-03-02"),
    (2024, 2, "Baku", "2024-04-28"),
    (2024, 3, "Jeddah", "2024-05-12"),
]


def _race(key: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for index, plan in enumerate(PLANS):
        lap_number, t = 0, 0.0
        for stint_index, (compound, length) in enumerate(plan):
            for age in range(1, length + 1):
                lap_number += 1
                if lap_number > TOTAL_LAPS:
                    break
                lap_time = 90 + 0.4 * index + OFFSET[compound] + DEGRADATION[compound] * age \
                    - 0.05 * lap_number + rng.normal(0, 0.05)
                pit_in = stint_index < len(plan) - 1 and age == length
                pit_out = stint_index > 0 and age == 1
                lap_time += PIT_LOSS / 2 * (pit_in + pit_out)
                t += lap_time
                rows.append({
                    "session_key": key, "driver_number": index + 1, "driver": f"D{index + 1:02d}",
                    "team": "T", "lap_number": lap_number, "stint": stint_index + 1,
                    "compound": compound, "tyre_life": age, "laps_in_stint": age,
                    "fresh_tyre": stint_index > 0, "lap_time_s": lap_time,
                    "sector1_s": lap_time / 3, "sector2_s": lap_time / 3, "sector3_s": lap_time / 3,
                    "lap_start_t": t - lap_time, "lap_end_t": t,
                    "pit_in_t": t if pit_in else None, "pit_out_t": t - lap_time if pit_out else None,
                    "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out,
                    "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                    "position": index + 1, "track_status": "1", "is_personal_best": False,
                    "deleted": False, "deleted_reason": None, "is_accurate": True,
                    "fastf1_generated": False,
                })
    return pd.DataFrame(rows)


def _results(key: str) -> pd.DataFrame:
    """A classification, so a grid slot can be traced to a car and its tyres."""
    numbers = list(range(1, len(PLANS) + 1))
    return pd.DataFrame({
        "session_key": key, "driver_number": numbers,
        "abbreviation": [f"D{n:02d}" for n in numbers], "full_name": [f"Driver {n}" for n in numbers],
        "team_name": "T", "team_id": "t", "team_color": "ffffff",
        "grid_position": numbers, "position": numbers,
        "classified_position": [str(n) for n in numbers], "status": "Finished",
        "points": 0.0, "laps": TOTAL_LAPS, "result_time_s": 0.0,
        "q1_s": None, "q2_s": None, "q3_s": None})


@pytest.fixture
def con(tmp_path, monkeypatch):
    for year, rnd, location, date in RACES:
        key = f"{year}_{rnd:02d}_R"
        lake.write_session({
            "sessions": pd.DataFrame({
                "session_key": [key], "event_name": [f"{location} Grand Prix"],
                "country": [location], "location": [location], "session_name": ["Race"],
                "date_utc": [pd.Timestamp(f"{date} 13:00", tz="UTC")],
                "t0_utc": [pd.Timestamp(f"{date} 12:00", tz="UTC")], "start_t": [0.0],
                "total_laps": [TOTAL_LAPS], "circuit_rotation_deg": [0.0],
                "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
            "laps": _race(key, seed=year * 10 + rnd),
            "results": _results(key),
            "track_status": pd.DataFrame({"session_key": [key], "t": [0.0],
                                          "status": ["1"], "message": ["AllClear"]}),
        }, year, rnd, "R", lake=tmp_path)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


# ------------------------------------------------------------- held out

def test_a_race_that_has_happened_is_not_fitted_on_itself_or_anything_after(con):
    inputs = race_inputs.build(con, "Baku", 2024)

    assert inputs.held_out is True
    assert inputs.target_session == "2024_02_R"
    assert inputs.cutoff == pd.Timestamp("2024-04-28 13:00", tz="UTC")
    # Sakhir came before; Baku 2024 is the race itself and Jeddah came after.
    assert inputs.fitted_on == ["Sakhir Grand Prix"]


def test_pit_loss_comes_only_from_earlier_races_at_the_circuit(con):
    """Every Baku race has ten stops; only the 2023 one had happened."""
    inputs = race_inputs.build(con, "Baku", 2024)
    assert inputs.pit_stops == 10, "the race's own stops were counted"
    assert inputs.pit_loss_s == pytest.approx(PIT_LOSS, abs=2.0)


def test_including_the_race_is_possible_but_says_so(con):
    inputs = race_inputs.build(con, "Baku", 2024, include_race=True)
    assert inputs.held_out is False
    assert set(inputs.fitted_on) == {"Sakhir Grand Prix", "Baku Grand Prix", "Jeddah Grand Prix"}
    assert inputs.pit_stops == 20
    assert any("in-sample" in note for note in inputs.notes)


def test_a_race_not_yet_run_uses_everything_that_has_finished(con):
    """The forecasting case: Monza has no 2024 race in the lake, so nothing is held out."""
    inputs = race_inputs.build(con, "Monza", 2024)
    assert inputs.held_out is False
    assert inputs.target_session is None
    assert set(inputs.fitted_on) == {"Sakhir Grand Prix", "Baku Grand Prix", "Jeddah Grand Prix"}


def test_the_first_race_at_a_circuit_refuses_rather_than_reading_its_own_pit_lane(con):
    """
    The rule costs something, and this is the cost. Sakhir 2024 has no earlier
    Sakhir race to measure its pit lane from; borrowing its own would be the
    leak this module exists to stop.
    """
    with pytest.raises(race_inputs.NotEnoughData, match="no earlier race at Sakhir"):
        race_inputs.build(con, "Sakhir", 2024)


def test_the_race_distance_is_the_scheduled_one_which_was_known_in_advance(con):
    assert race_inputs.build(con, "Baku", 2024).total_laps == TOTAL_LAPS


def test_a_named_session_is_the_race_being_analysed(con):
    """How the interface asks: by session rather than by circuit and season."""
    inputs = race_inputs.build(con, "Baku", 2024, session_key="2024_02_R")
    assert inputs.target_session == "2024_02_R"
    assert inputs.fitted_on == ["Sakhir Grand Prix"]


def test_a_thin_season_says_the_wake_was_not_measured(con):
    """Ten cars spread 0.4 s apart are rarely close; the fallback is named, not silent."""
    inputs = race_inputs.build(con, "Baku", 2024)
    if not inputs.following.measured:
        assert inputs.following_table is None
        assert any("wake penalty not measurable" in note for note in inputs.notes)


def test_the_inputs_report_where_each_number_came_from(con):
    record = race_inputs.build(con, "Baku", 2024).as_dict()
    for key in ("held_out", "target_session", "cutoff", "fitted_on", "fitted_on_count",
                "pit_loss_s", "pit_stops", "periods_per_race", "passes_per_race",
                "following", "notes", "degradation_used", "degradation_measured"):
        assert key in record, key


# ------------------------------------------------------------- end to end

def test_a_study_runs_on_held_out_inputs(con):
    inputs = race_inputs.build(con, "Baku", 2024)
    result = places.study(inputs, grid=4, plans=4, runs=40, field_draws=4)

    assert len(result.shortlist) >= 2
    assert len(result.ranking) == len(result.shortlist)
    finishes = [r.mean_finish for r in result.ranking]
    assert finishes == sorted(finishes)
    record = result.as_dict()
    assert record["cheapest_in_seconds"] == str(result.shortlist[0].plan)
    assert record["plans"][0]["expected_s"] is not None


# ------------------------------------------------------------- the garage

def test_the_car_on_a_grid_slot_brings_the_tyres_it_had(con):
    from racecraft.model import race_inputs as inputs_module

    stock = inputs_module.tyre_stock(con, "2024_02_R", grid=3)
    assert stock is not None
    assert stock.driver == "D03" and stock.grid == 3
    # Every set it ran in the race is one it held at the start.
    assert stock.sets > 0
    assert set(stock.left) == {"SOFT", "MEDIUM", "HARD"}


def test_a_grid_slot_nobody_started_from_has_no_tyres(con):
    from racecraft.model import race_inputs as inputs_module

    assert inputs_module.tyre_stock(con, "2024_02_R", grid=19) is None


def test_a_study_races_the_sets_the_car_had(con):
    stock = race_inputs.tyre_stock(con, "2024_02_R", grid=4)
    inputs = race_inputs.build(con, "Baku", 2024)
    result = places.study(inputs, grid=4, plans=4, runs=40, field_draws=4, stock=stock.left)

    assert result.stock == stock.left
    raced = {str(entry.plan) for entry in result.ranking}
    dropped = {entry["plan"] for entry in result.dropped}
    assert not (raced & dropped), "a plan was both raced and ruled out"
    for entry in result.ranking:
        assert len(entry.start_ages) == len(entry.plan.stints)
    for entry in result.dropped:
        assert "set" in entry["reason"]


# ------------------------------------------------------------- over HTTP

@pytest.fixture
def client(con):
    from fastapi.testclient import TestClient
    from racecraft.api.app import app
    return TestClient(app)


def test_the_interface_races_the_cars_own_tyres_and_can_be_told_not_to(client):
    on_its_own = client.get("/api/sessions/2024_02_R/places",
                            params={"grid": 4, "runs": 40}).json()
    assert on_its_own["tyres"] == "car"
    assert on_its_own["stock"]["driver"] == "D04"
    assert on_its_own["study"]["stock"] is not None

    fresh = client.get("/api/sessions/2024_02_R/places",
                       params={"grid": 4, "runs": 40, "tyres": "new"}).json()
    assert fresh["tyres"] == "new" and fresh["stock"] is None
    assert all(row["on_used_sets"] is False for row in fresh["study"]["plans"])


def test_the_interface_gets_the_same_held_out_answer_as_the_terminal(client):
    response = client.get("/api/sessions/2024_02_R/places", params={"grid": 4, "runs": 40})
    assert response.status_code == 200
    body = response.json()

    assert body["inputs"]["held_out"] is True
    assert body["inputs"]["target_session"] == "2024_02_R"
    assert body["inputs"]["fitted_on_count"] == 1          # Sakhir only
    assert body["study"]["plans"], "a ranking with nothing in it"
    for key in ("cheapest_in_seconds", "best_in_places", "agree", "tied", "price", "bad_plan"):
        assert key in body["verdict"], key
    assert body["omissions"], "the list of what it cannot see travels with it"


def test_a_race_that_cannot_be_simulated_says_why_rather_than_erroring(client):
    """Sakhir 2024 is the first race there: no earlier pit lane to measure."""
    response = client.get("/api/sessions/2024_01_R/places", params={"grid": 4, "runs": 40})
    assert response.status_code == 422
    assert "no earlier race at Sakhir" in response.json()["detail"]


def test_an_unknown_session_is_404(client):
    assert client.get("/api/sessions/1999_01_R/places", params={"runs": 40}).status_code == 404


def test_an_answer_is_kept_rather_than_simulated_again(client):
    import time
    params = {"grid": 5, "runs": 40}
    client.get("/api/sessions/2024_02_R/places", params=params)
    started = time.perf_counter()
    again = client.get("/api/sessions/2024_02_R/places", params=params)
    assert again.status_code == 200
    assert time.perf_counter() - started < 0.5, "the second request re-ran the simulation"


def test_the_grid_slot_is_bounded(client):
    assert client.get("/api/sessions/2024_02_R/places", params={"grid": 0}).status_code == 422
    assert client.get("/api/sessions/2024_02_R/places", params={"grid": 30}).status_code == 422


def test_a_car_with_nothing_left_to_run_is_told_so_rather_than_given_a_plan(con, monkeypatch):
    """
    Every shortlisted plan needs a set the car has not got. That is an answer —
    the wrong one to hide behind an empty table.
    """
    from racecraft.api import places_view

    empty = race_inputs.Stock(driver="D04", driver_number=4, grid=4, notes=[],
                              left={c: {"new": 0, "used": []} for c in ("SOFT", "MEDIUM", "HARD")})
    monkeypatch.setattr(race_inputs, "tyre_stock", lambda *a, **k: empty)
    places_view._cache.clear()
    with pytest.raises(places_view.NotSimulable, match="could not run any"):
        places_view.for_session("2024_02_R", grid=4, runs=40)


def test_the_study_keeps_the_plans_it_can_run_and_drops_the_rest(con):
    inputs = race_inputs.build(con, "Baku", 2024)
    # One hard set and nothing else: only plans with a single hard stint survive.
    left = {"SOFT": {"new": 0, "used": []}, "MEDIUM": {"new": 3, "used": []},
            "HARD": {"new": 1, "used": []}}
    result = places.study(inputs, grid=4, plans=6, runs=40, field_draws=4, stock=left)

    for entry in result.ranking:
        assert sum(1 for compound, _ in entry.plan.stints if compound == "HARD") <= 1
    assert all("hard" in entry["reason"] or "soft" in entry["reason"] for entry in result.dropped)


def test_a_car_that_cannot_run_the_best_plans_is_given_the_best_it_can(con):
    """
    Verstappen at Monaco 2025: one new medium, one new hard, four used softs,
    and every plan in the shortlist calling for two hard stints. The answer is
    the best plan he could have run, not an empty table.
    """
    inputs = race_inputs.build(con, "Baku", 2024)
    no_hards = {"SOFT": {"new": 2, "used": []}, "MEDIUM": {"new": 2, "used": []},
                "HARD": {"new": 0, "used": []}}
    plain = places.study(inputs, grid=4, plans=5, runs=40, field_draws=4)
    limited = places.study(inputs, grid=4, plans=5, runs=40, field_draws=4, stock=no_hards)

    assert any("HARD" in str(c.plan).upper() for c in plain.shortlist), "nothing to be short of"
    assert limited.ranking, "a car with tyres left was given nothing to race"
    for entry in limited.ranking:
        assert all(compound != "HARD" for compound, _ in entry.plan.stints)
    # The plans it could not run are named, and they were in the plain shortlist.
    assert limited.dropped
    plain_plans = {str(c.plan) for c in plain.shortlist}
    assert {entry["plan"] for entry in limited.dropped} <= plain_plans


def test_monacos_two_stop_rule_applied_to_one_season_only():
    """
    Introduced for 2025 and deleted from the 2026 regulations after teams
    answered it by backing the field up. A rule that carried forward would put
    a stop in every Monaco race from here on.
    """
    assert race_inputs.mandatory_stops("Monaco", 2024) == 0
    assert race_inputs.mandatory_stops("Monaco", 2025) == 2
    assert race_inputs.mandatory_stops("Monaco", 2026) == 0
    assert race_inputs.mandatory_stops("Baku", 2025) == 0


def test_a_study_of_monaco_never_offers_a_one_stop(con, monkeypatch):
    """The rule reaches the shortlist, not just the enumeration."""
    monkeypatch.setitem(race_inputs.MANDATORY_STOPS, ("Baku", 2024, 2024), 2)
    inputs = race_inputs.build(con, "Baku", 2024)
    assert inputs.min_stops == 2
    result = places.study(inputs, grid=4, plans=4, runs=40, field_draws=4)
    assert result.ranking
    assert all(entry.plan.stops == 2 for entry in result.ranking)


def test_a_race_that_ran_wet_says_so_before_anything_else_is_read(con, monkeypatch):
    """
    Hindsight, and labelled as such. A dry-tyre ranking of a wet race is not a
    wrong answer to the question asked; it is an answer to a different one.
    """
    monkeypatch.setattr(race_inputs, "_wet_share", lambda con, key: 0.74)
    notes = race_inputs.build(con, "Baku", 2024).notes
    assert any("looking back" in note and "74%" in note for note in notes)


def test_a_dry_race_is_not_flagged(con, monkeypatch):
    monkeypatch.setattr(race_inputs, "_wet_share", lambda con, key: 0.02)
    assert not any("looking back" in note for note in race_inputs.build(con, "Baku", 2024).notes)
