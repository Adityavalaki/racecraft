import { useMemo, useState, type MouseEvent, type ReactNode } from "react";
import { formatLapTime, type LapSeries } from "../api";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Measure = "gap" | "interval" | "lap";

const MEASURES: [Measure, string][] = [["gap", "Gap to leader"], ["interval", "Interval"], ["lap", "Lap time"]];
const STATUS_BANDS = new Set(["4", "5", "6", "7"]);
const HEIGHT = 440;

/** Each driver's value per lap for a measure; null where there is none. */
export function seriesFor(series: LapSeries[], measure: Measure): Map<number, Map<number, number>> {
  const out = new Map<number, Map<number, number>>();
  if (measure === "interval") {
    // Interval: the gap to whoever was one place ahead on that lap.
    const byLap = new Map<number, { driver: number; position: number; gap: number }[]>();
    for (const s of series) {
      s.laps.forEach((lap, i) => {
        const gap = s.gap_to_leader_s[i];
        const position = s.position[i];
        if (gap == null || position == null) return;
        if (!byLap.has(lap)) byLap.set(lap, []);
        byLap.get(lap)!.push({ driver: s.driver_number, position, gap });
      });
    }
    for (const [lap, rows] of byLap) {
      rows.sort((a, b) => a.position - b.position);
      rows.forEach((row, k) => {
        if (k === 0) return;
        if (!out.has(row.driver)) out.set(row.driver, new Map());
        out.get(row.driver)!.set(lap, row.gap - rows[k - 1]!.gap);
      });
    }
    return out;
  }
  for (const s of series) {
    const values = new Map<number, number>();
    s.laps.forEach((lap, i) => {
      const v = measure === "gap" ? s.gap_to_leader_s[i] : s.lap_time_s[i];
      // Pit laps are not race pace: on the lap-time chart they would flatten everyone else.
      if (v != null && !(measure === "lap" && (s.pit_in[i] || s.pit_in[i - 1]))) values.set(lap, v);
    });
    out.set(s.driver_number, values);
  }
  return out;
}

type Preset = "top10" | "followed" | "all";

/**
 * How the gaps opened and closed, lap by lap, up to the lap the clock is on.
 * Nothing after it is drawn, so a replay is not spoiled. Safety-car and VSC
 * laps are shaded, which is where most gaps close; a ring marks each pit stop.
 * Pick who is drawn with the presets or the driver list; click the chart to
 * jump to a lap.
 */
