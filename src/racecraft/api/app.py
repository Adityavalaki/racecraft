"""
HTTP API behind the replay interface.

Three shapes of request, matching how the panels actually consume data:

* `/state` is one instant, everything: order, gaps, tyres, positions,
  telemetry. Used while scrubbing and once per second while playing.
* `/frames` is a window of positions as parallel arrays. Playback pulls a
  few seconds ahead and animates locally, instead of asking per frame.
* `/laps` is the whole race in one response, for the race trace.
* `/insight` is what the models make of the session: degradation, pit loss,
  neutralisation risk, ranked plans. Slow once per season, then cached.

The session key `live` is served from a running recording instead of the lake,
so every endpoint above works against a session in progress without knowing it
is one. See `live_store`.

Telemetry is thinned server-side. The browser never receives raw samples.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from racecraft.api import insight
from racecraft.api import live_store
from racecraft.api import places_view
from racecraft.api import session as session_store
from racecraft.api import tyre_sets_view
from racecraft.api import penalties
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
    out = rows.to_dict("records")

    # Live goes at the top when a recording exists, so the interface can offer
    # it in the same list as everything else rather than as a separate mode.
    status = live_store.store.status()
    if status.get("recording"):
        session = status.get("session") or {}
        out.insert(0, {
            "session_key": live_store.SESSION_KEY,
            "year": session.get("year") or 0,
            "round": session.get("round") or 0,
            "session": "LIVE",
            "event_name": "Live timing",
            "location": "",
            "country": "",
            "session_name": session.get("name") or "Live",
            "date_utc": "",
            "total_laps": None,
        })
    return out


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
def session_messages(session_key: str, until: float,
                     limit: int = Query(30, ge=1, le=200),
                     topic: str | None = Query(
                         None, description="stewards, track or noise; omitted for all three")
                     ) -> list[dict]:
    if topic is not None and topic not in penalties.TOPICS:
        raise HTTPException(status_code=400, detail=f"topic must be one of {penalties.TOPICS}")
    return _load(session_key).messages(until, limit, topic)


@app.get("/api/sessions/{session_key}/insight")
def session_insight(session_key: str,
                    scale: float = Query(insight.DEFAULT_SCALE, ge=0.5, le=3.0)) -> dict:
    """
    What the models make of this session: degradation, pit loss, neutralisation
    risk and the cheapest plans.

    The first call for a season fits every race in it and takes about fifteen
    seconds; later calls are served from that fit. The race being viewed is
    held out of its own degradation figure.
    """
    if session_key == live_store.SESSION_KEY:
        try:
            return insight.for_live(_load(session_key), scale=scale,
                                    live_status=live_store.store.status())
        except live_store.NotLive as error:
            raise HTTPException(status_code=409, detail=str(error)) from None
    try:
        return insight.for_session(session_key, scale=scale)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None


@app.get("/api/sessions/{session_key}/places")
def session_places(session_key: str,
                   grid: int = Query(8, ge=1, le=22, description="grid slot of the car being advised"),
                   runs: int = Query(300, ge=40, le=1000, description="simulated races per plan"),
                   tyres: str = Query("car", pattern="^(car|new)$",
                                      description="race the sets that car had, or new sets")) -> dict:
    """
    Plans for one car, ranked by where they finish against the whole field.

    Held out: for a race that has happened, everything is fitted on races that
    started before it, including the tyres the car had left, which were known
    before the lights went out. `tyres=new` gives it fresh sets instead, which
    is the ideal case rather than the real one. Takes about half a minute the
    first time for a race, grid slot and tyre choice, then is served from memory.
    """
    live, status = None, None
    if session_key == live_store.SESSION_KEY:
        live, status = _load(session_key), live_store.store.status()
    try:
        return places_view.for_session(session_key, grid, runs, live=live, tyres=tyres,
                                       live_status=status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None
    except places_view.NotSimulable as error:
        # 422 rather than 404 or 409: the session exists and is ready, but the
        # races before it cannot support a simulation, and retrying will not help.
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/tyre-sets")
def session_tyre_sets(session_key: str) -> dict:
    """
    Every car's dry tyre sets: what it held when the session started, the sets
    handed back so far, and each set fitted during the session with its lap
    times, so the panel can follow the replay clock.
    """
    live, status = None, None
    if session_key == live_store.SESSION_KEY:
        live, status = _load(session_key), live_store.store.status()
    try:
        return tyre_sets_view.for_session(session_key, live=live, live_status=status)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None
    except tyre_sets_view.NoSets as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/api/live")
def live_status() -> dict:
    """Whether live is attached to a recording, and what it has read from it."""
    return live_store.store.status()


@app.post("/api/live/attach")
def live_attach(recording: str | None = None, year: int | None = None,
                round_number: int | None = None, session_name: str | None = None) -> dict:
    """
    Point live at a recording. Defaults to the newest one and the session now.

    Year, round and session are only needed outside a race weekend, when the
    schedule cannot say which session a recording belongs to.
    """
    from pathlib import Path

    from racecraft.live import feed as feed_module

    named = None
    if year and round_number and session_name:
        named = feed_module.LiveSession(year, round_number, session_name)
    try:
        live_store.store.attach(Path(recording) if recording else None, named)
    except live_store.NotLive as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    return live_store.store.status()


@app.post("/api/live/detach")
def live_detach() -> dict:
    live_store.store.detach()
    return live_store.store.status()


@app.get("/api/circuits")
def list_circuits() -> list[dict]:
    """Measured pit loss and neutralisation risk, every circuit in the lake."""
    return insight.circuits()


def _load(session_key: str):
    """
    A session by key, from the lake or from the live recording.

    Live is a key rather than a separate set of endpoints, which is what keeps
    the interface from needing a second code path for it.
    """
    if session_key == live_store.SESSION_KEY:
        try:
            return live_store.store.session()
        except live_store.NotLive as error:
            # 409 rather than 404: the session is not missing, it is not ready,
            # and the difference decides whether the interface should retry.
            raise HTTPException(status_code=409, detail=str(error)) from None
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
        # Never cached. Asset filenames carry a content hash, so a rebuild
        # changes them and the browser fetches the new ones — but only if it
        # re-reads this file, which names them. Cached, it keeps asking for the
        # bundle it already has and a rebuild silently does nothing.
        return FileResponse(WEB_DIST / "index.html",
                            headers={"Cache-Control": "no-store, must-revalidate"})
