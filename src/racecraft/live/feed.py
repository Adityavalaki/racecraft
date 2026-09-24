"""
Reading a live recording into the tables everything else already understands.

This is the whole of what makes live mode cheap. A recording parses into the
same FastF1 session object that a historic session parses into, so it goes
through the same `ingest.fastf1_source.extract` and comes out as the same
tables. The API, the panels and the models then cannot tell the difference,
which was the point of putting a single session clock underneath all of them.

Two things are deliberately not done here.

*No incremental parsing.* Each refresh re-reads the recording from the start,
because FastF1's parser is built that way and a race's timing data — laps,
track status, weather, race control, without car telemetry — is a few megabytes,
not gigabytes. Re-reading it costs a second or two. Parsing incrementally would
mean reimplementing the parser to save a second per minute.

*No positions or car telemetry.* Those are the overwhelming majority of the
feed's volume and the least of its strategy value: a race carries 1.4 million
position samples against a few thousand lap rows. The timing side is what the
tower, the trace, the tyre model and the strategy board all read. The track map
stays historic-only until this is proven on a real weekend.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from racecraft import config
from racecraft.ingest import fastf1_source

log = logging.getLogger(__name__)

# How stale the tables may be before a read re-parses the recording. A lap takes
# somewhere over a minute, so ten seconds is far finer than the data changes.
REFRESH_INTERVAL_S = 10.0
SESSION_KEY = "live"


class NotRecording(RuntimeError):
    """No recording to read, or nothing in it yet."""


def _use_project_cache() -> None:
    """
    Point FastF1 at the project's cache rather than a temporary folder.

    Live mode still asks FastF1 for the schedule and the event's identity, and
    without this those requests land in the system temp directory, so they are
    re-fetched on a machine that already has them and lost on reboot — during a
    race weekend, which is exactly when the network is least worth relying on.
    """
    import fastf1

    config.FASTF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        fastf1.Cache.enable_cache(str(config.FASTF1_CACHE_DIR))
    except Exception:                       # already enabled, or unwritable
        log.debug("could not enable the project cache", exc_info=True)


@dataclass
class LiveSession:
    """Which session a recording belongs to, as FastF1 names it."""
    year: int
    round_number: int
    session_name: str

    @property
    def key(self) -> str:
        return SESSION_KEY


def current_session(now: datetime | None = None, within: timedelta = timedelta(hours=4)) -> LiveSession | None:
    """
    The session running now, from the published schedule.

    `within` is generous on purpose: a session's listed start time is when the
    lights go out, and the feed carries useful data well before and after it.
    """
    import fastf1

    _use_project_cache()
    now = now or datetime.now(timezone.utc)
    schedule = fastf1.get_event_schedule(now.year, include_testing=False)
    best: tuple[timedelta, LiveSession] | None = None

    for _, event in schedule.iterrows():
        for number in range(1, 6):
            name = event.get(f"Session{number}")
            starts = event.get(f"Session{number}DateUtc")
            if not isinstance(name, str) or pd.isna(starts):
                continue
            starts = pd.Timestamp(starts)
            if starts.tzinfo is None:
                starts = starts.tz_localize("UTC")
            distance = abs(starts.to_pydatetime() - now)
            if distance <= within and (best is None or distance < best[0]):
                best = (distance, LiveSession(int(now.year), int(event["RoundNumber"]), name))
    return best[1] if best else None


def live_t0(livedata, path: Path) -> pd.Timestamp | None:
    """
    Session time zero for a recording: the moment FastF1 measured its laps from.

    Race control is stored as absolute times and has to be turned into session
    time on the same clock as the laps, and the laps are FastF1's. So the zero
    is read from FastF1's own parse of the recording rather than worked out a
    second time — two derivations of one number drift apart, and did:

    * FastF1 takes the moment the session status became **Started**, when the
      recording holds it, and only otherwise the first message it can read.
      Taking the first message regardless put a recorder switched on at 08:10
      for an 08:30 session twenty minutes out, and the runbook says to switch
      it on early.
    * FastF1 cannot read a line with an apostrophe in it, so its zero is the
      next line; reading that line properly put our zero a line earlier than
      its own.

    `recording_t0` remains as the fallback for a FastF1 that does not expose
    its start date, and it reads the file the way FastF1 does for that reason.
    """
    start = getattr(livedata, "_start_date", None)
    if start is not None:
        moment = pd.Timestamp(start)
        return moment.tz_localize(None) if moment.tzinfo else moment
    return recording_t0(path)


def recording_t0(path: Path) -> pd.Timestamp | None:
    """
    The timestamp of the first message FastF1 would read from a recording.

    FastF1's fallback zero when the recording has no Started status, read the
    way FastF1 reads it — including skipping a line it cannot parse — because
    what matters is agreeing with FastF1, not reading the file better than it.
    Outside a session the recording is only the connection snapshot, whose
    lines carry no timestamp at all, and then there is no zero to find.
    """
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line.startswith("["):
                    continue
                try:
                    _category, _message, stamp = json.loads(_as_json(line))
                except (ValueError, TypeError):
                    continue
                if not stamp:
                    continue
                moment = pd.Timestamp(stamp)
                return moment.tz_localize(None) if moment.tzinfo else moment
    except OSError:
        return None
    return None


def _as_json(line: str) -> str:
    """FastF1's own repair of a recording line into JSON, so both read the same lines."""
    return line.replace("'", '"').replace("True", "true").replace("False", "false")


