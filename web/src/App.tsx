import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LIVE_KEY, formatClock, type SessionState } from "./api";
import { useClock } from "./clock";
import { LAUNCHER_FEATURES, openFeature, type FeatureId } from "./features";
import { Workspace, useLayout } from "./layout";
import { usePositions } from "./positions";
import { ClockBar, SPEEDS } from "./panels/ClockBar";
import { DriverCards } from "./panels/DriverCards";
import { Leaderboard } from "./panels/Leaderboard";
import { Stewards, filterLabel } from "./panels/Stewards";
import { SyncButton } from "./panels/SyncButton";
import { TrackLog } from "./panels/TrackLog";
import { TrackMap } from "./panels/TrackMap";
import { useMessagesAt, useSession, useSessionList, useStateAt, type ListState } from "./sessionData";
import { SHORTCUTS, useShortcuts } from "./shortcuts";
import { useReplayBroadcast } from "./sync";

/** Drivers that can be picked at once: each gets a card, and the map rings them. */
const MAX_PICKED = 3;

/**
 * The replay window. In the middle, the track map, the session strip under it
 * (event, lap, time, weather) and, below that, the stewards and the track log
 * side by side. The leaderboard on the right; on the left, sync, the feature
 * launcher and the picked drivers' telemetry; the clock along the bottom.
 *
 * Everything else (the full timing tower, the race trace, the tyre model,
 * strategy, tyre sets, the race prediction) opens in a window of its own from
 * the left column, following this window's clock: it owns the clock, and
 * tells every feature window where it is (see sync.ts).
 */
