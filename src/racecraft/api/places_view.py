"""
Plans ranked by where they finish, for the interface.

This is `racecraft-analyse race` served over HTTP, and it is built from exactly
the same three pieces so the two cannot disagree: `race_inputs.build` for what
the simulator is told, `places.study` for the ranking, `places.verdict` for what
the ranking means.

The inputs are held out. For a race that has happened, the simulator is fitted
only on races that started before it — the same rule as the terminal — so the
ranking on screen is what the model would have said going into that race rather
than a description of it.

It is slow the first time, around half a minute: a season of fits and a few
thousand simulated races. So it is asked for only when the Places view is
opened, and each answer is kept. It does not depend on the session's own laps —
only on races that had finished — which is why a live session can be served from
the same cache without going stale as the race runs.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from racecraft import config
from racecraft.model import places, race_inputs
from racecraft.store.db import connect

log = logging.getLogger(__name__)

MAX_CACHED = 16


class NotSimulable(RuntimeError):
    """The races before this one cannot support a simulation. The message says why."""


_cache: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()
# One computation per key at a time: two tabs asking for the same ranking should
# cost one simulation, not two.
_computing: dict[tuple, threading.Event] = {}


def for_session(session_key: str, grid: int, runs: int = places.DEFAULT_RUNS,
                live=None) -> dict:
    """
    The places ranking for the race this session belongs to.

    `live` is the live `SessionData` when `session_key` is the live key; its
    circuit and season come from the recording, everything else from the lake.
    """
    key = (str(config.LAKE_DIR.resolve()), session_key, grid, runs)
    while True:
        with _lock:
            if key in _cache:
                _cache.move_to_end(key)
                return _cache[key]
            waiting = _computing.get(key)
            if waiting is None:
                _computing[key] = threading.Event()
                break
        waiting.wait(timeout=300)

    try:
        answer = _compute(session_key, grid, runs, live)
        with _lock:
            _cache[key] = answer
            _cache.move_to_end(key)
            while len(_cache) > MAX_CACHED:
                _cache.popitem(last=False)
        return answer
    finally:
        with _lock:
            _computing.pop(key).set()


def _compute(session_key: str, grid: int, runs: int, live) -> dict:
    con = connect()
    if live is not None:
        location = str(live.meta.get("location") or "")
        year = _year(live.meta)
        race_key = None                      # the live race is not in the lake yet
    else:
        rows = con.sql(f"""select location, year, "session" from sessions
                           where session_key = '{_safe(session_key)}'""").df()
        if rows.empty:
            raise KeyError(session_key)
        location, year = str(rows.iloc[0]["location"]), int(rows.iloc[0]["year"])
        # A race is itself the one being studied. Any other session of the
        # weekend studies that weekend's race.
        race_key = session_key if rows.iloc[0]["session"] == "R" else None

    if not year:
        raise NotSimulable("cannot tell which season this session belongs to")

    try:
        inputs = race_inputs.build(con, location, year, session_key=race_key)
    except race_inputs.NotEnoughData as error:
        raise NotSimulable(str(error)) from None

    result = places.study(inputs, grid, runs=runs)
    if not result.ranking:
        raise NotSimulable("no plans to race at this circuit")

    return {
        "session_key": session_key,
        "grid": grid,
        "runs": runs,
        "inputs": inputs.as_dict(),
        "study": result.as_dict(),
        "verdict": places.verdict(result),
        "omissions": list(places.OMISSIONS),
    }


def _year(meta: dict) -> int | None:
    import pandas as pd

    for field in ("date_utc", "t0_utc"):
        value = meta.get(field)
        if value is None:
            continue
        try:
            return int(pd.Timestamp(value).year)
        except (ValueError, TypeError):
            continue
    return None


def _safe(value: str) -> str:
    if not value.replace("_", "").replace("-", "").isalnum():
        raise KeyError(value)
    return value