export function TraceScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [measure, setMeasure] = useState<Measure>("gap");
  const [preset, setPreset] = useState<Preset>("top10");
  const [picked, setPicked] = useState<number[] | null>(null);
  const current = ctx.state?.leader_lap ?? 0;
  const order = ctx.state?.drivers ?? [];
  const presetList = preset === "all" ? order.map((d) => d.driver_number)
    : preset === "followed" ? ctx.selected : order.slice(0, 10).map((d) => d.driver_number);
  const shown = picked ?? presetList;
  const values = useMemo(() => seriesFor(ctx.laps, measure), [ctx.laps, measure]);
  const span = Math.max(current - 1, 1);
  const shownKey = shown.join(",");

  const scale = useMemo(() => {
    const keep = new Set(shownKey.split(",").filter(Boolean).map(Number));
    const all: number[] = [];
    for (const [driver, laps] of values) if (keep.has(driver)) for (const [lap, v] of laps) if (lap <= current) all.push(v);
    if (!all.length) return null;
    all.sort((a, b) => a - b);
    if (measure === "lap") {
      // Lap times: the quickest at the top, and the slowest 5% let off the chart.
      const low = all[0]!;
      const high = all[Math.floor(all.length * 0.95)] ?? all[all.length - 1]!;
      return { low, high: Math.max(high, low + 1) };
    }
    const high = all[Math.floor(all.length * 0.97)] ?? all[all.length - 1]!;
    return { low: 0, high: Math.max(high, 1) };
  }, [values, current, measure, shownKey]);

  const x = (lap: number) => ((lap - 1) / span) * 1000;
  const y = (v: number) => (scale ? Math.min(Math.max((v - scale.low) / (scale.high - scale.low), 0), 1.04) * HEIGHT : 0);
  const path = (driver: number) => {
    const laps = values.get(driver);
    if (!laps) return "";
    let d = "";
    let last = -1;
    for (const [lap, v] of [...laps].sort((a, b) => a[0] - b[0])) {
      if (lap > current) break;
      d += `${lap === last + 1 ? "L" : "M"}${x(lap).toFixed(1)} ${y(v).toFixed(1)}`;
      last = lap;
    }
    return d;
  };

  // Safety car, VSC and red flag periods, in laps, from the status changes and the leader's crossings.
  const bands = useMemo(() => {
    const statuses = [...(ctx.info.track_status ?? [])].sort((a, b) => a.t - b.t);
    const crossings = ctx.crossings;
    if (!crossings || !crossings.t.length) return [];
    // The lap the leader was on at a time: the first lap it had not yet finished.
    const lapAt = (t: number) => {
      const k = crossings.t.findIndex((end) => end >= t);
      return k < 0 ? current : crossings.laps[k]!;
    };
    const out: { from: number; to: number; red: boolean }[] = [];
    statuses.forEach((change, i) => {
      // Only what had happened by the clock's time: a later safety car would spoil the replay.
      if (!STATUS_BANDS.has(change.status) || change.t > ctx.t) return;
      const until = Math.min(statuses[i + 1]?.t ?? ctx.info.t_end, ctx.t);
      out.push({ from: lapAt(change.t), to: lapAt(until), red: change.status === "5" });
    });
    return out;
  }, [ctx.info, ctx.crossings, ctx.t, current]);

  const yTicks = scale ? Array.from({ length: 6 }, (_, k) => scale.low + ((scale.high - scale.low) * k) / 5) : [];
  const step = span > 30 ? 5 : span > 12 ? 2 : 1;
  const xTicks = Array.from({ length: Math.floor((current - 1) / step) + 1 }, (_, k) => 1 + k * step).filter((lap) => lap <= current);
  const toggle = (driver: number) =>
    setPicked((now) => {
      const base = now ?? shown;
      return base.includes(driver) ? base.filter((d) => d !== driver) : [...base, driver];
    });
  const pickLap = (event: MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const lap = Math.round(((event.clientX - box.left) / box.width) * span) + 1;
    if (lap >= 1 && lap <= current) ctx.onSelectLap(lap);
  };
  const label = (v: number) =>
    measure === "lap" ? formatLapTime(v) : v === 0 ? "0" : `+${v.toFixed(v >= 10 ? 0 : 1)}`;
  const series = new Map(ctx.laps.map((s) => [s.driver_number, s]));
  const colour = (driver: number) => `#${series.get(driver)?.team_color ?? "777"}`;
  const lastAt = (driver: number) => {
    const laps = values.get(driver);
    if (!laps) return null;
    const done = [...laps].filter(([lap]) => lap <= current).sort((a, b) => b[0] - a[0])[0];
    return done ? { lap: done[0], v: done[1] } : null;
  };
  // End labels top to bottom; one too close to the label above is left to its line.
  let lastY = -99;
  const ends = shown.map((driver) => ({ driver, end: lastAt(driver) }))
    .filter((e): e is { driver: number; end: { lap: number; v: number } } => e.end != null)
    .sort((a, b) => y(a.end.v) - y(b.end.v))
    .filter((e) => { const top = (y(e.end.v) / HEIGHT) * 100; if (top - lastY < 3.4) return false; lastY = top; return true; });
  const pits = shown.flatMap((driver) => {
    const s = series.get(driver);
    const laps = values.get(driver);
    if (!s || !laps) return [];
    return s.laps.filter((lap, i) => s.pit_in[i] && lap <= current && laps.has(lap)).map((lap) => ({ driver, lap, v: laps.get(lap)! }));
  });
  const firstPit = (driver: number) => {
    const s = series.get(driver);
    const k = s ? s.pit_in.findIndex((p, i) => p && s.laps[i]! <= current) : -1;
    return s && k >= 0 ? `L${s.laps[k]}` : "—";
  };
  const leader = order.find((d) => d.position === 1);

  return (
    <div className="screen">
      {header(
        <>
          <LapCounter lap={current} total={ctx.info.total_laps} />
          <div className="segmented" role="radiogroup" aria-label="Drivers shown">
            {([["top10", "Top 10"], ["followed", "Followed"], ["all", "All"]] as [Preset, string][]).map(([key, text]) => (
              <button key={key} type="button" role="radio" aria-checked={!picked && preset === key} className={!picked && preset === key ? "is-on" : ""}
                      onClick={() => { setPreset(key); setPicked(null); }}>{text}</button>
            ))}
          </div>
        </>,
      )}
      <main className="screen-body trace-layout">
        <section className="panel trace-panel" aria-label="Race trace chart">
          <div className="panel-bar">
            <h2>{measure === "gap" ? "Gap to leader by lap" : measure === "interval" ? "Interval by lap" : "Lap time by lap"}</h2>
            <span className="panel-meta">
              {measure === "lap" ? "higher is quicker · pit laps left out"
                : `seconds behind ${measure === "gap" ? leader?.abbreviation ?? "the leader" : "the car ahead"} · lines drop at a pit stop`}
            </span>
            <div className="segmented" role="radiogroup" aria-label="Measure" style={{ marginLeft: "auto" }}>
              {MEASURES.map(([key, text]) => (
                <button key={key} type="button" role="radio" aria-checked={measure === key}
                        className={measure === key ? "is-on" : ""} onClick={() => setMeasure(key)}>{text}</button>
              ))}
            </div>
            <span className="trace-key"><i className="trace-pit" />Pit stop</span>
          </div>
          {!scale || current < 1 ? (
            <p className="panel-note">{shown.length ? "No laps completed yet at this point of the session." : "Pick drivers to draw from the list."}</p>
          ) : (
            <div className="trace-chart">
              <div className="trace-y num">{yTicks.map((v) => <span key={v} style={{ top: `${(y(v) / HEIGHT) * 100}%` }}>{label(v)}</span>)}</div>
              <div className="trace-canvas">
                <svg viewBox={`0 0 1000 ${HEIGHT}`} preserveAspectRatio="none" role="img" onClick={pickLap}
                     aria-label={`${MEASURES.find(([m]) => m === measure)![1]}, lap by lap, to lap ${current}. Click to jump to a lap.`}>
                  {bands.map((b, k) => (
                    <rect key={k} x={x(b.from)} y="0" width={Math.max(x(b.to) - x(b.from), 3)} height={HEIGHT}
                          fill={b.red ? "rgba(255, 77, 94, 0.14)" : "rgba(255, 162, 58, 0.13)"} />
                  ))}
                  {yTicks.map((v, k) => (
                    <line key={v} x1="0" x2="1000" y1={y(v)} y2={y(v)} stroke={k === 0 && measure !== "lap" ? "rgba(255,255,255,.18)" : "rgba(255,255,255,.05)"}
                          strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  ))}
                  {xTicks.map((lap) => (
                    <line key={lap} x1={x(lap)} x2={x(lap)} y1="0" y2={HEIGHT} stroke="rgba(255,255,255,.05)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  ))}
                  {shown.map((driver) => {
                    const followed = ctx.selected.includes(driver);
                    return <path key={driver} d={path(driver)} fill="none" stroke={colour(driver)} strokeWidth={followed ? 2.4 : 1.4}
                                 strokeOpacity={followed ? 1 : 0.85} strokeLinejoin="round" vectorEffect="non-scaling-stroke" />;
                  })}
                </svg>
                {pits.map((p) => (
                  <span key={`${p.driver}-${p.lap}`} className="trace-pit" title={`${ctx.driverCodes[p.driver] ?? p.driver} pit stop, lap ${p.lap}`}
                        style={{ left: `${x(p.lap) / 10}%`, top: `${(y(p.v) / HEIGHT) * 100}%`, borderColor: colour(p.driver) }} />
                ))}
                {ends.map(({ driver, end }) => (
                  <span key={driver} className="trace-end num" style={{ top: `${(y(end.v) / HEIGHT) * 100}%`, color: colour(driver) }}>
                    {ctx.driverCodes[driver] ?? driver}
                  </span>
                ))}
              </div>
              <div className="trace-x num">
                {xTicks.map((lap) => <span key={lap} style={{ left: `${x(lap) / 10}%` }}>L{lap}</span>)}
              </div>
            </div>
          )}
          {bands.length > 0 && (
            <div className="map-legend">
              <span><i style={{ background: "rgba(255, 162, 58, 0.6)" }} />Safety car or VSC</span>
            </div>
          )}
        </section>

        <section className="panel trace-drivers" aria-label="Drivers on the chart">
          <div className="panel-bar">
            <h2>Drivers</h2><span className="panel-meta">{shown.length} shown</span>
            <button type="button" className="toggle" style={{ marginLeft: "auto" }} onClick={() => setPicked([])}>Clear</button>
          </div>
          <div className="trace-driver-list">
            <div className="trace-driver is-head cap" aria-hidden="true"><span /><span /><span>Drv</span><span /><span className="right">Gap</span><span className="right">Pit</span></div>
            {order.map((d) => {
              const on = shown.includes(d.driver_number);
              return (
                <button key={d.driver_number} type="button" aria-pressed={on} onClick={() => toggle(d.driver_number)}
                        className={`trace-driver${on ? " is-on" : ""}`}>
                  <span className="trace-check" style={on ? { background: `#${d.team_color ?? "777"}`, borderColor: "transparent" } : undefined}>
                    {on && <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="#07080A" strokeWidth="4" aria-hidden="true"><path d="m5 12 5 5 9-10" /></svg>}
                  </span>
                  <span className="team-bar" style={{ background: `#${d.team_color ?? "777"}` }} />
                  <span className="num code">{d.abbreviation ?? d.driver_number}</span>
                  <span className="team">{d.team_name ?? ""}</span>
                  <span className="num right">{d.status === "out" ? "OUT" : d.position === 1 ? "Leader" : d.gap_text || "—"}</span>
                  <span className="num right muted">{firstPit(d.driver_number)}</span>
                </button>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
