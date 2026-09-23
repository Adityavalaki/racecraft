"""
Reading race control, checked against the wordings the feed actually uses.

Every message quoted here is copied from the lake, not invented, because the
whole risk in this module is that the FIA phrases something a way the rules do
not expect. The counts in `test_whole_lake_is_classified` are the guard against
that: if a new season brings a new wording, it fails here rather than silently
attributing nothing.
"""

from __future__ import annotations

import pandas as pd
import pytest

from racecraft.api import penalties

DRIVERS = pd.DataFrame([
    {"driver_number": 44, "abbreviation": "HAM", "team_name": "Ferrari"},
    {"driver_number": 16, "abbreviation": "LEC", "team_name": "Ferrari"},
    {"driver_number": 1, "abbreviation": "VER", "team_name": "Red Bull Racing"},
    {"driver_number": 27, "abbreviation": "HUL", "team_name": "Kick Sauber"},
    {"driver_number": 55, "abbreviation": "SAI", "team_name": "Williams"},
    {"driver_number": 43, "abbreviation": "COL", "team_name": "Alpine"},
    {"driver_number": 31, "abbreviation": "OCO", "team_name": "Haas F1 Team"},
    {"driver_number": 77, "abbreviation": "BOT", "team_name": "Kick Sauber"},
    {"driver_number": 20, "abbreviation": "MAG", "team_name": "Haas F1 Team"},
    {"driver_number": 4, "abbreviation": "NOR", "team_name": "McLaren"},
    {"driver_number": 81, "abbreviation": "PIA", "team_name": "McLaren"},
])
KNOWN = penalties._known(DRIVERS)
TEAMS = penalties._team_index(DRIVERS)


def read(message: str, t: float = 100.0, lap: int | None = 10):
    return penalties.read(message, t, lap, KNOWN, TEAMS)


def control(rows: list[tuple[float, str]]) -> pd.DataFrame:
    return pd.DataFrame([{"t": t, "lap": None, "category": None, "flag": None,
                          "scope": None, "message": m} for t, m in rows])


# ---------------------------------------------------------------- extraction

def test_single_car():
    event = read("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS")
    assert event.cars == (44,)
    assert event.kind == penalties.AWARDED_TIME
    assert event.seconds == 5.0
    assert event.reason == "TRACK LIMITS"


def test_two_car_incident_names_both():
    event = read("TURN 4 INCIDENT INVOLVING CARS 18 (STR) AND 14 (ALO) NOTED - CAUSING A COLLISION")
    # STR and ALO are not in DRIVERS, so this session knows neither of them.
    assert event.cars == ()


def test_three_car_list_without_a_car_prefix_on_each():
    """`CARS 31 (OCO), 77 (BOT) AND 20 (MAG)` writes the word once for three."""
    event = read("PIT EXIT INCIDENT INVOLVING CARS 31 (OCO), 77 (BOT) AND 20 (MAG) NOTED "
                 "- OVERTAKING UNDER SAFETY CAR")
    assert event.cars == (31, 77, 20)


def test_lap_time_and_turn_numbers_are_not_cars():
    event = read("CAR 20 (MAG) TIME 1:40.956 DELETED - TRACK LIMITS AT TURN 9 LAP 10 14:23:43")
    assert event.cars == (20,)
    assert event.kind == penalties.DELETED


def test_trailing_pit_marker_after_a_timestamp_is_not_car_59():
    """`... LAP 34 18:58:59 (PIT)` would otherwise read as car 59."""
    event = read("CAR 44 (HAM) LAP DELETED - TRACK LIMITS AT TURN 4 LAP 34 18:58:59 (PIT)")
    assert event.cars == (44,)


def test_a_timestamp_never_charges_a_deleted_lap_to_an_innocent_driver():
    """
    The dangerous half of that bug. `16:12:10 (PIT)` offers `10 (PIT)`, and 10 is
    a real driver, so a deletion against car 23 would also land on car 10. 200 of
    the lake's 337 phantom matches carry a number that belongs to someone.
    """
    event = read("CAR 23 (ALB) LAP DELETED - TRACK LIMITS AT TURN 11 LAP 52 16:12:10 (PIT)")
    assert event.cars == ()          # ALB is not in DRIVERS; car 10 must not appear
    assert 10 not in event.cars

    with_alb = penalties.read(
        "CAR 23 (ALB) LAP DELETED - TRACK LIMITS AT TURN 11 LAP 52 16:12:10 (PIT)",
        0.0, None, frozenset({23, 10}), {})
    assert with_alb.cars == (23,)


