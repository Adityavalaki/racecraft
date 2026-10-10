"""
Sunday, predicted from Saturday night: the blend of a weekend's signals, and
the simulated race it feeds.

The blend is tested on readings drawn with a known answer. The whole
prediction is tested on a small lake where one car is plainly quickest, and
where a race after the one predicted must never be seen.
"""

import numpy as np
import pandas as pd
import pytest

from racecraft import config
from racecraft.model import predict, weekend
from racecraft.store import lake
from racecraft.store.db import connect

SIGNALS = list(predict.SIGNALS)


# ------------------------------------------------------------------ the blend

def _rows(n=1500, seed=1):
    """Readings with a known truth: quali = 0.8 x pace + noise 0.5, form = 0.7 x pace + noise 0.3."""
    rng = np.random.default_rng(seed)
    pace = rng.normal(0, 0.6, n)
    return pd.DataFrame({
        "quali_gap_s": 0.8 * pace + rng.normal(0, 0.5, n),
        "long_run_s": rng.normal(0, 0.7, n),                # unrelated to pace
        "sprint_s": np.nan,
        "form_s": 0.7 * pace + rng.normal(0, 0.3, n),
        "actual_s": pace,
    })


def _calibration(**over):
    values = dict(scale={"quali_gap_s": 1.0, "form_s": 1.0}, noise_sd={"quali_gap_s": 0.4, "form_s": 0.4},
                  prior_sd=0.6, inflate=1.0)
    values.update(over)
    return predict.Calibration(**values)


def test_each_signal_is_measured_against_the_pace_drivers_actually_showed():
    cal = predict.fit_calibration(_rows())
    assert cal.scale["quali_gap_s"] == pytest.approx(0.8, abs=0.05)
    assert cal.noise_sd["quali_gap_s"] == pytest.approx(0.5, abs=0.05)
    assert cal.scale["form_s"] == pytest.approx(0.7, abs=0.05)
    assert cal.noise_sd["form_s"] == pytest.approx(0.3, abs=0.03)
    assert cal.prior_sd == pytest.approx(0.6, abs=0.05)
    assert "long_run_s" not in cal.scale          # says nothing about race pace, so it is dropped
    assert "sprint_s" not in cal.scale            # never read
    assert cal.inflate >= 1.0


def test_the_stated_uncertainty_is_honest_on_the_rows_it_was_measured_on():
    rows = _rows()
    cal = predict.fit_calibration(rows)
    est = predict.combine(rows, cal)
    z = (rows["actual_s"] - est["pace"]) / est["sd"]
    assert z.std() == pytest.approx(1.0, abs=0.1)


def test_a_driver_with_no_readings_is_the_field_and_no_surer_than_it():
    table = pd.DataFrame({s: [np.nan] for s in SIGNALS})
    est = predict.combine(table, _calibration())
    assert est["pace"].iloc[0] == 0.0
    assert est["sd"].iloc[0] == pytest.approx(0.6)


def test_a_missing_signal_adds_nothing_rather_than_reading_as_zero():
    cal = _calibration()
    one = predict.combine(pd.DataFrame({"quali_gap_s": [-0.8], "form_s": [np.nan]}), cal)
    only = predict.combine(pd.DataFrame({"quali_gap_s": [-0.8]}), cal)
    assert one["pace"].iloc[0] == pytest.approx(only["pace"].iloc[0])
    assert one["pace"].iloc[0] < -0.4             # a quick lap, not dragged toward a zero form reading


def test_readings_that_agree_narrow_the_answer():
    cal = _calibration()
    single = predict.combine(pd.DataFrame({"quali_gap_s": [-0.5], "form_s": [np.nan]}), cal)
    both = predict.combine(pd.DataFrame({"quali_gap_s": [-0.5], "form_s": [-0.5]}), cal)
    assert both["sd"].iloc[0] < single["sd"].iloc[0]
    assert both["pace"].iloc[0] < single["pace"].iloc[0]


def test_one_wild_reading_is_held_at_the_limit():
    cal = _calibration()
    wild = predict.combine(pd.DataFrame({"quali_gap_s": [40.0], "form_s": [np.nan]}), cal)
    limit = predict.combine(pd.DataFrame({"quali_gap_s": [predict.SIGNAL_CLIP_S], "form_s": [np.nan]}), cal)
    assert wild["pace"].iloc[0] == pytest.approx(limit["pace"].iloc[0])


