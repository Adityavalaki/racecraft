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
* `/prediction` is the weekend's race predicted from before it started, saved
  once and scored against the result when there is one.

The session key `live` is served from a running recording instead of the lake,
so every endpoint above works against a session in progress without knowing it
is one. See `live_store`.

Telemetry is thinned server-side. The browser never receives raw samples.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from racecraft import resources
from racecraft.api import forecast
from racecraft.api import guard
from racecraft.api import insight
from racecraft.api import live_store
from racecraft.api import pit_view
from racecraft.api import places_view
from racecraft.api import prediction_view
from racecraft.api import session as session_store
from racecraft.api import sync_view
from racecraft.api import telemetry
from racecraft.api import tyre_sets_view
from racecraft.api import penalties
from racecraft.store.db import check_key, connect, has_table

log = logging.getLogger(__name__)

WEB_DIST = (resources.bundle_dir() / "web" / "dist" if resources.frozen()
            else Path(__file__).resolve().parents[3] / "web" / "dist")

# No /docs, /redoc or /openapi.json: nothing uses them, and the docs pages load
# their scripts from a CDN that the content security policy refuses.
app = FastAPI(title="Racecraft", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None)

# No CORS: the Vite dev server proxies /api and the interface uses relative
# paths, so every request is same-origin. Every request is checked and every
# response carries the headers, the 404s included. See guard.py.
app.add_middleware(guard.Guard)


@app.get("/api/sessions")
def list_sessions(year: int | None = None, session: str | None = None, limit: int = 500) -> list[dict]:
    """Every session in the lake, newest first."""
    where = ["1 = 1"]
    if year:
        where.append(f"year = {int(year)}")
    if session:
        where.append(f"session = '{_safe(session)}'")
    con = connect()
    if has_table(con, "sessions"):
        rows = con.sql(f"""
            select session_key, year, round, session, event_name, location, country,
                   session_name, date_utc, total_laps
            from sessions where {' and '.join(where)}
            order by year desc, round desc, session limit {int(limit)}""").df()
        rows["date_utc"] = rows["date_utc"].astype(str)
        out = rows.to_dict("records")
    else:
        out = []                               # a new lake: nothing ingested yet

    # Live goes at the top when a recording exists, so the interface can offer
    # it in the same list as everything else rather than as a separate mode.
    status = live_store.store.status()
    if status.get("recording") and _recording_now(status["recording"]):
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
    seconds; later calls are served from that fit. Degradation comes from the
    season's races before this one (a first race: the end of last season).
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


@app.get("/api/sessions/{session_key}/pit-windows")
def session_pit_windows(session_key: str, t: float = Query(..., description="session time in seconds")) -> dict:
    """
    When each running car is best off stopping, and the chance that stopping
    first gets a car within three seconds of the one ahead the place, at `t`.
    From the strategy model's held-out fit; slow the first time for a season.
    """
    _safe(session_key)
    try:
        return pit_view.for_session(session_key, t)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None
    except pit_view.NoStrategy as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/lap")
def session_lap(session_key: str, driver: int = Query(..., ge=0, le=99),
                lap: int | None = Query(None, ge=1, le=200),
                t: float | None = Query(None, description="latest lap completed by this session time"),
                or_earlier: bool = Query(False, description="that lap, or the latest before it with usable telemetry")
                ) -> dict:
    """
    One lap of one car by distance: speed, throttle, brake, gear and position
    every five metres, with its brake zones and the corners. Draws the pedal
    map and the traces.
    """
    try:
        return telemetry.lap(_load(session_key), driver, lap, t, or_earlier)
    except telemetry.NoLap as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/recent")
def session_recent(session_key: str, driver: int = Query(..., ge=0, le=99), t: float = Query(...),
                   seconds: float = Query(30.0, gt=0, le=telemetry.RECENT_MAX_S)) -> dict:
    """The last half-minute (by default) of one car's speed, throttle, brake and gear, up to `t`."""
    try:
        return telemetry.recent(_load(session_key), driver, t, seconds)
    except telemetry.NoLap as error:
        raise HTTPException(status_code=404, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/compare")
def session_compare(session_key: str, driver: int = Query(..., ge=0, le=99), lap: int | None = Query(None, ge=1, le=200),
                    ref: int = Query(..., ge=0, le=99), ref_lap: int | None = Query(None, ge=1, le=200),
                    t: float | None = None) -> dict:
    """
    Two laps laid over each other by distance: each lap in full, and the time
    between them along the first. Without lap numbers, each car's latest lap
    completed by `t`.
    """
    data = _load(session_key)
    try:
        subject = telemetry.lap(data, driver, lap, t)
        reference = telemetry.lap(data, ref, ref_lap, t)
    except telemetry.NoLap as error:
        raise HTTPException(status_code=404, detail=str(error)) from None
    return {"subject": subject, "reference": reference, "delta": telemetry.compare(subject, reference)}


@app.get("/api/sessions/{session_key}/prediction")
def session_prediction(session_key: str,
                       kind: str = Query("race", pattern="^(race|sprint)$",
                                         description="the weekend's Grand Prix, or its sprint")) -> dict:
    """
    The race of this weekend, predicted from practice, qualifying, the sprint
    and earlier races: each driver's chance to win, reach the podium and score,
    and where they are expected to finish. `kind=sprint` predicts the sprint,
    from sprint qualifying, FP1 and earlier races.

    Made once qualifying (or sprint qualifying) is in, saved, and never
    recomputed; afterwards it comes with the result and the scores beside the
    grid's. About twenty seconds the first time for a weekend.
    """
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422,
                            detail="open the weekend's qualifying or race from the session list for its prediction")
    _safe(session_key)
    try:
        return prediction_view.for_session(session_key, kind)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None
    except prediction_view.NotPredictable as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/standings")
