"""
Model output for one session, shaped for the interface.

The replay panels answer "what happened". These answer "what did the models
make of it" — measured degradation against what the tyres actually did, what
the pit lane costs here, how often this circuit neutralises, and which plans
the strategy model makes cheapest.

Two things make this affordable to serve.

*Fits are cached per season, per race.* Fitting a season's lap effects costs
tens of seconds; fitting one race costs a fraction of one. So every race in a
season is fitted once and kept, and a request combines the ones it wants. That
also makes the out-of-sample split below free.

*The race being watched is left out of its own fit.* Degradation shown over a
race is combined from the season's **other** races, so the curve on screen is a
prediction of the race rather than a description of it. This matters: a model
fitted on the race it is drawn over will hug the data and tell you nothing. The
response says which races went into the fit so the claim can be checked.

The observed curve on the same chart does come from the race itself, and is
meant to: the line is the prediction, the points are what happened. Both are
measured the same way, through the regression's partial residuals, so the gap
between them means something.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from racecraft import config
from racecraft.model import circuit as circuit_model
from racecraft.model import compounds as compounds_model
from racecraft.model import race_inputs as race_inputs_model
from racecraft.model import pace as pace_model
from racecraft.model import strategy as strategy_model
from racecraft.api import tyre_sets_view
from racecraft.store.db import connect

log = logging.getLogger(__name__)

# Degradation measured from race laps only covers the tyre life teams accept,
# because nobody drives past the cliff and so nobody records it. Multiplying by
# this reproduces the stop counts teams actually choose; see the README.
DEFAULT_SCALE = 1.5

MIN_LAPS_TO_FIT_RACE = 200
MIN_STINT_LAPS = 10
TOP_PLANS = 8
MAX_CACHED_SEASONS = 3
# Circuit constants are cut off at each session's start; one set per session viewed.
MAX_CACHED_CUTOFFS = 32
# Tyre ages counted as "new" when rebasing the observed curve to zero, so it
# starts where the model's line starts.
BASELINE_AGE = 3
# Below this many observations a median lap time at a given tyre age is noise.
MIN_OBSERVATIONS = 4


@dataclass
class SeasonFits:
    """Every fittable race in one season, fitted separately and kept."""
    year: int
    by_session: dict[str, pace_model.PaceModel]
    names: dict[str, str]
    fuel_s_per_lap: float

    def combined(self, exclude: str | None = None) -> tuple[dict[str, float], dict[str, float], list[str]]:
        """Degradation and compound offsets from every race but `exclude`."""
        used = [key for key in self.by_session if key != exclude]
        models = [self.by_session[key] for key in used]
        if not models:
            return {}, {}, []
        degradation = {c: v[0] for c, v in pace_model.combine(models).items()}
        offsets = {
            compound: float(np.median([m.compound_offset_s[compound]
                                       for m in models if compound in m.compound_offset_s]))
            for compound in pace_model.DRY_COMPOUNDS
            if any(compound in m.compound_offset_s for m in models)
        }
        return degradation, offsets, [self.names[key] for key in used]


def for_session(session_key: str, scale: float = DEFAULT_SCALE) -> dict:
    """Everything the models can say about the circuit and tyres of one session."""
    con = connect()
    meta = con.sql(
        "select session_key, year, round, session, event_name, location, total_laps, date_utc "
        f"from sessions where session_key = '{_safe(session_key)}'"
    ).df()
    if meta.empty:
        raise KeyError(session_key)
    row = meta.iloc[0]
    year = int(row["year"])
    name = str(circuit_model.canonical_circuit(str(row["location"])))

    # Only races that started before this session: a race's own stops and
    # safety cars are not evidence about it. For a practice session that leaves
    # out the weekend's race too, which had not happened.
    started = pd.Timestamp(row["date_utc"]) if pd.notna(row["date_utc"]) else None
    constants = _circuit_constants(before=started, year=year, round_number=int(row["round"]))
    loss = constants["pit_loss"].get(name)
    risk = constants["safety_car"].get(name)
    # The scheduled distance was known in advance; the median of past races is a fallback.
    total_laps = _int_or_none(row["total_laps"]) or constants["laps"].get(name)

    fits = _season_fits(year)
    measured, offsets, fitted_on = fits.combined(exclude=session_key)
    is_race = str(row["session"]) == "R"

    out: dict = {
        "session_key": session_key,
        "circuit": name,
        "event_name": str(row["event_name"]),
        "year": year,
        "is_race": is_race,
        "total_laps": total_laps,
        "pit_loss": loss,
        "safety_car": risk,
        "scale": scale,
        "degradation_measured": {c: round(v, 4) for c, v in measured.items()},
        "degradation_used": {c: round(v * scale, 4) for c, v in measured.items()},
        "compound_offset_s": {c: round(v, 3) for c, v in offsets.items()},
        "fuel_s_per_lap": round(fits.fuel_s_per_lap, 4),
        "fitted_on": fitted_on,
        "fitted_on_count": len(fitted_on),
        "held_out": session_key in fits.by_session,
        "constants_before": None if started is None else started.isoformat(),
        "compounds": compounds_model.for_race(year, int(row["round"])),
        "caveats": list(strategy_model.KNOWN_OMISSIONS),
    }

    # Only a race says anything about tyre wear or strategy. A practice session
    # mixes fuel runs, qualifying simulations and out-laps, and its "stints" are
    # cars trundling through the pit lane — a field average of four stops, which
    # is not a strategy. The modelled line below still holds, because it is
    # fitted on races and belongs to the season rather than to this session; the
    # observed side of it does not, and is withheld rather than drawn.
    laps = con.sql(f"select * from laps where session_key = '{_safe(session_key)}'").df()
    out["degradation_curve"] = _degradation_curve(laps, measured, scale, observed=is_race)
    out["stints"] = _observed_stints(laps) if is_race else []
    if not is_race:
        out["observed_unavailable"] = (
            "this is not a race: practice and qualifying laps mix fuel loads and "
            "run plans, so what they show about tyre wear is not comparable"
        )

    if measured and loss and total_laps:
        least = race_inputs_model.mandatory_stops(name, year or 0)
        out["min_stops"] = least
        out["plans"] = _plans(total_laps, measured, scale, offsets, loss["seconds"], least)
        out["plans_with_risk"] = _plans_with_risk(total_laps, measured, scale, offsets,
                                                  loss["seconds"], risk, least)
    else:
        out["plans"] = []
        out["plans_with_risk"] = []
        out["plans_unavailable"] = _why_no_plans(measured, loss, total_laps, name, held_out=True)

    out["tyre_sets"] = _tyre_sets(session_key, out)
    return out


def _tyre_sets(session_key: str, out: dict, live=None, live_status: dict | None = None) -> dict | None:
    """
    For a race: whether each car can run the plans above on the sets it had at
    the start, and what starting a stint on a used set costs it.

    The plans are the same for every car; the tyres are not. A plan that needs
    a new hard is no plan at all for a car that ran both its hards in practice.
    """
    if not out["is_race"] or not out["plans"]:
        return None
    try:
        weekend, code = tyre_sets_view.weekend_for(session_key, live, live_status)
    except (tyre_sets_view.NoSets, KeyError) as error:
        return {"unavailable": str(error), "cars": {}}
    # Every plan either ranking offers, each with its cost on a green race:
    # the seconds ranking calls it seconds_lost, the safety-car one green_s.
    seen: set[str] = set()
    plans = []
    for plan in out["plans"] + out["plans_with_risk"]:
        if plan["plan"] not in seen:
            seen.add(plan["plan"])
            green = plan.get("seconds_lost", plan.get("green_s"))
            plans.append({"plan": plan["plan"], "green_s": green})
    return {"unavailable": None,
            "cars": tyre_sets_view.plan_checks(weekend, code, plans, out["degradation_used"])}


def for_live(live, scale: float = DEFAULT_SCALE, live_status: dict | None = None) -> dict:
    """
    The same answer for a session still happening.

    A live session has no row in the lake, so the circuit, the distance and the
    laps come from what has been recorded instead. Everything the models are
    built on still comes from the lake, because it has to: degradation is fitted
    on this season's completed races, pit loss and neutralisation risk on years
    of them. Only the race being watched is live.

    `held_out` is false here and says so. A finished race is scored against a
    model that never saw it; a race in progress is watched with a model fitted
    on every race that finished before it, which is the honest arrangement and a
    different one.
    """
    name = str(circuit_model.canonical_circuit(str(live.meta.get("location") or "")))
    constants = _circuit_constants()
    loss = constants["pit_loss"].get(name)
    risk = constants["safety_car"].get(name)
    total_laps = _int_or_none(live.meta.get("total_laps")) or constants["laps"].get(name)

    year = _year_of(live)
    fits = _season_fits(year) if year else SeasonFits(0, {}, {}, 0.0)
    measured, offsets, fitted_on = fits.combined()

    is_race = str(live.meta.get("session_name", "")).lower().startswith("race")
    laps = live.laps

    out: dict = {
        "session_key": live.session_key,
        "circuit": name,
        "event_name": str(live.meta.get("event_name") or "Live timing"),
        "year": year or 0,
        "is_race": is_race,
        "is_live": True,
        "total_laps": total_laps,
        "pit_loss": loss,
        "safety_car": risk,
        "scale": scale,
        "degradation_measured": {c: round(v, 4) for c, v in measured.items()},
        "degradation_used": {c: round(v * scale, 4) for c, v in measured.items()},
        "compound_offset_s": {c: round(v, 3) for c, v in offsets.items()},
        "fuel_s_per_lap": round(fits.fuel_s_per_lap, 4),
        "fitted_on": fitted_on,
        "fitted_on_count": len(fitted_on),
        "held_out": False,
        "compounds": _live_compounds(year, live_status),
        "caveats": list(strategy_model.KNOWN_OMISSIONS),
    }

    out["degradation_curve"] = _degradation_curve(laps, measured, scale, observed=is_race)
    out["stints"] = _observed_stints(laps) if is_race else []
    if not is_race:
        out["observed_unavailable"] = (
            "this is not a race: practice and qualifying laps mix fuel loads and "
            "run plans, so what they show about tyre wear is not comparable"
        )

    if measured and loss and total_laps:
        least = race_inputs_model.mandatory_stops(name, year or 0)
        out["min_stops"] = least
        out["plans"] = _plans(total_laps, measured, scale, offsets, loss["seconds"], least)
        out["plans_with_risk"] = _plans_with_risk(total_laps, measured, scale, offsets,
                                                  loss["seconds"], risk, least)
    else:
        out["plans"] = []
        out["plans_with_risk"] = []
        out["plans_unavailable"] = _why_no_plans(measured, loss, total_laps)
    out["tyre_sets"] = _tyre_sets(live.session_key, out, live=live, live_status=live_status)
    return out


def _live_compounds(year: int | None, live_status: dict | None) -> dict | None:
    session = (live_status or {}).get("session") or {}
    if not year or not session.get("round"):
        return None
    return compounds_model.for_race(year, int(session["round"]))


def _year_of(live) -> int | None:
    """The season a live session belongs to, from whatever date it carries."""
    for field_name in ("date_utc", "t0_utc"):
        value = live.meta.get(field_name)
        if value is None:
            continue
        try:
            return int(pd.Timestamp(value).year)
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------- curves

def _degradation_curve(laps: pd.DataFrame, measured: dict[str, float],
                       scale: float, observed: bool = True) -> list[dict]:
    """
    The model's straight line against what this race's tyres actually did.

    The observed side has to be measured the way the model is fitted, or the
    two lines are not about the same thing. Two attempts got this wrong before
    the third worked, and both failures are worth keeping in mind.

    Measuring each lap against the driver's own pace early in that stint made
    hard tyres a second a lap *faster* by age 22 — not wear, but the track
    rubbering in while the car burned fuel off. Measuring instead against the
    field's median lap time removed that, and then flattened medium tyres to
    nothing: early in a stint the whole field is on tyres of the same age, so
    the median moves with them and the wear vanishes into it.

    What works is the regression's own partial residuals. Lap effects are
    estimated jointly with the wear slope rather than subtracted first, so
    fuel and track evolution come out while degradation stays in.
    """
    if laps.empty:
        return []
    clean = pace_model.clean_race_laps(laps) if observed else laps.iloc[:0]
    seen: dict[tuple[str, int], list[float]] = {}

    if not clean.empty:
        try:
            residuals = pace_model.partial_residuals(clean)
        except (pace_model.Confounded, ValueError) as error:
            log.info("%s has no separable wear to plot: %s", session_key, error)
            residuals = None
        if residuals is not None:
            # Rebased so a new tyre sits at zero, which is where the model's
            # line starts and what the chart's axis means.
            for compound, group in residuals.groupby("compound"):
                young = group[group["tyre_life"] <= BASELINE_AGE]
                base = float(young["partial_s"].median()) if len(young) >= 2 else 0.0
                for _, lap in group.iterrows():
                    seen.setdefault((str(compound), int(lap["tyre_life"])), []).append(
                        float(lap["partial_s"]) - base)

    out: list[dict] = []
    for compound, slope in sorted(measured.items()):
        ages = sorted(age for c, age in seen if c == compound)
        max_age = max(ages) if ages else 30
        points = []
        for age in range(1, max_age + 1):
            samples = seen.get((compound, age), [])
            points.append({
                "age": age,
                "model_s": round(slope * scale * age, 3),
                "model_unscaled_s": round(slope * age, 3),
                "observed_s": round(float(np.median(samples)), 3) if len(samples) >= MIN_OBSERVATIONS else None,
                "laps": len(samples),
            })
        out.append({"compound": compound, "points": points,
                    "observed_to_age": max(ages) if ages else 0})
    return out


def _observed_stints(laps: pd.DataFrame) -> list[dict]:
    """What each driver actually ran: compound, length, and when they stopped."""
    if laps.empty or "compound" not in laps:
        return []
    known = laps[laps["compound"].notna()]
    if known.empty:
        return []
    rows = (known.groupby(["driver", "driver_number", "stint", "compound"], as_index=False)
                 .agg(first_lap=("lap_number", "min"), last_lap=("lap_number", "max"),
                      laps=("lap_number", "size"))
                 .sort_values(["driver_number", "stint"]))
    if rows.empty:
        return []
    out = []
    for driver_number, group in rows.groupby("driver_number"):
        group = group.sort_values("stint")
        out.append({
            "driver": str(group["driver"].iloc[0]),
            "driver_number": int(driver_number),
            "stops": len(group) - 1,
            "stints": [
                {"compound": str(s["compound"]), "laps": int(s["laps"]),
                 "first_lap": int(s["first_lap"]), "last_lap": int(s["last_lap"])}
                for _, s in group.iterrows()
            ],
        })
    return out


# ---------------------------------------------------------------- plans

def _plans(total_laps: int, measured: dict[str, float], scale: float,
           offsets: dict[str, float], pit_loss_s: float, min_stops: int = 0) -> list[dict]:
    degradation = {c: v * scale for c, v in measured.items()}
    plans = strategy_model.enumerate_plans(total_laps, tuple(degradation), max_stops=2,
                                           min_stint=MIN_STINT_LAPS, step=1, min_stops=min_stops)
    costed = [strategy_model.cost(plan, degradation, pit_loss_s, compound_offset_s=offsets)
              for plan in plans]
    costed.sort(key=lambda c: c.seconds_lost)
    if not costed:
        return []

    # The model counts seconds, so running soft-then-medium costs exactly what
    # medium-then-soft costs and the ranking fills with mirror images. They are
    # different races — one starts on the quicker tyre and defends, the other
    # attacks at the end — but nothing here can tell them apart, so they are
    # collapsed to one row rather than pretending the order was chosen.
    best = costed[0].seconds_lost
    out, seen = [], set()
    for item in costed:
        shape = tuple(sorted(item.plan.stints))
        if shape in seen:
            continue
        seen.add(shape)
        record = item.as_dict()
        record["behind_best_s"] = round(item.seconds_lost - best, 1)
        record["stint_laps"] = [length for _, length in item.plan.stints]
        record["stop_laps"] = _stop_laps(item.plan)
        record["orders"] = sorted({
            str(other.plan) for other in costed
            if tuple(sorted(other.plan.stints)) == shape
        })
        out.append(record)
        if len(out) == TOP_PLANS:
            break
    return out


def _plans_with_risk(total_laps: int, measured: dict[str, float], scale: float,
                     offsets: dict[str, float], pit_loss_s: float,
                     risk: dict | None, min_stops: int = 0) -> list[dict]:
    """The plans over races that can be neutralised; see `simulate.rank_with_risk`."""
    from racecraft.model import simulate as simulate_model

    degradation = {c: v * scale for c, v in measured.items()}
    periods = risk["periods_per_race"] if risk else simulate_model.NEUTRALISATION_PER_LAP * total_laps
    neutralisation = simulate_model.Neutralisation.for_circuit(periods, total_laps)
    ranked = simulate_model.rank_with_risk(total_laps, degradation, pit_loss_s, neutralisation,
                                           offsets, keep=TOP_PLANS, min_stint=MIN_STINT_LAPS,
                                           min_stops=min_stops)
    out = []
    for costed in ranked:
        record = costed.as_dict()
        record["stop_laps"] = _stop_laps(costed.plan)
        out.append(record)
    if out:
        best = out[0]["expected_s"]
        for record in out:
            record["behind_best_s"] = round(record["expected_s"] - best, 1)
    return out


def _stop_laps(plan: strategy_model.Plan) -> list[int]:
    laps, running = [], 0
    for _, length in plan.stints[:-1]:
        running += length
        laps.append(running)
    return laps


def _why_no_plans(measured: dict, loss: dict | None, total_laps: int | None,
                  circuit: str = "this circuit", held_out: bool = False) -> str:
    if not measured:
        return "no fittable races in this season to measure degradation from"
    if loss is None:
        if held_out:
            return f"no earlier race at {circuit} to measure its pit lane from"
        return "not enough green-flag stops at this circuit to measure pit loss"
    return "race distance for this circuit is not known"


# ---------------------------------------------------------------- caches

_tables_cache: dict[str, dict] = {}
_circuit_cache: OrderedDict[tuple, dict] = OrderedDict()
_season_cache: OrderedDict[tuple[str, int], SeasonFits] = OrderedDict()
_lock = threading.Lock()


def _lake() -> str:
    return str(config.LAKE_DIR.resolve())


def _race_tables() -> dict:
    """Every race's laps, sessions and track status, read once per lake."""
    key = _lake()
    with _lock:
        if key in _tables_cache:
            return _tables_cache[key]
    con = connect()
    value = {
        "laps": con.sql("""select l.*, s.location, s.year from laps l join sessions s using (session_key)
                           where s.session = 'R'""").df(),
        "sessions": con.sql("""select session_key, location, year, round, date_utc
                               from sessions where session = 'R'""").df(),
        "status": con.sql("select session_key, t, status from track_status").df(),
    }
    with _lock:
        _tables_cache[key] = value
    return value


