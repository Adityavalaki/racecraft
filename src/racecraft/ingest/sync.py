"""
Bring the latest race weekends into the lake, on request.

The watcher (`racecraft-ingest --watch`) keeps the lake current by itself, but
only while it is running. This is the same work behind a button: look at the
most recent race weekends on the calendar, find every session whose data has
been published, check which of them the lake already has, and ingest the rest.

"Latest" means weekends, not races. A weekend in progress counts from its first
published session, so on a Saturday morning the sync brings in that weekend's
practice and qualifying as well as the four weekends before it — which is what
the tyre sets, the held-out inputs and the simulator all need.

It runs in the background, one job at a time, and reports progress per
session. Ingesting a session with telemetry takes about a minute, so a sync
that has to fill a whole weekend takes a few; one with nothing to do takes a
second.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

import fastf1
import pandas as pd

from racecraft import config
from racecraft.ingest import cli
from racecraft.store import lake

log = logging.getLogger("racecraft.sync")

DEFAULT_WEEKENDS = 5


@dataclass
class Item:
    """One session the sync looked at."""
    season: int
    round: int
    ident: str                        # FP1, Q, R, ...
    event: str
    name: str                         # FastF1's session name
    state: str = "pending"            # pending, ingesting, written, present, failed
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.season}_{self.round:02d}_{self.ident}"


@dataclass
class Job:
    state: str = "idle"               # idle, planning, running, done, failed
    weekends: list[str] = field(default_factory=list)
    items: list[Item] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        counts = {state: sum(1 for item in self.items if item.state == state)
                  for state in ("pending", "ingesting", "written", "present", "failed")}
        current = next((item for item in self.items if item.state == "ingesting"), None)
        return {
            "state": self.state,
            "weekends": self.weekends,
            "items": [asdict(item) | {"key": item.key} for item in self.items],
            "counts": counts,
            "to_fetch": sum(1 for item in self.items if item.state != "present"),
            "current": None if current is None else f"{current.event} {current.name}",
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error": self.error,
        }


def plan(weekends: int = DEFAULT_WEEKENDS, now: datetime | None = None) -> tuple[list[str], list[Item]]:
    """
    The latest `weekends` race weekends with anything published, and every
    published session in them, oldest first so the lake fills in order.

    Looks back into last season when this one has not had enough weekends yet.
    """
    now = now or datetime.now(timezone.utc)
    found: list[tuple[pd.Timestamp, int, int, str, list[Item]]] = []
    for season in (now.year, now.year - 1):
        schedule = fastf1.get_event_schedule(season, include_testing=False)
        for _, event in schedule.iterrows():
            ready: list[Item] = []
            latest = None
            for index in range(1, 6):
                name = event.get(f"Session{index}")
                start = event.get(f"Session{index}DateUtc")
                ident = config.SESSION_CODES.get(name)
                if ident is None or pd.isna(start):
                    continue
                published = pd.Timestamp(start).tz_localize("UTC") + cli.PUBLISH_DELAY
                if published > now:
                    continue
                ready.append(Item(season, int(event["RoundNumber"]), ident,
                                  str(event["EventName"]), str(name)))
                latest = published if latest is None else max(latest, published)
            if ready:
                found.append((latest, season, int(event["RoundNumber"]), str(event["EventName"]), ready))
        if len(found) >= weekends:
            break

    found.sort(key=lambda entry: entry[0], reverse=True)
    chosen = sorted(found[:weekends], key=lambda entry: entry[0])
    names = [f"{season} {event}" for _, season, _, event, _ in chosen]
    items = [item for *_, ready in chosen for item in ready]
    return names, items


class Syncer:
    """One sync at a time, in a background thread, with its progress readable."""

    def __init__(self, on_written=None) -> None:
        self._lock = threading.Lock()
        self._job = Job()
        self._thread: threading.Thread | None = None
        # Called once after a sync that wrote anything, so whatever has cached
        # the lake can let go of it. The API uses this to drop its model fits.
        self._on_written = on_written

    def status(self) -> dict:
        with self._lock:
            return self._job.as_dict()

    def start(self, weekends: int = DEFAULT_WEEKENDS, telemetry: bool = True) -> dict:
        """Begin a sync, or report the one already running."""
        with self._lock:
            if self._job.state in ("planning", "running"):
                return self._job.as_dict()
            self._job = Job(state="planning",
                            started_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            self._thread = threading.Thread(target=self._run, args=(weekends, telemetry),
                                            name="racecraft-sync", daemon=True)
            self._thread.start()
            return self._job.as_dict()

    def wait(self, timeout: float | None = None) -> None:
        """For tests and the command line: block until the running sync ends."""
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    # ------------------------------------------------------------ the work

    def _run(self, weekends: int, telemetry: bool) -> None:
        wrote = 0
        try:
            config.FASTF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            fastf1.Cache.enable_cache(str(config.FASTF1_CACHE_DIR))
            names, items = plan(weekends)
            for item in items:
                if lake.is_ingested(item.season, item.round, item.ident):
                    item.state = "present"
            with self._lock:
                self._job.weekends, self._job.items, self._job.state = names, items, "running"
            log.info("sync: %d weekends, %d sessions, %d to fetch", len(names), len(items),
                     sum(1 for item in items if item.state != "present"))

            for item in items:
                if item.state == "present":
                    continue
                with self._lock:
                    item.state = "ingesting"
                try:
                    result = cli.ingest_with_limits(item.season, item.round, item.ident, item.name,
                                                    telemetry=telemetry, force=False, prune=False)
                except Exception as error:          # one session must not stop the rest
                    result, detail = "failed", f"{type(error).__name__}: {error}"
                else:
                    detail = ""
                with self._lock:
                    # "skipped" here means another process wrote it meanwhile.
                    item.state = {"written": "written", "skipped": "present"}.get(result, "failed")
                    item.detail = detail or ("" if item.state != "failed" else "ingest failed")
                wrote += item.state == "written"

            with self._lock:
                self._job.state = "done"
        except Exception as error:
            log.exception("sync failed")
            with self._lock:
                self._job.state, self._job.error = "failed", f"{type(error).__name__}: {error}"
        finally:
            with self._lock:
                self._job.finished_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            if wrote and self._on_written is not None:
                try:
                    self._on_written()
                except Exception:                   # a stale cache is not worth a crash
                    log.exception("sync: could not refresh cached models")
