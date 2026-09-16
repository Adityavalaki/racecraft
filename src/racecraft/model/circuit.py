"""
What belongs to the circuit rather than the car.

Tyre degradation and relative pace change when the regulations change, so
2026 can only be learned from 2026. Two things do not: how long the pit lane
costs, and how often a race is neutralised. Pit loss is set by the length of
the lane and its speed limit; safety car likelihood is set by walls, run-off
and how easily a stricken car blocks the track. Both can therefore be learned
from every season in the lake, which is what makes them usable for a circuit
the current cars have not visited yet.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# Track status codes from the timing feed.
GREEN, YELLOW, SAFETY_CAR, RED, VSC, VSC_ENDING = "1", "2", "4", "5", "6", "7"
NEUTRALISED = (SAFETY_CAR, VSC, VSC_ENDING)

# FastF1's location names drift between seasons: Monaco became "Monte Carlo"
# in 2026 and Miami became "Miami Gardens" in 2025. Keying analysis on the raw
# name silently splits a circuit's history in two, which is exactly the history
# a circuit-level estimate depends on. (Event names drift too — Barcelona's
# race stopped being the "Spanish Grand Prix" when Madrid took the title in
# 2026 — which is why location, not event name, is the key.)
CIRCUIT_ALIASES = {
    "Monte Carlo": "Monaco",
    "Miami Gardens": "Miami",
}


def canonical_circuit(location: pd.Series | str) -> pd.Series | str:
    """One stable name per circuit, across every season."""
    if isinstance(location, str):
        return CIRCUIT_ALIASES.get(location, location)
    return location.map(lambda name: CIRCUIT_ALIASES.get(name, name))


# Laps either side of a stop used to establish the driver's normal pace.
PACE_WINDOW = 6
MIN_PACE_LAPS = 3


@dataclass
class PitLoss:
    circuit: str
    seconds: float
    spread_s: float          # median absolute deviation: how consistent stops are here
    stops: int
    seasons: int

    def as_dict(self) -> dict:
        return {"circuit": self.circuit, "seconds": round(self.seconds, 2),
                "spread_s": round(self.spread_s, 2), "stops": self.stops, "seasons": self.seasons}


def pit_loss(laps: pd.DataFrame) -> list[PitLoss]:
    """
    Time lost to a pit stop, per circuit, in seconds.

    Measured as the driver's own in-lap and out-lap against their normal pace
    either side of the stop, which cancels car, fuel and track: only the
    detour through the pit lane is left.

    Stops made under a safety car are excluded. They are far cheaper, because
    the rest of the field is circulating slowly, and mixing them in would
    understate what a green-flag stop costs — which is the number a strategy
    call actually turns on.

    `laps` needs `location` alongside the lap columns.
    """
    out = []
    laps = laps.assign(circuit=canonical_circuit(laps["location"]))
    for circuit, circuit_laps in laps.groupby("circuit"):
        losses, seasons = [], set()
        for (session, driver), driver_laps in circuit_laps.groupby(["session_key", "driver_number"]):
            driver_laps = driver_laps.sort_values("lap_number")
            for loss in _stop_costs(driver_laps):
                losses.append(loss)
                seasons.add(session[:4])
        if len(losses) >= 5:
            values = np.array(losses)
            median = float(np.median(values))
            out.append(PitLoss(
                circuit=str(circuit),
                seconds=median,
                spread_s=float(np.median(np.abs(values - median))),
                stops=len(values),
                seasons=len(seasons),
            ))
    return sorted(out, key=lambda p: p.seconds)


def _stop_costs(driver_laps: pd.DataFrame) -> list[float]:
    """Cost of each green-flag stop by this driver in this session."""
    costs = []
    green = driver_laps[(driver_laps["track_status"] == GREEN)
                        & ~driver_laps["is_pit_in_lap"].fillna(False)
                        & ~driver_laps["is_pit_out_lap"].fillna(False)
                        & driver_laps["lap_time_s"].notna()
                        & (driver_laps["lap_number"] > 1)]
    if green.empty:
        return costs

    for _, in_lap in driver_laps[driver_laps["is_pit_in_lap"].fillna(False)].iterrows():
        lap_number = in_lap["lap_number"]
        out_lap = driver_laps[driver_laps["lap_number"] == lap_number + 1]
        if out_lap.empty or not bool(out_lap.iloc[0]["is_pit_out_lap"]):
            continue
        out_lap = out_lap.iloc[0]
        if pd.isna(in_lap["lap_time_s"]) or pd.isna(out_lap["lap_time_s"]):
            continue
        # A stop under neutralisation is a different transaction entirely.
        if in_lap["track_status"] != GREEN or out_lap["track_status"] != GREEN:
            continue

        nearby = green[green["lap_number"].between(lap_number - PACE_WINDOW, lap_number + PACE_WINDOW)]
        if len(nearby) < MIN_PACE_LAPS:
            continue
        reference = float(nearby["lap_time_s"].median())
        cost = float(in_lap["lap_time_s"] + out_lap["lap_time_s"]) - 2 * reference
        if 5 < cost < 60:        # anything outside this is a penalty or a problem, not a stop
            costs.append(cost)
    return costs


# How many races of league-average evidence to blend into each circuit. Four
# is about one season: enough to stop three-from-three reading as certainty,
# light enough that a genuinely wild circuit still stands out.
PRIOR_RACES = 4.0


@dataclass
class SafetyCarRisk:
    circuit: str
    races: int
    share_of_races: float        # raw: races with at least one safety car or VSC
    probability: float           # shrunk toward the league average; use this one
    periods_per_race: float      # how many separate neutralisations, on average
    per_lap: float               # chance a given lap is neutralised
    median_laps_lost: float      # laps spent neutralised, when it happens

    def as_dict(self) -> dict:
        return {"circuit": self.circuit, "races": self.races,
                "share_of_races": round(self.share_of_races, 3),
                "probability": round(self.probability, 3),
                "periods_per_race": round(self.periods_per_race, 2),
                "per_lap": round(self.per_lap, 4),
                "median_laps_lost": round(self.median_laps_lost, 1)}


def safety_car_risk(track_status: pd.DataFrame, sessions: pd.DataFrame, laps: pd.DataFrame) -> list[SafetyCarRisk]:
    """
    How often each circuit neutralises a race, from the track status feed.

    This matters more to a strategy than almost anything else: a stop under a
    safety car costs roughly half a green-flag stop, so the chance of one
    arriving changes what the optimal plan is. Safety car and virtual safety
    car are counted together, since both hand back the same kind of cheap stop.
    """
    leader_laps = (laps.groupby("session_key")["lap_number"].max().rename("total_laps"))
    meta = sessions.set_index("session_key").join(leader_laps)
    meta = meta.assign(circuit=canonical_circuit(meta["location"]))

    out: list[SafetyCarRisk] = []
    tally: list[tuple[str, int, int, list[float], list[float], list[int]]] = []
    for circuit, group in meta.groupby("circuit"):
        races, neutralised, shares, durations, periods = 0, 0, [], [], []
        for session_key, race in group.iterrows():
            status = track_status[track_status["session_key"] == session_key].sort_values("t")
            if status.empty or pd.isna(race["total_laps"]):
                continue
            races += 1
            spans = _neutralised_spans(status)
            periods.append(len(spans))
            if not spans:
                shares.append(0.0)
                continue
            neutralised += 1
            session_laps = laps[laps["session_key"] == session_key]
            lap_seconds = float(session_laps["lap_time_s"].median())
            total_seconds = float(race["total_laps"]) * lap_seconds
            neutral_seconds = sum(end - start for start, end in spans)
            shares.append(min(1.0, neutral_seconds / total_seconds))
            durations.append(neutral_seconds / lap_seconds)
        if races >= 2:
            tally.append((str(circuit), races, neutralised, shares, durations, periods))

    # Three races out of three is not certainty. Each circuit is pulled toward
    # the league average by the weight of PRIOR_RACES races, so a short history
    # reads as "probably high" rather than "always".
    total_races = sum(races for _, races, _, _, _, _ in tally)
    total_neutralised = sum(n for _, _, n, _, _, _ in tally)
    league = total_neutralised / total_races if total_races else 0.0

    for name, races, neutralised, shares, durations, periods in tally:
        out.append(SafetyCarRisk(
            circuit=name,
            races=races,
            share_of_races=neutralised / races,
            probability=(neutralised + league * PRIOR_RACES) / (races + PRIOR_RACES),
            per_lap=float(np.mean(shares)) if shares else 0.0,
            median_laps_lost=float(np.median(durations)) if durations else 0.0,
            periods_per_race=float(np.mean(periods)) if periods else 0.0,
        ))
    return sorted(out, key=lambda r: -r.probability)


def _neutralised_spans(status: pd.DataFrame) -> list[tuple[float, float]]:
    """(start, end) of each safety car or VSC period, in session seconds."""
    spans, start = [], None
    for _, row in status.iterrows():
        if row["status"] in NEUTRALISED and start is None:
            start = float(row["t"])
        elif row["status"] not in NEUTRALISED and start is not None:
            spans.append((start, float(row["t"])))
            start = None
    if start is not None:
        spans.append((start, float(status["t"].iloc[-1])))
    return spans
