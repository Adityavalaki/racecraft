"""
Fetching new races from inside the running application.

The alternative was a scheduled job, and this is better for a deployment where
nobody is watching logs: a button reports what it is doing on the page, and a
failure is visible the moment it happens rather than the next time someone
thinks to look.

Three things shape how it works.

*It runs in the background and reports progress.* Ingesting a race weekend takes
minutes — FastF1 allows 500 requests an hour and ingest waits rather than
tripping the limit — so the request that starts it returns immediately and the
interface polls. Holding a connection open for ten minutes would be lost to the
first proxy timeout.

*It is one at a time.* Two ingests running together would race for the same
rate-limit budget and write the same partitions, so a second start while one is
running is refused rather than queued.

*It never fetches telemetry.* A deployed lake carries none: it is 98.5% of the
bytes and feeds only the track map. Skipping it makes ingest several times
faster and keeps the lake small enough to store where the application lives.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from racecraft import config
from racecraft.store import lake

log = logging.getLogger(__name__)

# A deployed lake has no telemetry, so neither does anything added to it.
TELEMETRY = False
MAX_LOG_LINES = 200


@dataclass
class Progress:
    """What an ingest is doing, in the shape the interface renders."""
    running: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    season: int | None = None
    total: int = 0
    done: int = 0
    written: int = 0
    skipped: int = 0
    failed: int = 0
    current: str | None = None
    error: str | None = None
    log: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        out = self.__dict__.copy()
        out["log"] = list(self.log[-MAX_LOG_LINES:])
        return out


class Busy(RuntimeError):
    """An ingest is already running."""


class IngestJob:
    """One ingest at a time, run off the request thread."""

    def __init__(self) -> None:
        self._progress = Progress()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self) -> dict:
        with self._lock:
            progress = self._progress.as_dict()
        progress["running"] = self.running
        progress["lake_bytes"] = lake.lake_size_bytes()
        return progress

    def start(self, season: int | None = None, on_finish=None) -> dict:
        with self._lock:
            if self.running:
                raise Busy("an ingest is already running")
            season = season or max(config.DEFAULT_SEASONS)
            self._progress = Progress(running=True, season=season,
                                      started_at=_now(), current="looking for new sessions")
            self._thread = threading.Thread(target=self._run, args=(season, on_finish), daemon=True)
            self._thread.start()
        return self.status()

    # ---------------------------------------------------------------- work

    def _say(self, message: str) -> None:
        log.info("ingest: %s", message)
        with self._lock:
            self._progress.log.append(f"{_now()}  {message}")
            del self._progress.log[:-MAX_LOG_LINES]

    def _run(self, season: int, on_finish) -> None:
        # Imported here rather than at module load: ingest pulls in FastF1,
        # which is slow to import and not needed to serve a page.
        from racecraft.ingest import cli as ingest_cli

        try:
            sessions = ingest_cli.completed_sessions(season, None, tuple(config.ALL_SESSIONS))
            missing = [s for s in sessions if not lake.is_ingested(season, s[0], s[1])]
            with self._lock:
                self._progress.total = len(missing)
            if not missing:
                self._say(f"nothing new in {season}: all {len(sessions)} sessions are already here")
                return

            self._say(f"{len(missing)} new session{'s' if len(missing) != 1 else ''} in {season}")
            for rnd, ident, event, session_name in missing:
                label = f"{event} {ident}"
                with self._lock:
                    self._progress.current = label
                try:
                    result = ingest_cli.ingest_with_limits(
                        season, rnd, ident, session_name,
                        telemetry=TELEMETRY, force=False, prune_cache=True, verbose=False)
                except Exception as error:                     # one session must not stop the rest
                    result = "failed"
                    self._say(f"{label}: {type(error).__name__}: {error}")
                with self._lock:
                    self._progress.done += 1
                    setattr(self._progress, _counter(result),
                            getattr(self._progress, _counter(result)) + 1)
                if result != "failed":
                    self._say(f"{label}: {result}")

            with self._lock:
                p = self._progress
                summary = f"done: {p.written} written, {p.skipped} skipped, {p.failed} failed"
            self._say(summary)

            if on_finish is not None and self._progress.written:
                try:
                    on_finish(self._progress.written)
                except Exception as error:
                    self._say(f"could not save the lake: {type(error).__name__}: {error}")
        except Exception as error:
            log.exception("ingest failed")
            with self._lock:
                self._progress.error = f"{type(error).__name__}: {error}"
            self._say(f"failed: {error}")
        finally:
            with self._lock:
                self._progress.running = False
                self._progress.finished_at = _now()
                self._progress.current = None


def _counter(result: str) -> str:
    return {"written": "written", "skipped": "skipped"}.get(result, "failed")


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


job = IngestJob()
