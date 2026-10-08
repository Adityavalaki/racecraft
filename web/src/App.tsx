import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { LIVE_KEY } from "./api";
import { useClock } from "./clock";
import { openFeature, screenById, type FeatureId, type ScreenId } from "./features";
import { useLayout } from "./layout";
import { usePositions } from "./positions";
import { ClockBar, SPEEDS } from "./panels/ClockBar";
import { MAX_FOLLOWED } from "./panels/DriverCards";
import { ReplayScreen } from "./screens/ReplayScreen";
import { NEEDS_INSIGHT, ScreenView } from "./screens/ScreenView";
import { SettingsScreen } from "./screens/SettingsScreen";
import { lapStartTime, useMessagesAt, useSession, useSessionList, useStateAt, type ListState } from "./sessionData";
import { useSettings } from "./settings";
import { Rail } from "./shell/Rail";
import { SessionPicker } from "./shell/ScreenHeader";
import { useShortcuts } from "./shortcuts";
import { useReplayBroadcast } from "./sync";

const SCREEN_KEY = "racecraft:screen";

/** The screen last on show, so the app opens where it was left. */
function loadScreen(): ScreenId {
  try {
    return screenById(localStorage.getItem(SCREEN_KEY))?.id ?? "replay";
  } catch {
    return "replay";
  }
}

/**
 * The main window: the navigation rail on the left, the screen it picks
 * beside it, and the playback bar along the foot of every screen that follows
 * the clock.
 *
 * This window owns the clock. Every screen here reads it, and every screen
 * popped out into a window of its own follows it (see sync.ts): its controls
 * are requests to this window, so every window always agrees.
 */
