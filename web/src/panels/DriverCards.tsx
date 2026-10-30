import { memo } from "react";
import { COMPOUND_COLORS, type CarState, type DriverTiming } from "../api";
import { speedIn, type Settings } from "../settings";
import { useTelemetry } from "../telemetryData";

/** How many drivers can be followed at once: a dashboard each. */
export const MAX_FOLLOWED = 2;

/** The regulated rev limit, the full scale of the RPM bar (Technical Regulations, 15,000 rpm). */
export const RPM_LIMIT = 15000;

interface Props {
  /** Followed drivers, oldest first; a dashboard each, the newest two. */
  selected: number[];
  drivers: DriverTiming[];
  cars: Record<string, CarState>;
  /** False when the session has no DRS (2026, or DRS disabled throughout). */
  hasDrs: boolean;
  /** True when the session has overtake mode instead (2026 on). */
  hasOvertake?: boolean;
  onUnpick: (driverNumber: number) => void;
  /** For the car's own telemetry, read at each frame of the clock. */
  sessionKey?: string | null;
  t?: number;
  units?: Settings["units"];
  /** Playback speed, so the telemetry is fetched far enough ahead to keep up. */
  playbackSpeed?: number;
  /** One dashboard only, for a place of its own in the replay's grid: 0 the older followed, 1 the newer. */
  slot?: 0 | 1;
  /** Full names by number, for the dashboard's header. */
  names?: Record<number, string>;
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
 * A dashboard for each followed driver, read like a steering wheel: speed,
 * gear, revs, throttle and brake now; where they stand (position, tyre, the
 * cars either side, DRS or overtake mode). The lap's traces are in the
 * telemetry strip beside the dashboards. Gaps are the timing's, exact at each crossing of
 * the line; the telemetry is the car's own, at the clock's time. No shift
 * lights: the feed gives revs but not where each car changes gear.
 */
export const DriverCards = memo(function DriverCards(props: Props) {
  const { selected, drivers, slot } = props;
  const shown = selected.slice(-MAX_FOLLOWED);
  const byNumber = new Map(drivers.map((driver, index) => [driver.driver_number, index]));
  const card = (number: number) => {
    const index = byNumber.get(number);
    const driver = index === undefined ? undefined : drivers[index];
    return (
      <DriverCard key={number} number={number} driver={driver}
                  ahead={index !== undefined && index > 0 ? drivers[index - 1] : undefined}
                  behind={index !== undefined ? drivers[index + 1] : undefined}
                  car={props.cars[String(number)] ?? {}} hasDrs={props.hasDrs} hasOvertake={props.hasOvertake ?? false}
                  onUnpick={props.onUnpick} sessionKey={props.sessionKey ?? null} t={props.t ?? 0}
                  units={props.units ?? "metric"} playbackSpeed={props.playbackSpeed ?? 1} name={props.names?.[number]} />
    );
  };
  if (slot !== undefined) {
    const number = shown[slot];
    if (number !== undefined) return card(number);
    return (
      <section className="panel dash-empty" aria-label={`Driver ${slot === 0 ? "A" : "B"}`}>
        <p className="cards-empty">
          {slot === 0 || shown.length === 0 ? "Click a driver in the timing tower to follow them here, up to two." : "Follow a second driver to compare them here."}
        </p>
      </section>
    );
  }
  if (!shown.length) {
    return <p className="cards-empty">Click a driver in the timing tower to follow them here, up to two.</p>;
  }
  return <div className="driver-cards">{shown.map(card)}</div>;
});

function DriverCard({ number, driver, ahead, behind, car, hasDrs, hasOvertake, onUnpick, sessionKey, t, units,
                      playbackSpeed, name }: {
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
  playbackSpeed: number;
  name?: string;
}) {
  const { now } = useTelemetry(sessionKey, number, t, playbackSpeed);
  // Speed, gear and pedals from the buffered telemetry, read at this very
  // frame; the state's own figures, a few times a second, until it arrives.
  const speed = speedIn(now?.speed ?? car.speed, units);
  const gear = now?.gear ?? car.gear;
  const throttle = now?.throttle ?? car.throttle ?? null;
  const braking = Boolean(now?.brake ?? car.brake);
  const rpm = car.rpm ?? null;
  const code = driver?.abbreviation ?? String(number);
  const aid = !hasDrs && hasOvertake ? overtakeLabel(driver?.overtake) : drsLabel(car.drs, hasDrs);
  const colour = `#${driver?.team_color ?? "555555"}`;
  const pct = (value: number) => `${Math.max(0, Math.min(100, value))}%`;
  return (
    <article className="panel driver-card" aria-label={`${code} telemetry`} style={{ ["--team" as string]: colour }}>
      <header className="card-head">
        <span className="card-pos">{driver ? `P${driver.position}` : "—"}</span>
        <span className="card-team-bar" />
        <span className="card-who">
          <span className="card-code">{code} <small>#{number}</small></span>
          <span className="card-team">{[name, driver?.team_name].filter(Boolean).join(" · ")}</span>
        </span>
        {driver?.compound && (
          <span className="card-tyre">
            <span className="tyre-chip small" style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}>
              {driver.compound[0]}
            </span>
            {driver.tyre_life != null ? `${driver.tyre_life} L` : ""}
          </span>
        )}
        <button type="button" className="card-close" onClick={() => onUnpick(number)}
                aria-label={`Stop following ${code}`}>
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
            <path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </button>
      </header>
      <div className="card-body">
        <div className="card-now">
          <div className="card-speed num">{speed.value}<small> {speed.unit}</small></div>
          <div className="card-gear"><span>Gear</span><b>{gear != null ? Math.round(gear) : "—"}</b></div>
        </div>
        <div className="card-meters">
          <span className="cap">RPM</span>
          <span className="meter" title={`Full scale: the ${RPM_LIMIT.toLocaleString("en")} rpm limit`}>
            <i style={{ width: rpm == null ? "0%" : pct((rpm / RPM_LIMIT) * 100), background: "#A78BFA" }} />
          </span>
          <span className="num meter-value">{rpm == null ? "—" : Math.round(rpm).toLocaleString("en")}</span>
          <span className="cap">Throttle</span>
          <span className="meter"><i style={{ width: throttle == null ? "0%" : pct(throttle), background: "#22C55E" }} /></span>
          <span className="num meter-value">{throttle == null ? "—" : `${Math.round(throttle)}%`}</span>
          <span className="cap">Brake</span>
          <span className="meter"><i style={{ width: braking ? "100%" : "0%", background: "#EF4444" }} /></span>
          <span className={`num meter-value${braking ? " is-on" : ""}`}>{braking ? "ON" : "OFF"}</span>
        </div>
        <div className="card-gaps">
          <div><span className="cap">Ahead</span>
            <b className="num">{ahead ? `${ahead.abbreviation ?? ahead.driver_number} ${driver?.interval_text || "—"}` : "—"}</b></div>
          <div><span className="cap">Behind</span>
            <b className="num">{behind ? `${behind.abbreviation ?? behind.driver_number} ${behind.interval_text || "—"}` : "—"}</b></div>
          <div><span className="cap">{!hasDrs && hasOvertake ? "Overtake" : "DRS"}</span>
            <b className={`aid is-${aid.state}`}
               title={!hasDrs && hasOvertake ? "Estimated from the timing gap: the feed does not say when it was used" : undefined}>
              {aid.text.replace(/^(Overtake|DRS) /, "").replace(/^./, (c) => c.toUpperCase())}
            </b></div>
        </div>
      </div>
    </article>
  );
}
