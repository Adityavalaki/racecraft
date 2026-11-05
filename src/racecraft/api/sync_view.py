"""
The interface's sync button, and how much a person chose to download (D-032).

Nothing has to be let go of after a sync writes: every model cache is keyed by
the lake's version (`store.db.lake_key`), which changes with its files, so the
next request fits again on the lake as it now is.
"""

from __future__ import annotations

from racecraft import config
from racecraft.ingest.sync import DEFAULT_WEEKENDS, EVERYTHING, SEASON, Syncer

syncer = Syncer()

CHOICES = {"last5": DEFAULT_WEEKENDS, "season": SEASON, "everything": EVERYTHING}


def status() -> dict:
    return syncer.status()


def _saved() -> str | None:
    """The saved choice. A missing or damaged file is the same as none, and only asks again."""
    try:
        text = (config.DATA_DIR / "data_choice.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if text in CHOICES else None


def _has_sessions() -> bool:
    return next(config.LAKE_DIR.glob("sessions/*/*/*/data.parquet"), None) is not None


def choice() -> dict:
    """
    What is chosen, and whether to ask. Only an install with no data is asked: anyone
    with sessions already keeps the five weekends they always had.
    """
    saved = _saved()
    has_sessions = saved is None and _has_sessions()
    return {"choice": saved or ("last5" if has_sessions else None), "ask": saved is None and not has_sessions}


def choose(what: str) -> dict:
    """Save the choice and begin. While a download runs it is left to finish, and the next one follows the choice."""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    (config.DATA_DIR / "data_choice.txt").write_text(what, encoding="utf-8")
    return start()


def start(weekends: int | None = None, telemetry: bool = True) -> dict:
    """Begin a sync of what was chosen, unless `weekends` asks for that many of the latest."""
    current = choice()
    if weekends is None and current["ask"]:
        return status()                     # WHY: an automatic sync must not start hours of download unasked
    return syncer.start(weekends or CHOICES[current["choice"]], telemetry=telemetry)
