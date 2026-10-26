"""
The API, served from inside the app on a port nobody else is using.

The app binds its own socket and hands it to uvicorn, so there is no gap
between choosing a port and taking it in which something else could take it
first, and no clash like the "only one usage of each socket address" error a
second `racecraft-serve` on 8000 produced.

It asks for one port first, PREFERRED_PORT, and only if that is taken lets the
operating system choose. A port chosen afresh at every launch made every
launch a different origin to the browser engine, which keeps local storage per
origin — so the panel layout the user had dragged into place was forgotten
each time. The preferred port keeps the origin, and the layout, from one
launch to the next; when it is taken, the app still starts.
"""

from __future__ import annotations

import logging
import socket
import threading

import uvicorn

log = logging.getLogger(__name__)

HOST = "127.0.0.1"


# Not 8000 (racecraft-serve), and below 49152, where Windows hands out ports
# for outgoing connections, so it is rarely taken.
PREFERRED_PORT = 47621


def _socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        # Windows: no other socket may share the port, even one asking to.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    return sock


def bound_socket(host: str = HOST, preferred: int | None = PREFERRED_PORT) -> socket.socket:
    """A socket bound on this machine only, ready for uvicorn: `preferred` if free, else any free port."""
    if preferred:
        sock = _socket()
        try:
            sock.bind((host, preferred))
            return sock
        except OSError:
            sock.close()
            log.info("port %d is taken; serving on one the system chooses", preferred)
    sock = _socket()
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
        if self.ident is not None:            # started: a thread never started cannot be joined
            self.join(timeout)
        try:
            self.sock.close()
        except OSError:
            pass
