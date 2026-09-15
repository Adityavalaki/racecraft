"""
Stay inside FastF1's request limits instead of tripping them.

FastF1 allows 500 uncached requests per hour to the F1 servers (200 to
Ergast) and raises RateLimitExceededError past that. Two details of its
limiter shape everything here:

* It is per process. Restarting the command resets the count, but the
  limit exists because F1's servers need it, and FastF1 warns that
  exceeding it can get users blocked. So a long backfill waits; it does
  not restart its way around the limit.
* A rejected request still records a timestamp. Retrying in a tight loop
  extends the lockout, which is exactly what a failing backfill does.

So before each session, work out how long until the limiter will accept
a full session's worth of requests, and sleep that long first. The
limiter's internals are private to FastF1; if they change, this degrades
to a fixed wait rather than breaking ingest.
"""

from __future__ import annotations

import time
from collections import deque

# Uncached requests one session load makes, with headroom. Measured at 13-15
# per race or sprint with telemetry, across 40 sessions from 2024-2025.
CALLS_PER_SESSION = 30
FALLBACK_WAIT_S = 15 * 60
SAFETY_MARGIN_S = 5.0


def _hourly_limiters() -> list:
    try:
        from fastf1.req import _SessionWithRateLimiting
        limiters = [lim for group in _SessionWithRateLimiting._RATE_LIMITS.values() for lim in group]
    except (ImportError, AttributeError):
        return []
    return [lim for lim in limiters
            if isinstance(getattr(lim, "_timestamps", None), deque) and hasattr(lim, "_interval")]


def seconds_until_available(timestamps: deque, interval: float, needed: int, now: float) -> float:
    """
    Seconds until `needed` more calls fit in a sliding window that holds at
    most `timestamps.maxlen` calls per `interval`.

    Once the window is full, each new call evicts the oldest timestamp and the
    limiter raises if the new oldest is still inside the interval. Making
    `needed` calls therefore requires the stored timestamp at index
    (len + needed - maxlen) to have aged out.
    """
    cap = timestamps.maxlen
    needed = min(needed, cap - 1)
    idx = len(timestamps) + needed - cap
    if idx < 0:
        return 0.0
    ordered = sorted(timestamps)  # appended in time order already; sort defends against clock jumps
    return max(0.0, ordered[idx] + interval - now + SAFETY_MARGIN_S)


def wait_needed(needed: int = CALLS_PER_SESSION) -> float | None:
    """Seconds to wait before starting a session, or None if the limiter can't be inspected."""
    limiters = _hourly_limiters()
    if not limiters:
        return None
    now = time.time()
    return max(seconds_until_available(lim._timestamps, lim._interval, needed, now) for lim in limiters)


def calls_recorded() -> int:
    """Uncached requests in the general limiter's window (capped at its maximum)."""
    limiters = _hourly_limiters()
    return max((len(lim._timestamps) for lim in limiters), default=0)
