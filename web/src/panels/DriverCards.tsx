import { memo } from "react";
import { COMPOUND_COLORS, type CarState, type DriverTiming } from "../api";
import { speedIn, type Settings } from "../settings";
import { useRecent } from "../telemetryData";
import { PedalTrace } from "./PedalTrace";

/** How many drivers can be followed at once: a card each, side by side. */
export const MAX_FOLLOWED = 2;

interface Props {
  /** Followed drivers, oldest first; a card each, the newest two. */
  selected: number[];
  drivers: DriverTiming[];
  cars: Record<string, CarState>;
  /** False when the session has no DRS (2026, or DRS disabled throughout). */
  hasDrs: boolean;
  /** True when the session has overtake mode instead (2026 on). */
  hasOvertake?: boolean;
  onUnpick: (driverNumber: number) => void;
  /** For the half-minute of telemetry under each card. */
  sessionKey?: string | null;
  t?: number;
  units?: Settings["units"];
}

/** DRS codes in the feed: 8 is within a second with the flap shut; 10 and up is open. */
export function drsLabel(code: number | null | undefined, hasDrs: boolean): { text: string; state: string } {
  if (!hasDrs) return { text: "—", state: "none" };
  if (code == null) return { text: "—", state: "none" };
  if (code >= 10) return { text: "DRS open", state: "open" };
  if (code >= 8) return { text: "DRS eligible", state: "eligible" };
  return { text: "DRS off", state: "off" };
}

/**
 * Overtake mode, the 2026 successor to DRS. The feed never says when a driver
 * used it, so this is whether they could have: race control had it on, and
 * they were within a second of the car ahead at the last timing line.
 */
export function overtakeLabel(status: DriverTiming["overtake"]): { text: string; state: string } {
  if (status === "eligible") return { text: "Overtake eligible", state: "eligible" };
  if (status === "disabled") return { text: "Overtake off", state: "off" };
  if (status === "not_eligible") return { text: "Not eligible", state: "none" };
  return { text: "—", state: "none" };
}

/**
 * A card for each followed driver: where they stand (position, tyre, the cars
 * either side), what the car is doing now (speed, gear, DRS or overtake mode),
 * and the last half-minute of speed, throttle and brake beneath. Gaps are the
 * timing's, exact at each crossing of the line; the telemetry is the car's
 * own, at the clock's time.
 */
export const DriverCards = memo(function DriverCards({ selected, drivers, cars, hasDrs, hasOvertake = false,
                                                        onUnpick, sessionKey = null, t = 0, units = "metric" }: Props) {
  if (!selected.length) {
    return <p className="cards-empty">Click a driver in the timing tower to follow them here, up to two.</p>;
  }
  const byNumber = new Map(drivers.map((driver, index) => [driver.driver_number, index]));
  return (
    <div className="driver-cards">
      {selected.slice(-MAX_FOLLOWED).map((number) => {
        const index = byNumber.get(number);
        const driver = index === undefined ? undefined : drivers[index];
        return (
          <DriverCard key={number} number={number} driver={driver}
                      ahead={index !== undefined && index > 0 ? drivers[index - 1] : undefined}
                      behind={index !== undefined ? drivers[index + 1] : undefined}
                      car={cars[String(number)] ?? {}} hasDrs={hasDrs} hasOvertake={hasOvertake}
                      onUnpick={onUnpick} sessionKey={sessionKey} t={t} units={units} />
        );
      })}
    </div>
  );
});

function DriverCard({ number, driver, ahead, behind, car, hasDrs, hasOvertake, onUnpick, sessionKey, t, units }: {
  number: number;
  driver: DriverTiming | undefined;
  ahead: DriverTiming | undefined;
  behind: DriverTiming | undefined;
  car: Partial<CarState>;
  hasDrs: boolean;
  hasOvertake: boolean;
  onUnpick: (driverNumber: number) => void;
  sessionKey: string | null;
  t: number;
  units: Settings["units"];
}) {
  const { trace } = useRecent(sessionKey, number, t);
  const speed = speedIn(car.speed, units);
  const code = driver?.abbreviation ?? String(number);
  const aid = !hasDrs && hasOvertake ? overtakeLabel(driver?.overtake) : drsLabel(car.drs, hasDrs);
  const colour = `#${driver?.team_color ?? "555555"}`;
  return (
    <article className="driver-card" aria-label={`${code} telemetry`}>
      <header className="card-head">
        <span className="card-team-bar" style={{ background: colour }} />
        <span className="card-pos">{driver ? `P${driver.position}` : "—"}</span>
        <span className="card-code display">{code}</span>
        <span className="card-team">{driver?.team_name ?? ""}</span>
        {driver?.compound && (
          <span className="card-tyre">
            <span className="tyre-chip small" style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}>
              {driver.compound[0]}
            </span>
            {driver.tyre_life != null ? `${driver.tyre_life} laps` : ""}
          </span>
        )}
        <button type="button" className="card-close" onClick={() => onUnpick(number)}
                aria-label={`Stop following ${code}`}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </header>
      <div className="card-now">
        <div className="card-speed display">
          {speed.value}<small> {speed.unit}</small>
        </div>
        <div className="card-gear">
          <span>Gear</span>
          <b className="display">{car.gear != null ? Math.round(car.gear) : "—"}</b>
        </div>
        <div className="card-gaps">
          <span className={`aid is-${aid.state}`}
                title={!hasDrs && hasOvertake ? "Estimated from the timing gap: the feed does not say when it was used" : undefined}>
            {aid.text}
          </span>
          <span className="num">{ahead ? `Ahead ${ahead.abbreviation ?? ahead.driver_number}` : "Ahead"} {driver?.interval_text || "—"}</span>
          <span className="num">{behind ? `Behind ${behind.abbreviation ?? behind.driver_number}` : "Behind"} {behind?.interval_text || "—"}</span>
        </div>
      </div>
      <PedalTrace trace={trace} code={code} />
    </article>
  );
}
