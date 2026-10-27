"""OpenF1's answers turned into the lake's own tables, offline (D-009 step 2)."""

from __future__ import annotations

import fastf1
import pandas as pd
import pytest

from racecraft import config
from racecraft.ingest import cli, fastf1_source, jolpica_source, openf1_source, quality, tracinginsights_source
from racecraft.store import lake

START = "2026-10-25T19:00:00+00:00"
HOUR = 3600.0                                    # t0 is an hour before the scheduled start


def at(seconds: float) -> str:
    return (pd.Timestamp(START) + pd.Timedelta(seconds=seconds)).isoformat()


def lap(n, number, start, duration, pit_out=False):
    return {"driver_number": n, "lap_number": number, "date_start": at(start), "lap_duration": duration,
            "duration_sector_1": 30.0, "duration_sector_2": 30.0, "duration_sector_3": None if duration is None
            else duration - 60.0, "i1_speed": 300, "i2_speed": 280, "st_speed": 320, "is_pit_out_lap": pit_out}


# A four-lap race for two cars: 44 stops on lap 2, a safety car runs from 150 s to 200 s,
# and 1's third lap is deleted. One weather sample is a stray from two weeks before. The
# grid is filed under the qualifying session the day before.
ANSWERS = {
    "sessions": [{"session_key": 9999, "meeting_key": 1, "session_type": "Race", "date_start": START,
                  "date_end": at(3600)},
                 {"session_key": 9998, "meeting_key": 1, "session_type": "Qualifying",
                  "date_start": "2026-10-24T21:00:00+00:00", "date_end": at(-80000)}],
    "drivers": [{"driver_number": 1, "name_acronym": "VER", "full_name": "Max VERSTAPPEN",
                 "first_name": "Max", "last_name": "Verstappen", "team_name": "Red Bull Racing",
                 "team_colour": "3671C6"},
                {"driver_number": 44, "name_acronym": "HAM", "full_name": "Lewis HAMILTON",
                 "team_name": "Ferrari", "team_colour": "E8002D"}],
    "laps": [lap(1, 1, 0, 100.0), lap(1, 2, 100, 90.0), lap(1, 3, 190, 95.0), lap(1, 4, 285, 90.0),
             lap(44, 1, 0, 101.0), lap(44, 2, 101, 110.0), lap(44, 3, 211, 92.0, pit_out=True),
             lap(44, 4, 303, 91.0)],
    "stints": [{"driver_number": 1, "stint_number": 1, "lap_start": 1, "lap_end": 4, "compound": "MEDIUM",
                "tyre_age_at_start": 0},
               {"driver_number": 44, "stint_number": 1, "lap_start": 1, "lap_end": 2, "compound": "SOFT",
                "tyre_age_at_start": 3},
               {"driver_number": 44, "stint_number": 2, "lap_start": 3, "lap_end": 4, "compound": "HARD",
                "tyre_age_at_start": 0}],
    "pit": [{"driver_number": 44, "lap_number": 2, "date": at(227.5), "pit_duration": 22.5}],   # when it left
    "position": [{"driver_number": 1, "position": 1, "date": at(-300)},
                 {"driver_number": 44, "position": 2, "date": at(-300)}],
    "race_control": [
        {"date": at(0), "category": "SessionStatus", "flag": None, "scope": None, "sector": None,
         "driver_number": None, "lap_number": 1, "message": "SESSION STARTED"},
        {"date": at(150), "category": "SafetyCar", "flag": None, "scope": None, "sector": None,
         "driver_number": None, "lap_number": 2, "message": "SAFETY CAR DEPLOYED"},
        {"date": at(200), "category": "Flag", "flag": "CLEAR", "scope": "Track", "sector": None,
         "driver_number": None, "lap_number": 3, "message": "TRACK CLEAR"},
        {"date": at(290), "category": "Other", "flag": None, "scope": None, "sector": None, "driver_number": 1,
         "lap_number": 4, "message": "CAR 1 (VER) TIME 1:35.000 DELETED - TRACK LIMITS AT TURN 12 LAP 3 19:04:50"},
    ],
    "weather": [{"date": at(60), "air_temperature": 25.1, "track_temperature": 38.0, "humidity": 50,
                 "pressure": 1012.0, "wind_speed": 1.2, "wind_direction": 180, "rainfall": 0},
                {"date": "2026-10-11T10:00:00+00:00", "air_temperature": 99.0, "track_temperature": 99.0,
                 "humidity": 0, "pressure": 0.0, "wind_speed": 0.0, "wind_direction": 0, "rainfall": 0}],
    "session_result": [{"driver_number": 1, "position": 1, "number_of_laps": 4, "points": 25.0,
                        "dnf": False, "dns": False, "dsq": False, "duration": 375.0},
                       {"driver_number": 44, "position": 2, "number_of_laps": 4, "points": 18.0,
                        "dnf": False, "dns": False, "dsq": False, "duration": 19.0}],
    "starting_grid": [{"driver_number": 44, "position": 1}, {"driver_number": 1, "position": 2}],
    "car_data": [{"date": at(10), "rpm": 11000, "speed": 280, "n_gear": 7, "throttle": 100, "brake": 0,
                  "drs": None}, {"date": at(11), "rpm": 9000, "speed": 120, "n_gear": 3, "throttle": 0,
                                 "brake": 100, "drs": None}],
    "location": [{"date": at(10), "x": 100, "y": -200, "z": 5}],
}


