"""
The API, served from inside the app on a port nobody else is using.

The app binds its own socket to port 0 and lets the operating system choose,
then hands that socket to uvicorn. There is no fixed port to collide with — the
"only one usage of each socket address" error that a second `racecraft-serve`
on 8000 produced cannot happen — and no gap between choosing a port and taking
it in which something else could take it first.
"""

from __future__ import annotations

import logging
import socket
import threading

import uvicorn

log = logging.getLogger(__name__)

HOST = "127.0.0.1"


def bound_socket(host: str = HOST) -> socket.socket:
    """A socket bound to a free port on this machine only, ready for uvicorn."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind((host, 0))
    return sock


class ServerThread(threading.Thread):
    """uvicorn in a background thread, stopped by asking it to exit."""

    def __init__(self, app, sock: socket.socket) -> None:
        super().__init__(name="racecraft-server", daemon=True)
        self.sock = sock
        self.port: int = sock.getsockname()[1]
        # log_config=None: uvicorn leaves logging alone, so its messages reach
        # the app's log file with everything else. No access log — a request per
        # poll of the tower would bury what matters.
        self.server = uvicorn.Server(uvicorn.Config(app, log_config=None, access_log=False))

    @property
    def url(self) -> str:
        return f"http://{HOST}:{self.port}/"

    def run(self) -> None:
        self.server.run(sockets=[self.sock])

    def stop(self, timeout: float = 5.0) -> None:
        self.server.should_exit = True
        self.join(timeout)
        try:
            self.sock.close()
        except OSError:
            pass
