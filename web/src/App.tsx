import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, type LapSeries, type SessionInfo, type SessionState, type SessionSummary } from "./api";
import { useClock } from "./clock";
import { usePositions } from "./positions";
import { BestSectors } from "./panels/BestSectors";
import { ClockBar } from "./panels/ClockBar";
import { RaceTrace } from "./panels/RaceTrace";
import { TimingTower } from "./panels/TimingTower";
import { TrackMap } from "./panels/TrackMap";

/** How often the tower refreshes while playing. Positions animate separately and far more often. */
const STATE_INTERVAL_MS = 400;

export default function App() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [sessionKey, setSessionKey] = useState<string | null>(null);
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [state, setState] = useState<SessionState | null>(null);
  const [laps, setLaps] = useState<LapSeries[]>([]);
  const [crossings, setCrossings] = useState<{ laps: number[]; t: number[] } | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.sessions()
      .then((all) => {
        setSessions(all);
        const firstRace = all.find((s) => s.session === "R") ?? all[0];
        if (firstRace) setSessionKey(firstRace.session_key);
      })
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  useEffect(() => {
    if (!sessionKey) return;
    const controller = new AbortController();
    setInfo(null);
    setState(null);
    setLaps([]);
    setCrossings(null);
    setSelected([]);
    setError(null);
    api.info(sessionKey, controller.signal).then(setInfo).catch(reportUnlessAborted(setError));
    api
      .laps(sessionKey, controller.signal)
      .then((chart) => {
        setLaps(chart.drivers);
        setCrossings(chart.leader_crossings);
      })
      .catch(reportUnlessAborted(setError));
    return () => controller.abort();
  }, [sessionKey]);

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

  const cars = positions.at(clock.t);
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

  // Jumping to a lap means the moment that lap began, which is the leader's
  // crossing of the lap before it.
  const seek = clock.seek;
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
        {info && (
          <div className="session-meta">
            {info.session.location} · {info.drivers.length} cars
            {!info.has_position_data && <span className="warn"> · no position data</span>}
          </div>
        )}
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

          <section className="panel panel-trace">
            <h2>
              Race trace <small>gap to the lap leader · click to jump</small>
            </h2>
            <RaceTrace
              series={laps}
              selected={selected}
              currentLap={state?.leader_lap ?? 0}
              onSelectLap={seekToLap}
            />
          </section>
        </main>
      ) : (
        <main className="grid loading">{error ? "" : "Loading session…"}</main>
      )}

      {info && (
        <ClockBar
          clock={clock}
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

function reportUnlessAborted(setError: (message: string) => void) {
  return (error: Error) => {
    if (error.name !== "AbortError") setError(String(error.message ?? error));
  };
}
