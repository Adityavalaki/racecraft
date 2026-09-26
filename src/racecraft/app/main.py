"""
Double-click Racecraft: `racecraft` (the GUI entry point, so no console).

The order matters, and each step exists because of something that went wrong
without it:

1. **One app at a time.** If Racecraft is already running, bring its window to
   the front and stop here. Two apps would mean two syncs on one lake.
2. **A window at once.** The window opens on a "starting" page before the API
   has loaded, because loading it takes a few seconds and a double-click that
   shows nothing for three seconds gets double-clicked again.
3. **A port of its own.** The API is served on a free port the app chose, not
   8000, so nothing else on the machine can be in its way.
4. **Sync while open.** The first sync a few seconds in, then every fifteen
   minutes; closing the window stops it. A session half-ingested at that moment
   is safe: the lake writes its session row last, so an unfinished session is
   simply fetched again next time.

Everything is logged to data/logs/app-YYYYMMDD.log, since there is no console.
Anything that stops the app from starting says so in a message box rather than
vanishing.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

from racecraft import config
from racecraft.app import instance, shortcuts
from racecraft.app.autosync import AutoSync
from racecraft.app.server import ServerThread, bound_socket

log = logging.getLogger("racecraft.app")

TITLE = "Racecraft"
ICON = Path(__file__).with_name("racecraft.ico")
READY_TIMEOUT_S = 60

STARTING = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;height:100%;background:#0c1015;color:#a8b4c1;
font:14px/1.5 "Segoe UI",system-ui,sans-serif;display:flex;align-items:center;justify-content:center}
b{display:block;color:#ff7a33;font:700 18px "Segoe UI";letter-spacing:.3em;margin-bottom:.4em}
</style></head><body><div><b>RACECRAFT</b>Starting… loading the lake and the models.</div></body></html>"""

