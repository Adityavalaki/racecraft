"""
Recording Formula 1's own timing feed.

The feed is a SignalR stream at `livetiming.formula1.com`, the same one
MultiViewer reads. It is free and unauthenticated, and FastF1 ships a client
for it. That client writes to a file rather than handing messages to the
process, which sounds like a limitation and is closer to a feature: the
recording is the source of truth, it survives a crash of whatever is reading
it, and it replays afterwards exactly as it arrived.

So live mode here is a recorder and a reader, not a streaming pipeline. The
recorder is this module. The reader is `feed.py`, and it builds the same tables
the lake holds, which is what lets every panel work against a live session
without knowing it is live.

The connection drops after about two hours, which is shorter than some race
weekends' sessions and longer than any single race. `record` reconnects and
appends rather than treating a drop as the end, because a recording with a hole
in it is worth much less than one without.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

from racecraft import config

log = logging.getLogger(__name__)

LIVE_DIR = config.DATA_DIR / "live"
# The feed goes quiet between sessions; this is how long to wait before
# deciding the connection is dead rather than the track merely empty.
SILENCE_TIMEOUT_S = 120
RECONNECT_WAIT_S = 5


def recording_path(name: str | None = None, when: datetime | None = None) -> Path:
    """Where a recording lives: data/live/<name>.txt, dated if unnamed."""
    if name:
        stem = name
    else:
        moment = when or datetime.now(timezone.utc)
        stem = moment.strftime("%Y-%m-%d_%H%M")
    return LIVE_DIR / f"{stem}.txt"


def record(path: Path | None = None, timeout_s: int = SILENCE_TIMEOUT_S,
           reconnect: bool = True) -> Path:
    """
    Record the live feed until interrupted. Blocks.

    Appends rather than truncating, so reconnecting after a dropped connection
    continues the same recording instead of starting a second one that would
    have to be stitched back together later.
    """
    from fastf1.livetiming.client import SignalRClient

    path = path or recording_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("recording the live feed to %s", path)

    while True:
        client = SignalRClient(filename=str(path), filemode="a", timeout=timeout_s)
        try:
            client.start()
        except KeyboardInterrupt:
            log.info("stopped by hand after %s", _size(path))
            return path
        except Exception:
            log.exception("the feed dropped after %s", _size(path))
        if not reconnect:
            return path
        log.info("reconnecting in %ds", RECONNECT_WAIT_S)
        try:
            time.sleep(RECONNECT_WAIT_S)
        except KeyboardInterrupt:
            return path


def recordings() -> list[Path]:
    """Every recording on disk, newest first."""
    if not LIVE_DIR.is_dir():
        return []
    return sorted(LIVE_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)


def latest_recording() -> Path | None:
    found = recordings()
    return found[0] if found else None


def _size(path: Path) -> str:
    if not path.exists():
        return "nothing"
    mb = path.stat().st_size / 1e6
    return f"{mb:.1f} MB" if mb >= 1 else f"{path.stat().st_size / 1e3:.0f} KB"
