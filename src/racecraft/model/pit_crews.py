"""
How fast each team's pit crew is.

The public timing never says how long a car stood still, only when it crossed
the pit-lane entry and exit lines. So a stop is measured as **pit-lane time**,
line to line, and compared with the typical stop of the same race: the lane,
its speed limit and its length are the same for everyone there, so what
differs is the crew's work (and a car queued behind its team-mate, which is
the team's call too). A team's figure is the median of its stops against the
race's: seconds quicker (minus) or slower than a typical stop.

Not every trip down the lane is a crew at work. Left out, and counted:

* **red flags**: every car waits in the lane; the time is the stoppage;
* **safety cars and VSCs**: the lane runs 3 to 4 s quicker under one at
  Monaco and Baku, and cars queue behind their team-mates, so those stops are
  not compared with green-flag ones;
* **penalties**: a time penalty is served at the stop, a drive-through or
  stop/go is a trip of its own (`api.penalties.penalised_stops`, the rule the
  pit-loss model uses);
* **no new tyres**: a stop that did not change tyres is not a pit stop;
* **over a minute**: a car taken into the garage.

Measured: a team's figure in one half of a season's races predicts the other
half closely (split-half correlation between odd and even rounds: 0.86 in
2023, 0.85 in 2024, 0.80 in 2025, 0.91 in 2026 so far), so the order is the
crews', not chance. Before safety-car stops were left out, 2025's was 0.64.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racecraft.model import standings
from racecraft.store.db import has_table

# Longer than this in the lane is the garage, not a stop.
MAX_LANE_S = 60.0
# A stop this much slower than the race's typical one went wrong somewhere.
SLOW_S = 2.0
# Below this many stops a team's figure is shown but called thin.
FEW_STOPS = 8
RED_FLAG = "5"
# Track status codes for a safety car, a VSC and a VSC ending.
NEUTRALISED = ("4", "6", "7")


@dataclass
class CrewRanking:
    year: int
    teams: list[dict]
    stops: int
    races: int
    excluded: dict[str, int]
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"year": self.year, "teams": self.teams, "stops": self.stops, "races": self.races,
                "excluded": self.excluded, "notes": self.notes}


def stops(con, year: int) -> pd.DataFrame:
    """
    Every trip down the pit lane in the season's Grands Prix and sprints: its
    lane time, whether it counts as a crew's stop (and if not, why), and how it
    compares with the race's typical stop. Teams as the standings resolve them.
    """
    if not has_table(con, "laps"):
        return pd.DataFrame()
    # lap_start_t, lap_end_t and is_pit_in_lap are what the penalty rule reads.
    laps = con.execute("""select session_key, driver_number, lap_number, stint, track_status, pit_in_t, pit_out_t,
                                 lap_start_t, lap_end_t, is_pit_in_lap
                          from laps where year = ? and "session" in ('R', 'S')""", [int(year)]).df()
    if laps.empty:
        return pd.DataFrame()
    after = laps[["session_key", "driver_number", "lap_number", "stint", "track_status", "pit_out_t"]].copy()
    after["lap_number"] -= 1
    trips = laps.merge(after, on=["session_key", "driver_number", "lap_number"], suffixes=("", "_out"))
    trips = trips[trips["pit_in_t"].notna() & trips["pit_out_t_out"].notna()].copy()
    if trips.empty:
        return pd.DataFrame()
    trips["lane_s"] = trips["pit_out_t_out"] - trips["pit_in_t"]

    from racecraft.api.penalties import penalised_stops_in

    penalised = penalised_stops_in(con, laps)
    statuses = trips["track_status"].astype(str) + trips["track_status_out"].astype(str)
    red = statuses.str.contains(RED_FLAG)
    neutralised = statuses.apply(lambda text: any(code in text for code in NEUTRALISED))
    same_tyres = trips["stint_out"].notna() & (trips["stint_out"] == trips["stint"])
    served = [(k, int(d), int(n)) in penalised
              for k, d, n in zip(trips["session_key"], trips["driver_number"], trips["lap_number"])]
    reason = np.select([red, trips["lane_s"] >= MAX_LANE_S, pd.Series(served, index=trips.index), same_tyres,
                        neutralised],
                       ["red flag", "garage", "penalty", "no new tyres", "safety car"], default="")
    trips["excluded"] = reason
    counted = trips["excluded"] == ""
    typical = trips[counted].groupby("session_key")["lane_s"].median()
    trips["typical_s"] = trips["session_key"].map(typical)
    trips["vs_typical_s"] = trips["lane_s"] - trips["typical_s"]

    teams = standings.results(con, year)
    if not teams.empty:
        keep = teams[["session_key", "driver_number", "abbreviation", "team_key", "team_name", "team_color", "event_name",
                      "round", "code"]]
        trips = trips.merge(keep, on=["session_key", "driver_number"], how="left")
    return trips.rename(columns={"pit_in_t": "t"}).drop(
        columns=["pit_out_t", "pit_out_t_out", "track_status_out", "stint_out", "lap_start_t", "lap_end_t",
                 "is_pit_in_lap", "lap_start_t_out", "lap_end_t_out", "is_pit_in_lap_out"], errors="ignore")


def ranking(con, year: int, as_of: pd.Timestamp | None = None) -> CrewRanking:
    """Every team's crew, from the season's stops in sessions that started before `as_of`."""
    trips = stops(con, year)
    if not trips.empty and as_of is not None:
        starts = con.execute("""select session_key, date_utc from sessions where year = ?""", [int(year)]).df()
        before = set(starts.loc[pd.to_datetime(starts["date_utc"], utc=True) < as_of, "session_key"])
        trips = trips[trips["session_key"].isin(before)]
    if trips.empty:
        return CrewRanking(year=int(year), teams=[], stops=0, races=0, excluded={},
                           notes=["no Grand Prix or sprint has been run yet this season"])
    counted = trips[(trips["excluded"] == "") & trips["team_key"].notna()]
    excluded = {k: int(v) for k, v in trips.loc[trips["excluded"] != "", "excluded"].value_counts().items()}
    out = []
    for key, team in counted.groupby("team_key"):
        rel = team["vs_typical_s"]
        latest = team.sort_values(["round", "t"]).iloc[-1]
        q1, q3 = rel.quantile([0.25, 0.75])
        out.append({
            "team": str(latest["team_name"]),
            "team_color": None if pd.isna(latest["team_color"]) else str(latest["team_color"]),
            "stops": int(len(team)),
            "typical_s": round(float(rel.median()), 2),
            "spread_s": round(float(q3 - q1), 2),
            "q1_s": round(float(q1), 2),
            "q3_s": round(float(q3), 2),
            "slow_share": round(float((rel > SLOW_S).mean()), 3),
            "thin": bool(len(team) < FEW_STOPS),
        })
    out.sort(key=lambda t: (t["thin"], t["typical_s"]))
    for place, team in enumerate(out, start=1):
        team["position"] = place
    notes = []
    if any(t["thin"] for t in out):
        notes.append(f"fewer than {FEW_STOPS} stops: ranked last, the figure is not yet a pattern")
    return CrewRanking(year=int(year), teams=out, stops=int(len(counted)), races=int(counted["session_key"].nunique()),
                       excluded=excluded, notes=notes)


def session_stops(con, session_key: str) -> list[dict]:
    """One race's (or sprint's) trips down the pit lane, in order, each against the race's typical stop."""
    year = int(session_key[:4])
    trips = stops(con, year)
    if trips.empty:
        return []
    here = trips[trips["session_key"] == session_key].sort_values("t")
    return [{
        "t": round(float(r.t), 2),
        "lap": int(r.lap_number),
        "driver_number": int(r.driver_number),
        "abbreviation": None if pd.isna(r.abbreviation) else str(r.abbreviation),
        "team": None if pd.isna(r.team_name) else str(r.team_name),
        "team_color": None if pd.isna(r.team_color) else str(r.team_color),
        "lane_s": round(float(r.lane_s), 2),
        "vs_typical_s": None if pd.isna(r.vs_typical_s) else round(float(r.vs_typical_s), 2),
        "excluded": r.excluded or None,
    } for r in here.itertuples()]
