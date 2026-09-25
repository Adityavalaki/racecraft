"""
One Racecraft at a time.

A second double-click on the icon must not start a second server and a second
sync — two syncs are the one way the lake gets two writers. So the first app
writes a lock naming its process and its port; a later launch finds it, asks the
running app to bring its window to the front, and exits.

A lock counts only while the process named in it is alive, checked the same way
the ingest locks are (`ingest.cli.process_alive`). An app that crashed does not
stand in the way of the next one.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from pathlib import Path

from racecraft import config
from racecraft.ingest.cli import process_alive

log = logging.getLogger(__name__)


def lock_path() -> Path:
    return config.DATA_DIR / "logs" / "app.lock"


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def running(path: Path | None = None) -> tuple[int, int] | None:
    """(pid, port) of a Racecraft that is running now, or None."""
    held = _read(path or lock_path())
    if not held or not process_alive(int(held.get("pid", 0))):
        return None
    port = int(held.get("port", 0))
    return (int(held["pid"]), port) if port else None


def running_port(path: Path | None = None) -> int | None:
    """The port of a Racecraft that is running now, or None."""
    held = running(path)
    return held[1] if held else None


def claim(port: int, path: Path | None = None) -> bool:
    """
    Take the lock for this process, or return False if a live app holds it.

    Created exclusively, so two launches at the same instant cannot both win.
    """
    path = path or lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps({"pid": os.getpid(), "port": port}).encode()
    for _ in range(2):
        try:
            handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            held = _read(path)
            if held and process_alive(int(held.get("pid", 0))):
                return False
            path.unlink(missing_ok=True)       # left by an app that is no longer running
            continue
        os.write(handle, body)
        os.close(handle)
        return True
    return False


def release(path: Path | None = None) -> None:
    """Give the lock up, if it is still this process's."""
    path = path or lock_path()
    held = _read(path)
    if held and int(held.get("pid", 0)) == os.getpid():
        path.unlink(missing_ok=True)


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
