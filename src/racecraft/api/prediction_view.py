"""
The race prediction, for the interface.

This is `racecraft-analyse predict` served over HTTP. A prediction is made once
qualifying is in the lake (and, on a sprint weekend, the sprint), and from
then on it is saved: `DATA_DIR/predictions/<race>.json`, written once and
never rewritten, so what the screen showed on Saturday night is what gets
scored on Sunday rather than something quietly recomputed after the fact.

For a race that has already been run and was never saved before it, the
prediction is rebuilt from what was known before the start (the model holds
everything after it out), saved the same way, and marked as rebuilt.

Either way, once the race is in the lake the answer carries the result next to
the prediction, and the same scores the replay uses, beside the grid's.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from racecraft import config
from racecraft.model import predict, race_inputs, weekend
from racecraft.store.db import connect

log = logging.getLogger(__name__)

RUNS = 1000


class NotPredictable(RuntimeError):
    """Not yet, or not at all: the message says which."""


_lock = threading.Lock()
_computing: dict[str, threading.Event] = {}


def predictions_dir() -> Path:
    return config.DATA_DIR / "predictions"


def for_session(session_key: str) -> dict:
    """The prediction for the race of the weekend `session_key` belongs to, with the result if there is one."""
    _safe(session_key)
    con = connect()
    ev = weekend.evidence(con, session_key)          # KeyError for a session not in the lake
    race_key = ev.race_key
    path = predictions_dir() / f"{race_key}.json"

    saved = _read(path)
    if saved is None:
        saved = _make_once(con, session_key, race_key, ev, path)

    answer = dict(saved)
    answer["result"] = _result(con, race_key, saved) if ev.race_in_lake else None
    return answer


def _make_once(con, session_key: str, race_key: str, ev, path: Path) -> dict:
    """Make and save the prediction, one computation per race however many windows ask."""
    while True:
        with _lock:
            saved = _read(path)
            if saved is not None:
                return saved
            waiting = _computing.get(race_key)
            if waiting is None:
                _computing[race_key] = threading.Event()
                break
        waiting.wait(timeout=300)
    try:
        ready, waiting_for = _ready(ev)
        if not ready:
            raise NotPredictable(f"the prediction is made once {waiting_for} is in")
        try:
            made = predict.race(con, session_key, runs=RUNS)
        except race_inputs.NotEnoughData as error:
            raise NotPredictable(str(error)) from None
        body = made.as_dict()
        body["before_race"] = not ev.race_in_lake
        body["in_sample"] = str(ev.year) in body["basis"]["calibration"]["fitted_on"]
        if ev.race_in_lake:
            body["basis"]["notes"].append(
                "rebuilt after the race, from what was known before it: nothing from the race or later is used")
        if body["in_sample"]:
            body["basis"]["notes"].append(
                f"{ev.year} is one of the seasons the signals were weighed on, so this is not a pure forecast")
        _write_once(path, body)
        return _read(path) or body          # what was saved, stamp included
    finally:
        with _lock:
            _computing.pop(race_key).set()


def _ready(ev) -> tuple[bool, str]:
    """Qualifying sets the grid; on a sprint weekend the sprint comes before the race too."""
    if "Q" not in ev.sessions_used:
        return False, "qualifying"
    sprint_weekend = any(code in ev.sessions_used for code in ("SQ", "SS"))
    if sprint_weekend and "S" not in ev.sessions_used:
        return False, "the sprint"
    return True, ""


def _result(con, race_key: str, saved: dict) -> dict | None:
    finish = predict.actual_finish(con, race_key)
    if finish.empty:
        return None
    grid = pd.Series({d["driver_number"]: d["grid"] for d in saved["drivers"]})
    grid = grid[grid < weekend.BACK_OF_GRID]
    years = [int(y) for y in saved["basis"]["calibration"]["fitted_on"]] or [saved["year"] - 1]
    model = predict.score(saved, finish)
    baseline = predict.grid_score(grid, finish, predict.slot_chances(con, years))
    return {
        "finish": {str(int(d)): int(p) for d, p in finish.items()},
        "scores": {"model": _plain(model), "grid": _plain(baseline)},
    }


def _plain(scores: dict) -> dict:
    return {k: (bool(v) if isinstance(v, bool) else round(float(v), 4) if isinstance(v, float) else int(v))
            for k, v in scores.items()}


def _read(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        log.warning("unreadable saved prediction %s: %s", path, error)
        return None


def _write_once(path: Path, body: dict) -> None:
    """Write if absent; a prediction that exists is never replaced."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {**body, "saved_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    handle, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(body, out, indent=1)
        if path.exists():
            return
        os.replace(tmp, path)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _safe(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise KeyError(value)
    return value