class _Schedule:
    date = pd.Timestamp("2026-10-25 19:00")          # FastF1's schedule time: naive UTC
    name = "Race"
    event = {"EventName": "United States Grand Prix", "Country": "United States", "Location": "Austin"}


@pytest.fixture
def openf1(monkeypatch, tmp_path):
    asked = []

    def get(endpoint, **params):
        asked.append((endpoint, params))
        rows = ANSWERS[endpoint]
        if "driver_number" in params:
            rows = [{**r, "driver_number": params["driver_number"]} for r in rows]
        return rows

    monkeypatch.setattr(openf1_source, "_get", get)
    monkeypatch.setattr(fastf1, "get_session", lambda *a: _Schedule())
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path)            # an empty lake: no corners to copy
    return asked


@pytest.fixture
def race(openf1):
    return openf1_source.extract(2026, 18, "R", "Race", "2026_18_R")


def test_the_tables_pass_the_quality_checks_and_write(race, tmp_path):
    findings = [f for f in quality.check_session(race) if f.check != "results.drivers"]   # a two-car field
    assert not quality.has_errors(findings), findings
    assert any(f.check == "results.winner_time_reconciles" and f.severity == "OK" for f in findings)
    report = lake.write_session(race, 2026, 18, "R", lake=tmp_path / "lake")
    assert report["laps"]["rows"] == 8 and report["car_data"]["rows"] == 4


def test_it_picks_the_session_by_its_start_time(openf1, race):
    asked = dict(openf1)
    assert asked["laps"] == {"session_key": 9999}
    assert race["sessions"].loc[0, "fastf1_version"] == "openf1"
    assert race["sessions"].loc[0, "total_laps"] == 4
    assert race["sessions"].loc[0, "start_t"] == HOUR                 # race control's SESSION STARTED
    assert asked["starting_grid"] == {"session_key": 9998}            # filed under qualifying


def test_tyres_count_laps_run_before_the_stint(race):
    ham = race["laps"].query("driver_number == 44").set_index("lap_number")
    assert list(ham["compound"]) == ["SOFT", "SOFT", "HARD", "HARD"]
    assert list(ham["tyre_life"]) == [4, 5, 1, 2]
    assert list(ham["laps_in_stint"]) == [1, 2, 1, 2]
    assert list(ham["fresh_tyre"]) == [False, False, True, True]


