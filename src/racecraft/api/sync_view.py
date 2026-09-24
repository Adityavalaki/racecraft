"""
The interface's sync button, and what it has to let go of afterwards.

Ingesting new races changes the lake underneath every cached answer: a season's
tyre fit was made without them, a circuit's pit loss did not count them, a
weekend's tyre sets stopped at the last session it saw. So once a sync writes
anything, every one of those caches is dropped and the next request fits again
on the lake as it now is.

A replay of one session (`session._cache`) is kept: new sessions do not change
an old one.
"""

from __future__ import annotations

import logging

from racecraft.ingest.sync import DEFAULT_WEEKENDS, Syncer

log = logging.getLogger(__name__)


def forget_models() -> None:
    """Drop every cached fit and answer built from the lake."""
    from racecraft.api import insight, places_view, tyre_sets_view
    from racecraft.model import race_inputs, tyre_sets

    for cache in (insight._tables_cache, insight._circuit_cache, insight._season_cache,
                  places_view._cache, tyre_sets_view._cache, tyre_sets_view._weekends,
                  tyre_sets._weekend_cache, race_inputs._race_cache):
        cache.clear()
    log.info("new sessions in the lake: cached model fits dropped")


syncer = Syncer(on_written=forget_models)


def status() -> dict:
    return syncer.status()


def start(weekends: int = DEFAULT_WEEKENDS, telemetry: bool = True) -> dict:
    return syncer.start(weekends=weekends, telemetry=telemetry)
