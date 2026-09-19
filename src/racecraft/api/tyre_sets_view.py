"""
Tyre sets for one session, shaped for the interface.

What each car had when the session started, and every set fitted during it
with the time of each lap, so the panel can move with the replay clock: a new
set becomes a used one the moment it leaves the pit lane, and its lap count
climbs as the laps are completed.

For a race it also answers the question the set count exists for: can this car
run the plans the strategy model likes, on the tyres it actually has? See
`plan_checks`.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from racecraft.model import tyre_sets
from racecraft.store.db import connect

log = logging.getLogger(__name__)

# Schedule names, as FastF1 and the live feed give them, to the lake's codes.
SESSION_CODES = {
    "Practice 1": "FP1", "Practice 2": "FP2", "Practice 3": "FP3",
    "Sprint Qualifying": "SQ", "Sprint Shootout": "SQ", "Sprint": "S",
    "Qualifying": "Q", "Race": "R",
}

MAX_CACHED = 24
_cache: OrderedDict[str, dict] = OrderedDict()
_weekends: OrderedDict[tuple[int, int], tyre_sets.Weekend] = OrderedDict()
_lock = threading.Lock()


class NoSets(RuntimeError):
    """The session exists but has nothing to say about tyre sets."""


def for_session(session_key: str, live=None, live_status: dict | None = None) -> dict:
    """
    Every car's sets for one session. Kept once built, except live, which grows.
    """
    if live is None:
        with _lock:
            if session_key in _cache:
                _cache.move_to_end(session_key)
                return _cache[session_key]
    weekend, code, key = _weekend(session_key, live, live_status)
    out = describe(weekend, code, key)
    if live is None:
        with _lock:
            _cache[session_key] = out
            while len(_cache) > MAX_CACHED:
                _cache.popitem(last=False)
    return out


def weekend_for(session_key: str, live=None, live_status: dict | None = None):
    """The weekend a session belongs to, and that session's code."""
    weekend, code, _ = _weekend(session_key, live, live_status)
    return weekend, code


def _weekend(session_key: str, live, live_status: dict | None):
    con = connect()
    if live is not None:
        session = (live_status or {}).get("session") or {}
        year, rnd = session.get("year"), session.get("round")
        code = SESSION_CODES.get(str(session.get("name") or ""))
        if not (year and rnd and code):
            raise NoSets("cannot tell which weekend the live session belongs to")
        weekend = tyre_sets.from_lake(con, int(year), int(rnd), live_laps=live.laps,
                                      live_session=code, sprint=_scheduled_sprint(int(year), int(rnd)))
        return weekend, code, session_key

    rows = con.sql(f"""select year, round, "session" from sessions
                       where session_key = '{_safe(session_key)}'""").df()
    if rows.empty:
        raise KeyError(session_key)
    year, rnd, code = int(rows.iloc[0]["year"]), int(rows.iloc[0]["round"]), str(rows.iloc[0]["session"])
    with _lock:
        weekend = _weekends.get((year, rnd))
    if weekend is None:
        weekend = tyre_sets.from_lake(con, year, rnd)
        with _lock:
            _weekends[(year, rnd)] = weekend
            while len(_weekends) > MAX_CACHED:
                _weekends.popitem(last=False)
    if code not in weekend.sessions:
        raise NoSets(f"no laps on dry tyres in {session_key}")
    return weekend, code, session_key


