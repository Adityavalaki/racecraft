"""
Ingest F1 sessions from FastF1 into the Parquet lake.

    racecraft-ingest --season 2024 --rounds 1 --sessions R   # one race
    racecraft-ingest --season 2026 --sessions FP2 Q          # every completed FP2 and qualifying
    racecraft-ingest --season 2026 2025 --prune-cache        # every session type, bounded disk

Already-ingested sessions are skipped, so an interrupted backfill resumes by
running the same command again.

FastF1 allows 500 uncached requests per hour. A long backfill pauses when it
gets close and carries on by itself; leave it running rather than restarting.
"""

from __future__ import annotations

import argparse
import logging
import os
import shutil
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import DataNotLoadedError, NoLapDataError, RateLimitExceededError

from racecraft import config
from racecraft.ingest import api_budget, fastf1_source, quality
from racecraft.store import lake

log = logging.getLogger("racecraft.ingest")

# How long after a session starts its timing data can be expected. The session
# itself is at most two hours of that; the rest is the feed being published.
PUBLISH_DELAY = pd.Timedelta(hours=4)


def completed_sessions(season: int, rounds: list[int] | None,
                       sessions: tuple[str, ...]) -> list[tuple[int, str, str, str]]:
    """(round, lake session code, event name, FastF1 session name) for sessions that have already happened."""
    schedule = fastf1.get_event_schedule(season, include_testing=False)
    now = datetime.now(timezone.utc)
    out = []
    for _, ev in schedule.iterrows():
        rnd = int(ev["RoundNumber"])
        if rounds and rnd not in rounds:
            continue
        for i in range(1, 6):
            name = ev.get(f"Session{i}")
            date = ev.get(f"Session{i}DateUtc")
            ident = config.SESSION_CODES.get(name)
            if ident not in sessions or pd.isna(date):
                continue
            # Timing data is published a little after the session ends.
            if pd.Timestamp(date).tz_localize("UTC") + PUBLISH_DELAY > now:
                continue
            out.append((rnd, ident, ev["EventName"], name))
    return out


def waiting_for(season: int, rounds: list[int] | None,
                sessions: tuple[str, ...]) -> list[tuple[str, "pd.Timestamp"]]:
    """
    Sessions that have run or will run today but are not ingestable yet, and
    when they will be.

    Only so the watcher can say what it is waiting for rather than sitting
    silent: a session becomes ingestable `PUBLISH_DELAY` after it starts,
    because the timing data is published a little after it ends.
    """
    schedule = fastf1.get_event_schedule(season, include_testing=False)
    now = datetime.now(timezone.utc)
    out = []
    for _, ev in schedule.iterrows():
        rnd = int(ev["RoundNumber"])
        if rounds and rnd not in rounds:
            continue
        for i in range(1, 6):
            name = ev.get(f"Session{i}")
            date = ev.get(f"Session{i}DateUtc")
            ident = config.SESSION_CODES.get(name)
            if ident not in sessions or pd.isna(date):
                continue
            ready = pd.Timestamp(date).tz_localize("UTC") + PUBLISH_DELAY
            if ready > now and ready - now < pd.Timedelta(days=2):
                out.append((f"{ev['EventName']} {name}", ready))
    return sorted(out, key=lambda pair: pair[1])


def prune_cache(ses) -> tuple[int, int]:
    """
    Delete what FastF1 cached for one session: its parsed-data folder, and its
    raw responses in the shared HTTP cache (fastf1_http_cache.sqlite). Over a
    backfill the HTTP cache is the larger of the two, about 20 MB per session,
    and it grows without bound unless entries are removed. Returns (bytes freed
    from the folder, HTTP responses deleted). The SQLite file only shrinks once
    compacted; see compact_http_cache().
    """
    folder = config.FASTF1_CACHE_DIR / ses.api_path.removeprefix("/static/").strip("/")
    freed = 0
    if folder.is_dir():
        freed = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder)

    return freed, purge_http_cache({ses.api_path})