def test_a_pit_stop_marks_the_in_lap_and_the_out_lap(race):
    ham = race["laps"].query("driver_number == 44").set_index("lap_number")
    assert ham.loc[2, "is_pit_in_lap"] and ham.loc[2, "pit_in_t"] == HOUR + 205.0
    assert ham.loc[3, "is_pit_out_lap"] and ham.loc[3, "pit_out_t"] == HOUR + 227.5
    assert not ham.loc[2, "is_accurate"] and not ham.loc[3, "is_accurate"] and ham.loc[4, "is_accurate"]


def test_track_status_comes_from_race_control(race):
    assert list(race["track_status"]["status"]) == ["1", "4", "1"]
    assert list(race["track_status"]["message"]) == ["AllClear", "SCDeployed", "AllClear"]
    ver = race["laps"].query("driver_number == 1").set_index("lap_number")
    assert list(ver["track_status"]) == ["1", "14", "41", "1"]
    assert list(ver["is_accurate"]) == [False, False, False, True]   # standing start, SC, lap after SC


def test_a_deleted_lap_is_marked_and_not_a_personal_best(race):
    ver = race["laps"].query("driver_number == 1").set_index("lap_number")
    assert ver.loc[3, "deleted"] and "TRACK LIMITS" in ver.loc[3, "deleted_reason"]
    assert list(ver["is_personal_best"]) == [False, True, False, False]   # never the standing start


def test_stray_samples_are_dropped(race):
    assert list(race["weather"]["air_temp"]) == [25.1]
    assert race["weather"].loc[0, "t"] == HOUR + 60.0


def test_results_carry_names_grid_and_classification(race):
    res = race["results"].set_index("driver_number")
    assert res.loc[1, "abbreviation"] == "VER" and res.loc[1, "grid_position"] == 2
    assert res.loc[1, "full_name"] == "Max Verstappen"             # the lake's form, not "Max VERSTAPPEN"
    assert res.loc[44, "classified_position"] == "2" and res.loc[44, "status"] == "Finished"
    assert res.loc[1, "points"] == 25.0


def test_telemetry_is_shaped_per_driver(race):
    car = race["car_data"]
    assert set(car["driver_number"]) == {1, 44}
    assert list(car.query("driver_number == 1")["brake"]) == [False, True]
    assert (car["drs"] == 0).all()


DRIVERS = pd.DataFrame([{"driver_number": n, "name_acronym": a} for n, a in
                        [(4, "NOR"), (5, "BOR"), (23, "ALB"), (10, "GAS")]]).set_index("driver_number")


def test_qualifying_times_come_from_the_duration_list():
    rows = [{"driver_number": 4, "position": 1, "duration": [90.1, 89.5, 88.9]},
            {"driver_number": 5, "position": "RT", "dnf": False, "duration": [None, None, None]}]
    res = openf1_source._results(rows, [], DRIVERS, "2026_18_Q", "Q").set_index("driver_number")
    assert list(res.loc[4, ["q1_s", "q2_s", "q3_s"]]) == [90.1, 89.5, 88.9]
    assert res.loc[5, "position"] == 2                               # "RT": placed after the rest
    assert res["classified_position"].isna().all() and res["laps"].isna().all()   # as FastF1


def test_a_race_is_classified_as_fastf1_writes_it():
    rows = [{"driver_number": 4, "position": 1, "number_of_laps": 62, "duration": 6120.8, "gap_to_leader": 0},
            {"driver_number": 10, "position": 2, "number_of_laps": 61, "gap_to_leader": "+1 LAP"},
            {"driver_number": 23, "position": 3, "number_of_laps": 59, "dnf": True},
            {"driver_number": 5, "position": None, "number_of_laps": 7, "dnf": True}]
    res = openf1_source._results(rows, [], DRIVERS, "2026_17_R", "R").set_index("driver_number")
    assert list(res["classified_position"]) == ["1", "2", "3", "R"]
    assert list(res["status"]) == ["Finished", "Lapped", "Retired", "Retired"]
    assert res.loc[5, "position"] == 4 and res.loc[4, "result_time_s"] == 6120.8


