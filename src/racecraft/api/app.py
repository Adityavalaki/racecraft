"""
HTTP API behind the replay interface.

Three shapes of request, matching how the panels actually consume data:

* `/state` is one instant, everything: order, gaps, tyres, positions,
  telemetry. Used while scrubbing and once per second while playing.
* `/frames` is a window of positions as parallel arrays. Playback pulls a
  few seconds ahead and animates locally, instead of asking per frame.
* `/laps` is the whole race in one response, for the race trace.

Telemetry is thinned server-side. The browser never receives raw samples.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from racecraft.api import session as session_store
from racecraft.store.db import connect

log = logging.getLogger(__name__)

WEB_DIST = Path(__file__).resolve().parents[3] / "web" / "dist"

app = FastAPI(title="Racecraft", version="0.1.0")

# The Vite dev server runs on another port during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/sessions")
def list_sessions(year: int | None = None, session: str | None = None, limit: int = 500) -> list[dict]:
    """Every session in the lake, newest first."""
    where = ["1 = 1"]
    if year:
        where.append(f"year = {int(year)}")
    if session:
        where.append(f"session = '{_safe(session)}'")
    rows = connect().sql(f"""
        select session_key, year, round, session, event_name, location, country,
               session_name, date_utc, total_laps
        from sessions where {' and '.join(where)}
        order by year desc, round desc, session limit {int(limit)}""").df()
    rows["date_utc"] = rows["date_utc"].astype(str)
    return rows.to_dict("records")


@app.get("/api/sessions/{session_key}")
def session_info(session_key: str) -> dict:
    return _load(session_key).info()


@app.get("/api/sessions/{session_key}/state")
def session_state(session_key: str, t: float = Query(..., description="session time in seconds")) -> dict:
    return _load(session_key).state(t)


@app.get("/api/sessions/{session_key}/frames")
def session_frames(session_key: str, start: float, end: float, hz: float = Query(5.0, ge=0.2, le=25.0),
                   smooth: float = Query(session_store.DEFAULT_SMOOTHING_S, ge=0.0, le=3.0)) -> dict:
    if end < start:
        raise HTTPException(status_code=400, detail="end must be at or after start")
    if end - start > 600:
        raise HTTPException(status_code=400, detail="window must be 600 s or less")
    return _load(session_key).frames(start, end, hz, smooth_s=smooth)


@app.get("/api/sessions/{session_key}/laps")
def session_laps(session_key: str) -> dict:
    return _load(session_key).lap_chart()


@app.get("/api/sessions/{session_key}/messages")
def session_messages(session_key: str, until: float, limit: int = Query(30, ge=1, le=200)) -> list[dict]:
    return _load(session_key).messages(until, limit)


def _load(session_key: str):
    try:
        return session_store.load(session_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None


def _safe(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"bad session code '{value}'")
    return value


# The built interface, when there is one. Mounted last so /api wins.
if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")
