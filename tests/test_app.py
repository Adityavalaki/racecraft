"""
The desktop app, without opening a window.

The window is pywebview's; what is Racecraft's is everything around it, and
each piece exists because of something that went wrong without it: a port of
its own (8000 was taken), one app at a time (two syncs on one lake), a sync
timer that leaves a running sync alone, and shortcuts that retire the old
logon watcher. Those are tested here. `webview` is never imported.
"""

import json
import os
import socket
import threading
import time

import pytest

from conftest import hold_lock_elsewhere, kill, soon
from racecraft.app import autosync, instance, server, shortcuts


# ------------------------------------------------------------- a port of its own

def test_the_server_gets_a_free_port_the_system_chose():
    sock = server.bound_socket(preferred=None)
    try:
        port = sock.getsockname()[1]
        assert port not in (0, 8000)
        # Already taken by this socket: nothing else can have it meanwhile.
        other = socket.socket()
        with pytest.raises(OSError):
            other.bind(("127.0.0.1", port))
        other.close()
    finally:
        sock.close()


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def test_the_same_port_every_launch_when_it_is_free():
    """The page's origin, and with it the saved panel layout, survives a restart."""
    wanted = _free_port()
    first = server.bound_socket(preferred=wanted)
    assert first.getsockname()[1] == wanted
    first.close()
    again = server.bound_socket(preferred=wanted)
    try:
        assert again.getsockname()[1] == wanted
    finally:
        again.close()


def test_a_taken_preferred_port_still_starts_the_app_elsewhere():
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    taken = holder.getsockname()[1]
    try:
        sock = server.bound_socket(preferred=taken)
        try:
            assert sock.getsockname()[1] not in (0, taken)
        finally:
            sock.close()
    finally:
        holder.close()


def test_the_preferred_port_is_not_racecraft_serves_nor_one_windows_hands_out():
    assert server.PREFERRED_PORT != 8000
    assert 1024 < server.PREFERRED_PORT < 49152


def test_the_api_is_served_on_that_port_and_stops_when_asked():
    from fastapi import FastAPI

    app = FastAPI()
    app.get("/api/sync")(lambda: {"state": "idle"})
    thread = server.ServerThread(app, server.bound_socket())
    thread.start()
    try:
        from racecraft.app.main import wait_until_ready
        assert wait_until_ready(thread.url, timeout_s=15)
    finally:
        thread.stop()
    assert not thread.is_alive()


def test_a_server_and_sync_that_never_started_can_still_be_stopped():
    """The window can close while start-up is half done; cleanup must not trip."""
    from fastapi import FastAPI

    sock = server.bound_socket()
    unstarted = server.ServerThread(FastAPI(), sock)
    unstarted.stop()
    assert sock.fileno() == -1, "the socket was left open"
    autosync.AutoSync(lambda: {}, lambda: {"state": "idle"}).stop()


# ------------------------------------------------------------- one app at a time

def test_a_second_app_is_turned_away_while_the_first_is_running(tmp_path):
    path = tmp_path / "app.lock"
    first = instance.claim(51234, path)
    assert first is not None
    try:
        assert json.loads(path.read_text()) == {"pid": os.getpid(), "port": 51234}
        assert instance.claim(51999, path) is None
        assert instance.running_port(path) == 51234
        # The pid too: the second launch hands the foreground to that process.
        assert instance.running(path) == (os.getpid(), 51234)
    finally:
        instance.release(first)


def test_a_running_app_in_another_process_is_found_and_refused(tmp_path):
    path = tmp_path / "app.lock"
    other = hold_lock_elsewhere(path, '{"pid": {pid}, "port": 50000}')
    try:
        assert instance.claim(51000, path) is None
        assert instance.running(path) == (other.holder_pid, 50000)
    finally:
        kill(other)


def test_an_app_that_crashed_does_not_block_the_next(tmp_path):
    path = tmp_path / "app.lock"
    other = hold_lock_elsewhere(path, '{"pid": {pid}, "port": 50000}')
    kill(other)
    assert instance.running_port(path) is None, "a crashed app is still reported as running"
    lock = soon(lambda: instance.claim(51000, path))
    assert lock is not None
    instance.release(lock)


def test_a_launch_right_after_a_crash_waits_for_windows_to_free_the_lock(tmp_path):
    """
    Windows frees a dead app's lock a moment after the app has exited. In that
    moment the lock is refused and no app is running; the launch must wait it
    out rather than exit without opening a window.
    """
    path = tmp_path / "app.lock"
    # Held, but naming no running app: what the lock looks like in that moment.
    other = hold_lock_elsewhere(path, '{"pid": 0, "port": 50000}')
    freed = threading.Timer(0.3, kill, args=(other,))
    freed.start()
    try:
        lock = instance.claim_when_free(51000, path, settle_s=5.0)
        assert lock is not None, "the launch gave up while the lock was being freed"
        assert instance.running(path) == (os.getpid(), 51000)
        instance.release(lock)
    finally:
        freed.join()


