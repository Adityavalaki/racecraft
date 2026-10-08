import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { api, formatLapTime, type LapComparison, type LapTrace } from "../api";
import { FLAT_OUT } from "../panels/TrackMap";
import type { ScreenContext } from "./ScreenView";

const isAbort = (e: Error) => e.name === "AbortError";
const comparisons = new Map<string, LapComparison>();

/** Where the reference is drawn: grey and dashed, behind the subject. */
const REFERENCE = "#9A9AA6";

/**
 * Pedals and speed: one lap of one driver against another's, metre for metre.
 *
 * The subject's lap and the reference's are laid along the subject's distance,
 * with the time between them on top: speed, throttle, the brake (on or off,
 * which is all the public feed says) and gear beneath, the corners marked
 * along the top. A cursor runs through every trace and the pedal map, and the
 * brake zones are listed corner by corner, the reference's beside each.
 */
export function PedalsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const order = ctx.state?.drivers ?? [];
  const running = order.filter((d) => d.laps_completed > 0);
  const [subject, setSubject] = useState<number | null>(null);
  const [reference, setReference] = useState<number | null>(null);
  const [lap, setLap] = useState<number | null>(null);
  const [ghost, setGhost] = useState(true);
  const [cursor, setCursor] = useState(0);
  const [answer, setAnswer] = useState<LapComparison | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Defaults: the followed drivers, else the top two; the subject's last full lap.
  const subjectNumber = subject ?? ctx.selected[0] ?? running[0]?.driver_number ?? null;
  const referenceNumber = reference ?? ctx.selected.find((n) => n !== subjectNumber)
    ?? running.find((d) => d.driver_number !== subjectNumber)?.driver_number ?? null;
  const subjectTiming = order.find((d) => d.driver_number === subjectNumber);
  const lastLap = subjectTiming?.laps_completed ?? 0;
  const lapNumber = lap != null && lap <= lastLap ? lap : lastLap || null;

  useEffect(() => {
    setError(null);
    if (subjectNumber == null || referenceNumber == null || lapNumber == null) {
      setAnswer(null);
      return;
    }
    const key = `${ctx.session}:${subjectNumber}:${referenceNumber}:${lapNumber}`;
    const cached = comparisons.get(key);
    if (cached) {
      setAnswer(cached);
      return;
    }
    const controller = new AbortController();
    const referenceLaps = order.find((d) => d.driver_number === referenceNumber)?.laps_completed ?? 0;
    api.compare(ctx.session, subjectNumber, referenceNumber,
                { lap: lapNumber, refLap: referenceLaps >= lapNumber ? lapNumber : undefined,
                  t: referenceLaps >= lapNumber ? undefined : ctx.t }, controller.signal)
      .then((next) => {
        // An error body is JSON too: the shape is checked rather than assumed.
        if (!next || !Array.isArray(next.subject?.distance) || !Array.isArray(next.reference?.distance) || !next.delta) {
          setAnswer(null);
          setError("The two laps came back in a shape this screen cannot read.");
          return;
        }
        comparisons.set(key, next);
        setAnswer(next);
      })
      .catch((e: Error) => {
        if (!isAbort(e)) {
          setAnswer(null);
          setError(e.message);
        }
      });
    return () => controller.abort();
    // The reference's lap count only decides which lap to ask for; it is read, not followed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ctx.session, subjectNumber, referenceNumber, lapNumber]);

  const code = (n: number | null) => (n == null ? "—" : ctx.driverCodes[n] ?? String(n));
  const colour = (n: number | null) => `#${order.find((d) => d.driver_number === n)?.team_color ?? "777"}`;
  const pickers = (
    <div className="pedal-pickers">
      <label className="pick">
        <span className="visually-hidden">Lap</span>
        <select value={lapNumber ?? ""} onChange={(e) => setLap(Number(e.target.value))} aria-label="Lap">
          {Array.from({ length: lastLap }, (_, i) => lastLap - i).map((n) => <option key={n} value={n}>Lap {n}</option>)}
        </select>
      </label>
      <DriverPick label="Subject driver" value={subjectNumber} drivers={running} codes={ctx.driverCodes}
                  colour={colour(subjectNumber)} onChange={setSubject} />
      <button type="button" className="icon-button" aria-label="Swap subject and reference driver"
              onClick={() => { setSubject(referenceNumber); setReference(subjectNumber); }}>
        <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
          <path d="M3 5h10l-3-3M13 11H3l3 3" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
      <DriverPick label="Reference driver" value={referenceNumber} drivers={running} codes={ctx.driverCodes}
                  colour={colour(referenceNumber)} onChange={setReference} reference />
    </div>
  );

  if (!running.length) {
    return (
      <div className="screen">
        {header(pickers)}
        <main className="screen-body"><p className="panel-note">No lap has been completed yet at this point of the session.</p></main>
      </div>
    );
  }
  return (
    <div className="screen">
      {header(pickers)}
      <main className="screen-body pedals">
        {error && <p className="panel-note error">{error}</p>}
        {!answer && !error && <p className="panel-note">Loading both laps…</p>}
        {answer && (
          <Comparison answer={answer} ghost={ghost} onGhost={() => setGhost((on) => !on)} cursor={cursor}
                      onCursor={setCursor} subjectColour={colour(subjectNumber)} subjectCode={code(subjectNumber)}
                      referenceCode={code(referenceNumber)} rotation={Number(ctx.info.session.circuit_rotation_deg ?? 0)} />
        )}
      </main>
    </div>
  );
}

function DriverPick({ label, value, drivers, codes, colour, onChange, reference = false }: {
  label: string;
  value: number | null;
  drivers: { driver_number: number; team_name: string | null }[];
  codes: Record<number, string>;
  colour: string;
  onChange: (n: number) => void;
  reference?: boolean;
}) {
  return (
    <label className={`pick driver-pick${reference ? " is-reference" : ""}`}>
      <span className="pick-swatch" style={{ background: colour }} aria-hidden="true" />
      <select value={value ?? ""} onChange={(e) => onChange(Number(e.target.value))} aria-label={label}>
        {drivers.map((d) => (
          <option key={d.driver_number} value={d.driver_number}>
            {codes[d.driver_number] ?? d.driver_number}{reference ? " · reference" : d.team_name ? ` · ${d.team_name}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Corner labels far enough apart to read: one closer than 1.8% of the lap to the last shown is skipped. */
function spacedCorners(corners: LapTrace["corners"], length: number) {
  const out: LapTrace["corners"] = [];
  for (const c of corners) {
    const last = out[out.length - 1];
    if (!last || (c.distance - last.distance) / length >= 0.018) out.push(c);
  }
  return out;
}

/** Which value of a lap sits at a distance along it, by nearest sample. */
function at(trace: LapTrace, metres: number): number {
  return Math.min(trace.distance.length - 1, Math.max(0, Math.round(metres / trace.step_m)));
}

function Comparison({ answer, ghost, onGhost, cursor, onCursor, subjectColour, subjectCode, referenceCode, rotation }: {
  answer: LapComparison;
  ghost: boolean;
  onGhost: () => void;
  cursor: number;
  onCursor: (metres: number) => void;
  subjectColour: string;
  subjectCode: string;
  referenceCode: string;
  rotation: number;
}) {
  const { subject, reference, delta } = answer;
  const length = subject.length_m;
  const stretch = length / Math.max(reference.length_m, 1);
  const x = (metres: number) => (metres / length) * 1000;
  const refX = (metres: number) => x(metres * stretch);
  const metres = Math.min(Math.max(cursor, 0), length);
  const i = at(subject, metres);
  const j = at(reference, metres / stretch);

  const paths = useMemo(() => {
    const line = (trace: LapTrace, xs: (m: number) => number, value: (k: number) => number) =>
      trace.distance.map((d, k) => `${k ? "L" : "M"}${xs(d).toFixed(1)} ${value(k).toFixed(1)}`).join("");
    const speedY = (v: number) => 168 - ((Math.min(Math.max(v, 40), 350) - 40) / 310) * 160;
    const throttleY = (v: number) => 86 - (Math.min(Math.max(v, 0), 100) / 100) * 80;
    const gearY = (g: number) => 66 - (Math.min(Math.max(g, 1), 8) - 1) / 7 * 58;
    const blocks = (trace: LapTrace, xs: (m: number) => number, top: number, bottom: number) => {
      let d = "";
      let start = -1;
      trace.brake.forEach((on, k) => {
        if (on && start < 0) start = k;
        if ((!on || k === trace.brake.length - 1) && start >= 0) {
          d += `M${xs(trace.distance[start]!).toFixed(1)} ${top}H${xs(trace.distance[k]!).toFixed(1)}V${bottom}H${xs(trace.distance[start]!).toFixed(1)}Z`;
          start = -1;
        }
      });
      return d;
    };
    const maxDelta = Math.max(0.1, ...delta.delta_s.map((v) => Math.abs(v)));
    // Ahead (negative) is up, behind is down.
    const deltaY = (v: number) => 42 + (v / maxDelta) * 36;
    return {
      maxDelta,
      delta: delta.distance.map((d, k) => `${k ? "L" : "M"}${x(d).toFixed(1)} ${deltaY(delta.delta_s[k]!).toFixed(1)}`).join(""),
      speed: line(subject, x, (k) => speedY(subject.speed[k]!)),
      speedRef: line(reference, refX, (k) => speedY(reference.speed[k]!)),
      throttle: line(subject, x, (k) => throttleY(subject.throttle[k]!)),
      throttleRef: line(reference, refX, (k) => throttleY(reference.throttle[k]!)),
      gear: line(subject, x, (k) => gearY(subject.gear[k]!)),
      gearRef: line(reference, refX, (k) => gearY(reference.gear[k]!)),
      brake: blocks(subject, x, 8, 30),
      brakeRef: blocks(reference, refX, 36, 52),
    };
    // x and refX follow from the two lengths, which `answer` fixes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answer]);

  const gapNow = delta.delta_s[i] ?? 0;
  const scrub = (event: MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    onCursor(((event.clientX - box.left) / box.width) * length);
  };
  const corner = [...subject.corners].reverse().find((c) => c.distance <= metres + 60);

  return (
    <>
      <div className="pedals-grid">
        <section className="panel pedal-traces" aria-label="Lap traces">
          <div className="panel-bar">
            <h2>Traces by distance</h2>
            <span className="legend"><i className="is-speed" />Speed</span>
            <span className="legend"><i className="is-throttle" />Throttle</span>
            <span className="legend"><i className="is-brake" />Brake</span>
            <span className="legend"><i className="is-reference" />{referenceCode}, reference</span>
            <button type="button" className={`toggle${ghost ? " is-on" : ""}`} aria-pressed={ghost} onClick={onGhost}>
              Show reference lap
            </button>
          </div>
          <div className="trace-stack" onMouseMove={scrub} onClick={scrub}>
            <div className="trace-row corners-row">
              <span className="trace-name">Turn</span>
              <div className="trace-plot corners">
                {spacedCorners(subject.corners, length).map((c) => (
                  <span key={`${c.number}${c.letter ?? ""}`} style={{ left: `${(c.distance / length) * 100}%` }}>
                    {c.number}{c.letter ?? ""}
                  </span>
                ))}
              </div>
            </div>
            <TraceRow name="Gap" unit={`${subjectCode} vs ${referenceCode}`} height={84}
                      label={`Time gap between the two laps: ${subjectCode} ${gapNow <= 0 ? "ahead" : "behind"} by ${Math.abs(gapNow).toFixed(3)} s here`}>
              <line x1="0" x2="1000" y1="42" y2="42" stroke="#45454F" strokeWidth="1" vectorEffect="non-scaling-stroke" />
              <path d={paths.delta} fill="none" stroke="var(--ink)" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
              <text x="4" y="12" className="axis-note">{subjectCode} ahead by {paths.maxDelta.toFixed(2)} s</text>
              <text x="4" y="80" className="axis-note">{subjectCode} behind by {paths.maxDelta.toFixed(2)} s</text>
            </TraceRow>
            <TraceRow name="Speed" unit="km/h" height={176} label="Speed against distance">
              {ghost && <path d={paths.speedRef} fill="none" stroke={REFERENCE} strokeWidth="1.4" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
              <path d={paths.speed} fill="none" stroke="var(--speed)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </TraceRow>
            <TraceRow name="Throttle" unit="% open" height={92} label="Throttle against distance">
              {ghost && <path d={paths.throttleRef} fill="none" stroke={REFERENCE} strokeWidth="1.3" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
              <path d={paths.throttle} fill="none" stroke="var(--throttle)" strokeWidth="1.8" vectorEffect="non-scaling-stroke" />
            </TraceRow>
            <TraceRow name="Brake" unit="on or off" height={60} label="Brake on and off against distance">
              <path d={paths.brake} fill="var(--brake)" />
              {ghost && <path d={paths.brakeRef} fill={REFERENCE} opacity="0.7" />}
            </TraceRow>
            <TraceRow name="Gear" unit="1 to 8" height={72} label="Gear against distance">
              {ghost && <path d={paths.gearRef} fill="none" stroke={REFERENCE} strokeWidth="1.3" strokeDasharray="5 4" vectorEffect="non-scaling-stroke" />}
              <path d={paths.gear} fill="none" stroke="var(--ink-mid)" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
            </TraceRow>
            <div className="trace-cursor" style={{ left: `calc(var(--trace-name-w) + (100% - var(--trace-name-w)) * ${metres / length})` }}
                 aria-hidden="true"><span className="num">{Math.round(metres)} m</span></div>
          </div>
          <div className="cursor-control">
            <label htmlFor="pedal-cursor">Cursor</label>
            <input id="pedal-cursor" type="range" min={0} max={Math.round(length)} step={5} value={Math.round(metres)}
                   onChange={(e) => onCursor(Number(e.target.value))} aria-label="Cursor position along the lap in metres" />
          </div>
        </section>

        <div className="pedals-side">
          <PedalMap trace={subject} cursor={i} rotation={rotation} code={subjectCode} />
          <section className="panel at-cursor" aria-label="At the cursor">
            <div className="panel-bar">
              <h2>At the cursor</h2>
              <span className="panel-meta num">{Math.round(metres)} m{corner ? ` · after turn ${corner.number}${corner.letter ?? ""}` : ""}</span>
            </div>
            <div className="at-cursor-body">
              <CursorCar code={subjectCode} colour={subjectColour} role="Subject" trace={subject} k={i} />
              <CursorCar code={referenceCode} colour={REFERENCE} role="Reference" trace={reference} k={j} />
              <div className="cursor-gap">
                <span>Gap at this point</span>
                <span className={`num ${gapNow <= 0 ? "is-better" : "is-worse"}`}>
                  {subjectCode} {gapNow <= 0 ? "ahead" : "behind"} by {Math.abs(gapNow).toFixed(3)} s
                </span>
              </div>
            </div>
          </section>
        </div>
      </div>

      <div className="screen-columns">
        <BrakeZones subject={subject} reference={reference} stretch={stretch} subjectCode={subjectCode}
                    referenceCode={referenceCode} onCursor={onCursor} />
        <LapSummary subject={subject} reference={reference} subjectCode={subjectCode} referenceCode={referenceCode}
                    finalGap={delta.final_s} />
      </div>
    </>
  );
}

function TraceRow({ name, unit, height, label, children }: {
  name: string; unit: string; height: number; label: string; children: ReactNode;
}) {
  return (
    <div className="trace-row">
      <span className="trace-name">{name}<small>{unit}</small></span>
      <svg className="trace-plot" viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none" style={{ height }}
           role="img" aria-label={label}>
        {children}
      </svg>
    </div>
  );
}

function CursorCar({ code, colour, role, trace, k }: { code: string; colour: string; role: string; trace: LapTrace; k: number }) {
  const braking = trace.brake[k];
  return (
    <div className="cursor-car">
      <div className="cursor-car-head">
        <span className="pick-swatch" style={{ background: colour }} aria-hidden="true" />
        <span className="display">{code}</span>
        <span className="cursor-role">{role}</span>
      </div>
      <div className="cursor-figures">
        <span className="display cursor-speed">{Math.round(trace.speed[k] ?? 0)}<small> km/h</small></span>
        <span className="cursor-gear"><span>Gear</span><b className="display">{trace.gear[k] ?? "—"}</b></span>
      </div>
      <div className="cursor-bars">
        <span>Throttle</span>
        <span className="bar"><i className="is-throttle" style={{ width: `${trace.throttle[k] ?? 0}%` }} /></span>
        <span className="num">{Math.round(trace.throttle[k] ?? 0)}%</span>
        <span>Brake</span>
        <span className="bar"><i className="is-brake" style={{ width: braking ? "100%" : "0%" }} /></span>
        <span className="num">{braking ? "On" : "Off"}</span>
      </div>
    </div>
  );
}

/**
 * The subject's lap on the circuit: green where the throttle was flat out,
 * red where the brake was on, the plain track where it lifted or was part
 * throttle. The dot is the cursor.
 */
export function PedalMap({ trace, cursor, rotation, code }: { trace: LapTrace; cursor: number; rotation: number; code: string }) {
  const shape = useMemo(() => {
    const rad = (rotation * Math.PI) / 180;
    const pts = trace.x.map((x, k) => {
      const y = trace.y[k];
      if (x == null || y == null) return null;
      return [x * Math.cos(rad) - y * Math.sin(rad), x * Math.sin(rad) + y * Math.cos(rad)] as const;
    });
    const real = pts.filter((p): p is readonly [number, number] => p !== null);
    if (real.length < 10) return null;
    const xs = real.map((p) => p[0]);
    const ys = real.map((p) => p[1]);
    const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
    const scale = Math.min(500 / (maxX - minX || 1), 360 / (maxY - minY || 1));
    const width = (maxX - minX) * scale + 40;
    const height = (maxY - minY) * scale + 40;
    const project = (p: readonly [number, number]) => [20 + (p[0] - minX) * scale, height - 20 - (p[1] - minY) * scale] as const;
    const path = (on: (k: number) => boolean) => {
      let d = "";
      let open = false;
      pts.forEach((p, k) => {
        if (!p || !on(k)) {
          open = false;
          return;
        }
        const [px, py] = project(p);
        d += `${open ? "L" : "M"}${px.toFixed(1)} ${py.toFixed(1)}`;
        open = true;
      });
      return d;
    };
    return {
      width, height, project, pts,
      base: path(() => true),
      throttle: path((k) => (trace.throttle[k] ?? 0) >= FLAT_OUT),
      brake: path((k) => Boolean(trace.brake[k])),
    };
  }, [trace, rotation]);

  const point = shape?.pts[cursor] ? shape.project(shape.pts[cursor]!) : null;
  return (
    <section className="panel pedal-map-panel" aria-label="Pedal map">
      <div className="panel-bar">
        <h2>Pedal map</h2>
        <span className="panel-meta">{code}, lap {trace.lap}</span>
      </div>
      {shape ? (
        <svg className="pedal-map" viewBox={`0 0 ${shape.width.toFixed(0)} ${shape.height.toFixed(0)}`} role="img"
             aria-label={`${code}'s lap ${trace.lap} coloured by throttle and brake`}>
          <path d={shape.base} fill="none" stroke="#1E1E24" strokeWidth="14" strokeLinejoin="round" strokeLinecap="round" />
          <path d={shape.base} fill="none" stroke="#62626E" strokeWidth="2" strokeLinejoin="round" />
          <path d={shape.throttle} fill="none" stroke="var(--throttle)" strokeWidth="4.5" strokeLinecap="round" strokeLinejoin="round" />
          <path d={shape.brake} fill="none" stroke="var(--brake)" strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
          {point && <circle cx={point[0]} cy={point[1]} r="7" fill="var(--ink)" stroke="#0A0A0C" strokeWidth="2" />}
        </svg>
      ) : (
        <p className="panel-note">No position data for this lap.</p>
      )}
      <div className="map-legend">
        <span><i className="is-throttle" />Full throttle</span>
        <span><i className="is-brake" />Braking</span>
        <span><i className="is-lift" />Lift or partial</span>
      </div>
    </section>
  );
}

/** The reference's zone matching one of the subject's: the one starting nearest, within 150 m. */
function matchZone(start: number, zones: LapTrace["brake_zones"], stretch: number) {
  let best: LapTrace["brake_zones"][number] | null = null;
  let gap = 150;
  for (const zone of zones) {
    const d = Math.abs(zone.start_m * stretch - start);
    if (d < gap) {
      gap = d;
      best = zone;
    }
  }
  return best;
}

function BrakeZones({ subject, reference, stretch, subjectCode, referenceCode, onCursor }: {
  subject: LapTrace; reference: LapTrace; stretch: number; subjectCode: string; referenceCode: string;
  onCursor: (m: number) => void;
}) {
  return (
    <section className="panel brake-zones" aria-label="Brake zones">
      <div className="panel-bar">
        <h2>Brake zones</h2>
        <span className="panel-meta">Every time {subjectCode} was on the brake, with {referenceCode} alongside.</span>
      </div>
      <table className="zones-table">
        <thead>
          <tr>
            <th scope="col">Turn</th><th scope="col">Brake point</th><th scope="col">Entry</th><th scope="col">Minimum</th>
            <th scope="col">On brake</th><th scope="col">{referenceCode} brake point</th><th scope="col">{referenceCode} minimum</th>
          </tr>
        </thead>
        <tbody>
          {subject.brake_zones.map((zone) => {
            const turn = subject.corners.find((c) => c.distance >= zone.start_m - 40);
            const ref = matchZone(zone.start_m, reference.brake_zones, stretch);
            const refPoint = ref ? ref.start_m * stretch : null;
            // Braking later, and carrying more speed through, is the better of the two.
            const pointTone = refPoint == null ? "" : zone.start_m > refPoint + 5 ? "is-better" : zone.start_m < refPoint - 5 ? "is-worse" : "";
            const minTone = ref == null ? "" : zone.min_speed > ref.min_speed + 2 ? "is-better" : zone.min_speed < ref.min_speed - 2 ? "is-worse" : "";
            return (
              <tr key={zone.start_m} onClick={() => onCursor(zone.start_m)} className="num">
                <th scope="row">{turn ? `T${turn.number}${turn.letter ?? ""}` : "—"}</th>
                <td className={pointTone}>{Math.round(zone.start_m)} m</td>
                <td>{Math.round(zone.entry_speed)} km/h</td>
                <td className={minTone}>{Math.round(zone.min_speed)} km/h</td>
                <td>{zone.duration_s.toFixed(2)} s</td>
                <td>{refPoint == null ? "—" : `${Math.round(refPoint)} m`}</td>
                <td>{ref ? `${Math.round(ref.min_speed)} km/h` : "—"}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="panel-note">Brake is on or off in the feed, so these show where and for how long, not how hard.
        Green is the later brake point or the higher minimum speed of the two; yellow the other.</p>
    </section>
  );
}

function LapSummary({ subject, reference, subjectCode, referenceCode, finalGap }: {
  subject: LapTrace; reference: LapTrace; subjectCode: string; referenceCode: string; finalGap: number | null;
}) {
  const rows: [string, (t: LapTrace) => string][] = [
    ["Lap time", (t) => formatLapTime(t.lap_time_s)],
    ["Top speed", (t) => `${Math.round(t.summary.top_speed)} km/h`],
    ["Slowest point", (t) => `${Math.round(t.summary.min_speed)} km/h`],
    ["Flat out", (t) => `${Math.round(t.summary.full_throttle_share * 100)}% of the lap`],
    ["On the brake", (t) => `${Math.round(t.summary.braking_share * 100)}% of the lap`],
    ["Brake zones", (t) => String(t.summary.brake_zones)],
    ["Tyre", (t) => (t.compound ? `${t.compound.toLowerCase()}${t.tyre_life != null ? `, ${t.tyre_life} laps` : ""}` : "—")],
  ];
  return (
    <section className="panel lap-summary" aria-label="Lap summary">
      <div className="panel-bar">
        <h2>Lap summary</h2>
        {finalGap != null && (
          <span className={`panel-meta num ${finalGap <= 0 ? "is-better" : "is-worse"}`}>
            {subjectCode} {finalGap <= 0 ? "quicker" : "slower"} by {Math.abs(finalGap).toFixed(3)} s
          </span>
        )}
      </div>
      <table className="summary-table">
        <thead><tr><th scope="col" /><th scope="col">{subjectCode}, lap {subject.lap}</th><th scope="col">{referenceCode}, lap {reference.lap}</th></tr></thead>
        <tbody>
          {rows.map(([label, value]) => (
            <tr key={label}><th scope="row">{label}</th><td className="num">{value(subject)}</td><td className="num">{value(reference)}</td></tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