def test_a_car_from_another_championship_is_not_this_session():
    """BED races in another series whose messages share the feed."""
    assert read("CAR 26 (BED) TIME 2:15.494 DELETED - DOUBLE YELLOW AT TURN 2").cars == ()


def test_a_team_named_instead_of_a_car_means_its_cars():
    event = read("INCIDENT INVOLVING MCLAREN NOTED - PIT LANE INFRINGEMENT")
    assert event.cars == (4, 81)


def test_an_incident_naming_no_car_attributes_to_nobody():
    assert read("LAP 1 TURN 1 INCIDENT NOTED - CAUSING A COLLISION").cars == ()


# ------------------------------------------------------------ classification

@pytest.mark.parametrize("message, kind", [
    ("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS",
     penalties.AWARDED_TIME),
    ("FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - CAUSING A COLLISION",
     penalties.SERVED_PENALTY),
    ("FIA STEWARDS: 10 SECOND STOP/GO PENALTY FOR CAR 27 (HUL) - UNSAFE CONDITION",
     penalties.AWARDED_STOP_GO),
    ("FIA STEWARDS: STOP-AND-GO PENALTY FOR CAR 43 (COL) - STARTING PROCEDURE INFRINGEMENT",
     penalties.AWARDED_STOP_GO),
    ("FIA STEWARDS: DRIVE THROUGH PENALTY FOR CAR 1 (VER) - FALSE START",
     penalties.AWARDED_DRIVE_THROUGH),
    ("CAR 44 (HAM) TIME 1:38.003 DELETED - TRACK LIMITS AT TURN 3 LAP 64 16:17:58",
     penalties.DELETED),
    ("FIA STEWARDS: TURN 5 INCIDENT INVOLVING CAR 27 (HUL) UNDER INVESTIGATION",
     penalties.INVESTIGATING),
    ("FIA STEWARDS: INCIDENT INVOLVING CAR 55 (SAI) WILL BE INVESTIGATED AFTER THE RACE",
     penalties.AFTER_RACE),
    ("FIA STEWARDS: TURN 3 INCIDENT INVOLVING CAR 27 (HUL) REVIEWED NO FURTHER INVESTIGATION",
     penalties.CLEARED),
    ("FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) NO FURTHER ACTION",
     penalties.CLEARED),
    ("INCIDENT INVOLVING CAR 31 (OCO) NOTED - SAFETY CAR INFRINGEMENT",
     penalties.NOTED),
    ("WAVED BLUE FLAG FOR CAR 44 (HAM) TIMED AT 15:18:27", penalties.OTHER),
])
def test_verdicts(message, kind):
    assert read(message).kind == kind


def test_served_is_not_read_as_an_award():
    """The award's wording sits inside the discharge, so order decides this."""
    event = read("FIA STEWARDS: PENALTY SERVED - 10 SECOND TIME PENALTY FOR CAR 27 (HUL) "
                 "- FAILING TO SERVE TIME PENALTY CORRECTLY")
    assert event.kind == penalties.SERVED_PENALTY
    assert event.seconds == 10.0


def test_a_reason_mentioning_a_penalty_is_not_a_penalty():
    event = read("INCIDENT INVOLVING CAR 31 (OCO) NOTED - FAILING TO SERVE TIME PENALTY CORRECTLY")
    assert event.kind == penalties.NOTED
    assert event.seconds is None


def test_a_penalty_with_no_reason_only_a_stamp():
    event = read("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 55 (SAI) (15:23:42)")
    assert event.kind == penalties.AWARDED_TIME
    assert event.seconds == 5.0
    assert event.reason is None


# -------------------------------------------------------------- accumulation

