"""
Official results from Jolpica (api.jolpi.ca, Ergast's successor), through FastF1's client.

FastF1 always took a session's classification, points, grid, team ids and Q1-Q3 times from
here. Since F1's archive wants an F1 TV login (BUG-004), a session it refuses is built from
OpenF1 (D-009), whose results lack some of these; this puts the official ones back over
OpenF1's, so the results table reads as FastF1 would have written it (D-011).

Jolpica has races, sprints and qualifying, not practice or sprint qualifying. It publishes a
session some hours after it ends: until then OpenF1's results stand, and a later refresh
does not revisit the session (`--force` does). Rate: 500 requests an hour; one a session.
"""

from __future__ import annotations

import logging

import pandas as pd
from fastf1.ergast import Ergast

log = logging.getLogger(__name__)

_ASK = {"R": "get_race_results", "S": "get_sprint_results", "Q": "get_qualifying_results"}


def official(season: int, rnd: int, ident: str) -> pd.DataFrame | None:
    """Jolpica's results for one session, or None if it has none (yet) or cannot be reached."""
    ask = _ASK.get(ident)
    if ask is None:
        return None
    try:
        answer = getattr(Ergast(result_type="pandas", auto_cast=True), ask)(season=season, round=rnd)
    except Exception as error:            # any failure leaves OpenF1's results in place
        log.warning("Jolpica: no results for %d round %d %s: %s", season, rnd, ident, error)
        return None
    return answer.content[0] if answer.content and not answer.content[0].empty else None


def _seconds(values: pd.Series) -> pd.Series:
    return pd.to_timedelta(values).dt.total_seconds()


def overlay(results: pd.DataFrame, jolpica: pd.DataFrame | None, ident: str) -> tuple[pd.DataFrame, list[int]]:
    """OpenF1's results with Jolpica's official fields over them, car by car.

    Also returns the cars the two place differently: the cross-check D-009 asked for.
    Cars Jolpica does not list keep OpenF1's fields.
    """
    if jolpica is None:
        return results, []
    j = jolpica.set_index(pd.to_numeric(jolpica["number"]))
    fields = {"team_id": j["constructorId"], "full_name": j["givenName"] + " " + j["familyName"],
              "position": j["position"]}
    if ident == "Q":
        fields.update({part.lower() + "_s": _seconds(j[part]) for part in ("Q1", "Q2", "Q3") if part in j})
    else:
        # As FastF1: the winner's total time, everyone else's gap, the lapped included.
        fields.update({"grid_position": j["grid"], "classified_position": j["positionText"].astype(str),
                       "status": j["status"], "points": j["points"], "laps": j["laps"],
                       "result_time_s": _seconds(j["totalRaceTime"])})
    out = results.copy()
    cars = out["driver_number"]
    listed = cars.isin(j.index)
    differ = sorted(int(n) for n in cars[listed & (out["position"] != cars.map(j["position"]))])
    for column, values in fields.items():
        out.loc[listed, column] = cars[listed].map(values).to_numpy()
    return out, differ
