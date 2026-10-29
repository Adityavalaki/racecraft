import { useMemo } from "react";
import { type RaceControlEvent, type SessionInfo, type SessionState } from "../api";
import type { Layout } from "../layout";
import { Workspace } from "../layout";
import { DriverCards } from "../panels/DriverCards";
import { Leaderboard } from "../panels/Leaderboard";
import { RaceControl } from "../panels/RaceControl";
import { TeamRadio } from "../panels/TeamRadio";
import { TrackMap } from "../panels/TrackMap";
import type { Settings } from "../settings";
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
  /** Playback speed: the cards fetch telemetry further ahead the faster it runs. */
  playbackSpeed?: number;
}

/**
 * The replay: the pedal map in the middle, the followed drivers' cards under
 * it, and the timing tower and race control beside it. The lap, the clock and
 * the weather are in the app's session bar above.
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
  const code = mapDriver == null ? "" : props.codes[mapDriver] ?? String(mapDriver);
  const aidOn = settings.rings && (hasDrs || hasOvertake);

  return (
    <div className="screen replay">
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
                         units={settings.units} playbackSpeed={props.playbackSpeed ?? 1} />
          </section>
        }
        right={
          <div className="replay-right">
            <section className="panel">
              <Leaderboard drivers={drivers} selected={selected} onSelect={props.onSelect}
                           onOpenTower={props.onOpenTower} lap={state?.leader_lap} />
            </section>
            <RaceControl stewards={props.stewards} trackLog={props.trackLog} start={info.t_start} codes={props.codes} />
            <TeamRadio clips={info.radio} t={props.t} start={info.t_start} codes={props.codes} />
          </div>
        }
      />
    </div>
  );
}