def test_the_calibration_survives_a_round_trip_to_disk(tmp_path):
    cal = predict.fit_calibration(_rows(), ["2023", "2024"])
    path = tmp_path / "weights.json"
    path.write_text(__import__("json").dumps(cal.as_dict()), encoding="utf-8")
    back = predict.load_calibration(path)
    assert back.fitted_on == ["2023", "2024"]
    assert back.scale["form_s"] == pytest.approx(cal.scale["form_s"], abs=1e-4)


def test_the_shipped_calibration_says_what_it_was_measured_on():
    cal = predict.load_calibration()
    assert cal.fitted_on and all(int(year) < 2026 for year in cal.fitted_on)
    assert "form_s" in cal.scale and "quali_gap_s" in cal.scale


# ------------------------------------------------------------------ scoring

def test_a_perfect_prediction_scores_perfectly():
    finish = pd.Series([1, 2, 3, 4], index=[44, 1, 16, 4])
    prediction = {"drivers": [
        {"driver_number": 44, "expected": 1.2, "win": 1.0, "podium": 1.0},
        {"driver_number": 1, "expected": 2.1, "win": 0.0, "podium": 1.0},
        {"driver_number": 16, "expected": 3.0, "win": 0.0, "podium": 1.0},
        {"driver_number": 4, "expected": 4.5, "win": 0.0, "podium": 0.0},
    ]}
    sc = predict.score(prediction, finish)
    assert sc["rho"] == pytest.approx(1.0)
    assert sc["winner_hit"] and sc["podium_hits"] == 3
    assert sc["brier_win"] == 0.0 and sc["brier_podium"] == 0.0


def test_the_grid_baseline_is_scored_the_same_way():
    finish = pd.Series([1, 2, 3], index=[10, 20, 30])
    grid = pd.Series([2, 1, 3], index=[10, 20, 30])
    sc = predict.grid_score(grid, finish, {1: (0.6, 0.9), 2: (0.2, 0.7), 3: (0.1, 0.5)})
    assert not sc["winner_hit"]                   # pole did not win
    assert sc["podium_hits"] == 3
    assert sc["logloss_win"] == pytest.approx(-np.log(0.2))


# ------------------------------------------------------------------ a whole weekend

LAPS = 40
DRIVERS = 10
# Car 1 is a second a lap clear of the rest, who are 0.3 s apart.
PACE = {d: 90.0 + (0.0 if d == 1 else 1.0 + 0.3 * (d - 2)) for d in range(1, DRIVERS + 1)}
RACES = [(2023, 1, "Baku", "2023-04-30"), (2023, 2, "Monza", "2023-09-03"),
         (2024, 1, "Sakhir", "2024-03-02"), (2024, 2, "Baku", "2024-04-28"),
         (2024, 3, "Jeddah", "2024-05-12")]


def _laps(key, seed, pace=PACE, laps=LAPS):
    rng = np.random.default_rng(seed)
    rows = []
    for driver, base in pace.items():
        stop = 15 + driver
        t = 0.0
        for lap in range(1, laps + 1):
            second = lap > stop
            compound = "HARD" if second else "MEDIUM"
            age = lap - stop if second else lap
            time = base + (0.03 if second else 0.06) * age + (0.4 if second else 0.0) \
                - 0.05 * lap + rng.normal(0, 0.05)
            pit_in, pit_out = lap == stop, lap == stop + 1
            time += 11.0 * (pit_in + pit_out)
            t += time
            rows.append({
                "session_key": key, "driver_number": driver, "driver": f"D{driver:02d}", "team": "T",
                "lap_number": lap, "stint": 2 if second else 1, "compound": compound, "tyre_life": age,
                "laps_in_stint": age, "fresh_tyre": second, "lap_time_s": time,
                "sector1_s": time / 3, "sector2_s": time / 3, "sector3_s": time / 3,
                "lap_start_t": t - time, "lap_end_t": t,
                "pit_in_t": t if pit_in else None, "pit_out_t": t - time if pit_out else None,
                "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out,
                "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
                "position": driver, "track_status": "1", "is_personal_best": False,
                "deleted": False, "deleted_reason": None, "is_accurate": True, "fastf1_generated": False,
            })
    return pd.DataFrame(rows)