export default function App() {
  const { sessions, listState, sessionKey, setSessionKey, reloadSessions } = useSessionList();
  const [selected, setSelected] = useState<number[]>([]);
  // A live session grows while it is being watched. Following means the clock
  // rides the newest lap; scrubbing back stops following, because someone
  // looking at lap 12 does not want to be yanked to lap 40 a second later.
  const [following, setFollowing] = useState(true);
  const [showNames, setShowNames] = useState(false);
  const [showDrs, setShowDrs] = useState(true);
  const isLive = sessionKey === LIVE_KEY;
  // How wide the side columns are: the user's to set by dragging, remembered here.
  const { layout, setLayout, reset: resetLayout, customised } = useLayout();

  // The replay window needs no model fit: the features that do have their own windows.
  const { info, crossings, error, waiting } = useSession(sessionKey, false);

  // A new session starts with nobody picked, riding the live edge if it has one.
  useEffect(() => {
    setSelected([]);
    setFollowing(true);
  }, [sessionKey]);

  const clock = useClock(info?.t_start ?? 0, info?.t_end ?? 1);
  const positions = usePositions(sessionKey, clock.t, Boolean(info?.has_position_data));
  const state = useStateAt(sessionKey, info, clock.t);
  const { stewards, trackLog } = useMessagesAt(sessionKey, info, clock.t);
  const driverCodes = useMemo(() => {
    const out: Record<number, string> = {};
    for (const driver of info?.drivers ?? []) {
      if (driver.abbreviation) out[driver.driver_number] = driver.abbreviation;
    }
    return out;
  }, [info]);

  // Ride the leading edge while following. Reading clock.t here would make this
  // fire on every tick, so it watches only where the session now ends.
  const seekRef = useRef(clock.seek);
  seekRef.current = clock.seek;
  const liveEdge = isLive ? info?.t_end : undefined;
  useEffect(() => {
    if (following && liveEdge !== undefined) seekRef.current(liveEdge);
  }, [following, liveEdge]);

  const cars = positions.at(clock.t);

  // Stable callbacks: the leaderboard and the map are memoised, and a new
  // function on every frame would re-render them 60 times a second for nothing.
  const toggleDriver = useCallback((driverNumber: number) => {
    setSelected((current) =>
      current.includes(driverNumber)
        ? current.filter((n) => n !== driverNumber)
        : [...current, driverNumber].slice(-MAX_PICKED),
    );
  }, []);

  // Any deliberate move of the clock stops following the live edge. Without
  // this, scrubbing back on a live session would snap forward a second later
  // and the scrubber would be unusable.
  const stopFollowingAndSeek = useCallback((t: number) => {
    setFollowing(false);
    seekRef.current(t);
  }, []);
  // The ±30 s buttons are a deliberate move too. Following is dropped first so
  // the live edge cannot pull the clock back before the nudge lands.
  const nudgeRef = useRef(clock.nudge);
  nudgeRef.current = clock.nudge;
  const stopFollowingAndNudge = useCallback((seconds: number) => {
    setFollowing(false);
    nudgeRef.current(seconds);
  }, []);
  const handClock = useMemo(
    () => ({ ...clock, seek: stopFollowingAndSeek, nudge: stopFollowingAndNudge }),
    [clock, stopFollowingAndSeek, stopFollowingAndNudge],
  );

  // Every feature window follows this clock, and asks it to move.
  useReplayBroadcast(
    sessionKey && info
      ? { session: sessionKey, t: clock.t, playing: clock.playing, speed: clock.speed, following, selected }
      : null,
    { seek: stopFollowingAndSeek, toggle: clock.toggle, select: toggleDriver },
  );

  const changeSpeed = (direction: 1 | -1) => {
    const index = SPEEDS.indexOf(clock.speed);
    const next = SPEEDS[Math.max(0, Math.min(SPEEDS.length - 1, (index === -1 ? 0 : index) + direction))];
    if (next !== undefined) clock.setSpeed(next);
  };
  useShortcuts({
    toggle: clock.toggle,
    nudge: stopFollowingAndNudge,
    faster: () => changeSpeed(1),
    slower: () => changeSpeed(-1),
    toStart: () => info && stopFollowingAndSeek(info.t_start),
    toggleNames: () => setShowNames((on) => !on),
    toggleDrs: () => setShowDrs((on) => !on),
  }, Boolean(info));

  const open = useCallback((feature: FeatureId) => {
    if (sessionKey) void openFeature(feature, sessionKey);
  }, [sessionKey]);
  const openTower = useCallback(() => open("tower"), [open]);
  const hasDrs = (info?.drs_zones?.length ?? 0) > 0;

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">RACECRAFT</div>
        <select
          className="session-select"
          value={sessionKey ?? ""}
          onChange={(event) => setSessionKey(event.target.value)}
        >
          {sessions.map((s) => (
            <option key={s.session_key} value={s.session_key}>
              {s.year} · R{String(s.round).padStart(2, "0")} · {s.event_name} · {s.session_name}
            </option>
          ))}
        </select>
        {isLive && (
          <div className="live-flag">
            <span className={following ? "live-dot is-following" : "live-dot"} />
            {following ? "LIVE" : "PAUSED"}
            {!following && (
              <button type="button" className="go-live" onClick={() => setFollowing(true)}>
                Go live
              </button>
            )}
            {waiting && info && <span className="live-waiting">waiting for live data</span>}
          </div>
        )}
        {info && (
          <div className="session-meta">
            {info.session.location} · {info.drivers.length} cars
            {!info.has_position_data && <span className="warn"> · no position data</span>}
          </div>
        )}
        {customised && info && (
          <button type="button" className="reset-layout" onClick={resetLayout}
                  title="Put both side columns back to their default width">
            Reset layout
          </button>
        )}
        {/* With a session on screen, sync sits at the top of the left column instead. */}
        {!info && <SyncButton onSynced={reloadSessions} />}
        {error && <div className="error">{error}</div>}
      </header>

      {info ? (
        <Workspace
          layout={layout}
          onChange={setLayout}
          left={
            <section className="panel panel-left">
              <div className="left-sync">
                <SyncButton onSynced={reloadSessions} />
              </div>
              <h2>Features</h2>
              <nav className="feature-launcher" aria-label="Open a feature in its own window">
                {LAUNCHER_FEATURES.map((feature) => (
                  <button key={feature.id} type="button" className="open-feature" title={feature.hint}
                          onClick={() => open(feature.id)}>
                    {feature.title} <span aria-hidden="true">↗</span>
                  </button>
                ))}
              </nav>
              <h2>Drivers</h2>
              <DriverCards selected={selected} drivers={state?.drivers ?? []} cars={state?.cars ?? {}}
                           hasDrs={hasDrs} onUnpick={toggleDriver} />
              <details className="keys">
                <summary>Keys</summary>
                <dl className="shortcuts">
                  {SHORTCUTS.map(([key, what]) => (
                    <div key={key}><dt>{key}</dt><dd>{what}</dd></div>
                  ))}
                </dl>
              </details>
            </section>
          }
          map={
            <section className="panel panel-map">
              <div className="panel-bar">
                <h2>Track map</h2>
                <span className="map-toggles">
                  <button type="button" className={`map-toggle${showNames ? " is-on" : ""}`}
                          aria-pressed={showNames} onClick={() => setShowNames((on) => !on)}>
                    Names <kbd>L</kbd>
                  </button>
                  <button type="button" className={`map-toggle${showDrs && hasDrs ? " is-on" : ""}`}
                          aria-pressed={showDrs && hasDrs} disabled={!hasDrs}
                          title={hasDrs ? "DRS zones" : "No DRS in this session (2026 cars have none)"}
                          onClick={() => setShowDrs((on) => !on)}>
                    DRS <kbd>D</kbd>
                  </button>
                </span>
              </div>
              <TrackMap info={info} cars={cars} drivers={info.drivers} selected={selected}
                        showNames={showNames} showDrs={showDrs} safetyCar={state?.safety_car ?? null} />
              <SessionStrip info={info} state={state} t={clock.t} />
            </section>
          }
          below={
            <>
              <section className="panel panel-stewards" aria-label="Stewards">
                <div className="panel-bar">
                  <h2>
                    Stewards
                    {filterLabel(selected, driverCodes) && <small> · {filterLabel(selected, driverCodes)}</small>}
                  </h2>
                  <button type="button" className="pop-out" onClick={() => open("stewards")}
                          aria-label="Open the stewards in a window of their own"
                          title="Open in a window of its own">↗</button>
                </div>
                <Stewards events={stewards} start={info.t_start} codes={driverCodes}
                          selected={selected} onSelect={toggleDriver} />
              </section>
              <section className="panel panel-track" aria-label="Track log">
                <div className="panel-bar">
                  <h2>Track log</h2>
                  <button type="button" className="pop-out" onClick={() => open("track")}
                          aria-label="Open the track log in a window of its own"
                          title="Open in a window of its own">↗</button>
                </div>
                <TrackLog events={trackLog} start={info.t_start} />
              </section>
            </>
          }
          right={
            <section className="panel panel-right">
              <h2>Leaderboard</h2>
              <Leaderboard drivers={state?.drivers ?? []} selected={selected} onSelect={toggleDriver}
                           onOpenTower={openTower} />
            </section>
          }
        />
      ) : (
        <main className="grid loading">
          <Placeholder list={listState} empty={sessions.length === 0} waiting={waiting} error={error} />
        </main>
      )}

      {info && (
        <ClockBar
          clock={handClock}
          start={info.t_start}
          end={info.t_end}
          trackStatus={state?.track_status ?? null}
          loading={positions.loading}
          statuses={info.track_status}
          crossings={crossings}
        />
      )}
    </div>
  );
}