def purge_http_cache(api_paths: set[str]) -> int:
    """Delete cached HTTP responses belonging to any of these sessions. Returns responses deleted."""
    http = fastf1.Cache._requests_session_cached
    if http is None or not api_paths:
        return 0
    keys = [r.cache_key for r in http.cache.filter(valid=True, expired=True)
            if any(path in r.url for path in api_paths)]
    if keys:
        http.cache.delete(*keys, vacuum=False)  # compacting per session would rewrite the file every time
    return len(keys)


def compact_http_cache() -> float:
    """Drop expired responses and compact the HTTP cache file. Returns MB saved."""
    http = fastf1.Cache._requests_session_cached
    path = config.FASTF1_CACHE_DIR / "fastf1_http_cache.sqlite"
    if http is None or not path.exists():
        return 0.0
    before = path.stat().st_size
    http.cache.delete(expired=True, vacuum=False)
    http.cache.responses.vacuum()
    return (before - path.stat().st_size) / 1e6


def wait_for_api_budget(key: str) -> None:
    """Sleep until FastF1's hourly limiter can take a whole session's requests."""
    wait = api_budget.wait_needed()
    if not wait:
        return
    resume = datetime.now() + pd.Timedelta(seconds=wait)
    log.info("%s: FastF1 request limit nearly used (%d calls this hour); waiting %d min, resuming about %s",
             key, api_budget.calls_recorded(), round(wait / 60), resume.strftime("%H:%M"))
    time.sleep(wait)


# One session is written by one process at a time. The watcher and the
# interface's sync button can both reach for the same session, and two writers
# on the same Parquet files is the one way the lake gets corrupted. A lock older
# than this belongs to a process that died mid-write and is taken over.
SESSION_LOCK_STALE = timedelta(minutes=30)


def process_alive(pid: int) -> bool:
    """
    Whether a process is still running. Asked without touching it: on Windows
    `os.kill(pid, 0)` does not test a process, it terminates it.
    """
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        query_limited, still_active = 0x1000, 259
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(query_limited, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code))) \
                and code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def lock_owner_gone(path: Path) -> bool:
    """True when the process named in a lock file is no longer running."""
    try:
        return not process_alive(int(path.read_text(encoding="utf-8").strip() or 0))
    except (OSError, ValueError):
        return True                            # unreadable: nobody can be relying on it


def session_lock(key: str) -> Path | None:
    """
    The lock for one session, or None if another *running* process is writing it.

    A lock is honoured only while its owner is alive. Baku FP2 sat unfetched
    behind one left by a watcher that had been closed: the sync that came six
    minutes later saw a young lock and stood aside for a writer that no longer
    existed. The age limit remains for an owner that is alive but stuck.
    """
    path = config.DATA_DIR / "logs" / "locks" / f"{key}.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = time.time() - path.stat().st_mtime
            if age < SESSION_LOCK_STALE.total_seconds() and not lock_owner_gone(path):
                return None
            path.unlink(missing_ok=True)       # its writer died or stalled; take it over
            continue
        os.write(handle, str(os.getpid()).encode())
        os.close(handle)
        return path
    return None


def ingest_one(season: int, rnd: int, ident: str, session_name: str, *,
               telemetry: bool, force: bool, prune: bool) -> str:
    key = fastf1_source.make_session_key(season, rnd, ident)
    if lake.is_ingested(season, rnd, ident) and not force:
        return "skipped"
    lock = session_lock(key)
    if lock is None:
        log.info("%s: another process is writing it; leaving it alone", key)
        return "busy"
    try:
        # Checked again under the lock: the other writer may have just finished.
        if lake.is_ingested(season, rnd, ident) and not force:
            return "skipped"
        return _ingest_locked(season, rnd, ident, session_name, key,
                              telemetry=telemetry, force=force, prune=prune)
    finally:
        lock.unlink(missing_ok=True)


