import { memo } from "react";
import { COMPOUND_COLORS, type CarState, type DriverTiming } from "../api";

interface Props {
  /** Picked drivers, oldest first; a card each, the newest three. */
  selected: number[];
  drivers: DriverTiming[];
  cars: Record<string, CarState>;
  /** False when the session has no DRS (2026, or DRS disabled throughout). */
  hasDrs: boolean;
  onUnpick: (driverNumber: number) => void;
}

/** DRS codes in the feed: 8 is within a second with the flap shut; 10 and up is open. */
export function drsLabel(code: number | null | undefined, hasDrs: boolean): { text: string; state: string } {
  if (!hasDrs) return { text: "—", state: "none" };
  if (code == null) return { text: "—", state: "none" };
  if (code >= 10) return { text: "OPEN", state: "open" };
  if (code >= 8) return { text: "ELIGIBLE", state: "eligible" };
  return { text: "OFF", state: "off" };
}

/**
 * A card for each picked driver: what the car is doing now (speed, gear,
 * DRS, throttle and brake) and where it stands (position, tyre, and the gaps
 * to the cars either side). Gaps are the timing's, exact at each crossing of
 * the line; the telemetry is the car's own, at the clock's time.
 */
export const DriverCards = memo(function DriverCards({ selected, drivers, cars, hasDrs, onUnpick }: Props) {
  if (!selected.length) {
    return <p className="cards-empty">Click a driver on the leaderboard to follow them here — up to three.</p>;
  }
  const byNumber = new Map(drivers.map((driver, index) => [driver.driver_number, index]));
  return (
    <div className="driver-cards">
      {selected.slice(-3).map((number) => {
        const index = byNumber.get(number);
        const driver = index === undefined ? undefined : drivers[index];
        const ahead = index !== undefined && index > 0 ? drivers[index - 1] : undefined;
        const behind = index !== undefined ? drivers[index + 1] : undefined;
        const car: Partial<CarState> = cars[String(number)] ?? {};
        const drs = drsLabel(car.drs, hasDrs);
        const colour = `#${driver?.team_color ?? "555555"}`;
        return (
          <article key={number} className="driver-card" style={{ borderColor: colour }}
                   aria-label={`${driver?.abbreviation ?? number} telemetry`}>
            <header style={{ background: colour }}>
              <span className="card-pos">{driver ? `P${driver.position}` : "—"}</span>
              <span className="card-code">{driver?.abbreviation ?? number}</span>
              <span className="card-team">{driver?.team_name ?? ""}</span>
              <button type="button" className="card-close" onClick={() => onUnpick(number)}
                      aria-label={`Stop following ${driver?.abbreviation ?? number}`}>×</button>
            </header>
            <div className="card-body">
              <div className="card-info">
              <dl className="card-figures">
                <div><dt>SPEED</dt><dd>{car.speed != null ? `${Math.round(car.speed)}` : "—"}<small> km/h</small></dd></div>
                <div><dt>GEAR</dt><dd>{car.gear != null ? Math.round(car.gear) : "—"}</dd></div>
                <div><dt>DRS</dt><dd className={`drs is-${drs.state}`}>{drs.text}</dd></div>
              </dl>
              <div className="card-line">
                <span>TYRE</span>
                {driver?.compound ? (
                  <span>
                    <span className="tyre-chip small" style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}>
                      {driver.compound[0]}
                    </span>
                    {driver.tyre_life != null && ` ${driver.tyre_life} laps`}
                  </span>
                ) : <span>—</span>}
              </div>
              <div className="card-line">
                <span>AHEAD {ahead?.abbreviation ?? ""}</span>
                <span className="num">{ahead ? driver?.interval_text || "—" : "—"}</span>
              </div>
              <div className="card-line">
                <span>BEHIND {behind?.abbreviation ?? ""}</span>
                <span className="num">{behind ? behind.interval_text || "—" : "—"}</span>
              </div>
              </div>
              <div className="card-pedals">
                <Pedal label="THR" value={car.throttle != null ? car.throttle / 100 : null} kind="throttle" />
                <Pedal label="BRK" value={car.brake != null ? (car.brake > 0 ? 1 : 0) : null} kind="brake" />
              </div>
            </div>
          </article>
        );
      })}
    </div>
  );
});

/**
 * One pedal as a tall bar filling from the bottom, the way broadcast
 * telemetry draws it: throttle green, brake red, the label underneath.
 */
function Pedal({ label, value, kind }: { label: string; value: number | null; kind: "throttle" | "brake" }) {
  const share = value == null ? 0 : Math.max(0, Math.min(1, value));
  return (
    <div className="pedal" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100}
         aria-valuenow={value == null ? undefined : Math.round(share * 100)}>
      <span className="pedal-track">
        <span className={`pedal-fill is-${kind}`} style={{ height: `${share * 100}%` }} />
      </span>
      <span className="pedal-label">{label}</span>
    </div>
  );
}
