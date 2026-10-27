"""
The title odds, for the interface: `model/title.py` at a session's moment.

Answers are kept for the last few moments asked about, keyed by the lake and
the moment: the standings screen asks again every time it is opened, and the
odds only change when a result arrives.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict

from racecraft.model import standings, title, title_history
from racecraft.store.db import connect, lake_key

log = logging.getLogger(__name__)
MAX_ANSWERS = 8


class NotAvailable(RuntimeError):
    """The odds cannot be worked out here: the message says why."""


_answers: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()


def for_session(session_key: str, moment: str = "before") -> dict:
    """The odds from the standings when `session_key` started (`before`) or once it was over (`after`)."""
    con = connect()
    year, as_of = standings.as_of(con, session_key, moment)      # KeyError if not in the lake
    key = (lake_key(), year, as_of.isoformat())
    with _lock:
        if key in _answers:
            _answers.move_to_end(key)
            return {**_answers[key], "moment": moment}
    try:
        odds = title.odds(con, year, as_of)
    except title.NoCalendar as error:
        raise NotAvailable(f"{error}: connect once to fetch the schedule") from None
    answer = {**odds.as_dict(), "second_opinion": _second_opinion(con, year, as_of, odds)}
    with _lock:
        _answers[key] = answer
        while len(_answers) > MAX_ANSWERS:
            _answers.popitem(last=False)
    return {**answer, "moment": moment}


def _second_opinion(con, year: int, as_of, odds: title.TitleOdds) -> dict[str, float] | None:
    """
    The results-only odds beside the lap-time ones, by driver code (D-018): an
    extra, so anything that stops it leaves the main odds alone.
    """
    try:
        events = [title.Event(e["round"], e["event_name"], e["session"] == "sprint") for e in odds.remaining]
        return {code: round(p, 4) for code, p in
                title_history.odds_now(con, year, as_of, events=events, runs=odds.runs).items()}
    except Exception as error:                   # noqa: BLE001 - never at the main odds' expense
        log.warning("no results-only odds for %s at %s: %s", year, as_of, error)
        return None


def forget() -> None:
    """Drop every kept answer: a sync has brought in new results."""
    with _lock:
        _answers.clear()