def _ingest_locked(season: int, rnd: int, ident: str, session_name: str, key: str, *,
                   telemetry: bool, force: bool, prune: bool) -> str:
    t, calls_before = time.time(), api_budget.calls_recorded()
    ses = fastf1_source.load_session(season, rnd, session_name, telemetry=telemetry)
    tables = fastf1_source.extract(ses, key, telemetry=telemetry)
    load_s, calls = time.time() - t, api_budget.calls_recorded() - calls_before

    findings = quality.check_session(tables)
    for f in findings:
        (log.error if f.severity == quality.ERROR else log.info)("%s %s", key, f)
    if quality.has_errors(findings):
        log.error("%s: not written, fix the errors above", key)
        return "failed"

    if force:
        lake.delete_session(season, rnd, ident)
    report = lake.write_session(tables, season, rnd, ident)
    total_mb = sum(r["bytes"] for r in report.values()) / 1e6
    rows = ", ".join(f"{name} {r['rows']:,}" for name, r in report.items())
    log.info("%s: wrote %.1f MB in %.0fs, %d API calls (%s)", key, total_mb, load_s, calls, rows)

    if prune:
        freed, responses = prune_cache(ses)
        log.info("%s: pruned %.0f MB of parsed cache and %d HTTP responses", key, freed / 1e6, responses)
    return "written"


def forget_session(season: int, session_name: str, rnd: int) -> int:
    """
    Throw away everything FastF1 has cached for one session, parsed and raw.

    A session read too early — mid-session, or before its data was published —
    leaves an empty parse in the cache, and FastF1 serves that forever after
    rather than asking again. Baku 2026 practice sat unfetched for two hours
    behind one. Returns the number of cached files and responses removed.
    """
    ses = fastf1.get_session(season, rnd, session_name)
    removed = purge_http_cache({ses.api_path})
    folder = config.FASTF1_CACHE_DIR / ses.api_path.strip("/").removeprefix("static/")
    if folder.is_dir():
        removed += sum(1 for _ in folder.rglob("*") if _.is_file())
        shutil.rmtree(folder, ignore_errors=True)
    return removed


# The errors a stale empty parse produces. The data exists on the server; what
# is in the cache is an answer from before it did.
STALE_CACHE_ERRORS = (DataNotLoadedError, NoLapDataError)


def ingest_with_limits(season: int, rnd: int, ident: str, session_name: str, **kwargs) -> str:
    """
    ingest_one, pausing for FastF1's rate limit instead of failing the session,
    and starting again from nothing if the cache has an empty parse in it.
    """
    key = fastf1_source.make_session_key(season, rnd, ident)
    cleared = False
    for attempt in range(1, 5):
        if kwargs["force"] or not lake.is_ingested(season, rnd, ident):
            wait_for_api_budget(key)
        try:
            return ingest_one(season, rnd, ident, session_name, **kwargs)
        except STALE_CACHE_ERRORS as e:
            if cleared:
                raise                      # asked again from nothing; the data really is not there
            removed = forget_session(season, session_name, rnd)
            log.warning("%s: %s — cleared %d cached items and trying once more from nothing",
                        key, type(e).__name__, removed)
            cleared = True
        except RateLimitExceededError as e:
            # Only reachable if the budget estimate was short or the limiter
            # can't be inspected. Responses already fetched are cached, so the
            # retry doesn't request them again.
            wait = api_budget.wait_needed() or api_budget.FALLBACK_WAIT_S
            log.warning("%s: %s (attempt %d); waiting %d min", key, e, attempt, round(wait / 60))
            time.sleep(wait)
    log.error("%s: still rate limited after 4 attempts, skipping", key)
    return "failed"


