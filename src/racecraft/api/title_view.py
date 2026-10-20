"""
The title odds, for the interface: `model/title.py` at a session's moment.

Answers are kept for the last few moments asked about, keyed by the lake and
the moment: the standings screen asks again every time it is opened, and the
odds only change when a result arrives.
"""

from __future__ import annotations

import threading
from collections import OrderedDict

import pandas as pd

from racecraft.model import title
from racecraft.store.db import connect, lake_key

MAX_ANSWERS = 8


class NotAvailable(RuntimeError):
    """The odds cannot be worked out here: the message says why."""


_answers: OrderedDict[tuple, dict] = OrderedDict()
_lock = threading.Lock()


def for_session(session_key: str, moment: str = "before") -> dict:
    """The odds from the standings when `session_key` started (`before`) or once it was over (`after`)."""
    con = connect()
    row = con.execute("select year, date_utc from sessions where session_key = ?", [session_key]).fetchone()
    if row is None:
        raise KeyError(session_key)
    year, start = int(row[0]), pd.Timestamp(row[1])
    start = start.tz_localize("UTC") if start.tzinfo is None else start.tz_convert("UTC")
    as_of = start if moment == "before" else start + pd.Timedelta(seconds=1)
    key = (lake_key(), year, as_of.isoformat())
    with _lock:
        if key in _answers:
            _answers.move_to_end(key)
            return {**_answers[key], "moment": moment}
    try:
        answer = title.odds(con, year, as_of).as_dict()
    except title.NoCalendar as error:
        raise NotAvailable(f"{error}: connect once to fetch the schedule") from None
    with _lock:
        _answers[key] = answer
        while len(_answers) > MAX_ANSWERS:
            _answers.popitem(last=False)
    return {**answer, "moment": moment}


def forget() -> None:
    """Drop every kept answer: a sync has brought in new results."""
    with _lock:
        _answers.clear()
