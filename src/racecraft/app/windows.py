"""
Feature windows: each analysis feature in a window of its own.

The replay window keeps the clock. A feature window (the timing tower, the race
trace, the strategy board, ...) shows the same session at the same moment and
follows it as it plays; the two talk over a BroadcastChannel in the page
(web/src/sync.ts), which works because every window shares one WebView2
profile (see `webview.start(private_mode=False, ...)` in main.py).

They have to be opened from here rather than by the page: pywebview hands a
page's `window.open` to the system browser, which would be outside the app and
out of reach of the channel. The page asks `POST /api/app/window` instead.

`create` is the window factory (pywebview's `create_window` in the app), passed
in so all of this is tested without opening anything.
"""

from __future__ import annotations

import logging
import re
import threading
from typing import Any, Callable
from urllib.parse import urlencode

log = logging.getLogger(__name__)

# The features a window can hold, and their titles. The page has the same list
# (web/src/features.ts); anything else is refused before a window is made.
FEATURES: dict[str, str] = {
    "tower": "Timing tower",
    "trace": "Race trace",
    "tyres": "Tyre model",
    "strategy": "Strategy",
    "sets": "Tyre sets",
    "stewards": "Stewards",
    "track": "Track log",
    "prediction": "Race prediction",
}

# A lake session code (2024_01_R) or the live key: nothing that could reach a URL oddly.
_SESSION = re.compile(r"[A-Za-z0-9_]{1,40}")


class FeatureWindows:
    """The feature windows of one running app, one per feature at most."""

    def __init__(self, base_url: str, create: Callable[..., Any],
                 on_created: Callable[[Any], None] | None = None,
                 bring_forward: Callable[[Any], None] | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._create = create
        self._on_created = on_created or (lambda window: None)
        self._bring_forward = bring_forward or (lambda window: None)
        self._open: dict[str, Any] = {}
        self._lock = threading.Lock()

    def open(self, feature: str, session: str) -> dict:
        """
        Open `feature` for `session`, or bring forward the window that already
        shows it. The session in the URL is only where the window starts: once
        open, it follows whatever session the replay window shows.
        """
        if feature not in FEATURES:
            raise ValueError(f"unknown feature '{feature}'")
        if not _SESSION.fullmatch(session or ""):
            raise ValueError(f"bad session code '{session}'")
        with self._lock:
            existing = self._open.get(feature)
            if existing is not None:
                self._bring_forward(existing)
                return {"feature": feature, "opened": False}
            url = f"{self.base_url}/?{urlencode({'feature': feature, 'session': session})}"
            window = self._create(f"Racecraft · {FEATURES[feature]}", url,
                                  width=1100, height=760, min_size=(640, 420),
                                  background_color="#0c1015")
            self._open[feature] = window
        try:
            window.events.closed += lambda: self._forget(feature, window)
        except AttributeError:
            pass                                     # a factory without events (tests)
        self._on_created(window)
        log.info("opened the %s window", feature)
        return {"feature": feature, "opened": True}

    def _forget(self, feature: str, window: Any) -> None:
        with self._lock:
            if self._open.get(feature) is window:
                del self._open[feature]

    def close_all(self) -> None:
        """Close every feature window: they follow the replay, which is closing."""
        with self._lock:
            windows, self._open = list(self._open.values()), {}
        for window in windows:
            try:
                window.destroy()
            except Exception:                        # already gone: nothing to do
                log.debug("a feature window was already closed", exc_info=True)

    @property
    def open_features(self) -> list[str]:
        with self._lock:
            return sorted(self._open)
