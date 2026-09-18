"""
The live session, held for the API the way a historic one is.

`session.load` keeps two sessions from the lake in memory and hands out the
same object until something evicts it. A live session cannot work that way: the
recording grows while people are looking at it, so the object has to be rebuilt
as the race runs.

This is that rebuild, and the only part of the server that knows live exists.
Everything downstream — the state endpoint, the lap chart, the models — is
handed a `SessionData` and cannot tell where it came from.

The rebuild is deliberately lazy rather than scheduled. A background timer
re-parsing every ten seconds would keep working when nobody is watching, and
would re-parse on a machine left running overnight. Building on demand, behind
the same staleness window the feed uses, costs nothing when the page is closed.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from racecraft.api import session as session_store
from racecraft.live import feed as feed_module
from racecraft.live import recorder

log = logging.getLogger(__name__)

SESSION_KEY = feed_module.SESSION_KEY
# How long a built session may be handed out before the recording is re-read.
# A lap takes over a minute; this is far finer than the data changes and far
# coarser than the panels poll.
REBUILD_INTERVAL_S = 10.0


class NotLive(RuntimeError):
    """Nothing is being recorded, or what is recorded is not yet a session."""


class LiveStore:
    """One live session, rebuilt from its recording when what is held goes stale."""

    def __init__(self) -> None:
        self._feed: feed_module.Feed | None = None
        self._session: session_store.SessionData | None = None
        self._built_at = 0.0
        self._error: str | None = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ attaching

    def attach(self, path: Path | None = None,
               live_session: feed_module.LiveSession | None = None) -> feed_module.Feed:
        """Point at a recording. Defaults to the newest one and the session now."""
        path = path or recorder.latest_recording()
        if path is None:
            empty = recorder.recordings()
            if empty:
                raise NotLive(f"{empty[0].name} is empty. The recorder is connected, but "
                              "nothing has come down the feed yet.")
            raise NotLive(f"no recording in {recorder.LIVE_DIR}. Start one: racecraft-live record")
        live_session = live_session or feed_module.current_session()
        if live_session is None:
            raise NotLive("the schedule has no session within four hours, so a recording "
                          "cannot be matched to one. Pass year, round and session.")
        with self._lock:
            self._feed = feed_module.Feed(path=path, session=live_session)
            self._session = None
            self._built_at = 0.0
            self._error = None
        log.info("live attached to %s as %s", path.name, live_session.session_name)
        return self._feed

    def detach(self) -> None:
        with self._lock:
            self._feed = None
            self._session = None
            self._error = None

    @property
    def attached(self) -> bool:
        return self._feed is not None

    # ------------------------------------------------------------- serving

    def session(self) -> session_store.SessionData:
        """The live session, rebuilt if what is held has gone stale."""
        with self._lock:
            if self._feed is None:
                raise NotLive("live is not attached to a recording")
            if self._session is None or (time.monotonic() - self._built_at) >= REBUILD_INTERVAL_S:
                self._rebuild()
            if self._session is None:
                raise NotLive(self._error or "the recording has nothing in it yet")
            return self._session

    def _rebuild(self) -> None:
        assert self._feed is not None
        started = time.monotonic()
        try:
            tables = self._feed.tables()
            self._session = session_store.SessionData.from_tables(tables, SESSION_KEY)
            self._error = None
            log.info("live rebuilt in %.1fs: %d laps", time.monotonic() - started,
                     len(self._session.laps))
        except (feed_module.NotRecording, KeyError) as error:
            # Normal in the opening minutes: the recorder is connected and the
            # session has not produced anything worth showing yet.
            self._error = str(error)
        except Exception as error:
            self._error = f"{type(error).__name__}: {error}"
            log.warning("live rebuild failed: %s", error)
        finally:
            self._built_at = time.monotonic()

    def status(self) -> dict:
        """Enough to tell whether live is working, without raising if it is not."""
        if self._feed is None:
            latest = recorder.latest_recording()
            if latest is not None:
                return {"attached": False, "recording": str(latest), "error": None}
            empty = recorder.recordings()
            return {
                "attached": False,
                "recording": None,
                "error": (f"{empty[0].name} is empty; the recorder is connected but the "
                          "session has not started" if empty
                          else f"no recording in {recorder.LIVE_DIR}"),
            }
        out = {"attached": True, **self._feed.status()}
        out["built_ago_s"] = None if not self._built_at else round(time.monotonic() - self._built_at, 1)
        if self._error:
            out["error"] = self._error
        if self._session is not None:
            out["drivers"] = len(self._session.drivers)
            out["t_end"] = self._session.t_end
        return out


store = LiveStore()