def _results(key, quali=False):
    numbers = list(range(1, DRIVERS + 1))
    return pd.DataFrame({
        "session_key": key, "driver_number": numbers,
        "abbreviation": [f"D{n:02d}" for n in numbers], "full_name": [f"Driver {n}" for n in numbers],
        "team_name": "T", "team_id": "t", "team_color": "ffffff",
        "grid_position": None if quali else numbers, "position": numbers,
        "classified_position": [str(n) for n in numbers], "status": "Finished",
        "points": 0.0, "laps": LAPS, "result_time_s": 0.0,
        "q1_s": [80.0 + 0.3 * n for n in numbers] if quali else None,
        "q2_s": None, "q3_s": [79.5 + (0.0 if n == 1 else 0.8 + 0.2 * n) for n in numbers] if quali else None})


def _session(path, year, rnd, code, location, when, laps, results=None):
    key = f"{year}_{rnd:02d}_{code}"
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": [f"{location} Grand Prix"], "country": [location],
            "location": [location], "session_name": [code], "date_utc": [when], "t0_utc": [when],
            "start_t": [0.0], "total_laps": [LAPS if code == "R" else None], "circuit_rotation_deg": [0.0],
            "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "laps": laps(key),
        "track_status": pd.DataFrame({"session_key": [key], "t": [0.0], "status": ["1"], "message": ["AllClear"]}),
    }
    if results is not None:
        tables["results"] = results(key)
    lake.write_session(tables, year, rnd, code, lake=path)


@pytest.fixture
def con(tmp_path, monkeypatch):
    for year, rnd, location, date in RACES:
        race_day = pd.Timestamp(f"{date} 13:00", tz="UTC")
        seed = year * 10 + rnd
        _session(tmp_path, year, rnd, "R", location, race_day, lambda k, s=seed: _laps(k, s), _results)
        _session(tmp_path, year, rnd, "Q", location, race_day - pd.Timedelta(days=1),
                 lambda k, s=seed: _laps(k, s + 1, laps=6), lambda k: _results(k, quali=True))
        _session(tmp_path, year, rnd, "FP2", location, race_day - pd.Timedelta(days=2),
                 lambda k, s=seed: _laps(k, s + 2, laps=14))
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return connect()


def test_the_weekend_is_read_from_before_the_race_only(con):
    ev = weekend.evidence(con, "2024_02_R")
    assert ev.form_races == ["Sakhir Grand Prix"]            # not Baku itself, not Jeddah after it
    assert ev.sessions_used == ["FP2", "Q"]
    assert ev.grid_source == "race"
    assert ev.table.loc[1, "quali_gap_s"] < ev.table.loc[5, "quali_gap_s"]
    assert ev.table.loc[1, "form_s"] < ev.table.loc[5, "form_s"]


def test_early_in_a_season_last_seasons_closing_form_is_read_too(con):
    ev = weekend.evidence(con, "2024_02_R")                  # one 2024 race behind it
    assert ev.table["carry_s"].notna().all()
    assert ev.table.loc[1, "carry_s"] < ev.table.loc[5, "carry_s"]
    assert any("end of 2023" in note for note in ev.notes)


def test_a_new_rulebook_does_not_carry_last_seasons_form(con, monkeypatch):
    monkeypatch.setattr(weekend, "NEW_RULES", {2024})
    ev = weekend.evidence(con, "2024_02_R")
    assert ev.table["carry_s"].isna().all()

def test_the_quickest_car_is_the_favourite_and_the_chances_add_up(con):
    result = predict.race(con, "2024_02_R", runs=200, calibration=_calibration())
    rows = {d["driver_number"]: d for d in result.drivers}

    assert result.drivers[0]["driver_number"] == 1
    assert rows[1]["win"] > 0.5
    assert sum(d["win"] for d in result.drivers) == pytest.approx(1.0, abs=0.01)
    assert sum(d["podium"] for d in result.drivers) == pytest.approx(3.0, abs=0.02)
    assert sum(d["points"] for d in result.drivers) == pytest.approx(10.0, abs=0.05)
    for d in result.drivers:
        assert d["win"] <= d["podium"] <= d["points"]
        assert 0.0 <= d["dnf"] <= 1.0
        assert 1 <= d["p10"] <= d["p50"] <= d["p90"] <= DRIVERS
    assert result.basis["runs"] == 200
    assert result.basis["form_races"] == ["Sakhir Grand Prix"]