def describe(weekend: tyre_sets.Weekend, code: str, session_key: str) -> dict:
    """The response: rules, then each car's sets at the start of `code` and during it."""
    order = weekend.sessions
    rules = weekend.rules
    cars = []
    for number, car in sorted(weekend.cars.items()):
        held = weekend.holding(number, code)
        returned_numbers = {r.set.number for r in held.returned}
        during = [s for s in car.sets if any(run.session == code for run in s.runs)]
        cars.append({
            "driver_number": number,
            "driver": car.driver,
            "team": car.team,
            "stand_ins": car.stand_ins,
            "at_start": {
                c: {"new": max(held.new[c], 0),
                    "used": [{"set": s.number, "laps": laps} for s, laps in held.used if s.compound == c]}
                for c in tyre_sets.DRY_COMPOUNDS
            },
            "returned": [{"set": r.set.number, "compound": r.set.compound, "after": r.after,
                          "laps": r.laps} for r in held.returned],
            "new_returned": held.new_returned,
            "this_session": [{
                "set": s.number,
                "compound": s.compound,
                "new_at_start": s.laps_before(code, order) is None,
                "laps_at_start": s.laps_before(code, order) or 0,
                # Run here although the tracker had it handed back: its guess was wrong.
                "thought_returned": s.number in returned_numbers,
                "runs": [{"start_t": run.start_t, "lap_end_t": run.lap_end_t}
                         for run in s.runs if run.session == code],
            } for s in during],
            "notes": held.notes,
        })
    returns = [{"after": after, "sets": n} for after, n, _ in rules.returns if after in order[:order.index(code)]]
    return {
        "session_key": session_key,
        "session": code,
        "event_name": weekend.event_name,
        "year": weekend.year,
        "sessions": order,
        "rules": {
            "name": rules.name,
            "allocation": weekend.allocation,
            "returns": [{"after": after, "sets": n} for after, n, _ in rules.returns],
            "q3_returns_soft": rules.q3_returns_soft,
            "extra": weekend.extra,
            "hand_backs_known": rules.hand_backs_known,
        },
        "returns_so_far": returns,
        "cars": cars,
        "notes": weekend.notes,
    }


def plan_checks(weekend: tyre_sets.Weekend, code: str, plans: list[dict],
                degradation: dict[str, float]) -> dict[str, dict]:
    """
    For every car, whether each plan can be run on the sets it held at the start
    of `code`, and what starting stints on used sets costs.

    `plans` are the strategy model's, as it serves them: a name, and its cost
    on a green race as `green_s` when known. Degradation is the scaled line the
    plans were costed on, so the extra seconds are on the same footing as the
    plan's own, and the two add up to what the plan costs this car.

    Each car's plans come back cheapest first on its own tyres, the ones it
    cannot run last. That order is the point: the model's best plan assumes new
    sets, and a car whose mediums all ran in qualifying may do better with the
    plan that runs them shortest.
    """
    out: dict[str, dict] = {}
    for number, car in weekend.cars.items():
        held = weekend.holding(number, code)
        left = held.left()
        checks = []
        for plan in plans:
            stints = _stints(plan["plan"])
            check = tyre_sets.check_plan(stints, left, degradation)
            green = plan.get("green_s")
            total = green + check.extra_s if green is not None and check.feasible else None
            checks.append({"plan": plan["plan"], **check.as_dict(),
                           "green_s": green, "total_s": None if total is None else round(total, 1)})
        checks.sort(key=lambda c: (not c["feasible"], c["total_s"] if c["total_s"] is not None else float("inf")))
        best = next((c["total_s"] for c in checks if c["total_s"] is not None), None)
        for c in checks:
            c["behind_best_s"] = None if c["total_s"] is None or best is None else round(c["total_s"] - best, 1)
        out[str(number)] = {"driver": car.driver, "left": left, "plans": checks}
    return out


def _stints(name: str) -> list[tuple[str, int]]:
    """'medium 22 > hard 29' -> [('MEDIUM', 22), ('HARD', 29)]."""
    out = []
    for part in name.split(" > "):
        compound, laps = part.split(" ")
        out.append((compound.upper(), int(laps)))
    return out


def _scheduled_sprint(year: int, rnd: int) -> bool | None:
    """Whether a weekend has a sprint, from the schedule, before the sprint exists."""
    try:
        import fastf1

        from racecraft.live.feed import _use_project_cache
        _use_project_cache()
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        row = schedule[schedule["RoundNumber"] == rnd]
        if row.empty:
            return None
        return "sprint" in str(row.iloc[0]["EventFormat"]).lower()
    except Exception:                                   # noqa: BLE001 - offline is normal
        log.info("no schedule for %s round %s; sprint format read from the lake", year, rnd)
        return None


def _safe(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise KeyError(value)
    return value
