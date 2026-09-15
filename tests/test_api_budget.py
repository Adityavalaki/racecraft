from collections import deque

from racecraft.ingest.api_budget import SAFETY_MARGIN_S, seconds_until_available

HOUR = 3600.0


def window(times, cap=500):
    return deque(times, maxlen=cap)


def test_no_wait_while_the_window_has_room():
    ts = window([1000.0 + i for i in range(400)])
    assert seconds_until_available(ts, HOUR, needed=60, now=2000.0) == 0.0


def test_full_window_waits_for_enough_old_calls_to_expire():
    # 500 calls, one per second from t=0. Each new call evicts the oldest before
    # the check, so the 60th new call is checked against the stored call at
    # index 60 (t=60), which must be over an hour old.
    ts = window([float(i) for i in range(500)])
    wait = seconds_until_available(ts, HOUR, needed=60, now=600.0)
    assert wait == 60.0 + HOUR - 600.0 + SAFETY_MARGIN_S


def test_partly_full_window_only_counts_the_overflow():
    # 480 stored, 60 needed: the first 20 fill the window, the last is checked
    # against the stored call at index 40.
    ts = window([float(i) for i in range(480)])
    wait = seconds_until_available(ts, HOUR, needed=60, now=600.0)
    assert wait == 40.0 + HOUR - 600.0 + SAFETY_MARGIN_S


def test_no_wait_once_old_calls_have_aged_out():
    ts = window([float(i) for i in range(500)])
    assert seconds_until_available(ts, HOUR, needed=60, now=HOUR + 100.0) == 0.0


def test_matches_fastf1s_own_limiter():
    """Simulate FastF1's limiter: after waiting the computed time, `needed` calls must not raise."""
    cap, needed, now = 500, 60, 0.0
    ts = window([], cap)
    for _ in range(cap):  # a burst that fills the window
        ts.append(now)
        now += 0.25
    now += seconds_until_available(ts, HOUR, needed, now)
    for _ in range(needed):
        ts.append(now)  # FastF1 appends before checking
        assert not (len(ts) == cap and ts[0] > now - HOUR), "limiter would have raised"
        now += 0.25
