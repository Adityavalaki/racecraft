"""
A race weekend's weather forecast at the circuit, from Open-Meteo (open-meteo.com; free for
non-commercial use, no key, data under CC BY 4.0): rain chance, rain, air temperature and
wind at the start of the weekend's race and sprint (D-015). Shown beside the prediction;
no model uses it.

The circuit's position and the start times come from Jolpica's race schedule. A start in
the next sixteen days gets the current forecast; an earlier one gets the forecast Open-Meteo
archived for that hour (kept from 2022), which says what was expected, not what happened:
the session's own weather table says that.
"""

from __future__ import annotations

import time

import pandas as pd
import requests
from fastf1.ergast import Ergast

FORECAST = "https://api.open-meteo.com/v1/forecast"
ARCHIVE = "https://historical-forecast-api.open-meteo.com/v1/forecast"
HOURLY = "precipitation_probability,precipitation,temperature_2m,wind_speed_10m"
AHEAD = pd.Timedelta(days=16)               # as far as Open-Meteo forecasts
FRESH_S = 3600                              # a forecast is asked again after an hour
CREDIT = "Weather data by Open-Meteo.com"

_cache: dict[tuple[int, int], tuple[float, dict]] = {}


class Unavailable(LookupError):
    """No forecast to give: no such round, or Open-Meteo or Jolpica could not be reached."""


def _start(date, clock) -> pd.Timestamp | None:
    if pd.isna(date):
        return None
    day = pd.Timestamp(date).strftime("%Y-%m-%d")
    return pd.Timestamp(f"{day} {pd.Timestamp(str(clock)).strftime('%H:%M') if pd.notna(clock) else '12:00'}",
                        tz="UTC")


def _hour(lat: float, lon: float, at: pd.Timestamp, url: str) -> dict:
    """Open-Meteo's hourly values for the hour a session starts in."""
    day = at.strftime("%Y-%m-%d")
    response = requests.get(url, params={"latitude": lat, "longitude": lon, "hourly": HOURLY,
                                         "start_date": day, "end_date": day, "timezone": "UTC"}, timeout=30)
    response.raise_for_status()
    hourly = response.json()["hourly"]
    index = hourly["time"].index(at.floor("h").strftime("%Y-%m-%dT%H:%M"))
    return {"rain_chance": hourly["precipitation_probability"][index], "rain_mm": hourly["precipitation"][index],
            "air_temp": hourly["temperature_2m"][index], "wind_kmh": hourly["wind_speed_10m"][index]}


def for_weekend(season: int, rnd: int, now: pd.Timestamp | None = None) -> dict:
    """The forecast for the start of this round's race, then its sprint if it has one."""
    cached = _cache.get((season, rnd))
    if cached and time.monotonic() - cached[0] < FRESH_S:
        return cached[1]
    now = now or pd.Timestamp.now(tz="UTC")
    try:
        schedule = Ergast(result_type="pandas", auto_cast=True).get_race_schedule(season=season, round=rnd)
    except Exception as error:                   # Jolpica unreachable: nothing to forecast for
        raise Unavailable(f"no schedule for {season} round {rnd}: {error}") from None
    if schedule.empty:
        raise Unavailable(f"no round {rnd} in {season}")
    event = schedule.iloc[0]
    out = []
    for name, date, clock in [("Race", event["raceDate"], event.get("raceTime")),
                              ("Sprint", event.get("sprintDate"), event.get("sprintTime"))]:
        at = _start(date, clock)
        if at is None or at > now + AHEAD:
            continue
        upcoming = at > now
        try:
            values = _hour(float(event["lat"]), float(event["long"]), at, FORECAST if upcoming else ARCHIVE)
        except (requests.RequestException, KeyError, ValueError) as error:
            raise Unavailable(f"Open-Meteo: {error}") from None
        out.append({"session": name, "starts_utc": at.isoformat(), "upcoming": upcoming, **values})
    answer = {"event": str(event["raceName"]), "circuit": str(event["circuitName"]), "forecasts": out,
              "credit": CREDIT}
    _cache[(season, rnd)] = (time.monotonic(), answer)
    return answer
