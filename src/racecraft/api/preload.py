"""
Work done ahead, when the app starts, so the slow answers are there when asked for.

The latest race's strategy model and the latest weekend's prediction are the two
answers that take tens of seconds; both then come from disk on later starts. It
runs on a background thread: the app is usable while it works, only a little
slower, and a failure here costs only the head start.
"""

from __future__ import annotations

import logging
import threading

from racecraft.api import insight, prediction_view
from racecraft.store.db import connect, has_table

log = logging.getLogger(__name__)


def latest_sessions(con) -> tuple[str | None, str | None]:
    """(the latest race, the latest session of any kind): a prediction is asked for from either."""
    if not has_table(con, "sessions"):
        return None, None
    race = con.execute("""select session_key from sessions where "session" = 'R' order by date_utc desc limit 1""").fetchone()
    latest = con.execute("select session_key from sessions order by date_utc desc limit 1").fetchone()
    return race[0] if race else None, latest[0] if latest else None


def run() -> None:
    try:
        race, latest = latest_sessions(connect())
    except Exception:
        log.warning("preload: could not read the lake", exc_info=True)
        return
    for name, work in (("strategy model", lambda: insight.for_session(race) if race else None),
                       ("prediction", lambda: prediction_view.for_session(latest) if latest else None)):
        try:
            work()
            log.info("preload: %s ready", name)
        except Exception as error:                   # often just "qualifying has not run yet": it is made on asking
            log.info("preload: %s not made: %s", name, error)


def start() -> threading.Thread:
    thread = threading.Thread(target=run, name="preload", daemon=True)
    thread.start()
    return thread
