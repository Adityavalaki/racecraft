import { memo } from "react";
import type { CarState, DriverTiming } from "../api";
import { useHeld } from "../held";
import { useTelemetry } from "../telemetryData";
import { MAX_FOLLOWED, Meter } from "./DriverCards";

interface Props {
  /** Followed drivers, oldest first. */
  selected: number[];
  drivers: DriverTiming[];
  cars: Record<string, CarState>;
  sessionKey: string | null;
  t: number;
  playbackSpeed: number;
}

/**
 * Every followed driver's throttle and brake, one above the other beside the
 * map (D-028), so up to four cars can be read against each other. Each slot
 * keeps its place, so a driver joining moves nobody already there.
 */
export const PedalColumn = memo(function PedalColumn({ selected, drivers, cars, sessionKey, t, playbackSpeed }: Props) {
  return (
    <section className="panel pw-pedals" aria-label="Followed drivers' pedals">
      <div className="panel-bar"><h2>Pedals</h2><span className="panel-meta num">{selected.length} of {MAX_FOLLOWED}</span></div>
      {selected.length === 0 ? (
        <p className="cards-empty">Click drivers in the timing tower to compare their throttle and brake here, up to four.</p>
      ) : (
        <div className="pedal-list">
          {selected.map((number) => (
            <PedalRow key={number} number={number} driver={drivers.find((d) => d.driver_number === number)}
                      car={cars[String(number)] ?? {}} sessionKey={sessionKey} t={t} playbackSpeed={playbackSpeed} />
          ))}
        </div>
      )}
    </section>
  );
});

function PedalRow({ number, driver, car, sessionKey, t, playbackSpeed }: {
  number: number;
  driver: DriverTiming | undefined;
  car: Partial<CarState>;
  sessionKey: string | null;
  t: number;
  playbackSpeed: number;
}) {
  const { now } = useTelemetry(sessionKey, number, t, playbackSpeed);
  const throttle = now?.throttle ?? car.throttle ?? null;
  const brake = now?.brake ?? car.brake ?? null;
  const braking = Boolean(brake);
  // As on the dashboards: the bars follow every frame, the figure ticks so it can be read, and brake is a state, so it stays live.
  const throttleShown = useHeld(throttle);
  const code = driver?.abbreviation ?? String(number);
  return (
    <div className="pedal-driver" role="group" aria-label={`${code} pedals`} style={{ ["--team" as string]: `#${driver?.team_color ?? "555555"}` }}>
      <div className="pedal-head num"><i />{code}<small>{driver ? `P${driver.position}` : ""}</small></div>
      <div className="pedal-line cap">
        <span>Thr</span>
        <Meter share={throttle == null ? 0 : throttle / 100} color="#22C55E" />
        <span className="num meter-value">{throttleShown == null ? "—" : `${Math.round(throttleShown)}%`}</span>
      </div>
      <div className="pedal-line cap">
        <span>Brk</span>
        <Meter share={braking ? 1 : 0} color="#EF4444" />
        <span className={`num meter-value${braking ? " is-on" : ""}`}>{brake == null ? "—" : braking ? "ON" : "OFF"}</span>
      </div>
    </div>
  );
}
