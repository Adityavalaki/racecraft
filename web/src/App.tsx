import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { HttpError, LIVE_KEY, api, type Insight, type LapSeries, type RaceControlEvent, type SessionInfo, type SessionState, type SessionSummary } from "./api";
import { useClock } from "./clock";
import { usePositions } from "./positions";
import { BestSectors } from "./panels/BestSectors";
import { ClockBar } from "./panels/ClockBar";
import { Stewards, filterLabel } from "./panels/Stewards";
import { TrackLog } from "./panels/TrackLog";
import { RaceTrace } from "./panels/RaceTrace";
import { StrategyBoard } from "./panels/StrategyBoard";
import { SyncButton } from "./panels/SyncButton";
import { TimingTower } from "./panels/TimingTower";
import { TrackMap } from "./panels/TrackMap";
import { TyreModel } from "./panels/TyreModel";
import { TyreSets } from "./panels/TyreSets";

/** How often the tower refreshes while playing. Positions animate separately and far more often. */
const STATE_INTERVAL_MS = 400;

/**
 * How often a live session is re-read. The server re-parses its recording at
 * the same cadence, and a lap takes over a minute, so this is far finer than
 * the data changes and far coarser than re-parsing on every poll would be.
 */
const LIVE_INTERVAL_MS = 10_000;

/** The lower-right panel shows one of these at a time. */
const TABS = [
  { id: "trace", label: "Race trace", hint: "gap to the lap leader · click to jump" },
  { id: "tyres", label: "Tyre model", hint: "modelled wear against what this race did" },
  { id: "strategy", label: "Strategy", hint: "cheapest plans, and what they ignore" },
  { id: "sets", label: "Tyre sets", hint: "every car's sets · follows the clock · click a car" },
] as const;
type TabId = (typeof TABS)[number]["id"];

/** Where reading the session list has got. An empty list is an answer, not a failure. */
type ListState = { status: "loading" } | { status: "loaded" } | { status: "failed"; message: string };

/**
 * The session to open when none is chosen yet. Live first when there is one: a
 * recording exists only because someone started it, which is as clear a
 * statement of intent as the interface is going to get. Otherwise the newest
 * race (the list is newest first), otherwise whatever there is.
 */
function defaultSession(all: SessionSummary[]): string | null {
  const opening = all.find((s) => s.session_key === LIVE_KEY)
    ?? all.find((s) => s.session === "R")
    ?? all[0];
  return opening?.session_key ?? null;
}