/**
 * The session at a glance, under the map: which event, the lap and the clock,
 * then the weather. The flag is shown in the clock bar, so it is not repeated.
 */
function SessionStrip({ info, state, t }: {
  info: NonNullable<ReturnType<typeof useSession>["info"]>;
  state: SessionState | null;
  t: number;
}) {
  const weather = state?.weather;
  const figure = (value: number | null | undefined, unit: string, digits = 0) =>
    value == null ? "—" : `${value.toFixed(digits)}${unit}`;
  return (
    <div className="session-strip" aria-label="Session">
      <div className="strip-event">
        <b>{info.session.event_name}</b>
        <span>{info.session.session_name}</span>
      </div>
      <dl className="strip-figures">
        <div>
          <dt>LAP</dt>
          <dd>{state?.leader_lap ?? 0}{info.total_laps ? <small> / {info.total_laps}</small> : null}</dd>
        </div>
        <div><dt>TIME</dt><dd>{formatClock(t - info.t_start)}</dd></div>
      </dl>
      <dl className="strip-figures">
        <div><dt>TRACK</dt><dd>{figure(weather?.track_temp, "°C")}</dd></div>
        <div><dt>AIR</dt><dd>{figure(weather?.air_temp, "°C")}</dd></div>
      </dl>
      <dl className="strip-figures">
        <div><dt>WIND</dt><dd>{figure(weather?.wind_speed, " m/s", 1)}</dd></div>
        <div>
          <dt>RAIN</dt>
          <dd className={weather?.rainfall ? "wet" : ""}>{weather ? (weather.rainfall ? "YES" : "DRY") : "—"}</dd>
        </div>
      </dl>
    </div>
  );
}

/** What fills the page before a session is on it: each case says what to do next. */
function Placeholder({ list, empty, waiting, error }: {
  list: ListState;
  empty: boolean;
  waiting: boolean;
  error: string | null;
}) {
  if (list.status === "failed") {
    return (
      <div className="placeholder">
        <p>Could not read the session list.</p>
        <p className="placeholder-error">{list.message}</p>
      </div>
    );
  }
  if (list.status === "loading") return <>Loading sessions…</>;
  if (empty) {
    return (
      <div className="placeholder">
        <p>No sessions yet.</p>
        <p className="placeholder-hint">Refresh downloads the latest race weekends. Use the Refresh button above.</p>
      </div>
    );
  }
  if (waiting) {
    return (
      <div className="placeholder">
        <p>Waiting for live data…</p>
        <p className="placeholder-hint">The recording has nothing to show yet. This checks again every few seconds.</p>
      </div>
    );
  }
  return <>{error ? "" : "Loading session…"}</>;
}