def test_practice_has_no_places():
    rows = [{"driver_number": 4, "position": 1, "number_of_laps": 25}]
    res = openf1_source._results(rows, [], DRIVERS, "2026_17_FP1", "FP1")
    assert res["position"].isna().all() and res["laps"].isna().all()


LAPS = pd.DataFrame({"driver_number": [4, 4, 4], "lap_number": [1, 2, 3], "lap_time_s": [None, 98.239, 90.0]})


def test_a_deleted_lap_is_found_by_its_time():
    rc = pd.DataFrame({"message": ["CAR 4 (NOR) TIME 1:38.239 DELETED - TRACK LIMITS AT TURN 16 LAP 3 16:35:36"]})
    assert list(openf1_source._deleted_laps(rc, LAPS, race=False)) == [(4, 2)]


def test_without_a_time_the_lap_number_is_one_ahead_outside_a_race():
    rc = pd.DataFrame({"message": ["CAR 4 (NOR) LAP DELETED - TRACK LIMITS AT TURN 16 LAP 3 22:04:01 (PIT)"]})
    assert list(openf1_source._deleted_laps(rc, LAPS, race=False)) == [(4, 2)]
    assert list(openf1_source._deleted_laps(rc, LAPS, race=True)) == [(4, 3)]


def test_a_reinstated_lap_is_not_deleted():
    rc = pd.DataFrame({"message": ["CAR 4 (NOR) TIME 1:30.000 DELETED - TRACK LIMITS AT TURN 1 LAP 3 14:00:00",
                                   "CAR 4 (NOR) TIME 1:30.000 LAP 3 REINSTATED, DELETED IN ERROR"]})
    assert openf1_source._deleted_laps(rc, LAPS, race=True) == {}


def test_a_virtual_safety_car_is_not_read_as_a_safety_car():
    rc = pd.DataFrame({"t": [10.0, 20.0, 25.0, 30.0, 40.0], "flag": [None] * 5, "scope": [None] * 5,
                       "message": ["VIRTUAL SAFETY CAR DEPLOYED", "VIRTUAL SAFETY CAR ENDING",
                                   "GREEN LIGHT - PIT EXIT OPEN", "VSC DEPLOYED", "VSC ENDING"]})
    assert list(openf1_source.track_status(rc, "k")["status"]) == ["1", "6", "7", "1", "6", "7"]


def test_the_track_is_yellow_while_any_sector_is():
    rc = pd.DataFrame({"t": [10.0, 10.0, 20.0, 30.0, 40.0],
                       "flag": ["YELLOW", "YELLOW", "CLEAR", "CLEAR", "DOUBLE YELLOW"],
                       "scope": ["Sector", "Sector", "Sector", "Sector", "Sector"], "sector": [5, 6, 5, 6, 13],
                       "message": ["YELLOW IN TRACK SECTOR 5", "YELLOW IN TRACK SECTOR 6", "CLEAR IN TRACK SECTOR 5",
                                   "CLEAR IN TRACK SECTOR 6", "DOUBLE YELLOW IN TRACK SECTOR 13"]})
    status = openf1_source.track_status(rc, "k")
    assert status[["t", "status", "message"]].values.tolist() == [
        [0.0, "1", "AllClear"], [10.0, "2", "Yellow"], [30.0, "1", "AllClear"], [40.0, "2", "Yellow"]]


def test_stints_are_recut_at_the_stops_for_a_pit_lane_start():
    # Singapore 2026, HAD: from the pit lane on mediums, one stop on lap 33, softs to the end.
    stints = [{"driver_number": 6, "stint_number": 1, "lap_start": 1, "lap_end": 1, "compound": "MEDIUM"},
              {"driver_number": 6, "stint_number": 2, "lap_start": 2, "lap_end": 62, "compound": "SOFT"}]
    laps = pd.DataFrame({"driver_number": [6] * 62, "lap_number": range(1, 63)})
    out = openf1_source._stints(stints, [{"driver_number": 6, "lap_number": 33}], laps)
    assert out[["lap_start", "lap_end"]].values.tolist() == [[1, 33], [34, 62]]
    assert list(out["pit_lane_start"]) == [True, False]