/** Live answers 409 until it has a recording to read and something in it. */
function isNotReady(error: unknown): boolean {
  return error instanceof HttpError && error.status === 409;
}

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [sessionKey, setSessionKey] = useState<string | null>(null);
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [state, setState] = useState<SessionState | null>(null);
  const [laps, setLaps] = useState<LapSeries[]>([]);
  const [crossings, setCrossings] = useState<{ laps: number[]; t: number[] } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabId>("trace");
  const [stewards, setStewards] = useState<RaceControlEvent[]>([]);
  const [trackLog, setTrackLog] = useState<RaceControlEvent[]>([]);
  // The models' answer, and why there is none, each kept with the session it
  // is for: another session's result or failure must not stand in for, or
  // hold back, this one's.
  const [insightEntry, setInsightEntry] = useState<{ key: string; insight: Insight } | null>(null);
  const [insightFailure, setInsightFailure] = useState<{ key: string; message: string } | null>(null);
  // Bumped when a live session moves on, so a fit asked for before is dropped.
  const [insightGeneration, setInsightGeneration] = useState(0);
  const insight = insightEntry?.key === sessionKey ? insightEntry.insight : null;
  const insightError = insightFailure?.key === sessionKey ? insightFailure.message : null;
  // A live session grows while it is being watched. Following means the clock
  // rides the newest lap; scrubbing back stops following, because someone
  // looking at lap 12 does not want to be yanked to lap 40 a second later.
  const [following, setFollowing] = useState(true);
  // Live is selected before it has anything to show: the recorder may not have
  // started, or the server may have restarted and let go of the recording.
  // Waiting is that state, shown as such rather than as an error.
  const [waiting, setWaiting] = useState(false);
  const waitingRef = useRef(false);
  waitingRef.current = waiting;
  const isLive = sessionKey === LIVE_KEY;

  // A list that arrives picks a session only if none is open: the first sync
  // on a new install fills an empty picker, and a later one leaves the session
  // being viewed alone.
  const takeSessions = useCallback((all: SessionSummary[]) => {
    setSessions(all);
    setListState({ status: "loaded" });
    setSessionKey((current) => current ?? defaultSession(all));
  }, []);

  // Every read of the list is numbered, and one older than the list already
  // shown is dropped: a slow first read must not replace the list a later sync
  // brought, nor pick a session over it.
  const listRequest = useRef(0);
  const listShown = useRef(0);
  const takeNewestSessions = useCallback((request: number, all: SessionSummary[]) => {
    if (request < listShown.current) return;
    listShown.current = request;
    takeSessions(all);
  }, [takeSessions]);

  // After a sync writes new sessions, the list is read again so they appear in
  // the picker. A failure here keeps the list already shown.
  const reloadSessions = useCallback(() => {
    const request = ++listRequest.current;
    api.sessions().then((all) => takeNewestSessions(request, all)).catch(() => undefined);
  }, [takeNewestSessions]);

  useEffect(() => {
    let active = true;
    const request = ++listRequest.current;
    api.sessions()
      .then((all) => {
        if (active) takeNewestSessions(request, all);
      })
      .catch((e) => {
        if (active && listShown.current === 0) {
          setListState({ status: "failed", message: String(e.message ?? e) });
        }
      });
    return () => {
      active = false;
    };
  }, [takeNewestSessions]);

  // Info and laps are asked for by the first load and again by every live
  // refresh. Each request is numbered, and a response older than one already
  // shown is dropped, so a slow early answer cannot move the live edge back.
  const infoRequest = useRef(0);
  const shown = useRef({ info: 0, laps: 0 });
  const newest = useCallback((kind: "info" | "laps", request: number) => {
    if (request < shown.current[kind]) return false;
    shown.current[kind] = request;
    return true;
  }, []);

  useEffect(() => {
    if (!sessionKey) return;
    // Aborting stops the requests; `active` also stops any answer that arrives
    // anyway, success or failure, once another session has been picked.
    let active = true;
    const controller = new AbortController();
    const current = () => active && !controller.signal.aborted;
    setInfo(null);
    setState(null);
    setLaps([]);
    setCrossings(null);
    setStewards([]);
    setTrackLog([]);
    setSelected([]);
    setError(null);
    setInsightEntry(null);
    setInsightFailure(null);
    setFollowing(true);
    setWaiting(false);
    // Not ready yet is waiting, for live; anything else is an error.
    const report = reportUnlessAborted(setError);
    const fail = (error: Error) => {
      if (!current()) return;
      if (sessionKey === LIVE_KEY && isNotReady(error)) setWaiting(true);
      else report(error);
    };
    const load = () => {
      const request = ++infoRequest.current;
      api
        .info(sessionKey, controller.signal)
        .then((next) => {
          if (current() && newest("info", request)) setInfo(next);
        })
        .catch(fail);
      api
        .laps(sessionKey, controller.signal)
        .then((chart) => {
          if (!current() || !newest("laps", request)) return;
          setLaps(chart.drivers);
          setCrossings(chart.leader_crossings);
        })
        .catch(fail);
    };
    // Live is served from whatever recording the server is attached to, and a
    // server that has just started is attached to none: attach, then read.
    if (sessionKey === LIVE_KEY) {
      api
        .liveAttach(controller.signal)
        .then(() => {
          if (current()) load();
        })
        .catch(fail);
    } else {
      load();
    }
    return () => {
      active = false;
      controller.abort();
    };
  }, [sessionKey, newest]);

  // Fitting a season costs seconds, so it is asked for only once a tab that
  // needs it is opened, and then kept for as long as the session is loaded.
  // The sets tab uses it only to check plans against a car's tyres, and shows
  // the sets themselves without waiting for it.
  const wantsInsight = tab === "tyres" || tab === "strategy" || tab === "sets";

  // A failed fit is asked for again when a model tab is opened again, rather
  // than showing the old failure until another session is picked. A fit that
  // worked is kept, and shared by every model tab.
  const wantedInsight = useRef(wantsInsight);
  useEffect(() => {
    if (wantsInsight && !wantedInsight.current) setInsightFailure(null);
    wantedInsight.current = wantsInsight;
  }, [wantsInsight]);

  useEffect(() => {
    if (!sessionKey || !wantsInsight || insight || insightError) return;
    let active = true;
    const controller = new AbortController();
    api
      .insight(sessionKey, controller.signal)
      .then((next) => {
        if (active) setInsightEntry({ key: sessionKey, insight: next });
      })
      .catch((error: Error) => {
        if (active && error.name !== "AbortError") {
          setInsightFailure({ key: sessionKey, message: String(error.message ?? error) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sessionKey, wantsInsight, insight, insightError, insightGeneration]);

  // A historic session is fetched once. A live one has to be asked again: its
  // end moves every lap, and the lap chart gains a row. While waiting it is
  // attached again first, which is how it recovers once the recording has
  // something in it, or after the server restarted and let go of it.
  useEffect(() => {
    if (!isLive || !sessionKey) return;
    let active = true;
    let inFlight = false;
    const pull = async () => {
      if (inFlight || !active) return;
      inFlight = true;
      try {
        if (waitingRef.current) await api.liveAttach();
        if (!active) return;
        const request = ++infoRequest.current;
        const [nextInfo, nextLaps] = await Promise.allSettled([api.info(sessionKey), api.laps(sessionKey)]);
        if (!active) return;
        if (nextInfo.status === "fulfilled" && newest("info", request)) setInfo(nextInfo.value);
        if (nextLaps.status === "fulfilled" && newest("laps", request)) {
          setLaps(nextLaps.value.drivers);
          setCrossings(nextLaps.value.leader_crossings);
        }
        if (nextInfo.status === "fulfilled" && nextLaps.status === "fulfilled") {
          setWaiting(false);
          setError(null);
        } else if ([nextInfo, nextLaps].some((r) => r.status === "rejected" && isNotReady(r.reason))) {
          setWaiting(true);
        }
      } catch (error) {
        if (active && isNotReady(error)) setWaiting(true);
      } finally {
        inFlight = false;
      }
      if (!active) return;
      // Dropping the models makes the open tab refetch them; a closed one pays
      // nothing, which is why this clears rather than fetches. The generation
      // also drops a fit still on its way, which was asked for before this.
      setInsightEntry(null);
      setInsightFailure(null);
      setInsightGeneration((g) => g + 1);
    };
    const timer = setInterval(pull, LIVE_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [isLive, sessionKey, newest]);

  const clock = useClock(info?.t_start ?? 0, info?.t_end ?? 1);
  const positions = usePositions(sessionKey, clock.t, Boolean(info?.has_position_data));

  // The tower is polled on a timer rather than on every clock tick: it only
  // changes when a car crosses the line, and a request per frame would be waste.
  const latest = useRef({ key: sessionKey, t: clock.t });
  latest.current = { key: sessionKey, t: clock.t };
  useEffect(() => {
    if (!sessionKey || !info) return;
    let active = true;
    let inFlight = false;
    let lastT: number | null = null;
    const fetchState = () => {
      if (inFlight || !active) return;
      const { key, t } = latest.current;
      if (!key) return;
      if (lastT !== null && Math.abs(t - lastT) < 0.05) return;   // paused and nothing moved
      inFlight = true;
      lastT = t;
      api.state(key, t)
        .then((next) => active && setState(next))
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    };
    fetchState();
    const timer = setInterval(fetchState, STATE_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [sessionKey, info]);

  // The stewards' panel is always on screen, so it is always polled — but half
  // as often as the tower, because a verdict arrives a few times a race and the
  // rows are a few dozen. Asked for with `stewards=true` so the limit applies
  // after the filter: sixty of theirs, not sixty of everything of which twenty
  // are theirs. The tower's PEN column does not depend on this — it arrives with
  // the state above, at the same `t`.
  useEffect(() => {
    if (!sessionKey || !info) return;
    let active = true;
    let inFlight = false;
    const pull = () => {
      if (inFlight || !active) return;
      const { key, t } = latest.current;
      if (!key) return;
      inFlight = true;
      // Two requests, because the limit applies after the filter: each list gets
      // its own newest rather than sharing one budget.
      Promise.all([
        api.messages(key, t, 60, "stewards"),
        api.messages(key, t, 25, "track"),
      ])
        // An error body is JSON too, so the shape is checked rather than assumed.
        .then(([verdicts, log]) => {
          if (!active) return;
          setStewards(Array.isArray(verdicts) ? verdicts : []);
          setTrackLog(Array.isArray(log) ? log : []);
        })
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    };
    pull();
    const timer = setInterval(pull, STATE_INTERVAL_MS * 2);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [sessionKey, info]);

  // Ride the leading edge while following. Reading clock.t here would make this
  // fire on every tick, so it watches only where the session now ends.
  const seekRef = useRef(clock.seek);
  seekRef.current = clock.seek;
  const liveEdge = isLive ? info?.t_end : undefined;
  useEffect(() => {
    if (following && liveEdge !== undefined) seekRef.current(liveEdge);
  }, [following, liveEdge]);

  const cars = positions.at(clock.t);
  const actualStops = useMemo(() => {
    const counts = laps.map((d) => d.pit_in.filter(Boolean).length);
    return counts.length ? counts.reduce((a, b) => a + b, 0) / counts.length : null;
  }, [laps]);
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

  // Stable callbacks: the tower and the trace are memoised, and a new function
  // on every frame would re-render them 60 times a second for nothing.
  const toggleDriver = useCallback((driverNumber: number) => {
    setSelected((current) =>
      current.includes(driverNumber)
        ? current.filter((n) => n !== driverNumber)
        : [...current, driverNumber].slice(-4),
    );
  }, []);

  // Any deliberate move of the clock stops following the live edge. Without
  // this, scrubbing back on a live session would snap forward a second later
  // and the scrubber would be unusable.
  const stopFollowingAndSeek = useCallback(
    (t: number) => {
      setFollowing(false);
      seekRef.current(t);
    },
    [],
  );
  // The ±30 s buttons are a deliberate move too. Following is dropped first so
  // the live edge cannot pull the clock back before the nudge lands.
  const nudgeRef = useRef(clock.nudge);
  nudgeRef.current = clock.nudge;
  const stopFollowingAndNudge = useCallback(
    (seconds: number) => {
      setFollowing(false);
      nudgeRef.current(seconds);
    },
    [],
  );
  const handClock = useMemo(
    () => ({ ...clock, seek: stopFollowingAndSeek, nudge: stopFollowingAndNudge }),
    [clock, stopFollowingAndSeek, stopFollowingAndNudge],
  );

  // Jumping to a lap means the moment that lap began, which is the leader's
  // crossing of the lap before it.
  const seek = stopFollowingAndSeek;
  const seekToLap = useCallback(
    (lap: number) => {
      if (!crossings || !info) return;
      const index = crossings.laps.indexOf(lap - 1);
      seek(index === -1 ? info.t_start : crossings.t[index] ?? info.t_start);
    },
    [crossings, info, seek],
  );

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
        <SyncButton onSynced={reloadSessions} />
        {error && <div className="error">{error}</div>}
      </header>

      {info ? (
        <main className="grid">
          <section className="panel panel-tower">
            <h2>Timing tower</h2>
            <TimingTower
              drivers={state?.drivers ?? []}
              selected={selected}
              onSelect={toggleDriver}
              sessionBest={sessionBest}
            />
            <BestSectors
              sectors={state?.best_sectors ?? []}
              idealLap={state?.ideal_lap_s ?? null}
              fastestLap={sessionBest}
            />
          </section>

          <section className="panel panel-map">
            <h2>Track map</h2>
            <TrackMap info={info} cars={cars} drivers={info.drivers} selected={selected} />
          </section>

          <section className="panel panel-stewards">
            <h2>
              Stewards
              {filterLabel(selected, driverCodes) && <small> {filterLabel(selected, driverCodes)}</small>}
            </h2>
            <Stewards
              events={stewards}
              start={info.t_start}
              codes={driverCodes}
              selected={selected}
              onSelect={toggleDriver}
            />
          </section>

          <section className="panel panel-track">
            <h2>Track</h2>
            <TrackLog events={trackLog} start={info.t_start} />
          </section>

          <section className="panel panel-trace">
            <div className="panel-bar with-tabs">
              <span className="tabs" role="tablist" aria-label="Lower panel">
                {TABS.map((item) => (
                  <button
                    key={item.id}
                    id={`tab-${item.id}`}
                    role="tab"
                    type="button"
                    aria-selected={tab === item.id}
                    className={tab === item.id ? "tab is-active" : "tab"}
                    onClick={() => setTab(item.id)}
                  >
                    {item.label}
                  </button>
                ))}
              </span>
              <small>{TABS.find((item) => item.id === tab)?.hint}</small>
            </div>
            <div className="tab-body" role="tabpanel" aria-labelledby={`tab-${tab}`}>
              {tab === "trace" && (
                <RaceTrace
                  series={laps}
                  selected={selected}
                  currentLap={state?.leader_lap ?? 0}
                  onSelectLap={seekToLap}
                />
              )}
              {tab === "tyres" && (
                <TyreModel insight={insight} loading={!insight && !insightError} error={insightError} />
              )}
              {tab === "strategy" && (
                <StrategyBoard
                  insight={insight}
                  loading={!insight && !insightError}
                  error={insightError}
                  actualStops={actualStops}
                  sessionKey={sessionKey}
                />
              )}
              {tab === "sets" && sessionKey && (
                <TyreSets
                  sessionKey={sessionKey}
                  t={state?.t ?? info.t_start}
                  drivers={state?.drivers ?? []}
                  selected={selected}
                  onSelect={toggleDriver}
                  insight={insight}
                />
              )}
            </div>
          </section>
        </main>
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
          leaderLap={state?.leader_lap ?? 0}
          totalLaps={info.total_laps}
          trackStatus={state?.track_status ?? null}
          weather={state?.weather ?? null}
          loading={positions.loading}
        />
      )}
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
        <p className="placeholder-hint">Sync downloads the latest race weekends. Use the Sync button above.</p>
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

function reportUnlessAborted(setError: (message: string) => void) {
  return (error: Error) => {
    if (error.name !== "AbortError") setError(String(error.message ?? error));
  };
}
