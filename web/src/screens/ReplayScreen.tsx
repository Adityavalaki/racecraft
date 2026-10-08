import { useMemo, type ReactNode } from "react";
import { formatClock, type RaceControlEvent, type SessionInfo, type SessionState } from "../api";
import type { Layout } from "../layout";
import { Workspace } from "../layout";
import { DriverCards } from "../panels/DriverCards";
import { Leaderboard } from "../panels/Leaderboard";
import { RaceControl } from "../panels/RaceControl";
import { TrackMap } from "../panels/TrackMap";
import type { Settings } from "../settings";
import { LapCounter } from "../shell/ScreenHeader";
import { useLapTrace } from "../telemetryData";

interface Props {
  sessionKey: string;
  info: SessionInfo;
  state: SessionState | null;
  t: number;
  cars: Record<number, { x: number; y: number }>;
  selected: number[];
  onSelect: (driver: number) => void;
  settings: Settings;
  onToggleNames: () => void;
  onToggleRings: () => void;
  stewards: RaceControlEvent[];
  trackLog: RaceControlEvent[];
  codes: Record<number, string>;
  onOpenTower: () => void;
  layout: Layout;
  onLayout: (next: Layout) => void;
  /** The session picker, the live flag and the reset button, for the session bar. */
  picker: ReactNode;
  status?: ReactNode;
}

/**
 * The replay: the pedal map in the middle, the followed drivers' cards under
 * it, the timing tower and race control beside it, and the session bar above
 * with the lap, the clock and the weather.
 *
 * The pedal map colours the circuit by one car's last full lap: the first
 * followed driver, or the leader while nobody is followed.
 */
export function ReplayScreen(props: Props) {
  const { info, state, settings, selected } = props;
  const drivers = state?.drivers ?? [];
  const hasDrs = (info.drs_zones?.length ?? 0) > 0;
  const hasOvertake = !hasDrs && Boolean(info.has_overtake);
  const eligible = useMemo(() => drivers.filter((d) => d.overtake === "eligible").map((d) => d.driver_number), [drivers]);
  const mapDriver = selected[0] ?? drivers.find((d) => d.position === 1)?.driver_number ?? null;
  const mapTiming = drivers.find((d) => d.driver_number === mapDriver);
  const { trace } = useLapTrace(props.sessionKey, mapDriver, mapTiming?.laps_completed ?? null);
  const weather = state?.weather;
  const code = mapDriver == null ? "" : props.codes[mapDriver] ?? String(mapDriver);
  const aidOn = settings.rings && (hasDrs || hasOvertake);
  const figure = (value: number | null | undefined, unit: string, digits = 0) =>
    value == null ? "—" : `${value.toFixed(digits)}${unit}`;

  return (
    <div className="screen replay">
      <header className="session-bar">
        {props.picker}
        <LapCounter lap={state?.leader_lap ?? 0} total={info.total_laps} />
        {settings.clock === "race" && <span className="session-clock num">{formatClock(props.t - info.t_start)}</span>}
        {/* Where it is, as well as what it is called: a Grand Prix is not always at the circuit its name suggests. */}
        <span className="session-meta">{info.session.location} · {info.drivers.length} cars</span>
        {props.status}
        <dl className="weather">
          <div><dt>Track</dt><dd className="num">{figure(weather?.track_temp, "°C")}</dd></div>
          <div><dt>Air</dt><dd className="num">{figure(weather?.air_temp, "°C")}</dd></div>
          <div><dt>Wind</dt><dd className="num">{figure(weather?.wind_speed, " m/s", 1)}</dd></div>
          <div><dt>Rain</dt><dd className={`num${weather?.rainfall ? " wet" : ""}`}>{weather ? (weather.rainfall ? "Wet" : "Dry") : "—"}</dd></div>
        </dl>
      </header>

      <Workspace
        layout={props.layout}
        onChange={props.onLayout}
        map={
          <section className="panel panel-map" aria-label="Pedal map">
            <div className="panel-bar">
              <h2>Pedal map</h2>
              <span className="panel-meta">
                {trace ? `${code}, lap ${trace.lap}: where the throttle was flat and where the brake was on`
                  : info.has_position_data ? "Positions only: no full lap for this car yet" : ""}
              </span>
              <span className="map-toggles">
                <button type="button" className={`toggle${settings.names ? " is-on" : ""}`} aria-pressed={settings.names}
                        onClick={props.onToggleNames}>
                  Names <kbd>L</kbd>
                </button>
                <button type="button" className={`toggle is-aid${aidOn ? " is-on" : ""}`} aria-pressed={aidOn}
                        disabled={!hasDrs && !hasOvertake} onClick={props.onToggleRings}
                        title={hasOvertake ? "Overtake mode, 2026's successor to DRS: rings the cars within a second of the car ahead while race control has it on. Estimated from the timing."
                          : hasDrs ? "DRS zones" : "No DRS in this session"}>
                  {hasOvertake ? `Overtake${state?.overtake && !state.overtake.enabled ? " · off" : ""}` : "DRS"} <kbd>D</kbd>
                </button>
              </span>
            </div>
            <TrackMap info={info} cars={props.cars} drivers={info.drivers} selected={selected}
                      showNames={settings.names} showDrs={settings.rings} safetyCar={state?.safety_car ?? null}
                      overtakeEligible={hasOvertake ? eligible : undefined} pedalLap={trace} />
            <div className="map-legend">
              {trace && <span><i className="is-throttle" />Full throttle</span>}
              {trace && <span><i className="is-brake" />Braking</span>}
              {hasOvertake && aidOn && <span><i className="is-ring" />Overtake eligible, estimated from the timing gap</span>}
              {hasDrs && aidOn && <span><i className="is-drs" />DRS zones</span>}
            </div>
          </section>
        }
        below={
          <section className="followed" aria-label="Followed drivers">
            <DriverCards selected={selected} drivers={drivers} cars={state?.cars ?? {}} hasDrs={hasDrs}
                         hasOvertake={hasOvertake} onUnpick={props.onSelect} sessionKey={props.sessionKey} t={props.t}
                         units={settings.units} />
          </section>
        }
        right={
          <div className="replay-right">
            <section className="panel">
              <Leaderboard drivers={drivers} selected={selected} onSelect={props.onSelect}
                           onOpenTower={props.onOpenTower} lap={state?.leader_lap} />
            </section>
            <RaceControl stewards={props.stewards} trackLog={props.trackLog} start={info.t_start} codes={props.codes} />
          </div>
        }
      />
    </div>
  );
}