def session_standings(session_key: str,
                      moment: str = Query("before", pattern="^(before|after)$",
                                          description="results before this session started, or with it too")) -> dict:
    """
    The drivers' and constructors' championships of this session's season, as
    they stood when it started (so opening a race does not give its result
    away), or once it was over.
    """
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422, detail="open a session from the session list for its standings")
    _safe(session_key)
    from racecraft.model import standings

    con = connect()
    year, as_of = _as_of(con, session_key, moment)
    body = standings.standings(con, year, as_of=as_of).as_dict()
    body["moment"] = moment
    return body


@app.get("/api/sessions/{session_key}/title")
def session_title(session_key: str,
                  moment: str = Query("before", pattern="^(before|after)$",
                                      description="from the standings before this session started, or after it")) -> dict:
    """
    Each driver's and constructor's chance of the championship, the rest of
    the season simulated from the standings at this session. A few seconds the
    first time for a season, then from memory.
    """
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422, detail="open a session from the session list for the title odds")
    _safe(session_key)
    from racecraft.api import title_view

    try:
        return title_view.for_session(session_key, moment)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None
    except title_view.NotAvailable as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/pit-crews")
def session_pit_crews(session_key: str,
                      moment: str = Query("before", pattern="^(before|after)$",
                                          description="the season's stops before this session started, or with it")) -> dict:
    """
    Every team's pit crew this season, ranked: their typical stop against the
    race's typical stop, how consistent, how often slow; and this session's
    own stops, each with its time so the interface can follow the clock.
    """
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422, detail="open a session from the session list for the pit crews")
    _safe(session_key)
    from racecraft.model import pit_crews

    con = connect()
    year, as_of = _as_of(con, session_key, moment)
    body = pit_crews.ranking(con, year, as_of).as_dict()
    body["moment"] = moment
    body["session_stops"] = pit_crews.session_stops(con, session_key)
    return body


@app.get("/api/sessions/{session_key}/forecast")
def session_forecast(session_key: str) -> dict:
    """
    The weather forecast at the circuit for the start of this weekend's race and
    sprint, from Open-Meteo (D-015): rain chance, rain, air temperature, wind. For
    a weekend already run, the forecast as it stood then. Display only.
    """
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422, detail="open a session from the list for its weekend's forecast")
    season, rnd, _ = _safe(session_key).split("_")
    try:
        return forecast.for_weekend(int(season), int(rnd))
    except forecast.Unavailable as error:
        raise HTTPException(status_code=503, detail=str(error)) from None


@app.get("/api/sessions/{session_key}/weekend")
def session_weekend(session_key: str) -> dict:
    """The weekend's sessions in the lake, in running order, and whether it has a sprint."""
    if session_key == live_store.SESSION_KEY:
        raise HTTPException(status_code=422, detail="live has no weekend in the lake yet")
    _safe(session_key)
    try:
        return prediction_view.weekend_of(session_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None


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


@app.get("/api/sync")
def sync_status() -> dict:
    """How the last sync of recent race weekends went, or how the running one is going."""
    return sync_view.status()


@app.post("/api/sync")
def sync_start(weekends: int = Query(5, ge=1, le=10, description="latest race weekends to bring in"),
               telemetry: bool = Query(True, description="include car and position data")) -> dict:
    """
    Bring the latest race weekends into the lake: every session whose data has
    been published and is not already there. Runs in the background — poll
    GET /api/sync — and a second request while one is running reports that one.
    """
    return sync_view.start(weekends=weekends, telemetry=telemetry)


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
    from racecraft.live import feed as feed_module
    from racecraft.live import recorder

    path = None
    if recording:
        # Only a recording in the live folder: this is a request, and a path
        # from a request must not open any file on the computer. A bare name
        # is looked up there; a full path must lead there.
        live_dir = recorder.LIVE_DIR.resolve()
        path = (live_dir / recording).resolve()
        if not path.is_relative_to(live_dir) or not path.is_file():
            raise HTTPException(status_code=400, detail=f"no recording '{recording}' in {live_dir}")
    named = None
    if year and round_number and session_name:
        named = feed_module.LiveSession(year, round_number, session_name)
    try:
        live_store.store.attach(path, named)
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


# A recording counts as live while it is still being written. The feed sends a
# heartbeat every few seconds even when no car is running, so a file untouched
# for this long belongs to a session that has ended — and opening the interface
# on it lands on "not attached" instead of on the race that has since arrived.
LIVE_FRESH_S = 15 * 60


def _recording_now(recording: str) -> bool:
    import time

    try:
        return time.time() - Path(recording).stat().st_mtime < LIVE_FRESH_S
    except OSError:
        return False


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
    _safe(session_key)                         # a key goes straight into SQL; refuse a bad one here
    try:
        return session_store.load(session_key)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None


def _as_of(con, session_key: str, moment: str):
    """The session's season and cut-off (`standings.as_of`), or a 404."""
    from racecraft.model import standings

    try:
        return standings.as_of(con, session_key, moment)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"no session '{session_key}' in the lake") from None


def _safe(value: str) -> str:
    try:
        return check_key(value)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"bad session code '{value}'") from None


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
