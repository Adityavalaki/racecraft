import { useCallback, useMemo } from "react";
import { formatClock } from "./api";
import { type Feature } from "./features";
import { BestSectors } from "./panels/BestSectors";
import { RaceTrace } from "./panels/RaceTrace";
import { Stewards, filterLabel } from "./panels/Stewards";
import { StrategyBoard } from "./panels/StrategyBoard";
import { TimingTower } from "./panels/TimingTower";
import { TrackLog } from "./panels/TrackLog";
import { TyreModel } from "./panels/TyreModel";
import { TyreSets } from "./panels/TyreSets";
import { lapStartTime, useMessagesAt, useSession, useStateAt } from "./sessionData";
import { useFollowedClock } from "./sync";

const NEEDS_INSIGHT = new Set(["tyres", "strategy", "sets"]);
const NEEDS_STATE = new Set(["tower", "trace", "sets"]);
const NEEDS_MESSAGES = new Set(["stewards", "track"]);

/**
 * One feature in a window of its own, following the replay window's clock.
 *
 * It reads the same session the replay window shows, at the same moment, and
 * moves with it as it plays. Its own controls (play/pause, the scrubber,
 * picking drivers, a lap in the race trace) are requests to the replay
 * window, which owns the clock — so every window always agrees.
 */
export function FeatureWindow({ feature, initialSession }: { feature: Feature; initialSession: string }) {
  const follow = useFollowedClock();
  const session = follow.state?.session ?? initialSession;
  const selected = follow.state?.selected ?? [];

  const { info, laps, crossings, error, waiting, insight, insightError } =
    useSession(session, NEEDS_INSIGHT.has(feature.id));
  const t = follow.state?.t ?? info?.t_start ?? 0;
  const state = useStateAt(NEEDS_STATE.has(feature.id) ? session : null, info, t);
  const { stewards, trackLog } = useMessagesAt(session, info, t, NEEDS_MESSAGES.has(feature.id));

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

  const { seek } = follow;
  const seekToLap = useCallback(
    (lap: number) => info && seek(lapStartTime(lap, crossings, info.t_start)),
    [crossings, info, seek],
  );

  const status = follow.state === null
    ? (follow.connected ? "connecting to the replay…" : "not following: open it from the replay window")
    : follow.connected ? "following the replay" : "replay window closed";

  return (
    <div className="feature-app">
      <header className="feature-head">
        <div className="brand">RACECRAFT</div>
        <div className="feature-title">
          <h1>{feature.title}</h1>
          <small>{feature.hint}</small>
        </div>
        {info && (
          <div className="session-meta">
            {info.session.event_name} · {info.session.session_name}
            {state && ` · LAP ${state.leader_lap}${info.total_laps ? ` / ${info.total_laps}` : ""}`}
          </div>
        )}
        <div className={`feature-sync${follow.connected && follow.state ? " is-on" : ""}`} role="status">
          {status}
        </div>
      </header>

      <main className="feature-body panel">
        {info ? (
          <FeatureBody
            id={feature.id}
            session={session}
            t={t}
            info={info}
            state={state}
            laps={laps}
            selected={selected}
            onSelect={follow.select}
            onSelectLap={seekToLap}
            insight={insight}
            insightError={insightError}
            actualStops={actualStops}
            sessionBest={sessionBest}
            stewards={stewards}
            trackLog={trackLog}
            driverCodes={driverCodes}
          />
        ) : (
          <div className="feature-placeholder">
            {error ? <span className="placeholder-error">{error}</span>
              : waiting ? "Waiting for live data…" : "Loading…"}
          </div>
        )}
      </main>

      {info && (
        <footer className="feature-clock">
          <button type="button" className="transport" onClick={follow.toggle}
                  aria-label={follow.state?.playing ? "Pause" : "Play"} disabled={!follow.connected}>
            {follow.state?.playing ? "❚❚" : "▶"}
          </button>
          <input
            className="scrub"
            type="range"
            min={info.t_start}
            max={info.t_end}
            step={0.1}
            value={t}
            disabled={!follow.connected}
            onChange={(event) => follow.seek(Number(event.target.value))}
            aria-label="Session time"
          />
          <span className="time">{formatClock(t - info.t_start)}</span>
        </footer>
      )}
    </div>
  );
}

interface BodyProps {
  id: Feature["id"];
  session: string;
  t: number;
  info: NonNullable<ReturnType<typeof useSession>["info"]>;
  state: ReturnType<typeof useStateAt>;
  laps: ReturnType<typeof useSession>["laps"];
  selected: number[];
  onSelect: (driver: number) => void;
  onSelectLap: (lap: number) => void;
  insight: ReturnType<typeof useSession>["insight"];
  insightError: string | null;
  actualStops: number | null;
  sessionBest: number | null;
  stewards: ReturnType<typeof useMessagesAt>["stewards"];
  trackLog: ReturnType<typeof useMessagesAt>["trackLog"];
  driverCodes: Record<number, string>;
}

/** The feature itself: the same panel the replay window used to hold, given the whole window. */
function FeatureBody(props: BodyProps) {
  const { id, info, state, selected, onSelect } = props;
  const loading = !props.insight && !props.insightError;
  switch (id) {
    case "tower":
      return (
        <>
          <TimingTower drivers={state?.drivers ?? []} selected={selected} onSelect={onSelect} />
          <BestSectors sectors={state?.best_sectors ?? []} idealLap={state?.ideal_lap_s ?? null}
                       fastestLap={props.sessionBest} />
        </>
      );
    case "trace":
      return (
        <div className="tab-body">
          <RaceTrace series={props.laps} selected={selected} currentLap={state?.leader_lap ?? 0}
                     onSelectLap={props.onSelectLap} />
        </div>
      );
    case "tyres":
      return <TyreModel insight={props.insight} loading={loading} error={props.insightError} />;
    case "strategy":
      return (
        <StrategyBoard insight={props.insight} loading={loading} error={props.insightError}
                       actualStops={props.actualStops} sessionKey={props.session} />
      );
    case "sets":
      return (
        <TyreSets sessionKey={props.session} t={state?.t ?? info.t_start} drivers={state?.drivers ?? []}
                  selected={selected} onSelect={onSelect} insight={props.insight} />
      );
    case "stewards":
      return (
        <>
          {filterLabel(selected, props.driverCodes) && (
            <div className="feature-filter">{filterLabel(selected, props.driverCodes)}</div>
          )}
          <Stewards events={props.stewards} start={info.t_start} codes={props.driverCodes}
                    selected={selected} onSelect={onSelect} />
        </>
      );
    case "track":
      return <TrackLog events={props.trackLog} start={info.t_start} />;
  }
}
