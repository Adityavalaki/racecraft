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

/**
 * How the gaps opened and closed, lap by lap, up to the lap the clock is on.
 * Nothing after it is drawn, so a replay is not spoiled; the rest of the race
 * is shaded as still to run. Safety-car and VSC laps are shaded too, which is
 * where most gaps close. Click the chart to jump to a lap.
 */
export function TraceScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [measure, setMeasure] = useState<Measure>("gap");
  const [highlight, setHighlight] = useState<number[] | null>(null);
  const current = ctx.state?.leader_lap ?? 0;
  const total = ctx.info.total_laps ?? Math.max(current, ...ctx.laps.flatMap((s) => s.laps), 1);
  const order = ctx.state?.drivers ?? [];
  const shown = highlight ?? (ctx.selected.length ? ctx.selected : order.slice(0, 5).map((d) => d.driver_number));
  const values = useMemo(() => seriesFor(ctx.laps, measure), [ctx.laps, measure]);

  const scale = useMemo(() => {
    const all: number[] = [];
    for (const [, laps] of values) for (const [lap, v] of laps) if (lap <= current) all.push(v);
    if (!all.length) return null;
    all.sort((a, b) => a - b);
    if (measure === "lap") {
      // Lap times: the quickest at the top, and the slowest 5% let off the chart.
      const low = all[0]!;
      const high = all[Math.floor(all.length * 0.95)] ?? all[all.length - 1]!;
      return { low, high: Math.max(high, low + 1), invert: false };
    }
    const high = all[Math.floor(all.length * 0.97)] ?? all[all.length - 1]!;
    return { low: 0, high: Math.max(high, 1), invert: false };
  }, [values, current, measure]);

  const x = (lap: number) => ((lap - 1) / Math.max(total - 1, 1)) * 1000;
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
      return k < 0 ? total : crossings.laps[k]!;
    };
    const out: { from: number; to: number; red: boolean }[] = [];
    statuses.forEach((change, i) => {
      // Only what had happened by the clock's time: a later safety car would spoil the replay.
      if (!STATUS_BANDS.has(change.status) || change.t > ctx.t) return;
      const until = Math.min(statuses[i + 1]?.t ?? ctx.info.t_end, ctx.t);
      out.push({ from: lapAt(change.t), to: lapAt(until), red: change.status === "5" });
    });
    return out;
  }, [ctx.info, ctx.crossings, ctx.t, total]);

  const yTicks = scale
    ? Array.from({ length: 6 }, (_, k) => scale.low + ((scale.high - scale.low) * k) / 5)
    : [];
  const xTicks = Array.from({ length: Math.floor(total / 5) + 1 }, (_, k) => Math.max(1, k * 5)).filter((lap) => lap <= total);
  const toggle = (driver: number) =>
    setHighlight((now) => {
      const base = now ?? shown;
      return base.includes(driver) ? base.filter((d) => d !== driver) : [...base, driver];
    });
  const pickLap = (event: MouseEvent<SVGSVGElement>) => {
    const box = event.currentTarget.getBoundingClientRect();
    const lap = Math.round(((event.clientX - box.left) / box.width) * (total - 1)) + 1;
    if (lap >= 1 && lap <= total) ctx.onSelectLap(lap);
  };
  const label = (v: number) =>
    measure === "lap" ? formatLapTime(v) : v === 0 ? "0" : `+${v.toFixed(v >= 10 ? 0 : 1)} s`;
  const endOf = (driver: number) => {
    const laps = values.get(driver);
    if (!laps) return null;
    const done = [...laps].filter(([lap]) => lap <= current).sort((a, b) => b[0] - a[0])[0];
    return done ? { lap: done[0], v: done[1] } : null;
  };
  const colour = (driver: number) => `#${ctx.laps.find((s) => s.driver_number === driver)?.team_color ?? "777"}`;

  return (
    <div className="screen">
      {header(<LapCounter lap={current} total={ctx.info.total_laps} />)}
      <main className="screen-body trace-layout">
        <section className="panel trace-panel" aria-label="Race trace chart">
          <div className="panel-bar">
            <h2>{MEASURES.find(([m]) => m === measure)![1]}</h2>
            <span className="panel-meta">
              {measure === "lap" ? "Higher on the chart is quicker. Pit laps are left out."
                : "Lower on the chart means further behind."}
            </span>
            <div className="segmented" role="radiogroup" aria-label="Measure" style={{ marginLeft: "auto" }}>
              {MEASURES.map(([key, text]) => (
                <button key={key} type="button" role="radio" aria-checked={measure === key}
                        className={measure === key ? "is-on" : ""} onClick={() => setMeasure(key)}>{text}</button>
              ))}
            </div>
          </div>
          {!scale ? (
            <p className="panel-note">No laps completed yet at this point of the session.</p>
          ) : (
            <div className="trace-chart">
              <div className="trace-y num">{yTicks.map((v) => <span key={v}>{label(v)}</span>)}</div>
              <div className="trace-canvas">
                <svg viewBox={`0 0 1000 ${HEIGHT}`} preserveAspectRatio="none" role="img" onClick={pickLap}
                     aria-label={`${MEASURES.find(([m]) => m === measure)![1]}, lap by lap, to lap ${current}. Click to jump to a lap.`}>
                  {bands.map((b, k) => (
                    <rect key={k} x={x(b.from)} y="0" width={Math.max(x(b.to) - x(b.from), 3)} height={HEIGHT}
                          fill={b.red ? "rgba(255, 77, 94, 0.14)" : "rgba(255, 162, 58, 0.13)"} />
                  ))}
                  <rect x={x(Math.max(current, 1))} y="0" width={1000 - x(Math.max(current, 1))} height={HEIGHT} fill="rgba(255, 255, 255, 0.025)" />
                  {yTicks.map((v) => (
                    <line key={v} x1="0" x2="1000" y1={y(v)} y2={y(v)} stroke="#1E1E24" strokeWidth="1" vectorEffect="non-scaling-stroke" />
                  ))}
                  {ctx.laps.filter((s) => !shown.includes(s.driver_number)).map((s) => (
                    <path key={s.driver_number} d={path(s.driver_number)} fill="none" stroke={`#${s.team_color ?? "777"}`}
                          strokeOpacity="0.28" strokeWidth="1.2" vectorEffect="non-scaling-stroke" />
                  ))}
                  {shown.map((driver) => (
                    <path key={driver} d={path(driver)} fill="none" stroke={colour(driver)} strokeWidth="2.6"
                          strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
                  ))}
                </svg>
                {shown.map((driver) => {
                  const end = endOf(driver);
                  if (!end) return null;
                  return (
                    <span key={driver} className="trace-end display"
                          style={{ left: `${x(end.lap) / 10}%`, top: `${(y(end.v) / HEIGHT) * 100}%`, color: colour(driver) }}>
                      {ctx.driverCodes[driver] ?? driver}
                    </span>
                  );
                })}
                {current < total && <span className="trace-note num" style={{ left: `${x(Math.max(current, 1)) / 10}%` }}>Still to run</span>}
              </div>
              <div />
              <div className="trace-x num">
                {xTicks.map((lap) => <span key={lap} style={{ left: `${x(lap) / 10}%` }}>{lap}</span>)}
              </div>
            </div>
          )}
          {bands.length > 0 && (
            <div className="map-legend">
              <span><i style={{ background: "rgba(255, 162, 58, 0.6)" }} />Safety car or VSC</span>
              <span><i style={{ background: "rgba(255, 255, 255, 0.12)" }} />Still to run</span>
            </div>
          )}
        </section>

        <section className="panel trace-drivers" aria-label="Drivers on the chart">
          <div className="panel-bar"><h2>Drivers</h2><span className="panel-meta">Pick the lines to highlight.</span></div>
          <div className="trace-driver-list">
            {order.map((d) => {
              const on = shown.includes(d.driver_number);
              return (
                <button key={d.driver_number} type="button" aria-pressed={on} onClick={() => toggle(d.driver_number)}
                        className={`trace-driver${on ? " is-on" : ""}`}>
                  <span className="team-bar" style={{ background: `#${d.team_color ?? "777"}` }} />
                  <span className="display code">{d.abbreviation ?? d.driver_number}</span>
                  <span className="team">{d.team_name ?? ""}</span>
                  <span className="num">{d.status === "out" ? "OUT" : d.gap_text || (d.position === 1 ? "Leader" : "")}</span>
                </button>
              );
            })}
          </div>
        </section>
      </main>
    </div>
  );
}