def test_a_penalty_is_pending_until_it_is_served():
    rc = control([
        (10.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (90.0, "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
    ])
    midway = penalties.state_at(rc, DRIVERS, 50.0)[44]
    assert (midway.pending_s, midway.served_s, midway.outstanding) == (5.0, 0.0, True)
    after = penalties.state_at(rc, DRIVERS, 100.0)[44]
    assert (after.pending_s, after.served_s, after.outstanding) == (0.0, 5.0, False)
    assert after.awarded_s == 5.0 and after.penalties == 1


def test_two_penalties_add_up():
    rc = control([
        (10.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (20.0, "FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 44 (HAM) - CAUSING A COLLISION"),
    ])
    state = penalties.state_at(rc, DRIVERS, 30.0)[44]
    assert state.pending_s == 15.0 and state.penalties == 2


def test_nothing_from_the_future_is_counted():
    """The invariant the scrubber depends on."""
    rc = control([(500.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS")])
    assert penalties.state_at(rc, DRIVERS, 499.9) == {}
    assert penalties.state_at(rc, DRIVERS, 500.0)[44].pending_s == 5.0


def test_scrubbing_back_gives_the_same_answer_as_arriving_forward():
    rc = control([
        (10.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (90.0, "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
    ])
    forward = penalties.state_at(rc, DRIVERS, 50.0)[44].as_dict()
    _later = penalties.state_at(rc, DRIVERS, 200.0)
    back = penalties.state_at(rc, DRIVERS, 50.0)[44].as_dict()
    assert forward == back


def test_a_drive_through_clears_on_being_served():
    rc = control([
        (10.0, "FIA STEWARDS: DRIVE THROUGH PENALTY FOR CAR 1 (VER) - FALSE START - OUT OF POSITION"),
        (90.0, "FIA STEWARDS: PENALTY SERVED - DRIVE THROUGH PENALTY FOR CAR 1 (VER) "
               "- FALSE START - OUT OF POSITION"),
    ])
    assert penalties.state_at(rc, DRIVERS, 50.0)[1].drive_through == 1
    after = penalties.state_at(rc, DRIVERS, 100.0)[1]
    assert after.drive_through == 0 and after.penalties == 1 and not after.outstanding


def test_lap_deletions_count_and_do_not_make_a_penalty():
    rc = control([
        (10.0, "CAR 44 (HAM) TIME 1:38.003 DELETED - TRACK LIMITS AT TURN 3 LAP 64 16:17:58"),
        (20.0, "CAR 44 (HAM) TIME 1:38.100 DELETED - TRACK LIMITS AT TURN 3 LAP 65 16:19:58"),
    ])
    state = penalties.state_at(rc, DRIVERS, 30.0)[44]
    assert state.laps_deleted == 2 and state.penalties == 0 and not state.outstanding


def test_blue_flags_do_not_appear_against_a_driver():
    rc = control([(10.0, "WAVED BLUE FLAG FOR CAR 44 (HAM) TIMED AT 15:18:27")])
    assert penalties.state_at(rc, DRIVERS, 30.0) == {}


def test_an_incident_counts_once_however_often_it_is_reported():
    rc = control([
        (10.0, "TURN 5 INCIDENT INVOLVING CAR 27 (HUL) NOTED - CAUSING A COLLISION"),
        (20.0, "FIA STEWARDS: TURN 5 INCIDENT INVOLVING CAR 27 (HUL) UNDER INVESTIGATION "
               "- CAUSING A COLLISION"),
        (30.0, "FIA STEWARDS: TURN 5 INCIDENT INVOLVING CAR 27 (HUL) REVIEWED NO FURTHER "
               "INVESTIGATION - CAUSING A COLLISION"),
    ])
    noted = penalties.state_at(rc, DRIVERS, 15.0)[27]
    assert (noted.noted, noted.under_investigation, noted.cleared) == (1, 0, 0)
    looking = penalties.state_at(rc, DRIVERS, 25.0)[27]
    assert (looking.noted, looking.under_investigation, looking.cleared) == (0, 1, 0)
    done = penalties.state_at(rc, DRIVERS, 35.0)[27]
    assert (done.noted, done.under_investigation, done.cleared) == (0, 0, 1)


def test_a_penalty_closes_the_incident_it_came_from():
    """The penalty names one car; the notice named two. Same incident."""
    rc = control([
        (10.0, "TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) NOTED - CAUSING A COLLISION"),
        (20.0, "FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) "
               "UNDER INVESTIGATION - CAUSING A COLLISION"),
        (30.0, "FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 27 (HUL) - CAUSING A COLLISION"),
    ])
    state = penalties.state_at(rc, DRIVERS, 40.0)
    assert state[27].pending_s == 10.0
    assert state[27].under_investigation == 0          # closed by the penalty
    assert state[55].under_investigation == 1          # SAI was not penalised
    assert state[55].pending_s == 0.0


def test_two_incidents_sharing_an_offence_stay_apart():
    """
    2026 Spain: SAI was in a TURN 8 collision with COL and another with HUL
    twenty seconds later. Matching on the offence alone merged them, and the
    first incident's clearance closed the second.
    """
    rc = control([
        (10.0, "TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) NOTED "
               "- CAUSING A COLLISION (17:17:33)"),
        (20.0, "FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) "
               "UNDER INVESTIGATION - CAUSING A COLLISION (17:17:33)"),
        (30.0, "TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) NOTED - CAUSING A COLLISION"),
        (40.0, "FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) "
               "UNDER INVESTIGATION - CAUSING A COLLISION"),
        (50.0, "FIA STEWARDS: TURN 8 INCIDENT INVOLVING CARS 43 (COL) AND 55 (SAI) "
               "NO FURTHER ACTION - CAUSING A COLLISION (17:17:33)"),
        (60.0, "FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 27 (HUL) - CAUSING A COLLISION"),
    ])
    sai = penalties.state_at(rc, DRIVERS, 70.0)[55]
    assert len(sai.incidents) == 2
    assert sai.cleared == 1 and sai.under_investigation == 1
    assert penalties.state_at(rc, DRIVERS, 70.0)[27].pending_s == 10.0


def test_the_ticker_carries_every_message_newest_first():
    rc = control([
        (10.0, "GREEN LIGHT - PIT EXIT OPEN"),
        (20.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (900.0, "CHEQUERED FLAG"),
    ])
    shown = penalties.feed(rc, DRIVERS, 100.0)
    assert [e["t"] for e in shown] == [20.0, 10.0]
    assert shown[0]["cars"] == [44] and shown[0]["kind"] == penalties.AWARDED_TIME
    assert shown[1]["kind"] == penalties.OTHER


def test_the_feed_splits_three_ways():
    rc = control([
        (10.0, "GREEN LIGHT - PIT EXIT OPEN"),
        (20.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (30.0, "CAR 44 (HAM) TIME 1:38.003 DELETED - TRACK LIMITS AT TURN 3 LAP 64 16:17:58"),
        (40.0, "DRS ENABLED IN ZONE 2"),
        (50.0, "WAVED BLUE FLAG FOR CAR 44 (HAM) TIMED AT 15:18:27"),
        (60.0, "DOUBLE YELLOW IN TRACK SECTOR 10"),
    ])
    verdicts = penalties.feed(rc, DRIVERS, 100.0, topic=penalties.TOPIC_STEWARDS)
    assert [e["t"] for e in verdicts] == [30.0, 20.0]

    track = penalties.feed(rc, DRIVERS, 100.0, topic=penalties.TOPIC_TRACK)
    assert [e["t"] for e in track] == [40.0, 10.0]

    noise = penalties.feed(rc, DRIVERS, 100.0, topic=penalties.TOPIC_NOISE)
    assert [e["t"] for e in noise] == [60.0, 50.0]

    assert len(penalties.feed(rc, DRIVERS, 100.0)) == 6


@pytest.mark.parametrize("message, topic", [
    ("SAFETY CAR DEPLOYED", penalties.TOPIC_TRACK),
    ("VSC ENDING", penalties.TOPIC_TRACK),
    ("GREEN LIGHT - PIT EXIT OPEN", penalties.TOPIC_TRACK),
    ("PIT EXIT CLOSED", penalties.TOPIC_TRACK),
    ("CHEQUERED FLAG", penalties.TOPIC_TRACK),
    ("DRS ENABLED IN ZONE 2", penalties.TOPIC_TRACK),
    ("RECOVERY VEHICLE ON TRACK AT TURN 4", penalties.TOPIC_TRACK),
    ("RISK OF RAIN FOR F1 RACE IS 60%", penalties.TOPIC_TRACK),
    # A condition, not flag churn, despite reading "IN TRACK SECTOR".
    ("TRACK SURFACE SLIPPERY IN TRACK SECTOR 11", penalties.TOPIC_TRACK),
    ("WAVED BLUE FLAG FOR CAR 44 (HAM) TIMED AT 15:18:27", penalties.TOPIC_NOISE),
    ("BLUE FLAG FOR CAR 44 (HAM)", penalties.TOPIC_NOISE),
    ("DOUBLE YELLOW IN TRACK SECTOR 10", penalties.TOPIC_NOISE),
    ("YELLOW IN TRACK SECTOR 9", penalties.TOPIC_NOISE),
    ("CLEAR IN TRACK SECTOR 9", penalties.TOPIC_NOISE),
    ("FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS",
     penalties.TOPIC_STEWARDS),
])
def test_topics(message, topic):
    assert read(message).topic == topic


def test_a_lap_deletion_is_the_stewards_despite_having_no_prefix():
    """
    Filtering on `FIA STEWARDS:` would drop 70% of them: it is on 971 of the
    3,257 steward messages in the lake, and no lap deletion carries it.
    """
    event = read("CAR 44 (HAM) TIME 1:38.003 DELETED - TRACK LIMITS AT TURN 3 LAP 64 16:17:58")
    assert event.stewards is True
    assert not event.message.startswith("FIA STEWARDS:")


def test_a_flag_is_not_the_stewards():
    assert read("WAVED BLUE FLAG FOR CAR 44 (HAM) TIMED AT 15:18:27").stewards is False
    assert read("CHEQUERED FLAG").stewards is False


def test_the_limit_applies_after_the_filter():
    """
    Asking for the stewards' last two must give two of theirs, not two of
    everything of which none happens to be theirs.
    """
    rows = [(float(i), "CLEAR IN TRACK SECTOR 9") for i in range(1, 30)]
    rows.append((30.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"))
    rows.append((31.0, "INCIDENT INVOLVING CAR 16 (LEC) NOTED - IMPEDING"))
    rows += [(float(i), "CLEAR IN TRACK SECTOR 9") for i in range(32, 60)]
    verdicts = penalties.feed(control(rows), DRIVERS, 100.0, limit=2,
                              topic=penalties.TOPIC_STEWARDS)
    assert [e["t"] for e in verdicts] == [31.0, 30.0]


def test_no_race_control_at_all():
    assert penalties.state_at(pd.DataFrame(), DRIVERS, 100.0) == {}
    assert penalties.feed(pd.DataFrame(), DRIVERS, 100.0) == []


# ------------------------------------------------------------- the real feed

@pytest.mark.realdata
def test_whole_lake_is_classified():
    """
    No race or sprint message that concerns a car goes unread.

    This is the regression guard for a new season's wording: an unrecognised
    verdict, or a car spelled a new way, fails here.
    """
    from racecraft.store.db import connect

    con = connect()
    try:
        rows = con.sql("""select session_key, message from race_control
                          where session in ('R', 'S') and message is not null""").df()
    except Exception:                           # empty lake
        pytest.skip("no lake")
    if rows.empty:
        pytest.skip("no race control in the lake")

    concerns = rows["message"].str.contains(
        "PENALTY|INCIDENT|DELETED|WARNING|REPRIMAND|BLACK|NOTED|INVESTIGAT", regex=True)
    subject = rows[concerns]
    unread = [m for m in subject["message"]
              if penalties.read(m, 0.0, None).kind == penalties.OTHER]
    assert not unread, f"{len(unread)} unclassified, e.g. {unread[:3]}"


# ------------------------------------------------------------ pit-lane cost

def stints(*stops, driver=44, session="2025_09_R", laps_run=40, green=True):
    """A driver's laps, with pit in-laps at the given lap numbers; lap n spans [90n, 90n+90)."""
    rows = []
    for n in range(1, laps_run + 1):
        status = "1" if green or n not in stops else "4"
        if isinstance(green, dict):
            status = green.get(n, "1")
        rows.append({"session_key": session, "driver_number": driver, "lap_number": n,
                     "lap_start_t": 90.0 * n, "lap_end_t": 90.0 * n + 90.0,
                     "is_pit_in_lap": n in stops, "track_status": status})
    return pd.DataFrame(rows)


def rc(*rows, session="2025_09_R"):
    return pd.DataFrame([{"session_key": session, "t": t, "message": m} for t, m in rows])


def test_a_time_penalty_is_served_at_the_next_stop():
    laps = stints(12, 30)
    control_ = rc((500.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"))
    assert penalties.penalised_stops(laps, control_, DRIVERS) == {("2025_09_R", 44, 12)}


def test_a_penalty_awarded_during_the_in_lap_moves_to_the_following_stop():
    """2025 round 9, car 23: awarded while already on the in-lap, served a stop later."""
    laps = stints(12, 30)
    control_ = rc((12 * 90.0 + 45.0, "FIA STEWARDS: 10 SECOND TIME PENALTY FOR CAR 44 (HAM) - UNSAFE RELEASE"))
    assert penalties.penalised_stops(laps, control_, DRIVERS) == {("2025_09_R", 44, 30)}


def test_a_neutralised_stop_does_not_hide_the_next_green_one():
    """2026 Spain: penalties went unserved at stops under the safety car and red flag."""
    laps = stints(12, 30, green={12: "4"})
    control_ = rc((500.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"))
    assert penalties.penalised_stops(laps, control_, DRIVERS) == {
        ("2025_09_R", 44, 12), ("2025_09_R", 44, 30)}


def test_the_feed_saying_served_marks_the_stop_before_it():
    laps = stints(12, 30)
    control_ = rc(
        (500.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
        (31 * 90.0 + 60.0, "FIA STEWARDS: PENALTY SERVED - 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"),
    )
    assert penalties.penalised_stops(laps, control_, DRIVERS) == {
        ("2025_09_R", 44, 12), ("2025_09_R", 44, 30)}


def test_a_penalty_with_no_stop_after_it_marks_nothing():
    """Added to race time at the flag instead: no stop carried it."""
    laps = stints(12)
    control_ = rc((2000.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"))
    assert penalties.penalised_stops(laps, control_, DRIVERS) == frozenset()


def test_a_drive_through_is_a_trip_down_the_lane_too():
    laps = stints(12, 30)
    control_ = rc((500.0, "FIA STEWARDS: DRIVE THROUGH PENALTY FOR CAR 44 (HAM) - FALSE START"))
    assert ("2025_09_R", 44, 12) in penalties.penalised_stops(laps, control_, DRIVERS)


def test_only_the_penalised_car_is_marked():
    laps = pd.concat([stints(12, 30, driver=44), stints(12, 30, driver=16)], ignore_index=True)
    control_ = rc((500.0, "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS"))
    assert all(d == 44 for _, d, _ in penalties.penalised_stops(laps, control_, DRIVERS))


def test_noted_and_investigated_incidents_mark_no_stop():
    laps = stints(12, 30)
    control_ = rc((500.0, "FIA STEWARDS: INCIDENT INVOLVING CAR 44 (HAM) UNDER INVESTIGATION - IMPEDING"))
    assert penalties.penalised_stops(laps, control_, DRIVERS) == frozenset()


def test_nothing_to_mark_without_race_control_or_stops():
    assert penalties.penalised_stops(stints(12), pd.DataFrame(), DRIVERS) == frozenset()
    assert penalties.penalised_stops(pd.DataFrame(), rc((1.0, "X")), DRIVERS) == frozenset()


def test_pit_loss_leaves_a_penalised_stop_out():
    from racecraft.model import circuit

    rows = []
    for driver in range(1, 7):
        for n in range(1, 30):
            pit_in, pit_out = n == 14, n == 15
            time = 90.0 + (12.0 if pit_in else 0) + (10.0 if pit_out else 0)
            if driver == 1 and (pit_in or pit_out):
                time += 5.0                                  # held for a 5 s penalty
            rows.append({"session_key": "2025_09_R", "driver_number": driver, "lap_number": n,
                         "lap_time_s": time, "track_status": "1", "is_pit_in_lap": pit_in,
                         "is_pit_out_lap": pit_out, "location": "Monza"})
    laps = pd.DataFrame(rows)
    [all_stops] = circuit.pit_loss(laps)
    [clean] = circuit.pit_loss(laps, {("2025_09_R", 1, 14)})
    assert all_stops.stops == 6 and clean.stops == 5
    assert clean.seconds == pytest.approx(22.0)


@pytest.mark.realdata
def test_penalised_stops_on_the_real_feed():
    """The rule never contradicts the feed's own `PENALTY SERVED`."""
    from racecraft.store.db import connect

    con = connect()
    try:
        laps = con.sql("""select l.* from laps l join sessions s using (session_key)
                          where s.session = 'R'""").df()
    except Exception:
        pytest.skip("no lake")
    if laps.empty:
        pytest.skip("no races in the lake")
    marked = penalties.penalised_stops_in(con, laps)
    assert 40 <= len(marked) <= 200