def setup_logging() -> Path:
    """
    Console: Racecraft progress, plus FastF1 errors. Log file: everything,
    including FastF1's per-session warnings ("Car data is incomplete!", "Fixed
    incorrect tyre stint information"). Those describe real gaps in the feed
    and are worth keeping, but at 20-40 lines per session they bury progress.

    FastF1 attaches its own console handler and also propagates to the root
    logger, which printed every warning twice. Its handler is removed so each
    message is emitted once, in one format.
    """
    log_dir = config.DATA_DIR / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"ingest-{datetime.now():%Y%m%d-%H%M%S}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", datefmt="%H:%M:%S")

    # Run windowless (pythonw, as the Startup launcher does) there is no
    # console to write to, and the log file is the whole record.
    console = logging.StreamHandler() if sys.stderr is not None else logging.NullHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(message)s", datefmt="%H:%M:%S"))
    console.addFilter(lambda r: r.name.startswith("racecraft") or r.levelno >= logging.ERROR)
    file = logging.FileHandler(log_file, encoding="utf-8")
    file.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.handlers[:] = [console, file]

    ff1 = logging.getLogger("fastf1")
    ff1.handlers.clear()
    ff1.setLevel(logging.WARNING)
    ff1.propagate = True
    return log_file


def run_once(args) -> dict[str, int]:
    """One pass: ingest every completed session that is not in the lake yet."""
    plan = []
    for season in args.season:
        todo = completed_sessions(season, args.rounds, tuple(args.sessions))
        done = sum(lake.is_ingested(season, rnd, ident) for rnd, ident, _, _ in todo)
        log.info("%d: %d completed sessions, %d already in the lake", season, len(todo), done)
        plan += [(season, rnd, ident, event, name) for rnd, ident, event, name in todo]

    if args.prune_cache and not args.force:
        # Earlier runs may have left raw responses for sessions that are already
        # safely in the lake. Clear them in one pass before starting.
        in_lake = {fastf1.get_session(season, rnd, name).api_path
                   for season, rnd, ident, _, name in plan if lake.is_ingested(season, rnd, ident)}
        if in_lake:
            log.info("clearing cached HTTP responses for %d sessions already in the lake", len(in_lake))
            log.info("removed %d responses", purge_http_cache(in_lake))

    counts = {"written": 0, "skipped": 0, "busy": 0, "failed": 0}
    for season, rnd, ident, event, name in plan:
        try:
            status = ingest_with_limits(season, rnd, ident, name, telemetry=not args.no_telemetry,
                                        force=args.force, prune=args.prune_cache)
        except Exception as e:  # one broken session must not stop a season backfill
            log.error("%s round %d %s (%s) failed: %s: %s", season, rnd, ident, event,
                      type(e).__name__, e, exc_info=args.verbose)
            status = "failed"
        counts[status] += 1
        if status == "written" and ident == "R" and not args.no_brief:
            brief(season, rnd, event)

    if args.prune_cache:
        log.info("compacted HTTP cache, %.0f MB freed", compact_http_cache())
    return counts