def _circuit_constants(before: pd.Timestamp | None = None, year: int | None = None,
                       round_number: int | None = None) -> dict:
    """
    Pit loss, neutralisation risk and usual distance for every circuit.

    With `before`, only from races that started before it — the same cutoff the
    simulator's inputs use, tie broken by round for a same-day start. Without,
    from every race, which is right for a session still in progress and for
    the circuits table.
    """
    key = (_lake(), None if before is None else before.isoformat(), year, round_number)
    with _lock:
        if key in _circuit_cache:
            _circuit_cache.move_to_end(key)
            return _circuit_cache[key]

    tables = _race_tables()
    sessions = tables["sessions"]
    if before is not None:
        dates = pd.to_datetime(sessions["date_utc"], utc=True)
        cutoff = before if before.tzinfo else before.tz_localize("UTC")
        earlier = dates < cutoff
        same_day = (dates == cutoff) & (sessions["year"] == year) & (sessions["round"] < (round_number or 0))
        sessions = sessions[earlier | same_day]
    keys = set(sessions["session_key"])
    laps = tables["laps"][tables["laps"]["session_key"].isin(keys)]
    status = tables["status"][tables["status"]["session_key"].isin(keys)]

    by_circuit = circuit_model.canonical_circuit(laps["location"]) if not laps.empty else laps["location"]
    value = {
        "pit_loss": {p.circuit: p.as_dict() for p in circuit_model.pit_loss(laps)} if not laps.empty else {},
        "safety_car": ({r.circuit: r.as_dict()
                        for r in circuit_model.safety_car_risk(status, sessions[["session_key", "location"]], laps)}
                       if not laps.empty else {}),
        "laps": {
            str(name): int(group.groupby("session_key")["lap_number"].max().median())
            for name, group in laps.assign(circuit=by_circuit).groupby("circuit")
        },
    }
    with _lock:
        _circuit_cache[key] = value
        while len(_circuit_cache) > MAX_CACHED_CUTOFFS:
            _circuit_cache.popitem(last=False)
    return value


