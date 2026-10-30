import { useEffect, useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { api, formatLapTime, type LapComparison, type LapTrace } from "../api";
import type { ScreenContext } from "./ScreenView";

const isAbort = (e: Error) => e.name === "AbortError";
const comparisons = new Map<string, LapComparison>();

/** The reference's colour when both drivers share a team colour. */
const REFERENCE = "#9A9AA6";

/**
 * Pedals and speed: one lap of one driver against another's, metre for metre,
 * as racecraft-ui.html lays it out. Both laps are drawn along the subject's
 * distance in the two drivers' colours: speed, the time between them, the
 * throttle, the brake (on or off, which is all the public feed says) and gear,
 * the corners marked along the top. Beside them the circuit coloured by who
 * gains where, and the corners: minimum speeds and where each began braking.
 */
export function PedalsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const order = ctx.state?.drivers ?? [];
  const running = order.filter((d) => d.laps_completed > 0);
  const [subject, setSubject] = useState<number | null>(null);
  const [reference, setReference] = useState<number | null>(null);
  const [lap, setLap] = useState<number | null>(null);
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
          <Comparison answer={answer} cursor={cursor} onCursor={setCursor} colourA={colour(subjectNumber)}
                      colourB={colour(referenceNumber)} codeA={code(subjectNumber)} codeB={code(referenceNumber)}
                      rotation={Number(ctx.info.session.circuit_rotation_deg ?? 0)} />
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

function Comparison({ answer, cursor, onCursor, colourA, colourB, codeA, codeB, rotation }: {
  answer: LapComparison;
  cursor: number;
  onCursor: (metres: number) => void;
  colourA: string;
  colourB: string;
  codeA: string;
  codeB: string;
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
  // Teammates share a colour: the reference then goes grey, so the two lines stay apart.
  const colourRef = colourB.toLowerCase() === colourA.toLowerCase() ? REFERENCE : colourB;

  const paths = useMemo(() => {
    const line = (trace: LapTrace, xs: (m: number) => number, value: (k: number) => number) =>
      trace.distance.map((d, k) => `${k ? "L" : "M"}${xs(d).toFixed(1)} ${value(k).toFixed(1)}`).join("");
    const speedY = (v: number) => 94 - ((Math.min(Math.max(v, 60), 345) - 60) / 285) * 88;
    const throttleY = (v: number) => 56 - (Math.min(Math.max(v, 0), 100) / 100) * 52;
    const gearY = (g: number) => 54 - ((Math.min(Math.max(g, 1), 8) - 1) / 7) * 48;
    const brakeY = (on: boolean) => (on ? 4 : 26);
    const step = (trace: LapTrace, xs: (m: number) => number) => {
      let d = `M0 ${brakeY(Boolean(trace.brake[0]))}`;
      trace.distance.forEach((m, k) => { d += `H${xs(m).toFixed(1)}V${brakeY(Boolean(trace.brake[k]))}`; });
      return d;
    };
    const maxDelta = Math.max(0.1, ...delta.delta_s.map((v) => Math.abs(v)));
    // Ahead (negative) is up, behind is down.
    const deltaY = (v: number) => 30 + (v / maxDelta) * 26;
    const deltaLine = delta.distance.map((d, k) => `${k ? "L" : "M"}${x(d).toFixed(1)} ${deltaY(delta.delta_s[k]!).toFixed(1)}`).join("");
    return {
      delta: deltaLine,
      deltaFill: delta.distance.length ? `${deltaLine}L${x(delta.distance[delta.distance.length - 1]!).toFixed(1)} 30L0 30Z` : "",
      speed: [line(subject, x, (k) => speedY(subject.speed[k]!)), line(reference, refX, (k) => speedY(reference.speed[k]!))],
      throttle: [line(subject, x, (k) => throttleY(subject.throttle[k]!)), line(reference, refX, (k) => throttleY(reference.throttle[k]!))],
      brake: [step(subject, x), step(reference, refX)],
      gear: [line(subject, x, (k) => gearY(subject.gear[k]!)), line(reference, refX, (k) => gearY(reference.gear[k]!))],
    };
    // x and refX follow from the two lengths, which `answer` fixes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answer]);

  const deltaAt = (m: number) => {
    const n = delta.distance.length;
    if (!n) return 0;
    const stepM = n > 1 ? delta.distance[1]! - delta.distance[0]! : 1;
    return delta.delta_s[Math.min(n - 1, Math.max(0, Math.round(m / (stepM || 1))))] ?? 0;
  };
  const gapNow = deltaAt(metres);
  const speedDiff = (subject.speed[i] ?? 0) - (reference.speed[j] ?? 0);
  const sign = (v: number, digits: number) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)}`;
  const scrub = (event: MouseEvent<HTMLDivElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    onCursor(((event.clientX - box.left) / box.width) * length);
  };
  const final = delta.final_s;
  const finalColour = final == null ? "var(--ink-mid)" : final <= 0 ? colourA : colourRef;
  const cursorLeft = `${(metres / length) * 100}%`;
  const corners = spacedCorners(subject.corners, length);
  const channel = (name: string, unit: string, values: ReactNode, flex: number, label: string, h: number, body: ReactNode) => (
    <div className="pc-ch" style={{ flex: `${flex} 1 0` }}>
      <div className="pc-label"><span className="cap">{name} {unit && <small>{unit}</small>}</span><div className="pc-vals num">{values}</div></div>
      <div className="pc-plot" onClick={scrub}>
        {corners.map((c) => <span key={`${c.number}${c.letter ?? ""}`} className="pc-corner" style={{ left: `${(c.distance / length) * 100}%` }} />)}
        <svg viewBox={`0 0 1000 ${h}`} preserveAspectRatio="none" role="img" aria-label={label}>{body}</svg>
        <span className="pc-cursor" style={{ left: cursorLeft }} aria-hidden="true" />
      </div>
    </div>
  );
  const two = (a: ReactNode, b: ReactNode) => <><span style={{ color: colourA }}>{a}</span><span style={{ color: colourRef }}>{b}</span></>;
  const pair = (ds: string[], width = 1.6) => (
    <>
      <path d={ds[1]} fill="none" stroke={colourRef} strokeWidth={width - 0.1} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
      <path d={ds[0]} fill="none" stroke={colourA} strokeWidth={width + 0.1} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </>
  );

  return (
    <div className="pedals-grid">
      <section className="panel pedal-traces" aria-label="Lap comparison">
        <div className="panel-bar">
          <h2>Lap comparison</h2>
          <span className="panel-meta">by lap distance · click a channel to move the cursor</span>
          <span className="pc-legend num" style={{ marginLeft: "auto" }}><i style={{ background: colourA }} /><b>{codeA}</b><span className="muted">{formatLapTime(subject.lap_time_s)}</span></span>
          <span className="pc-legend num"><i style={{ background: colourRef }} /><b>{codeB}</b><span className="muted">{formatLapTime(reference.lap_time_s)}</span></span>
          {final != null && <span className="pc-chip num" style={{ color: finalColour }}>Δ {sign(final, 3)} s</span>}
        </div>
        <div className="pc-body">
          <div className="pc-ruler num" aria-hidden="true">
            {corners.map((c) => <span key={`${c.number}${c.letter ?? ""}`} style={{ left: `${(c.distance / length) * 100}%` }}>{c.number}{c.letter ?? ""}</span>)}
          </div>
          {channel("Speed", "km/h", two(Math.round(subject.speed[i] ?? 0), Math.round(reference.speed[j] ?? 0)), 2, "Speed against distance", 100, pair(paths.speed, 1.6))}
          {channel("Delta", "s", <span style={{ color: gapNow <= 0 ? colourA : colourRef }}>{sign(gapNow, 3)} s</span>, 1.1,
            `Time between the laps: ${codeA} ${gapNow <= 0 ? "ahead" : "behind"} by ${Math.abs(gapNow).toFixed(3)} s here`, 60,
            <>
              <path d="M0 30H1000" stroke="#FFFFFF" strokeOpacity=".2" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
              <path d={paths.deltaFill} fill={colourA} fillOpacity=".12" />
              <path d={paths.delta} fill="none" stroke="#F2F3F5" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
            </>)}
          {channel("Throttle", "%", two(Math.round(subject.throttle[i] ?? 0), Math.round(reference.throttle[j] ?? 0)), 1, "Throttle against distance", 60, pair(paths.throttle))}
          {channel("Brake", "", two(subject.brake[i] ? "ON" : "OFF", reference.brake[j] ? "ON" : "OFF"), 0.55, "Brake on and off against distance", 30, pair(paths.brake))}
          {channel("Gear", "", two(subject.gear[i] ?? "—", reference.gear[j] ?? "—"), 0.9, "Gear against distance", 60, pair(paths.gear))}
          <div className="pc-axis num" aria-hidden="true">
            {Array.from({ length: Math.floor(length / 1000) + 1 }, (_, km) => (
              <span key={km} style={{ left: `${((km * 1000) / length) * 100}%` }}>{km} km</span>
            ))}
          </div>
          <div className="cursor-control">
            <label htmlFor="pedal-cursor" className="cap">Cursor</label>
            <input id="pedal-cursor" type="range" min={0} max={Math.round(length)} step={5} value={Math.round(metres)}
                   onChange={(e) => onCursor(Number(e.target.value))} aria-label="Cursor position along the lap in metres" />
          </div>
        </div>
      </section>

      <div className="pedals-side">
        <TimeMap answer={answer} cursor={i} rotation={rotation} colourA={colourA} colourB={colourRef} codeA={codeA} codeB={codeB}
                 stats={[["Cursor", `${Math.round(metres)} m`, undefined], ["Δ here", `${sign(gapNow, 3)} s`, gapNow <= 0 ? colourA : colourRef],
                         ["Speed Δ", `${sign(Math.round(speedDiff), 0)} km/h`, undefined]]} />
        <Corners subject={subject} reference={reference} stretch={stretch} codeA={codeA} codeB={codeB}
                 colourA={colourA} colourB={colourRef} onCursor={onCursor} />
      </div>
    </div>
  );
}

/**
 * The subject's lap on the circuit, coloured by who was gaining time there:
 * the subject's colour where the gap to the reference shrinks, the
 * reference's where it grows. The dot is the cursor; three figures at it below.
 */
function TimeMap({ answer, cursor, rotation, colourA, colourB, codeA, codeB, stats }: {
  answer: LapComparison; cursor: number; rotation: number; colourA: string; colourB: string; codeA: string; codeB: string;
  stats: [string, string, string | undefined][];
}) {
  const trace = answer.subject;
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
    const scale = Math.min(760 / (maxX - minX || 1), 260 / (maxY - minY || 1));
    const width = (maxX - minX) * scale + 40;
    const height = (maxY - minY) * scale + 40;
    const project = (p: readonly [number, number]) => [20 + (p[0] - minX) * scale, height - 20 - (p[1] - minY) * scale] as const;
    // The gap at each of the subject's samples; who gains is the gap's slope over a few samples, to steady the colours.
    const { distance, delta_s: gap } = answer.delta;
    const stepM = distance.length > 1 ? distance[1]! - distance[0]! : 1;
    const gapAt = (m: number) => gap[Math.min(gap.length - 1, Math.max(0, Math.round(m / (stepM || 1))))] ?? 0;
    const gains = trace.distance.map((m) => gapAt(m + 3 * trace.step_m) - gapAt(m - 3 * trace.step_m) < 0);
    let base = "", a = "", b = "";
    pts.forEach((p, k) => {
      const q = pts[k + 1];
      if (!p || !q) return;
      const [x1, y1] = project(p);
      const [x2, y2] = project(q);
      const seg = `M${x1.toFixed(1)} ${y1.toFixed(1)}L${x2.toFixed(1)} ${y2.toFixed(1)}`;
      base += seg;
      if (gains[k]) a += seg; else b += seg;
    });
    return { width, height, project, pts, base, a, b };
  }, [answer, trace, rotation]);

  const point = shape?.pts[cursor] ? shape.project(shape.pts[cursor]!) : null;
  return (
    <section className="panel time-map" aria-label="Where the time goes">
      <div className="panel-bar">
        <h2>Where the time goes</h2>
        <span className="pc-legend" style={{ marginLeft: "auto" }}><i style={{ background: colourA }} />{codeA} faster</span>
        <span className="pc-legend"><i style={{ background: colourB }} />{codeB} faster</span>
      </div>
      <div className="time-map-body">
        {shape ? (
          <svg viewBox={`0 0 ${shape.width.toFixed(0)} ${shape.height.toFixed(0)}`} role="img"
               aria-label={`${codeA}'s lap ${trace.lap}, coloured by where ${codeA} or ${codeB} gained time`}>
            <path d={shape.base} fill="none" stroke="#2C333D" strokeWidth="20" strokeLinejoin="round" strokeLinecap="round" />
            <path d={shape.a} fill="none" stroke={colourA} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
            <path d={shape.b} fill="none" stroke={colourB} strokeWidth="9" strokeLinecap="round" strokeLinejoin="round" />
            {point && <circle cx={point[0]} cy={point[1]} r="7" fill="#F2F3F5" stroke="#07080A" strokeWidth="2" />}
          </svg>
        ) : (
          <p className="panel-note">No position data for this lap.</p>
        )}
      </div>
      <div className="time-map-stats">
        {stats.map(([label, value, colour]) => (
          <div key={label}><span className="cap">{label}</span><b className="num" style={colour ? { color: colour } : undefined}>{value}</b></div>
        ))}
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

/**
 * Corner by corner, every time the subject was on the brake: both drivers'
 * minimum speed, the difference, and where each began braking. Braking later
 * and carrying more speed through are the better of the two. Brake is on or
 * off in the feed, so this says where, not how hard. Click a row to put the
 * cursor there.
 */
function Corners({ subject, reference, stretch, codeA, codeB, colourA, colourB, onCursor }: {
  subject: LapTrace; reference: LapTrace; stretch: number; codeA: string; codeB: string; colourA: string; colourB: string;
  onCursor: (m: number) => void;
}) {
  return (
    <section className="panel pc-corners" aria-label="Corners">
      <div className="panel-bar"><h2>Corners</h2><span className="panel-meta">minimum speed · where braking starts</span></div>
      <div className="pc-corners-scroll">
        <table className="pc-table">
          <thead>
            <tr>
              <th scope="col">Turn</th><th scope="col" className="right">{codeA} min</th><th scope="col" className="right">{codeB} min</th>
              <th scope="col" className="right">Δ km/h</th><th scope="col" className="right">Brakes at</th><th scope="col" className="right" title={`Plus: ${codeA} began braking later than ${codeB}`}>vs {codeB}</th>
            </tr>
          </thead>
          <tbody>
            {subject.brake_zones.map((zone) => {
              const turn = subject.corners.find((c) => c.distance >= zone.start_m - 40);
              const ref = matchZone(zone.start_m, reference.brake_zones, stretch);
              const refPoint = ref ? ref.start_m * stretch : null;
              const later = refPoint == null ? null : zone.start_m - refPoint;
              const d = ref ? zone.min_speed - ref.min_speed : null;
              return (
                <tr key={zone.start_m} onClick={() => onCursor(zone.start_m)}>
                  <th scope="row" className="num">{turn ? `T${turn.number}${turn.letter ?? ""}` : "—"}</th>
                  <td className="num right" style={{ color: colourA }}>{Math.round(zone.min_speed)}</td>
                  <td className="num right" style={{ color: colourB }}>{ref ? Math.round(ref.min_speed) : "—"}</td>
                  <td className="num right" style={{ color: d == null || Math.abs(d) < 2 ? undefined : d > 0 ? colourA : colourB }}>
                    {d == null ? "—" : `${d > 0 ? "+" : d < 0 ? "−" : "±"}${Math.abs(Math.round(d))}`}</td>
                  <td className="num right muted">{Math.round(zone.start_m)} m</td>
                  <td className={`num right${later == null || Math.abs(later) <= 5 ? "" : later > 0 ? " is-better" : " is-worse"}`}>
                    {later == null ? "—" : Math.abs(later) <= 5 ? "same" : `${later > 0 ? "+" : "−"}${Math.abs(Math.round(later))} m`}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </section>
  );
}