def tables_from_recording(path: Path, session: LiveSession,
                          telemetry: bool = False) -> dict[str, pd.DataFrame]:
    """Parse a recording into the lake's table shapes."""
    import fastf1
    from fastf1.exceptions import DataNotLoadedError
    from fastf1.livetiming.data import LiveTimingData

    _use_project_cache()

    if not path.exists() or path.stat().st_size == 0:
        raise NotRecording(f"{path} is empty; is the recorder running?")

    livedata = LiveTimingData(str(path))
    livedata.load()

    ses = fastf1.get_session(session.year, session.round_number, session.session_name)
    try:
        ses.load(laps=True, telemetry=telemetry, weather=True, messages=True, livedata=livedata)
        return fastf1_source.extract(ses, SESSION_KEY, telemetry=telemetry,
                                     t0=live_t0(livedata, path))
    except DataNotLoadedError as error:
        # The recorder is connected and the feed is arriving, but nobody has
        # completed a timed lap yet, so FastF1 has nothing to hand over. That is
        # the first ten minutes of every session, not a fault.
        raise NotRecording("no timed lap in the recording yet; the session has "
                           f"not produced one ({error})") from None


@dataclass
class Feed:
    """
    A recording, re-read when what it last gave back has gone stale.

    Held behind a lock because the API serves requests on several threads and
    two of them arriving together should cost one parse, not two.
    """
    path: Path
    session: LiveSession
    interval_s: float = REFRESH_INTERVAL_S
    telemetry: bool = False

    _tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    _read_at: float = 0.0
    _error: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def tables(self, force: bool = False) -> dict[str, pd.DataFrame]:
        with self._lock:
            stale = (time.monotonic() - self._read_at) >= self.interval_s
            if force or stale or not self._tables:
                self._refresh()
            if not self._tables and self._error:
                raise NotRecording(self._error)
            return self._tables

    def _refresh(self) -> None:
        started = time.monotonic()
        try:
            self._tables = tables_from_recording(self.path, self.session, self.telemetry)
            self._error = None
            log.info("re-read %s in %.1fs: %d laps", self.path.name,
                     time.monotonic() - started, len(self._tables.get("laps", [])))
        except NotRecording as error:
            self._error = str(error)
        except Exception as error:                       # a partial recording is normal early on
            self._error = f"{type(error).__name__}: {error}"
            log.warning("could not read %s: %s", self.path, error)
        finally:
            self._read_at = time.monotonic()

    def status(self) -> dict:
        """What the interface needs to say whether live is working."""
        size = self.path.stat().st_size if self.path.exists() else 0
        laps = self._tables.get("laps")
        return {
            "recording": str(self.path),
            "bytes": size,
            "session": {
                "year": self.session.year,
                "round": self.session.round_number,
                "name": self.session.session_name,
            },
            "laps": 0 if laps is None else len(laps),
            "last_read_ago_s": None if not self._read_at else round(time.monotonic() - self._read_at, 1),
            "error": self._error,
        }
