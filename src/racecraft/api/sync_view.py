"""
The interface's sync button.

Nothing has to be let go of after a sync writes: every model cache is keyed by
the lake's version (`store.db.lake_key`), which changes with its files, so the
next request fits again on the lake as it now is.
"""

from __future__ import annotations

from racecraft.ingest.sync import DEFAULT_WEEKENDS, Syncer

syncer = Syncer()


def status() -> dict:
    return syncer.status()


def start(weekends: int = DEFAULT_WEEKENDS, telemetry: bool = True) -> dict:
    return syncer.start(weekends=weekends, telemetry=telemetry)