def test_a_launch_with_an_app_running_hands_over_without_waiting(tmp_path):
    path = tmp_path / "app.lock"
    other = hold_lock_elsewhere(path, '{"pid": {pid}, "port": 50000}')
    try:
        started = time.monotonic()
        assert instance.claim_when_free(51000, path, settle_s=5.0) is None
        assert time.monotonic() - started < 1.0, "waited although an app is running"
    finally:
        kill(other)


def test_releasing_gives_the_lock_to_the_next_launch_and_is_safe_twice(tmp_path):
    path = tmp_path / "app.lock"
    first = instance.claim(50000, path)
    instance.release(first)
    assert instance.running(path) is None
    second = instance.claim(50001, path)
    assert second is not None
    try:
        instance.release(first)                # again, late: must not free the new owner
        assert instance.claim(50002, path) is None
        assert instance.running_port(path) == 50001
    finally:
        instance.release(second)


@pytest.mark.parametrize("text", ["", '{"pid": 12', "[1, 2]", '{"pid": 1}', "not json"])
def test_partial_or_unreadable_lock_text_means_nobody_is_known(tmp_path, text):
    path = tmp_path / "app.lock"
    path.write_text(text)
    assert instance.running(path) is None


def test_asking_a_running_app_to_come_forward_reaches_its_focus_route():
    from fastapi import FastAPI

    focused = []
    app = FastAPI()
    app.get("/api/sync")(lambda: {"state": "idle"})
    app.post("/api/app/focus")(lambda: focused.append(True) or {"ok": True})
    thread = server.ServerThread(app, server.bound_socket())
    thread.start()
    try:
        from racecraft.app.main import wait_until_ready
        wait_until_ready(thread.url, timeout_s=15)
        assert instance.ask_to_focus(thread.port) is True
    finally:
        thread.stop()
    assert focused == [True]


def test_asking_a_port_nobody_answers_on_is_a_no_not_a_crash():
    sock = server.bound_socket()
    port = sock.getsockname()[1]
    sock.close()
    assert instance.ask_to_focus(port, timeout=1) is False


# ------------------------------------------------------------- sync while open

def test_the_first_sync_comes_soon_and_then_on_the_interval():
    started = []
    sync = autosync.AutoSync(lambda: started.append(time.monotonic()) or {},
                             lambda: {"state": "done"}, every_s=0.05, first_after_s=0.01)
    sync.start()
    time.sleep(0.3)
    sync.stop()
    assert len(started) >= 3


def test_a_sync_already_running_is_left_to_finish():
    started = []
    sync = autosync.AutoSync(lambda: started.append(1) or {},
                             lambda: {"state": "running"}, every_s=0.02, first_after_s=0.01)
    sync.start()
    time.sleep(0.15)
    sync.stop()
    assert started == []


def test_closing_the_window_stops_the_timer_at_once():
    sync = autosync.AutoSync(lambda: {}, lambda: {"state": "idle"}, every_s=3600, first_after_s=3600)
    sync.start()
    began = time.monotonic()
    sync.stop()
    assert not sync.is_alive() and time.monotonic() - began < 1.5


def test_a_sync_that_cannot_start_does_not_end_the_timer():
    calls = []

    def flaky():
        calls.append(1)
        raise RuntimeError("the lake is busy")

    sync = autosync.AutoSync(flaky, lambda: {"state": "idle"}, every_s=0.02, first_after_s=0.01)
    sync.start()
    time.sleep(0.15)
    sync.stop()
    assert len(calls) >= 2


# ------------------------------------------------------------- shortcuts

class _Recorder:
    def __init__(self, stdout=""):
        self.calls, self.stdout = [], stdout

    def __call__(self, command, **kwargs):
        self.calls.append(command)

        class Result:
            returncode, stdout, stderr = 0, self.stdout, ""
        return Result()


def test_the_shortcuts_point_at_the_app_with_its_icon_and_retire_the_watcher():
    run = _Recorder("C:\\Users\\me\\Desktop\\Racecraft.lnk")
    done = shortcuts.install(run=run)
    script = run.calls[0][-1]
    assert str(shortcuts.app_executable()) in script
    assert str(shortcuts.ICON) in script
    assert "GetFolderPath('Desktop')" in script and "GetFolderPath('Programs')" in script
    # What the app replaces: the logon launcher, and a watcher still running.
    assert "racecraft-ingest.cmd" in script and "--watch" in script
    assert done == ["C:\\Users\\me\\Desktop\\Racecraft.lnk"]


def test_a_path_with_an_apostrophe_cannot_break_out_of_the_script():
    assert shortcuts._quote("C:\\Users\\O'Neil\\x") == "'C:\\Users\\O''Neil\\x'"


def test_the_icon_ships_with_the_package():
    assert shortcuts.ICON.exists() and shortcuts.ICON.stat().st_size > 1000


def test_the_desktop_build_bundles_every_data_file_the_package_reads():
    """PyInstaller takes code, not files beside it: each one has to be named in the spec."""
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = (repo / "packaging" / "Racecraft.spec").read_text(encoding="utf-8")
    shipped = [p for pattern in ("*.csv", "*.json", "*.ico", "*.png")
               for p in (repo / "src" / "racecraft").rglob(pattern)]
    assert shipped
    missing = [p.name for p in shipped if p.name not in spec]
    assert not missing, f"not in packaging/Racecraft.spec: {missing}"
