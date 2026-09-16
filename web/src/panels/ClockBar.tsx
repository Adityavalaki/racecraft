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
}

const SPEEDS = [1, 2, 5, 10, 30];

/** The spine: one scrubber driving every panel, plus the flag state. */
export function ClockBar({ clock, start, end, leaderLap, totalLaps, trackStatus, weather, loading }: Props) {
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
