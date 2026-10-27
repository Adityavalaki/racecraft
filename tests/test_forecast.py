"""The weekend forecast from Open-Meteo, offline (D-015)."""

from __future__ import annotations

import pandas as pd
import pytest
import requests
from fastf1 import ergast

from racecraft.api import forecast

SCHEDULE = pd.DataFrame([{"raceName": "Mexico City Grand Prix", "circuitName": "Hermanos Rodriguez",
                          "raceDate": pd.Timestamp("2026-11-01"), "raceTime": "20:00:00+00:00",
                          "sprintDate": pd.Timestamp("2026-10-11"), "sprintTime": "09:00:00+00:00",
                          "lat": 19.40, "long": -99.09}])


class _Answer:
    def __init__(self, day):
        self.day = day

    def raise_for_status(self):
        pass

    def json(self):
        hours = [f"{self.day}T{h:02d}:00" for h in range(24)]
        return {"hourly": {"time": hours, "precipitation_probability": list(range(24)),
                           "precipitation": [0.1] * 24, "temperature_2m": [20.0] * 24, "wind_speed_10m": [7.0] * 24}}


@pytest.fixture
def asked(monkeypatch):
    urls = []
    forecast._cache.clear()
    monkeypatch.setattr(ergast.Ergast, "get_race_schedule", lambda self, **k: SCHEDULE)

    def get(url, params, timeout):
        urls.append(url)
        return _Answer(params["start_date"])

    monkeypatch.setattr(forecast.requests, "get", get)
    return urls


def test_upcoming_is_forecast_and_past_is_the_archive(asked):
    out = forecast.for_weekend(2026, 19, now=pd.Timestamp("2026-10-27", tz="UTC"))
    race, sprint = out["forecasts"]
    assert race["session"] == "Race" and race["upcoming"] and race["rain_chance"] == 20       # the 20:00 hour
    assert not sprint["upcoming"] and sprint["rain_chance"] == 9
    assert asked == [forecast.FORECAST, forecast.ARCHIVE]
    assert out["credit"] == "Weather data by Open-Meteo.com"


def test_beyond_sixteen_days_there_is_no_forecast_yet(asked):
    # On 1 October the race (1 November) is too far ahead; the sprint (11 October) is not.
    out = forecast.for_weekend(2026, 19, now=pd.Timestamp("2026-10-01", tz="UTC"))
    assert [(f["session"], f["upcoming"]) for f in out["forecasts"]] == [("Sprint", True)]
    assert asked == [forecast.FORECAST]


def test_open_meteo_down_is_unavailable(asked, monkeypatch):
    def down(*a, **k):
        raise requests.ConnectionError("offline")

    monkeypatch.setattr(forecast.requests, "get", down)
    with pytest.raises(forecast.Unavailable, match="Open-Meteo"):
        forecast.for_weekend(2026, 19, now=pd.Timestamp("2026-10-27", tz="UTC"))
