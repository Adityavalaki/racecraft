"""The analysis commands run end to end against a small lake."""

import pandas as pd
import pytest

from racecraft import config
from racecraft.model import cli
from racecraft.store import lake

LAP = 92.0


def _tables(session_key, year, rnd, location, stop_lap=20, laps=40):
    rows = []
    for offset, driver in enumerate([1, 11, 16, 55, 44, 63]):
        plan = [("SOFT", 1, stop_lap + offset), ("HARD", stop_lap + offset + 1, laps)]
        for stint, (compound, first, last) in enumerate(plan, start=1):
            for age, lap in enumerate(range(first, last + 1), start=1):
                pit_in = lap == last and stint == 1
                pit_out = lap == first and stint == 2
                rows.append({
                    "session_key": session_key, "driver_number": driver, "driver": f"D{driver}",
                    "team": "T", "lap_number": lap, "stint": stint, "compound": compound,
                    "tyre_life": age, "laps_in_stint": age, "fresh_tyre": stint == 2,
                    "lap_time_s": LAP + 0.05 * (laps - lap) + 0.06 * age + offset * 0.1
                                  + (10.0 if pit_in or pit_out else 0.0),
                    "sector1_s": None, "sector2_s": None, "sector3_s": None,
                    "lap_start_t": 1000.0 + lap * LAP, "lap_end_t": 1000.0 + (lap + 1) * LAP,
                    "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": pit_in, "is_pit_out_lap": pit_out,
                    "speed_i1": None, "speed_i2": None, "speed_fl": None, "speed_st": None,
                    "position": offset + 1, "track_status": "1", "is_personal_best": False,
                    "deleted": False, "deleted_reason": None, "is_accurate": True, "fastf1_generated": False,
                })
    return {
        "laps": pd.DataFrame(rows),
        "sessions": pd.DataFrame({
            "session_key": [session_key], "event_name": [f"{location} Grand Prix"], "country": [location],
            "location": [location], "session_name": ["Race"],
            "date_utc": [pd.Timestamp(f"{year}-05-01", tz="UTC")], "t0_utc": [pd.Timestamp(f"{year}-05-01", tz="UTC")],
            "start_t": [1000.0], "total_laps": [laps], "circuit_rotation_deg": [0.0],
            "fastf1_version": ["test"], "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "track_status": pd.DataFrame({
            "session_key": [session_key] * 3, "t": [0.0, 2000.0, 2400.0],
            "status": ["1", "4", "1"], "message": ["AllClear", "SCDeployed", "AllClear"]}),
    }


@pytest.fixture
def small_lake(tmp_path, monkeypatch):
    for year, rnd in [(2025, 1), (2026, 1), (2026, 2)]:
        lake.write_session(_tables(f"{year}_{rnd:02d}_R", year, rnd, "Baku"), year, rnd, "R", lake=tmp_path)
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)
    return tmp_path


def test_pace_command_reports_every_season(small_lake, capsys):
    assert cli.main(["pace"]) == 0
    out = capsys.readouterr().out
    assert "2026" in out and "2025" in out
    assert "SOFT" in out and "HARD" in out


def test_pace_command_can_list_one_season_race_by_race(small_lake, capsys):
    assert cli.main(["pace", "--season", "2026"]) == 0
    assert "per race" in capsys.readouterr().out


def test_circuits_command_lists_pit_loss_and_risk(small_lake, capsys):
    assert cli.main(["circuits"]) == 0
    out = capsys.readouterr().out
    assert "Baku" in out and "pit loss" in out


def test_circuit_command_describes_one_circuit(small_lake, capsys):
    assert cli.main(["circuit", "Baku"]) == 0
    out = capsys.readouterr().out
    assert "pit lane costs" in out
    assert "stops per driver" in out


def test_circuit_command_says_so_when_it_has_no_data(small_lake, capsys):
    assert cli.main(["circuit", "Nowhere"]) == 1
    assert "no races at 'Nowhere'" in capsys.readouterr().out


def test_strategy_command_costs_plans_for_a_circuit(small_lake, capsys):
    assert cli.main(["strategy", "Baku", "--season", "2026", "--laps", "40", "--top", "2", "--step", "5"]) == 0
    out = capsys.readouterr().out
    assert "pit loss" in out
    assert "stop" in out
    assert "It leaves out" in out          # the limits travel with the numbers


def test_strategy_command_refuses_an_unknown_circuit(small_lake, capsys):
    assert cli.main(["strategy", "Nowhere", "--season", "2026"]) == 1
    assert "no pit loss known" in capsys.readouterr().out


def test_race_command_compares_plans_for_one_car(small_lake, capsys):
    assert cli.main(["race", "Baku", "--season", "2026", "--laps", "30",
                     "--grid", "3", "--cars", "6", "--runs", "20"]) == 0
    out = capsys.readouterr().out
    assert "passes per race" in out
    assert "mean finish" in out
    assert "does not predict" in out      # the caveat travels with the numbers


def test_race_command_refuses_an_unknown_circuit(small_lake, capsys):
    assert cli.main(["race", "Nowhere", "--season", "2026"]) == 1
    assert "no races at 'Nowhere'" in capsys.readouterr().out