FAILED = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{{margin:0;height:100%;background:#0c1015;color:#e4e9ef;
font:14px/1.6 "Segoe UI",system-ui,sans-serif;display:flex;align-items:center;justify-content:center}}
div{{max-width:560px;padding:24px}} b{{color:#f0656a}} code{{color:#a8b4c1}}
</style></head><body><div><b>Racecraft could not start.</b><br>{reason}<br><br>
<code>The details are in {log}</code></div></body></html>"""


# ------------------------------------------------------------------ helpers

def setup_logging() -> Path:
    folder = config.DATA_DIR / "logs"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"app-{datetime.now():%Y%m%d}.log"
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-5s %(name)s: %(message)s", "%H:%M:%S"))
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return path


def message(text: str, error: bool = False) -> None:
    """
    Printed when there is somewhere to print it; a message box only for the GUI
    executable, which has no stdout at all.
    """
    if sys.stdout is not None:
        print(text)
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, text, TITLE, 0x10 if error else 0x40)
    except Exception:
        log.warning("could not show a message: %s", text)


def wait_until_ready(url: str, timeout_s: float = READY_TIMEOUT_S) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url + "api/sync", timeout=2) as response:
                if response.status == 200:
                    return True
        except OSError:
            time.sleep(0.25)
    return False


def set_app_identity() -> None:
    """Group the window under Racecraft in the taskbar, not under Python."""
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Racecraft.App")
    except Exception:
        pass


def set_window_icon(window) -> None:
    """The WinForms form behind the window takes the icon; best effort."""
    try:
        import clr  # noqa: F401  (pythonnet, which pywebview's Windows backend uses)
        from System import Action
        from System.Drawing import Icon

        form = window.native
        form.Invoke(Action(lambda: setattr(form, "Icon", Icon(str(ICON)))))
    except Exception as error:
        log.info("window icon not set: %s", error)


def bring_to_front(window) -> None:
    """
    Restore and activate, both marshalled to the UI thread by pywebview. The
    foreground itself is granted by the launch that asked (instance.allow_focus).

    Not `window.on_top`: pywebview's WinForms backend sets TopMost from the
    calling thread, which deadlocks against the window's own activation handler
    and froze the whole app when tried.
    """
    window.restore()
    window.show()


# ------------------------------------------------------------------ the app

def run_app() -> int:
    log_file = setup_logging()
    log.info("starting")

    held = instance.running()
    if held is not None:
        pid, port = held
        log.info("already running on port %d; bringing it to the front", port)
        instance.ask_to_focus(port, pid=pid)
        return 0

    try:
        import webview
    except ImportError:
        message("Racecraft needs pywebview to open its window.\n\n"
                "In the project folder, run:\n    pip install -e .[app]", error=True)
        return 1

    from racecraft.api.app import WEB_DIST
    if not (WEB_DIST / "index.html").exists():
        message("The interface has not been built.\n\n"
                "In the project folder, run:\n    cd web\n    npm run build", error=True)
        return 1

    sock = bound_socket()
    if not instance.claim(sock.getsockname()[1]):
        # Another launch won the race a moment ago.
        sock.close()
        held = instance.running()
        if held:
            instance.ask_to_focus(held[1], pid=held[0])
        return 0

    set_app_identity()
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    window = webview.create_window(TITLE, html=STARTING, width=1440, height=900,
                                   min_size=(1024, 700), background_color="#0c1015")
    window.events.shown += lambda: set_window_icon(window)
    parts: dict = {}

    def boot() -> None:
        """Runs once the window is up: load the API, serve it, point the window at it."""
        try:
            from racecraft.api import sync_view
            from racecraft.api.app import app as api

            def focus() -> dict:
                bring_to_front(window)
                return {"ok": True}

            api.add_api_route("/api/app/focus", focus, methods=["POST"])
            server = ServerThread(api, sock)
            server.start()
            parts["server"] = server
            if not wait_until_ready(server.url):
                raise RuntimeError(f"the server did not answer on {server.url}")
            log.info("serving on %s", server.url)
            window.load_url(server.url)

            auto = AutoSync(sync_view.start, sync_view.status)
            auto.start()
            parts["sync"] = auto
        except Exception as error:
            log.exception("could not start")
            window.load_html(FAILED.format(reason=f"{type(error).__name__}: {error}", log=log_file))

    try:
        webview.start(boot)
    finally:
        # The window is closed: stop syncing, stop serving, let the next launch in.
        if "sync" in parts:
            parts["sync"].stop()
        if "server" in parts:
            parts["server"].stop()
        else:
            sock.close()
        instance.release()
        log.info("closed")
    exit_now()


def exit_now() -> None:
    """
    End the process the moment the window has closed and everything is shut down.

    A normal exit runs pythonnet's exit hook, which garbage-collects every object
    the app loaded: nine seconds of a closed app still running. `os._exit` is no
    better: with the .NET runtime loaded, the DLL detach it runs hung for good.
    TerminateProcess skips both; the log is flushed first and nothing else is
    open (the server, the sync and the lock were closed above).
    """
    logging.shutdown()
    if sys.stdout is not None:
        sys.stdout.flush()
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        kernel32.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
    except Exception:
        pass
    os._exit(0)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="racecraft", description="Open Racecraft in its own window.")
    ap.add_argument("--install-shortcuts", action="store_true",
                    help="put Racecraft on the Desktop and in the Start menu, and retire the "
                         "old logon watcher")
    ap.add_argument("--uninstall-shortcuts", action="store_true", help="remove the shortcuts")
    args = ap.parse_args(argv)

    if args.install_shortcuts or args.uninstall_shortcuts:
        setup_logging()
        try:
            done = shortcuts.install() if args.install_shortcuts else shortcuts.uninstall()
        except Exception as error:
            message(f"Could not change the shortcuts:\n\n{error}", error=True)
            return 1
        message("Done.\n\n" + ("\n".join(done) or "Nothing to change."))
        return 0

    try:
        return run_app()
    except Exception as error:
        # Under the GUI executable an uncaught error goes nowhere: the app just
        # never appears. A broken source file did exactly that, launch after
        # launch, and looked like the app had been deleted.
        log.exception("could not start")
        message(f"Racecraft could not start.\n\n{type(error).__name__}: {error}\n\n"
                f"The details are in {config.DATA_DIR / 'logs'}", error=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
