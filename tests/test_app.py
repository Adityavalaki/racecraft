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

from racecraft.app import autosync, instance, server, shortcuts


# ------------------------------------------------------------- a port of its own

def test_the_server_gets_a_free_port_the_system_chose():
    sock = server.bound_socket()
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


# ------------------------------------------------------------- one app at a time

def test_a_second_app_is_turned_away_while_the_first_is_running(tmp_path, monkeypatch):
    lock = tmp_path / "app.lock"
    monkeypatch.setattr(instance, "process_alive", lambda pid: True)
    assert instance.claim(51234, lock) is True
    assert json.loads(lock.read_text()) == {"pid": os.getpid(), "port": 51234}
    assert instance.claim(51999, lock) is False
    assert instance.running_port(lock) == 51234
    # The pid too: the second launch hands the foreground to that process.
    assert instance.running(lock) == (os.getpid(), 51234)


def test_an_app_that_crashed_does_not_block_the_next(tmp_path, monkeypatch):
    lock = tmp_path / "app.lock"
    lock.write_text(json.dumps({"pid": 4764, "port": 50000}))
    monkeypatch.setattr(instance, "process_alive", lambda pid: False)
    assert instance.running_port(lock) is None
    assert instance.claim(51000, lock) is True


def test_the_lock_is_given_up_only_by_its_owner(tmp_path):
    lock = tmp_path / "app.lock"
    lock.write_text(json.dumps({"pid": os.getpid() + 1, "port": 50000}))
    instance.release(lock)
    assert lock.exists(), "released a lock that belongs to another app"
    lock.write_text(json.dumps({"pid": os.getpid(), "port": 50000}))
    instance.release(lock)
    assert not lock.exists()


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
