"""
One Racecraft at a time.

A second double-click on the icon must not start a second server and a second
sync — two syncs are the one way the lake gets two writers. So the first app
holds an OS lock (`racecraft.locking`) for as long as it runs, with its process
and port written in the lock file; a later launch fails to take the lock, reads
the port, asks the running app to bring its window to the front, and exits.

The lock is the OS's, so it goes when the app does, even one that crashed. The
text in the file is only for finding the running app: it counts while the
process named in it is alive (`ingest.cli.process_alive`), and taking the lock
is what decides who runs.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from pathlib import Path

from racecraft import config, locking
from racecraft.ingest.cli import process_alive

log = logging.getLogger(__name__)


def lock_path() -> Path:
    return config.DATA_DIR / "logs" / "app.lock"


def _read(path: Path) -> tuple[int, int] | None:
    """(pid, port) from the lock file, or None if it is empty, partial or unreadable."""
    try:
        held = json.loads(path.read_text(encoding="utf-8"))
        return int(held["pid"]), int(held["port"])
    except (OSError, ValueError, TypeError, KeyError):
        return None


def running(path: Path | None = None) -> tuple[int, int] | None:
    """(pid, port) of a Racecraft that is running now, or None."""
    held = _read(path or lock_path())
    if not held or not held[1] or not process_alive(held[0]):
        return None
    return held


def running_port(path: Path | None = None) -> int | None:
    """The port of a Racecraft that is running now, or None."""
    held = running(path)
    return held[1] if held else None


def claim(port: int, path: Path | None = None) -> locking.FileLock | None:
    """
    Take the lock for this process, or return None if another app holds it.

    The OS decides, so two launches at the same instant cannot both win. The
    returned lock is held until `release`.
    """
    body = json.dumps({"pid": os.getpid(), "port": port})
    return locking.acquire(path or lock_path(), body)


# Windows frees a dead process's lock a moment after the process has exited:
# up to about a second, measured. A lock that is refused while nobody is
# running is that moment after a crash, not another app.
SETTLE_S = 2.0


def claim_when_free(port: int, path: Path | None = None,
                    settle_s: float = SETTLE_S) -> locking.FileLock | None:
    """
    `claim`, but give a crashed app's lock the moment Windows takes to free it.

    Retries only while the lock is refused and no running app is found, so a
    launch with Racecraft already open still hands over at once.
    """
    path = path or lock_path()
    lock = claim(port, path)
    deadline = time.monotonic() + settle_s
    while lock is None and running(path) is None and time.monotonic() < deadline:
        time.sleep(0.1)
        lock = claim(port, path)
    return lock


def release(lock: locking.FileLock | None) -> None:
    """Give the lock up. Safe to call more than once."""
    if lock is not None:
        lock.release()


def allow_focus(pid: int) -> None:
    """
    Let the running app take the foreground.

    Windows refuses focus to a background process unless the process the user
    just started hands it on; without this the window only flashes in the
    taskbar. Best effort, and a no-op off Windows.
    """
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(int(pid))
    except Exception:
        pass


def ask_to_focus(port: int, timeout: float = 3.0, pid: int | None = None) -> bool:
    """Ask the running app to bring its window to the front."""
    if pid is not None:
        allow_focus(pid)
    request = urllib.request.Request(f"http://127.0.0.1:{port}/api/app/focus", method="POST", data=b"")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status == 200
    except OSError as error:
        log.info("the running app did not answer a focus request: %s", error)
        return False
