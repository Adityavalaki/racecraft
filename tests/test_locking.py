"""
The one lock every writer and the desktop app share.

What went wrong with pid files is what is pinned here: two callers arriving
together both won, and a crashed owner either blocked the next one or was
guessed dead while alive. The OS decides now, so these tests race real handles
and kill real processes.
"""

import threading

from conftest import hold_lock_elsewhere, kill, soon
from racecraft import locking


def test_callers_arriving_together_get_exactly_one_winner(tmp_path):
    path = tmp_path / "locks" / "race.lock"
    callers = 8
    barrier = threading.Barrier(callers)
    results = [None] * callers

    def take(i):
        barrier.wait()
        results[i] = locking.acquire(path, f"caller {i}")

    threads = [threading.Thread(target=take, args=(i,)) for i in range(callers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    winners = [r for r in results if r is not None]
    try:
        assert len(winners) == 1, f"{len(winners)} callers hold one lock"
        assert path.read_text() == f"caller {results.index(winners[0])}"
    finally:
        for w in winners:
            w.release()


def test_a_lock_held_by_another_process_is_refused(tmp_path):
    path = tmp_path / "held.lock"
    holder = hold_lock_elsewhere(path)
    try:
        assert locking.acquire(path) is None
    finally:
        kill(holder)


def test_a_killed_holder_lets_go_at_once(tmp_path):
    path = tmp_path / "held.lock"
    holder = hold_lock_elsewhere(path)
    kill(holder)
    lock = soon(lambda: locking.acquire(path))
    assert lock is not None, "a crashed owner still blocks the lock"
    lock.release()
    assert path.exists(), "the lock file is never deleted"


def test_the_holders_text_is_readable_from_another_process(tmp_path):
    """On Windows the lock covers a byte far past the text, not the text itself."""
    path = tmp_path / "held.lock"
    holder = hold_lock_elsewhere(path, '{"pid": {pid}, "port": 50000}')
    try:
        assert path.read_text() == f'{{"pid": {holder.holder_pid}, "port": 50000}}'
    finally:
        kill(holder)


def test_shorter_text_replaces_longer_while_the_lock_is_held(tmp_path):
    path = tmp_path / "held.lock"
    lock = locking.acquire(path, "x" * 200)
    try:
        lock.write("short")
        assert path.read_text() == "short"
        assert locking.acquire(path) is None
    finally:
        lock.release()


def test_releasing_twice_does_not_touch_the_next_owner(tmp_path):
    path = tmp_path / "held.lock"
    old = locking.acquire(path, "old")
    old.release()
    new = locking.acquire(path, "new")
    assert new is not None
    try:
        old.release()                          # late, repeated, and harmless
        assert locking.acquire(path) is None, "the old owner's release freed the new owner's lock"
        assert path.read_text() == "new"
    finally:
        new.release()


def test_a_released_lock_leaves_no_owner_text(tmp_path):
    path = tmp_path / "held.lock"
    with locking.acquire(path, "me") as lock:
        assert lock.held
    assert not lock.held
    assert path.read_text() == ""
    again = locking.acquire(path)
    assert again is not None
    again.release()
