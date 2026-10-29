import type { ReactNode } from "react";
import { formatClock, TRACK_STATUS, type SessionInfo, type SessionState } from "../api";
import { flagClass } from "../panels/ClockBar";
import { BrandMark } from "./Rail";
import { PopOutButton } from "./ScreenHeader";

interface Props {
  picker: ReactNode;
  info: SessionInfo | null;
  state: SessionState | null;
  /** The clock, a few times a second: the bar has no need of every frame. */
  t: number;
  showClock: boolean;
  /** The live flag, warnings, the reset button and errors: whatever the session has to say. */
  extra?: ReactNode;
  onPopOut?: () => void;
  popOutLabel?: string;
}

/**
 * The bar across the top of every screen: the brand, the session, then the
 * lap, the race time and the track status in one readout, and the weather.
 * One bar for the whole app, so the session is chosen in one place and the
 * screens below keep their height for data.
 */
export function SessionBar({ picker, info, state, t, showClock, extra, onPopOut, popOutLabel }: Props) {
  const weather = state?.weather;
  const status = state?.track_status ?? null;
  const figure = (value: number | null | undefined, unit: string, digits = 0) =>
    value == null ? "—" : `${value.toFixed(digits)}${unit}`;
  return (
    <header className="session-bar">
      <div className="brand" aria-label="Racecraft">
        <BrandMark size={24} />
        <span className="brand-word">RACECRAFT</span>
      </div>
      {picker}
      {/* Where it is, as well as what it is called: a Grand Prix is not always at the circuit its name suggests. */}
      {info && <span className="session-meta">{info.session.location} · {info.drivers.length} cars</span>}
      {extra}
      <span className="bar-spacer" />
      {info && (
        <div className="readout-box">
          <div className="readout-cell" aria-label={`Lap ${state?.leader_lap ?? 0}${info.total_laps ? ` of ${info.total_laps}` : ""}`}>
            <span className="cap">Lap</span>
            <span className="num readout-big">{state?.leader_lap ?? 0}<small>/{info.total_laps ?? "—"}</small></span>
          </div>
          {showClock && (
            <div className="readout-cell">
              <span className="cap">Time</span>
              <span className="num readout-big">{formatClock(t - info.t_start)}</span>
            </div>
          )}
          <div className={`readout-status ${flagClass(status?.status)}`}>
            <span className="live-pip" aria-hidden="true" />
            {status ? TRACK_STATUS[status.status]?.label ?? status.message : "—"}
          </div>
        </div>
      )}
      {weather && (
        <dl className="weather">
          <div><dt className="cap">Track</dt><dd className="num">{figure(weather.track_temp, "°")}</dd></div>
          <div><dt className="cap">Air</dt><dd className="num">{figure(weather.air_temp, "°")}</dd></div>
          <div><dt className="cap">Wind</dt><dd className="num">{figure(weather.wind_speed, " m/s", 1)}</dd></div>
          <div><dt className="cap">Rain</dt><dd className={`num${weather.rainfall ? " wet" : ""}`}>{weather.rainfall ? "Wet" : "Dry"}</dd></div>
        </dl>
      )}
      {onPopOut && <PopOutButton onPopOut={onPopOut} label={popOutLabel ?? "this screen"} />}
    </header>
  );
}