def test_an_out_lap_from_the_garage_starts_where_the_last_lap_ended(openf1, monkeypatch):
    # FP1, Singapore 2026: in on lap 2, twelve minutes in the garage, out on lap 3. OpenF1 starts
    # lap 3 at the garage exit but times it from the line, and stamps the stop when it left.
    answers = {**ANSWERS,
               "laps": [lap(4, 1, 0, None, pit_out=True), lap(4, 2, 100, 132.6), lap(4, 3, 982.6, 895.7, pit_out=True),
                        lap(4, 4, 1128.3, 92.0)],
               "pit": [{"driver_number": 4, "lap_number": 3, "date": at(982.6), "pit_duration": 755.8},
                       {"driver_number": 4, "lap_number": 1, "date": at(0.03), "pit_duration": None}],
               "stints": [{"driver_number": 4, "stint_number": 1, "lap_start": 1, "lap_end": 4, "compound": "SOFT",
                           "tyre_age_at_start": 0}]}
    monkeypatch.setattr(openf1_source, "_get", lambda endpoint, **p: answers[endpoint])
    tables = openf1_source.extract(2026, 17, "FP1", "Practice 1", "2026_17_FP1", telemetry=False)
    nor = tables["laps"].set_index("lap_number")
    assert nor.loc[3, "lap_start_t"] == HOUR + 232.6 and pd.isna(nor.loc[3, "lap_time_s"])
    assert nor.loc[3, "lap_end_t"] == pytest.approx(HOUR + 1128.3)
    assert nor.loc[2, "is_pit_in_lap"] and nor.loc[2, "pit_in_t"] == pytest.approx(HOUR + 226.8)
    assert nor.loc[1, "is_pit_out_lap"] and nor.loc[3, "is_pit_out_lap"] and nor.loc[4, "is_pit_in_lap"]
    assert "laps.time_monotonic" not in {f.check for f in quality.check_session(tables)}


def test_no_session_near_the_scheduled_start_is_not_available(openf1, monkeypatch):
    monkeypatch.setattr(_Schedule, "date", pd.Timestamp("2026-11-08 18:00"))
    with pytest.raises(openf1_source.NotAvailable, match="no session starting near"):
        openf1_source.extract(2026, 19, "R", "Race", "2026_19_R")


def test_a_session_f1_refuses_is_taken_from_openf1(monkeypatch):
    def locked(*a, **k):
        raise fastf1_source.ArchiveLocked(fastf1_source.LOCKED)

    written = {}
    openf1 = pd.DataFrame({"driver_number": [1], "position": [1.0], "points": [None]})
    official = pd.DataFrame({"number": [1], "position": [1], "positionText": ["1"], "grid": [2], "laps": [56],
                             "status": ["Finished"], "points": [25.0], "totalRaceTime": [pd.Timedelta(seconds=5716.65)],
                             "constructorId": ["red_bull"], "givenName": ["Max"], "familyName": ["Verstappen"]})
    monkeypatch.setattr(fastf1_source, "load_session", locked)
    sessions = pd.DataFrame({"event_name": ["United States Grand Prix"]})
    monkeypatch.setattr(openf1_source, "extract",
                        lambda *a, **k: {"laps": "from openf1", "results": openf1, "sessions": sessions})
    monkeypatch.setattr(tracinginsights_source, "improve", lambda tables, *a: tables)
    monkeypatch.setattr(jolpica_source, "official", lambda *a: official)
    monkeypatch.setattr(quality, "check_session", lambda tables: [])
    monkeypatch.setattr(lake, "write_session", lambda tables, *a: written.update(tables) or {})
    assert cli._ingest_locked(2026, 18, "R", "Race", "2026_18_R",
                              telemetry=False, force=False, prune=True) == "written"
    assert written["laps"] == "from openf1"
    assert written["results"].loc[0, "points"] == 25.0 and written["results"].loc[0, "team_id"] == "red_bull"