def brief(season: int, rnd: int, event: str) -> None:
    """
    What the models make of a race, logged the moment it lands.

    The point of ingesting straight after a session is to have the answer
    waiting rather than to have the data waiting, so this fits the race's own
    inputs — held out, as ever — and says what it found. It also warms the
    caches the interface reads, so the page opens on an answer.
    """
    from racecraft.model import race_inputs
    from racecraft.store.db import connect

    try:
        con = connect()
        key = fastf1_source.make_session_key(season, rnd, "R")
        rows = con.sql(f"select location from sessions where session_key = '{key}'").df()
        if rows.empty:
            return
        inputs = race_inputs.build(con, str(rows.iloc[0]["location"]), season, session_key=key)
        log.info("%s: %d laps, pit lane %.1fs, %.2f safety cars a race, tyres from %d races",
                 event, inputs.total_laps, inputs.pit_loss_s, inputs.periods_per_race,
                 len(inputs.fitted_on))
        log.info("%s: wear %s s/lap", event,
                 ", ".join(f"{c.lower()} {v:.3f}" for c, v in inputs.degradation.items()))
        for note in inputs.notes:
            log.info("%s: note: %s", event, note)
    except Exception as error:                      # a brief is a bonus, not the job
        log.info("%s: no brief (%s: %s)", event, type(error).__name__, error)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, nargs="+", default=list(config.DEFAULT_SEASONS))
    ap.add_argument("--rounds", type=int, nargs="+", help="round numbers; default is every completed round")
    ap.add_argument("--sessions", nargs="+", default=list(config.ALL_SESSIONS), choices=config.ALL_SESSIONS,
                    help="session codes to ingest; default is all of them")
    ap.add_argument("--no-telemetry", action="store_true", help="skip car and position data (much faster)")
    ap.add_argument("--force", action="store_true", help="re-ingest sessions already in the lake")
    ap.add_argument("--prune-cache", action="store_true", help="delete each session's FastF1 cache after writing")
    ap.add_argument("--verbose", action="store_true", help="print full tracebacks for failed sessions")
    ap.add_argument("--watch", action="store_true",
                    help="keep running and ingest each session as it becomes available")
    ap.add_argument("--every", type=int, default=15, metavar="MINUTES",
                    help="how often to look, in watch mode (default 15)")
    ap.add_argument("--no-brief", action="store_true",
                    help="skip the summary logged after a race is ingested")
    args = ap.parse_args(argv)

    log_file = setup_logging()

    config.FASTF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(config.FASTF1_CACHE_DIR))

    if args.watch:
        return watch(args, log_file)

    counts = run_once(args)
    hint = " (re-run with --verbose for tracebacks)" if counts["failed"] and not args.verbose else ""
    log.info("done: %d written, %d skipped, %d failed%s", counts["written"], counts["skipped"], counts["failed"], hint)
    log.info("lake size: %.1f MB at %s", lake.lake_size_bytes() / 1e6, config.LAKE_DIR)
    log.info("full log, including FastF1 feed warnings: %s", log_file)
    return 1 if counts["failed"] else 0


# A watcher writes into the lake, and two of them ingesting the same session
# would race each other over the same Parquet files. The lock is a file whose
# timestamp is refreshed each pass, so a watcher killed without cleaning up
# hands over after a few quiet minutes rather than blocking the next one for
# good.
LOCK_STALE_AFTER = timedelta(minutes=90)


def take_lock(path: Path) -> bool:
    """True if this process may watch; False if another one already is."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        age = datetime.now(timezone.utc).timestamp() - path.stat().st_mtime
        if age < LOCK_STALE_AFTER.total_seconds() and not lock_owner_gone(path):
            return False
        log.info("taking over a lock left behind %.0f minutes ago by a watcher "
                 "that is no longer running", age / 60)
    path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def watch(args, log_file) -> int:
    """
    Keep the lake up to date by itself: look every few minutes, ingest whatever
    has become available, say what it is waiting for, and sleep again.

    A session becomes available a few hours after it starts, because the timing
    data is published after it ends, so there is nothing to gain from looking
    often and nothing to lose from looking at all — a pass with nothing to do
    costs one schedule request.
    """
    lock = config.LOG_DIR / "watch.lock" if hasattr(config, "LOG_DIR") else \
        config.LAKE_DIR.parent / "logs" / "watch.lock"
    if not take_lock(lock):
        log.info("another watcher is already running (%s); nothing to do here", lock)
        return 0

    log.info("watching %s every %d minutes; Ctrl+C to stop",
             ", ".join(str(season) for season in args.season), args.every)
    try:
        while True:
            lock.write_text(str(os.getpid()), encoding="utf-8")   # still alive
            counts = run_once(args)
            if counts["written"] or counts["failed"]:
                log.info("this pass: %d written, %d failed. Lake %.1f MB",
                         counts["written"], counts["failed"], lake.lake_size_bytes() / 1e6)
            for season in args.season:
                for name, ready in waiting_for(season, args.rounds, tuple(args.sessions))[:3]:
                    log.info("waiting for %s, ready %s UTC", name, ready.strftime("%a %d %b %H:%M"))
            time.sleep(args.every * 60)
    except KeyboardInterrupt:
        log.info("stopped watching; the lake is at %.1f MB", lake.lake_size_bytes() / 1e6)
        log.info("full log: %s", log_file)
        return 0
    finally:
        lock.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
