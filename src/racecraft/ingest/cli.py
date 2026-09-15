"""
Ingest F1 sessions from FastF1 into the Parquet lake.

    racecraft-ingest --season 2024 --rounds 1              # one race
    racecraft-ingest --season 2024                         # every completed race + sprint
    racecraft-ingest --season 2023 2024 2025 --prune-cache # full backfill, bounded disk

Already-ingested sessions are skipped, so an interrupted backfill resumes by
running the same command again.

FastF1 allows 500 uncached requests per hour. A long backfill pauses when it
gets close and carries on by itself; leave it running rather than restarting.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import fastf1
import pandas as pd
from fastf1.exceptions import RateLimitExceededError

from racecraft import config
from racecraft.ingest import api_budget, fastf1_source, quality
from racecraft.store import lake

log = logging.getLogger("racecraft.ingest")


def completed_sessions(season: int, rounds: list[int] | None, sessions: tuple[str, ...]) -> list[tuple[int, str, str]]:
    """(round, session identifier, event name) for sessions that have already happened."""
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
            ident = {"Race": "R", "Sprint": "S"}.get(name)
            if ident not in sessions or pd.isna(date):
                continue
            # Timing data is published a little after the chequered flag.
            if pd.Timestamp(date).tz_localize("UTC") + pd.Timedelta(hours=4) > now:
                continue
            out.append((rnd, ident, ev["EventName"]))
    return out


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


def ingest_one(season: int, rnd: int, ident: str, *, telemetry: bool, force: bool, prune: bool) -> str:
    key = fastf1_source.make_session_key(season, rnd, ident)
    if lake.is_ingested(season, rnd, ident) and not force:
        return "skipped"

    t, calls_before = time.time(), api_budget.calls_recorded()
    ses = fastf1_source.load_session(season, rnd, ident, telemetry=telemetry)
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


def ingest_with_limits(season: int, rnd: int, ident: str, **kwargs) -> str:
    """ingest_one, pausing for FastF1's rate limit instead of failing the session."""
    key = fastf1_source.make_session_key(season, rnd, ident)
    for attempt in range(1, 5):
        if kwargs["force"] or not lake.is_ingested(season, rnd, ident):
            wait_for_api_budget(key)
        try:
            return ingest_one(season, rnd, ident, **kwargs)
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

    console = logging.StreamHandler()
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--season", type=int, nargs="+", default=list(config.DEFAULT_SEASONS))
    ap.add_argument("--rounds", type=int, nargs="+", help="round numbers; default is every completed round")
    ap.add_argument("--sessions", nargs="+", default=list(config.RACE_SESSIONS), choices=["R", "S"])
    ap.add_argument("--no-telemetry", action="store_true", help="skip car and position data (much faster)")
    ap.add_argument("--force", action="store_true", help="re-ingest sessions already in the lake")
    ap.add_argument("--prune-cache", action="store_true", help="delete each session's FastF1 cache after writing")
    ap.add_argument("--verbose", action="store_true", help="print full tracebacks for failed sessions")
    args = ap.parse_args(argv)

    log_file = setup_logging()

    config.FASTF1_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(config.FASTF1_CACHE_DIR))

    plan = []
    for season in args.season:
        todo = completed_sessions(season, args.rounds, tuple(args.sessions))
        done = sum(lake.is_ingested(season, rnd, ident) for rnd, ident, _ in todo)
        log.info("%d: %d completed sessions, %d already in the lake", season, len(todo), done)
        plan += [(season, rnd, ident, name) for rnd, ident, name in todo]

    if args.prune_cache and not args.force:
        # Earlier runs may have left raw responses for sessions that are already
        # safely in the lake. Clear them in one pass before starting.
        in_lake = {fastf1.get_session(season, rnd, ident).api_path
                   for season, rnd, ident, _ in plan if lake.is_ingested(season, rnd, ident)}
        if in_lake:
            log.info("clearing cached HTTP responses for %d sessions already in the lake", len(in_lake))
            log.info("removed %d responses", purge_http_cache(in_lake))

    counts = {"written": 0, "skipped": 0, "failed": 0}
    for season, rnd, ident, name in plan:
        try:
            status = ingest_with_limits(season, rnd, ident, telemetry=not args.no_telemetry,
                                        force=args.force, prune=args.prune_cache)
        except Exception as e:  # one broken session must not stop a season backfill
            log.error("%s round %d %s (%s) failed: %s: %s", season, rnd, ident, name,
                      type(e).__name__, e, exc_info=args.verbose)
            status = "failed"
        counts[status] += 1

    if args.prune_cache:
        log.info("compacted HTTP cache, %.0f MB freed", compact_http_cache())
    hint = " (re-run with --verbose for tracebacks)" if counts["failed"] and not args.verbose else ""
    log.info("done: %d written, %d skipped, %d failed%s", counts["written"], counts["skipped"], counts["failed"], hint)
    log.info("lake size: %.1f MB at %s", lake.lake_size_bytes() / 1e6, config.LAKE_DIR)
    log.info("full log, including FastF1 feed warnings: %s", log_file)
    return 1 if counts["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