def test_a_season_with_little_history_retires_cars_at_the_default_rate(con):
    assert predict.retire_rate(con, 2024, 2) == 0.10


def test_a_disqualified_driver_is_classified_behind_everyone_with_a_position(con, tmp_path):
    results = _results("2024_03_R")
    results.loc[results["driver_number"] == 2, "position"] = None        # second on the road, then excluded
    lake.write_session({"results": results}, 2024, 3, "R", lake=tmp_path)
    finish = predict.actual_finish(connect(), "2024_03_R")
    assert len(finish) == DRIVERS
    assert finish[2] == DRIVERS
    assert finish[3] == 2 and sorted(finish.values) == list(range(1, DRIVERS + 1))


# ------------------------------------------------------------------ the interface

@pytest.fixture
def client(con, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from racecraft.api.app import app

    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(predict, "load_calibration", lambda path=None: _calibration(fitted_on=["2023"]))
    monkeypatch.setattr("racecraft.api.prediction_view.RUNS", 100)
    return TestClient(app, base_url="http://127.0.0.1")


def _saturday(tmp_path):
    """Monza 2024: practice and qualifying are in, the race has not been run."""
    day = pd.Timestamp("2024-09-01 13:00", tz="UTC")
    _session(tmp_path, 2024, 4, "FP2", "Monza", day - pd.Timedelta(days=2), lambda k: _laps(k, 50, laps=14))
    _session(tmp_path, 2024, 4, "Q", "Monza", day - pd.Timedelta(days=1), lambda k: _laps(k, 51, laps=6),
             lambda k: _results(k, quali=True))


def test_saturday_night_the_race_is_predicted_from_qualifying_and_saved(client, tmp_path):
    _saturday(tmp_path)
    response = client.get("/api/sessions/2024_04_Q/prediction")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["race_key"] == "2024_04_R" and body["before_race"] is True
    assert body["result"] is None
    assert body["drivers"][0]["abbreviation"] == "D01"
    assert body["basis"]["grid_source"] == "qualifying"
    saved = tmp_path / "data" / "predictions" / "2024_04_R.json"
    assert saved.exists()

    # Asked again, from another session of the weekend: the saved one, not a new one.
    again = client.get("/api/sessions/2024_04_FP2/prediction").json()
    assert again["made_at"] == body["made_at"] and again["saved_at"] == body["saved_at"]


def test_a_saved_prediction_is_never_rewritten(client, tmp_path):
    _saturday(tmp_path)
    saved = tmp_path / "data" / "predictions" / "2024_04_R.json"
    saved.parent.mkdir(parents=True)
    first = client.get("/api/sessions/2024_04_Q/prediction").json()
    from racecraft.api import prediction_view
    prediction_view._write_once(saved, {**first, "made_at": "later"})
    assert client.get("/api/sessions/2024_04_Q/prediction").json()["made_at"] == first["made_at"]


def test_before_qualifying_there_is_nothing_to_predict_yet(client, tmp_path):
    day = pd.Timestamp("2024-09-01 13:00", tz="UTC")
    _session(tmp_path, 2024, 4, "FP2", "Monza", day - pd.Timedelta(days=2), lambda k: _laps(k, 50, laps=14))
    response = client.get("/api/sessions/2024_04_FP2/prediction")
    assert response.status_code == 422
    assert "qualifying" in response.json()["detail"]


def test_after_the_race_the_result_and_scores_come_with_it(client):
    body = client.get("/api/sessions/2024_02_R/prediction").json()
    assert body["before_race"] is False
    assert any("rebuilt after the race" in note for note in body["basis"]["notes"])
    assert body["result"]["finish"]["1"] == 1
    assert set(body["result"]["scores"]) == {"model", "grid"}
    assert body["result"]["scores"]["model"]["winner_hit"] is True


def test_a_bad_or_unknown_session_is_refused(client):
    assert client.get("/api/sessions/1999_01_R/prediction").status_code == 404
    assert client.get("/api/sessions/live/prediction").status_code == 422
