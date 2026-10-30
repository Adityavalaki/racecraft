import { useMemo, useState } from "react";
import { type RaceControlEvent, type SessionInfo, type SessionState } from "../api";
import { DriverCards } from "../panels/DriverCards";
import { Leaderboard } from "../panels/Leaderboard";
import { RaceControl } from "../panels/RaceControl";
import { TelemetryStrip } from "../panels/TelemetryStrip";
import { GEAR_COLOURS, SPEED_COLOURS, TrackMap, type ColourBy } from "../panels/TrackMap";
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
  /** Playback speed: the cards fetch telemetry further ahead the faster it runs. */
  playbackSpeed?: number;
}

/**
 * The replay, laid out as a pit wall: the timing tower down the left beside
 * the track map, the two followed drivers' dashboards side by side under the
 * map; race control and the followed drivers' telemetry by lap distance
 * below. The lap, the clock and the weather are in the session bar.
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
  const [colourBy, setColourBy] = useState<ColourBy>("throttle");
  const names = useMemo(() => Object.fromEntries(info.drivers.map((d) => [d.driver_number, d.full_name ?? ""])), [info.drivers]);

  return (
    <div className="screen replay">
      <div className="pitwall">
        <section className="panel pw-tower">
          <Leaderboard drivers={drivers} selected={selected} onSelect={props.onSelect}
                       onOpenTower={props.onOpenTower} lap={state?.leader_lap} />
        </section>
          <section className="panel panel-map pw-map" aria-label="Track map">
            <div className="panel-bar">
              <h2>Track map</h2>
              <span className="panel-meta">
                {info.session.location}{trace ? ` · trace ${code} L${trace.lap}` : info.has_position_data ? " · no full lap for this car yet" : ""}
              </span>
              <span className="map-toggles">
                <span className="segmented" role="radiogroup" aria-label="Colour the track by">
                  {([["throttle", "Throttle"], ["speed", "Speed"], ["gear", "Gear"]] as [ColourBy, string][]).map(([key, text]) => (
                    <button key={key} type="button" role="radio" aria-checked={colourBy === key} className={colourBy === key ? "is-on" : ""}
                            onClick={() => setColourBy(key)}>{text}</button>
                  ))}
                </span>
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
            <div className="map-body">
              <TrackMap info={info} cars={props.cars} drivers={info.drivers} selected={selected}
                        showNames={settings.names} showDrs={settings.rings} safetyCar={state?.safety_car ?? null}
                        overtakeEligible={hasOvertake ? eligible : undefined} pedalLap={trace} colourBy={colourBy} />
            </div>
            <div className="map-legend">
              {trace && colourBy === "throttle" && (
                <>
                  <span><i style={{ background: "#22C55E" }} />Full throttle</span>
                  <span><i style={{ background: "#F5C518" }} />Partial</span>
                  <span><i style={{ background: "#EF4444" }} />Braking</span>
                </>
              )}
              {trace && colourBy === "speed" && (
                <span className="legend-scale">
                  <span className="num">{Math.round(Math.min(...trace.speed))}</span>
                  {SPEED_COLOURS.map((c) => <i key={c} style={{ background: c }} />)}
                  <span className="num">{Math.round(Math.max(...trace.speed))} km/h</span>
                </span>
              )}
              {trace && colourBy === "gear" && (
                <span className="legend-scale">
                  {GEAR_COLOURS.map((c, g) => <span key={c} className="gear-key"><i style={{ background: c }} />{g + 1}</span>)}
                </span>
              )}
              {hasOvertake && aidOn && <span><i className="is-ring" />Overtake eligible, estimated from the timing gap</span>}
              {hasDrs && aidOn && <span><i className="is-drs" />DRS zones</span>}
            </div>
          </section>
        <div className="pw-drv">
          {([0, 1] as const).map((slot) => (
            <div key={slot} className={`pw-dash pw-dash-${slot === 0 ? "a" : "b"}`} aria-label={`Followed driver ${slot === 0 ? "A" : "B"}`}>
              <DriverCards slot={slot} selected={selected} drivers={drivers} cars={state?.cars ?? {}} hasDrs={hasDrs}
                           hasOvertake={hasOvertake} onUnpick={props.onSelect} sessionKey={props.sessionKey} t={props.t}
                           units={settings.units} playbackSpeed={props.playbackSpeed ?? 1} names={names} />
            </div>
          ))}
        </div>
        <div className="pw-rc">
          <RaceControl stewards={props.stewards} trackLog={props.trackLog} start={info.t_start} codes={props.codes} />
        </div>
        <div className="pw-tel">
          <TelemetryStrip sessionKey={props.sessionKey} followed={selected.slice(-2)} drivers={drivers} cars={props.cars} />
        </div>
      </div>
    </div>
  );
}
