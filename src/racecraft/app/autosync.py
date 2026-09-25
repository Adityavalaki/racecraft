"""
Keep the lake current while the app is open.

Nothing new here: an automatic sync is the Sync button pressed on a timer. It
uses the same background job (`ingest.sync.Syncer`, through `api.sync_view`),
so the button shows an automatic sync's progress exactly as it shows its own,
and the same job drops the cached model fits when it writes.

A first sync a few seconds after launch, so the window paints first; then every
fifteen minutes. A sync already running — started by a click — is left to
finish rather than started again.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

log = logging.getLogger(__name__)

FIRST_AFTER_S = 10
EVERY_S = 15 * 60
BUSY = {"planning", "running"}


class AutoSync(threading.Thread):
    def __init__(self, start_sync: Callable[[], dict], status: Callable[[], dict], *,
                 every_s: float = EVERY_S, first_after_s: float = FIRST_AFTER_S) -> None:
        super().__init__(name="racecraft-autosync", daemon=True)
        self._start_sync = start_sync
        self._status = status
        self._every_s = every_s
        self._first_after_s = first_after_s
        # Not `_stop`: threading.Thread has a private method of that name, and
        # shadowing it breaks join().
        self._halt = threading.Event()

    def run(self) -> None:
        if self._halt.wait(self._first_after_s):
            return
        while True:
            try:
                if self._status().get("state") not in BUSY:
                    self._start_sync()
            except Exception:                       # a failed pass must not end the timer
                log.exception("automatic sync could not start")
            if self._halt.wait(self._every_s):
                return

    def stop(self, timeout: float = 2.0) -> None:
        self._halt.set()
        self.join(timeout)
