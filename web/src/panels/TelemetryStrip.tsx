import { useHeld } from "../held";
import type { DriverTiming, LapTrace } from "../api";
import { useLapTrace } from "../telemetryData";

interface Props {
  sessionKey: string;
  /** The followed drivers, A then B (up to two). */
  followed: number[];
  drivers: DriverTiming[];
  /** Where each car is on the map now, to place its cursor on its lap. */
  cars: Record<number, { x: number; y: number }>;
}

type Channel = "speed" | "throttle" | "brake" | "gear";
const CHANNELS: { id: Channel; label: string; unit: string; height: number }[] = [
  { id: "speed", label: "Speed", unit: "km/h", height: 100 },
  { id: "throttle", label: "Throttle", unit: "%", height: 60 },
  { id: "brake", label: "Brake", unit: "on/off", height: 30 },
  { id: "gear", label: "Gear", unit: "", height: 60 },
];

/**
 * The followed drivers' last full laps, channel by channel against lap
 * distance: speed, throttle, brake and gear, the corners marked along the top.
 * Each car's cursor is where it is on the map now, found as the nearest point
 * of its lap: so the trace ahead of the cursor is the last lap, not this one.
 */
export function TelemetryStrip({ sessionKey, followed, drivers, cars }: Props) {
  const timing = (n: number | undefined) => (n === undefined ? undefined : drivers.find((d) => d.driver_number === n));
  const a = timing(followed[0]);
  const b = timing(followed[1]);
  const traceA = useLapTrace(sessionKey, a?.driver_number ?? null, a?.laps_completed ?? null).trace;
  const traceB = useLapTrace(sessionKey, b?.driver_number ?? null, b?.laps_completed ?? null).trace;
  const lines = [
    a && traceA ? { driver: a, trace: traceA } : null,
    b && traceB ? { driver: b, trace: traceB } : null,
  ].filter((x): x is { driver: DriverTiming; trace: LapTrace } => x !== null)
    .map((line) => ({ ...line, colour: `#${line.driver.team_color ?? "8E959F"}`, at: cursorIndex(line.trace, cars[line.driver.driver_number]) }));
  const ref = lines[0]?.trace;
  const topSpeed = Math.max(300, ...lines.map((l) => Math.max(...l.trace.speed)));

  return (
    <section className="panel telemetry-strip" aria-label="Telemetry for the followed drivers">
      <div className="panel-bar">
        <h2>Telemetry</h2>
        <span className="panel-meta">Last full lap by distance · cursor where the car is now</span>
        <span className="tel-keys">
          {lines.map((l) => (
            <span key={l.driver.driver_number} className="tel-key num">
              <i style={{ background: l.colour }} />
              <b>{l.driver.abbreviation}</b> L{l.trace.lap}
            </span>
          ))}
        </span>
      </div>
      {lines.length === 0 ? (
        <p className="panel-note">Follow a driver in the timing tower to see their last full lap here, channel by channel.</p>
      ) : (
        <div className="tel-body">
          <div className="tel-ruler" aria-hidden="true">
            {ref?.corners.map((c) => (
              <span key={`${c.number}${c.letter ?? ""}`} style={{ left: `${(c.distance / ref.length_m) * 100}%` }}>
                {c.number}{c.letter ?? ""}
              </span>
            ))}
          </div>
          {CHANNELS.map((ch) => (
            <div key={ch.id} className={`tel-ch tel-${ch.id}`}>
              <div className="tel-label">
                <span className="cap">{ch.label} {ch.unit && <small>{ch.unit}</small>}</span>
                <span className="tel-values num">
                  {lines.map((l) => (
                    <ChannelValue key={l.driver.driver_number} text={valueText(l.trace, ch.id, l.at)} color={l.colour} hold={ch.id === "speed" || ch.id === "throttle"} />
                  ))}
                </span>
              </div>
              <div className="tel-graph">
                {ref?.corners.map((c) => (
                  <span key={`${c.number}${c.letter ?? ""}`} className="tel-grid" style={{ left: `${(c.distance / ref.length_m) * 100}%` }} />
                ))}
                <svg viewBox={`0 0 1000 ${ch.height}`} preserveAspectRatio="none" role="img"
                     aria-label={`${ch.label} through the lap for ${lines.map((l) => l.driver.abbreviation).join(" and ")}`}>
                  {lines.map((l) => (
                    <path key={l.driver.driver_number} d={channelPath(l.trace, ch.id, ch.height, topSpeed)} fill="none"
                          stroke={l.colour} strokeWidth={1.6} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                  ))}
                </svg>
                {lines.map((l) => l.at === null ? null : (
                  <span key={l.driver.driver_number} className="tel-cursor"
                        style={{ left: `${(l.trace.distance[l.at]! / l.trace.length_m) * 100}%`, background: l.colour }} />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** A channel's figure at the cursor: speed and throttle tick once a second to be read; brake and gear are states, and stay live. */
function ChannelValue({ text, color, hold }: { text: string; color: string; hold: boolean }) {
  const held = useHeld(text);
  return <span style={{ color }}>{hold ? held : text}</span>;
}

/** The SVG path of one channel across the lap, in a 1000-wide box `height` tall. */
export function channelPath(trace: LapTrace, channel: Channel, height: number, topSpeed: number): string {
  const pad = height * 0.08;
  const y = (v: number) => {
    const share = channel === "speed" ? v / topSpeed : channel === "throttle" ? v / 100 : channel === "gear" ? (v - 1) / 7 : v;
    return (height - pad - Math.max(0, Math.min(1, share)) * (height - 2 * pad)).toFixed(1);
  };
  const values = trace[channel] as (number | boolean)[];
  return trace.distance
    .map((d, i) => `${i === 0 ? "M" : "L"}${((d / trace.length_m) * 1000).toFixed(1)} ${y(Number(values[i]))}`)
    .join("");
}

/** The index of the lap point nearest the car's position now; null with no position. */
export function cursorIndex(trace: LapTrace, car: { x: number; y: number } | undefined): number | null {
  if (!car) return null;
  let best: number | null = null;
  let bestD = Infinity;
  trace.x.forEach((x, i) => {
    const y = trace.y[i];
    if (x == null || y == null) return;
    const d = (x - car.x) ** 2 + (y - car.y) ** 2;
    if (d < bestD) { bestD = d; best = i; }
  });
  return best;
}

function valueText(trace: LapTrace, channel: Channel, at: number | null): string {
  if (at === null) return "—";
  const v = trace[channel][at];
  if (v === undefined || v === null) return "—";
  if (channel === "brake") return v ? "ON" : "OFF";
  return String(Math.round(Number(v)));
}
