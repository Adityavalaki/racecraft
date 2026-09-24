"""Small hand-built frames shaped like FastF1's output, so transforms can be tested offline."""

import numpy as np
import pandas as pd
import pytest

T0 = pd.Timestamp("2024-03-02 14:03:42.431")


def td(seconds):
    return pd.to_timedelta(seconds, unit="s")


@pytest.fixture(autouse=True)
def no_real_recordings(tmp_path_factory, monkeypatch):
    """
    Keep the machine's own live recordings out of every test.

    A recording on disk puts a LIVE row at the top of the session list, so a
    test that passed all week failed the afternoon someone recorded Baku
    practice. Tests about live mode point it at their own recordings.
    """
    from racecraft.live import recorder

    monkeypatch.setattr(recorder, "LIVE_DIR", tmp_path_factory.mktemp("no-live"))


@pytest.fixture
def fastf1_laps():
    """
    Two drivers, three laps each. Driver 1 starts on a used set (TyreLife 4 on
    lap 1) and pits at the end of lap 2. Driver 44's lap 2 has a combined
    TrackStatus '12', which a CSV round-trip would turn into the integer 12.
    """
    rows = []
    for drv, abbr, statuses in [("1", "VER", ["1", "1", "1"]), ("44", "HAM", ["1", "12", "1"])]:
        start = 3600.0
        for lap in (1, 2, 3):
            lap_time = 96.0 + lap * 0.1
            pit_in = start + lap_time if (drv == "1" and lap == 2) else np.nan
            pit_out = start + 3.0 if (drv == "1" and lap == 3) else np.nan
            stint = 2.0 if (drv == "1" and lap == 3) else 1.0
            rows.append({
                "Time": td(start + lap_time), "Driver": abbr, "DriverNumber": drv,
                "LapTime": td(lap_time), "LapNumber": float(lap), "Stint": stint,
                "PitOutTime": td(pit_out), "PitInTime": td(pit_in),
                "Sector1Time": td(30.0), "Sector2Time": td(40.0), "Sector3Time": td(lap_time - 70.0),
                "Sector1SessionTime": pd.NaT, "Sector2SessionTime": pd.NaT, "Sector3SessionTime": pd.NaT,
                "SpeedI1": 250.0, "SpeedI2": 260.0, "SpeedFL": 280.0, "SpeedST": 320.0,
                "IsPersonalBest": False,
                "Compound": "HARD" if stint == 2.0 else "SOFT",
                "TyreLife": 1.0 if stint == 2.0 else (3.0 + lap if drv == "1" else float(lap)),
                "FreshTyre": stint == 2.0, "Team": "Team", "LapStartTime": td(start),
                "LapStartDate": T0 + td(start), "TrackStatus": statuses[lap - 1], "Position": 1.0 if drv == "1" else 2.0,
                "Deleted": False, "DeletedReason": "", "FastF1Generated": False, "IsAccurate": True,
            })
            start += lap_time
    return pd.DataFrame(rows)


@pytest.fixture
def fastf1_race_control():
    return pd.DataFrame({
        "Time": [T0 + td(3700.5), T0 + td(4000.0)],
        "Category": ["Flag", "SafetyCar"],
        "Message": ["YELLOW IN TRACK SECTOR 4", "SAFETY CAR DEPLOYED"],
        "Status": [None, "DEPLOYED"],
        "Flag": ["YELLOW", None],
        "Scope": ["Sector", None],
        "Sector": [4.0, np.nan],
        "RacingNumber": [None, None],
        "Lap": [2, 5],
    })