export default function App() {
  const { sessions, listState, sessionKey, setSessionKey, reloadSessions } = useSessionList();
  const [screen, setScreenState] = useState<ScreenId>(loadScreen);
  const [selected, setSelected] = useState<number[]>([]);
  // A live session grows while it is being watched. Following means the clock
  // rides the newest lap; scrubbing back stops following, because someone
  // looking at lap 12 does not want to be yanked to lap 40 a second later.
  const [following, setFollowing] = useState(true);
  const { settings, update: updateSettings } = useSettings();
  const isLive = sessionKey === LIVE_KEY;
  // How wide the timing tower is and how tall the cards: the user's to drag, remembered.
  const { layout, setLayout, reset: resetLayout, customised } = useLayout();

  const setScreen = useCallback((next: ScreenId) => {
    setScreenState(next);
    try {
      localStorage.setItem(SCREEN_KEY, next);
    } catch {
      // Not remembered, which is all that is lost.
    }
  }, []);

  // Only the tyre and strategy screens need the season's model fit, which is slow the first time.
  const { info, laps, crossings, error, waiting, insight, insightError } =
    useSession(sessionKey, NEEDS_INSIGHT.has(screen));

  // A new session starts with nobody followed, riding the live edge if it has one.
  useEffect(() => {
    setSelected([]);
    setFollowing(true);
  }, [sessionKey]);

  const clock = useClock(info?.t_start ?? 0, info?.t_end ?? 1);
  const positions = usePositions(sessionKey, clock.t, Boolean(info?.has_position_data), clock.speed);
  const state = useStateAt(sessionKey, info, clock.t);
  const { stewards, trackLog } = useMessagesAt(sessionKey, info, clock.t);
  const driverCodes = useMemo(() => {
    const out: Record<number, string> = {};
    for (const driver of info?.drivers ?? []) {
      if (driver.abbreviation) out[driver.driver_number] = driver.abbreviation;
    }
    return out;
  }, [info]);
  const sessionBest = useMemo(() => {
    const times = laps.flatMap((d) => d.lap_time_s.filter((v): v is number => v !== null));
    return times.length ? Math.min(...times) : null;
  }, [laps]);
  const actualStops = useMemo(() => {
    const counts = laps.map((d) => d.pit_in.filter(Boolean).length);
    return counts.length ? counts.reduce((a, b) => a + b, 0) / counts.length : null;
  }, [laps]);

  // Ride the leading edge while following. Reading clock.t here would make this
  // fire on every tick, so it watches only where the session now ends.
  const seekRef = useRef(clock.seek);
  seekRef.current = clock.seek;
  const liveEdge = isLive ? info?.t_end : undefined;
  useEffect(() => {
    if (following && liveEdge !== undefined) seekRef.current(liveEdge);
  }, [following, liveEdge]);

  const cars = positions.at(clock.t);

  // Stable callbacks: the timing tower and the map are memoised, and a new
  // function on every frame would re-render them 60 times a second for nothing.
  const toggleDriver = useCallback((driverNumber: number) => {
    setSelected((current) =>
      current.includes(driverNumber)
        ? current.filter((n) => n !== driverNumber)
        : [...current, driverNumber].slice(-MAX_FOLLOWED),
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
  const seekToLap = useCallback(
    (lap: number) => info && stopFollowingAndSeek(lapStartTime(lap, crossings, info.t_start)),
    [crossings, info, stopFollowingAndSeek],
  );

  // Every pop-out window follows this clock, and asks it to move.
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
  const toggleNames = useCallback(() => updateSettings({ names: !settings.names }), [settings.names, updateSettings]);
  const toggleRings = useCallback(() => updateSettings({ rings: !settings.rings }), [settings.rings, updateSettings]);
  useShortcuts({
    toggle: clock.toggle,
    nudge: stopFollowingAndNudge,
    faster: () => changeSpeed(1),
    slower: () => changeSpeed(-1),
    toStart: () => info && stopFollowingAndSeek(info.t_start),
    toggleNames,
    toggleDrs: toggleRings,
  }, Boolean(info));

  const popOut = useCallback((feature: FeatureId) => {
    if (sessionKey) void openFeature(feature, sessionKey);
  }, [sessionKey]);
  const openTower = useCallback(() => setScreen("tower"), [setScreen]);

  const picker = useMemo(() => <SessionPicker sessions={sessions} value={sessionKey} onChange={setSessionKey} />,
                         [sessions, sessionKey, setSessionKey]);
  const liveFlag = useMemo(() => (isLive ? (
    <div className="live-flag">
      <span className={following ? "live-dot is-following" : "live-dot"} />
      {following ? "LIVE" : "PAUSED"}
      {!following && (
        <button type="button" className="go-live" onClick={() => setFollowing(true)}>Go live</button>
      )}
      {waiting && info && <span className="live-waiting">waiting for live data</span>}
    </div>
  ) : null), [isLive, following, waiting, info]);
  const status = (
    <>
      {liveFlag}
      {info && !info.has_position_data && <span className="session-warn">No position data in this session</span>}
      {customised && screen === "replay" && (
        <button type="button" className="reset-layout" onClick={resetLayout}
                title="Put the timing tower and the driver cards back to their default size">
          Reset layout
        </button>
      )}
      {error && <span className="error">{error}</span>}
    </>
  );

  // The screens other than the replay change with the timing, a few times a
  // second, not with every animation frame: they are given the state's own
  // time, and a context that changes only when something they show does, so
  // the full timing tower is not redrawn sixty times a second.
  const coarseT = state?.t ?? info?.t_start ?? 0;
  const screenContext = useMemo(() => (info && sessionKey ? {
    session: sessionKey, t: coarseT, info, state, laps, crossings, selected, onSelect: toggleDriver, onSelectLap: seekToLap,
    insight, insightError, actualStops, sessionBest, stewards, trackLog, driverCodes, picker,
    onPopOut: screen === "replay" || screen === "settings" ? undefined : () => popOut(screen), extra: liveFlag,
  } : null), [sessionKey, coarseT, info, state, laps, crossings, selected, toggleDriver, seekToLap, insight, insightError,
              actualStops, sessionBest, stewards, trackLog, driverCodes, picker, screen, popOut, liveFlag]);

  const body = () => {
    if (screen === "settings") {
      return <SettingsScreen settings={settings} update={updateSettings} picker={picker} onSynced={reloadSessions} />;
    }
    if (!info || !sessionKey) {
      // The picker stays on screen while a session loads, or fails to: another can always be chosen.
      return (
        <div className="screen">
          {sessions.length > 0 && <header className="session-bar">{picker}{status}</header>}
          <main className="grid loading">
            <Placeholder list={listState} empty={sessions.length === 0} waiting={waiting} error={error} />
          </main>
        </div>
      );
    }
    if (screen === "replay") {
      return (
        <ReplayScreen sessionKey={sessionKey} info={info} state={state} t={clock.t} cars={cars} selected={selected}
                      onSelect={toggleDriver} settings={settings} onToggleNames={toggleNames} onToggleRings={toggleRings}
                      stewards={stewards} trackLog={trackLog} codes={driverCodes} onOpenTower={openTower}
                      layout={layout} onLayout={setLayout} picker={picker} status={status}
                      playbackSpeed={clock.speed} />
      );
    }
    return (
      <ScreenView id={screen} ctx={screenContext!} />
    );
  };

  return (
    <div className={`app density-${settings.density}`}>
      <Rail screen={screen} onScreen={setScreen} onSynced={reloadSessions} />
      <div className="shell-main">
        {body()}
        {info && screen !== "settings" && (
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
        <p className="placeholder-hint">Refresh data, at the foot of the rail, downloads the latest race weekends.</p>
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
