import { useCallback, useMemo } from "react";
import { formatClock } from "./api";
import type { FeatureId, Screen } from "./features";
import { NEEDS_INSIGHT, ScreenView } from "./screens/ScreenView";
import { lapStartTime, useMessagesAt, useSession, useStateAt } from "./sessionData";
import { useSettings } from "./settings";
import { BrandMark } from "./shell/Rail";
import { useFollowedClock } from "./sync";

/**
 * One screen in a window of its own, following the main window's clock.
 *
 * It reads the same session the main window shows, at the same moment, and
 * moves with it as it plays. Its own controls (play/pause, the scrubber,
 * following a driver, a lap in the race trace) are requests to the main
 * window, which owns the clock, so every window always agrees.
 */
export function FeatureWindow({ feature, initialSession }: { feature: Screen & { id: FeatureId }; initialSession: string }) {
  const follow = useFollowedClock();
  const { settings } = useSettings();
  const session = follow.state?.session ?? initialSession;
  const selected = follow.state?.selected ?? [];

  const { info, laps, crossings, error, waiting, insight, insightError } =
    useSession(session, NEEDS_INSIGHT.has(feature.id));
  const t = follow.state?.t ?? info?.t_start ?? 0;
  const state = useStateAt(session, info, t);
  // Race control is polled only by the screen that shows it.
  const { stewards, trackLog } = useMessagesAt(session, info, t, feature.id === "stewards");

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
    ? (follow.connected ? "Connecting to the replay…" : "Not following: open it from the main window")
    : follow.connected ? "Following the replay" : "Main window closed";

  const sessionName = info ? (
    <span className="session-name">
      <span className="num">R{String(info.session.round ?? "").padStart(2, "0")}</span>
      <b>{info.session.event_name}</b>
      <span>{info.session.session_name}</span>
    </span>
  ) : null;
  const followChip = (
    <span className={`follow-chip${follow.connected && follow.state ? " is-on" : ""}`} role="status">
      <span className="follow-dot" aria-hidden="true" />{status}
    </span>
  );

  return (
    <div className={`feature-app density-${settings.density}`}>
      <div className="feature-brand"><BrandMark size={22} /><span className="display">RACECRAFT</span></div>
      {info ? (
        <ScreenView id={feature.id} ctx={{
          session, t, info, state, laps, crossings, selected, onSelect: follow.select, onSelectLap: seekToLap,
          insight, insightError, actualStops, sessionBest, stewards, trackLog, driverCodes,
          picker: sessionName, extra: followChip,
        }} />
      ) : (
        <div className="feature-placeholder">
          {error ? <span className="placeholder-error">{error}</span>
            : waiting ? "Waiting for live data…" : "Loading…"}
        </div>
      )}

      {info && (
        <footer className="feature-clock">
          <button type="button" className="transport play" onClick={follow.toggle}
                  aria-label={follow.state?.playing ? "Pause" : "Play"} disabled={!follow.connected}>
            {follow.state?.playing ? (
              <svg width="14" height="16" viewBox="0 0 14 16" aria-hidden="true"><path d="M2 1.5h3.5v13H2zM8.5 1.5H12v13H8.5z" fill="currentColor" /></svg>
            ) : (
              <svg width="14" height="16" viewBox="0 0 14 16" aria-hidden="true"><path d="M2 1.5v13l11-6.5z" fill="currentColor" /></svg>
            )}
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
          <span className="time num">{formatClock(t - info.t_start)}</span>
        </footer>
      )}
    </div>
  );
}