def _season_fits(year: int) -> SeasonFits:
    """Every race in a season, fitted separately so any one can be left out."""
    key = (_lake(), year)
    with _lock:
        if key in _season_cache:
            _season_cache.move_to_end(key)
            return _season_cache[key]

    con = connect()
    races = con.sql(f"""select session_key, total_laps, event_name from sessions
                        where year = {int(year)} and session = 'R' order by round""").df()
    by_session: dict[str, pace_model.PaceModel] = {}
    names: dict[str, str] = {}
    clean_all: dict[str, pd.DataFrame] = {}
    totals: dict[str, int] = {}

    for _, race in races.iterrows():
        laps = con.sql(f"select * from laps where session_key = '{race.session_key}'").df()
        clean = pace_model.clean_race_laps(laps)
        if len(clean) < MIN_LAPS_TO_FIT_RACE:
            continue
        clean_all[race.session_key] = clean
        names[race.session_key] = str(race.event_name)
        if pd.notna(race.total_laps):
            totals[race.session_key] = int(race.total_laps)
        try:
            by_session[race.session_key] = pace_model.fit_lap_effects(clean)
        except (pace_model.Confounded, ValueError) as error:
            log.info("%s not fittable: %s", race.event_name, error)

    fuel = float("nan")
    if clean_all:
        try:
            fuel = pace_model.fit_pooled(clean_all, totals).fuel_s_per_lap
        except (pace_model.Confounded, ValueError) as error:
            log.info("%s fuel not separable: %s", year, error)
    if not np.isfinite(fuel):
        fuel = 0.0

    fits = SeasonFits(year=year, by_session=by_session, names=names, fuel_s_per_lap=fuel)
    with _lock:
        _season_cache[key] = fits
        _season_cache.move_to_end(key)
        while len(_season_cache) > MAX_CACHED_SEASONS:
            _season_cache.popitem(last=False)
    return fits


def circuits() -> list[dict]:
    """Every circuit's measured constants, for a standalone table."""
    constants = _circuit_constants()
    out = []
    for name in sorted(set(constants["pit_loss"]) | set(constants["safety_car"])):
        out.append({
            "circuit": name,
            "laps": constants["laps"].get(name),
            "pit_loss": constants["pit_loss"].get(name),
            "safety_car": constants["safety_car"].get(name),
        })
    return out


def _safe(value: str) -> str:
    if not value.replace("_", "").replace("-", "").isalnum():
        raise KeyError(value)
    return value


def _int_or_none(value) -> int | None:
    return None if value is None or pd.isna(value) else int(value)
