import { formatClock, TRACK_STATUS } from "../api";
import type { Clock } from "../clock";

interface Props {
  clock: Clock;
  start: number;
  end: number;
  leaderLap: number;
  totalLaps: number | null;
  trackStatus: { status: string; message: string } | null;
  weather: { air_temp: number | null; track_temp: number | null; rainfall: boolean | null } | null;
  loading: boolean;
  /** Every change of track status, for the coloured timeline. */
  statuses?: { t: number; status: string }[];
  /** When the leader completed each lap, for the lap marks under the timeline. */
  crossings?: { laps: number[]; t: number[] } | null;
}

export const SPEEDS = [1, 2, 5, 10, 30];

/** The statuses worth seeing on the timeline, and how they are drawn. */
export const TIMELINE_STATUS: Record<string, { label: string; className: string }> = {
  "2": { label: "Yellow", className: "is-yellow" },
  "4": { label: "Safety car", className: "is-sc" },
  "5": { label: "Red flag", className: "is-red" },
  "6": { label: "VSC", className: "is-vsc" },
  "7": { label: "VSC", className: "is-vsc" },
};

/**
 * The spans of the session spent under each status worth marking, as
 * fractions of the timeline: from one change of status to the next.
 */
export function statusBands(statuses: { t: number; status: string }[], start: number, end: number) {
  const span = end - start;
  if (!(span > 0)) return [];
  const ordered = [...statuses].sort((a, b) => a.t - b.t);
  const bands: { from: number; to: number; status: string }[] = [];
  ordered.forEach((change, index) => {
    if (!TIMELINE_STATUS[change.status]) return;
    const until = ordered[index + 1]?.t ?? end;
    const from = Math.max(0, (change.t - start) / span);
    const to = Math.min(1, (until - start) / span);
    if (to > from) bands.push({ from, to, status: change.status });
  });
  return bands;
}

/**
 * The spine: one scrubber driving every panel, plus the flag state. The
 * scrubber sits on the race's own timeline: yellow, safety car, VSC and red
 * flag periods coloured in, and the leader's laps marked beneath, so an
 * incident is something to see and jump to rather than hunt for.
 */
export function ClockBar({ clock, start, end, leaderLap, totalLaps, trackStatus, weather, loading,
                           statuses = [], crossings = null }: Props) {
  const bands = statusBands(statuses, start, end);
  const span = end - start;
  const laps = crossings && span > 0
    ? crossings.laps.map((lap, i) => ({ lap, at: (crossings.t[i]! - start) / span }))
        .filter((mark) => mark.at >= 0 && mark.at <= 1)
    : [];
  const flag = trackStatus ? TRACK_STATUS[trackStatus.status] : undefined;
  return (
    <div className="clockbar">
      <div className="flag" style={{ background: flag?.color ?? "#39434f" }}>
        {flag?.label ?? trackStatus?.message ?? "—"}
      </div>

      <button className="transport" onClick={clock.toggle} aria-label={clock.playing ? "Pause" : "Play"}>
        {clock.playing ? "❚❚" : "▶"}
      </button>
      <button className="transport" onClick={() => clock.nudge(-30)} aria-label="Back 30 seconds">
        −30s
      </button>
      <button className="transport" onClick={() => clock.nudge(30)} aria-label="Forward 30 seconds">
        +30s
      </button>

      <div className="speeds">
        {SPEEDS.map((speed) => (
          <button
            key={speed}
            className={`speed${clock.speed === speed ? " is-active" : ""}`}
            onClick={() => clock.setSpeed(speed)}
          >
            {speed}×
          </button>
        ))}
      </div>

      <div className="timeline">
        <div className="timeline-bands" aria-hidden="true">
          <span className="timeline-played"
                style={{ width: `${span > 0 ? Math.max(0, Math.min(1, (clock.t - start) / span)) * 100 : 0}%` }} />
          {bands.map((band) => (
            <span key={`${band.status}-${band.from}`} className={`band ${TIMELINE_STATUS[band.status]!.className}`}
                  style={{ left: `${band.from * 100}%`, width: `${(band.to - band.from) * 100}%` }}
                  title={TIMELINE_STATUS[band.status]!.label} />
          ))}
        </div>
        <input
          className="scrub"
          type="range"
          min={start}
          max={end}
          step={0.1}
          value={clock.t}
          onChange={(event) => clock.seek(Number(event.target.value))}
          aria-label="Session time"
        />
        <div className="timeline-laps" aria-hidden="true">
          {laps.map((mark) => (
            <span key={mark.lap} className={`lap-mark${mark.lap % 10 === 0 ? " is-major" : ""}`}
                  style={{ left: `${mark.at * 100}%` }}>
              {mark.lap % 10 === 0 ? mark.lap : ""}
            </span>
          ))}
        </div>
      </div>

      <div className="readout">
        <span className="time">{formatClock(clock.t - start)}</span>
        <span className="lap">
          LAP {leaderLap}
          {totalLaps ? ` / ${totalLaps}` : ""}
        </span>
        {weather?.track_temp != null && <span className="weather">TRACK {weather.track_temp.toFixed(0)}°C</span>}
        {weather?.rainfall && <span className="weather wet">RAIN</span>}
        <span className={`dot${loading ? " is-loading" : ""}`} title={loading ? "buffering" : "buffered"} />
      </div>
    </div>
  );
}
