import { formatLapTime, type LapSeries } from "../api";
import { boxOf } from "./CrewsScreen";

/**
 * Race trace's gap, interval and lap-time views (D-035). Positions keeps its
 * line chart in TraceScreen; these give each driver a row of their own, so
 * the reader compares lengths instead of following 20 crossing lines.
 */

export interface BarRow {
  driver: number;
  code: string;
  colour: string;
  position: number;
  /** Seconds behind the leader (gap) or the car a place ahead (interval); null for the leader's interval. */
  value: number | null;
  /** How much `value` grew (+) or shrank (−) on this lap; null without a lap before. */
  change: number | null;
  /** In or out lap of a stop: the gap jumps for a reason the reader should see. */
  pit: boolean;
  /** Interval only: the last ten laps, oldest first, null where there is none. */
  spark: (number | null)[];
}

/**
 * One row per shown driver at `lap`, in that lap's order. Gaps are the
 * timing's at the line, stops included (a stop is a real loss of time, and
 * the row says PIT); intervals come from `intervals` (`seriesFor(…,
 * "interval")`), the gap to whoever was a place ahead on that lap.
 */
export function barRows(series: LapSeries[], measure: "gap" | "interval", lap: number, shown: number[],
                        intervals: Map<number, Map<number, number>>): BarRow[] {
  const keep = new Set(shown);
  const rows: BarRow[] = [];
  for (const s of series) {
    if (!keep.has(s.driver_number)) continue;
    const index = s.laps.indexOf(lap);
    const position = index < 0 ? null : s.position[index];
    if (position == null) continue;
    const valueAt = (l: number): number | null => {
      if (measure === "interval") return intervals.get(s.driver_number)?.get(l) ?? null;
      const i = s.laps.indexOf(l);
      if (i < 0) return null;
      return s.position[i] === 1 ? 0 : s.gap_to_leader_s[i] ?? null;
    };
    const value = valueAt(lap);
    const before = valueAt(lap - 1);
    const pitLaps = new Set(s.laps.filter((_, i) => s.pit_in[i]));
    rows.push({
      driver: s.driver_number, code: s.abbreviation ?? String(s.driver_number), colour: `#${s.team_color ?? "777"}`,
      position, value,
      change: value != null && before != null && !(measure === "gap" && position === 1) ? value - before : null,
      pit: pitLaps.has(lap) || pitLaps.has(lap - 1),
      spark: measure === "interval" ? Array.from({ length: 10 }, (_, k) => valueAt(lap - 9 + k)) : [],
    });
  }
  return rows.sort((a, b) => a.position - b.position);
}

/** Linear-interpolated quantile of an ascending list. */
function quantile(sorted: number[], p: number): number {
  const k = (sorted.length - 1) * p;
  const lo = Math.floor(k);
  return sorted[lo]! + (sorted[Math.ceil(k)]! - sorted[lo]!) * (k - lo);
}

export interface PaceRow { driver: number; code: string; colour: string; laps: number; q1: number; typical: number; q3: number; low: number; high: number; outliers: number[] }

/** Fewer green-flag laps than this and a box says nothing: the driver is left out. */
export const MIN_PACE_LAPS = 3;

/**
 * Each shown driver's race pace up to `current`: the green-flag laps only.
 * Left out: lap 1 (a standing start), a stop's in and out laps, and any lap
 * with a safety car, VSC or red flag (`neutral`), which are slow for reasons
 * that are not pace. Sorted quickest typical lap first.
 */
export function paceRows(series: LapSeries[], current: number, neutral: Set<number>, shown: number[]): PaceRow[] {
  const keep = new Set(shown);
  const rows: PaceRow[] = [];
  for (const s of series) {
    if (!keep.has(s.driver_number)) continue;
    const pitLaps = new Set(s.laps.filter((_, i) => s.pit_in[i]));
    const times = s.laps.flatMap((lap, i) => {
      const v = s.lap_time_s[i];
      return v == null || lap <= 1 || lap > current || neutral.has(lap) || pitLaps.has(lap) || pitLaps.has(lap - 1) ? [] : [v];
    }).sort((a, b) => a - b);
    if (times.length < MIN_PACE_LAPS) continue;
    const q1 = quantile(times, 0.25);
    const q3 = quantile(times, 0.75);
    rows.push({ driver: s.driver_number, code: s.abbreviation ?? String(s.driver_number), colour: `#${s.team_color ?? "777"}`,
                laps: times.length, q1, typical: quantile(times, 0.5), q3, ...boxOf(times, q1, q3) });
  }
  return rows.sort((a, b) => a.typical - b.typical);
}

/** The smallest of `steps` that puts no more than six ticks on a span this wide. */
function stepFor(span: number, steps: number[]): number {
  return steps.find((s) => span / s <= 6) ?? steps[steps.length - 1]!;
}

/** An axis label for a lap time: 1:18 on whole seconds, 1:18.5 between. */
const tickTime = (v: number) => {
  const s = Math.round((v % 60) * 10) / 10;
  return `${Math.floor(v / 60)}:${s < 10 ? "0" : ""}${Number.isInteger(s) ? s : s.toFixed(1)}`;
};

const signed = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(1)}`;

/** Interval bars stop here: past it a car is on its own, and a longer bar would squeeze the close ones flat. */
const INTERVAL_CAP_S = 8;
/** The attacking range: within a second of the car ahead. */
const ATTACK_S = 1;

/**
 * Gap or interval at one lap as a bar per driver (D-035). Each row: place,
 * code, the bar, the figure, and the change on that lap (green closing, red
 * dropping back). Interval adds the 1 s line and a sparkline of the last ten
 * laps. Click a row to follow that driver.
 */
export function LapBars({ measure, rows, followed, onFollow }: {
  measure: "gap" | "interval"; rows: BarRow[]; followed: number[]; onFollow: (driver: number) => void;
}) {
  const most = Math.max(...rows.map((r) => r.value ?? 0), 1);
  const span = measure === "interval" ? Math.min(most, INTERVAL_CAP_S) : most;
  const step = stepFor(span, measure === "interval" ? [0.5, 1, 2] : [1, 2, 5, 10, 20, 30, 60]);
  const top = Math.max(Math.ceil(span / step) * step, step);
  const ticks = Array.from({ length: Math.round(top / step) + 1 }, (_, k) => k * step);
  const pct = (v: number) => `${(Math.min(v, top) / top) * 100}%`;
  // Faint gridlines at the ticks, drawn as the track's background so a row costs no extra elements.
  const grid = { backgroundImage: ticks.slice(1, -1).map((v) => `linear-gradient(to right, transparent calc(${pct(v)} - 1px), var(--rule) calc(${pct(v)} - 1px), var(--rule) ${pct(v)}, transparent ${pct(v)})`).join(", ") || "none" };
  return (
    <div className={`lapbars${measure === "interval" ? " is-interval" : ""}`} role="table"
         aria-label={measure === "gap" ? "Gap to the leader, a bar per driver" : "Interval to the car ahead, a bar per driver"}>
      <div className="lapbar is-head cap" role="row">
        <span role="columnheader">P</span><span role="columnheader">Drv</span>
        <span role="columnheader" className="lapbar-track">
          {ticks.map((v) => <i key={v} className="num" style={{ left: pct(v) }}>{v === top ? `${v} s` : v}</i>)}
        </span>
        <span role="columnheader" className="right">{measure === "gap" ? "Behind" : "To ahead"}</span>
        <span role="columnheader" className="right" title="Change on this lap">Lap Δ</span>
        {measure === "interval" && <span role="columnheader" className="right">Last 10</span>}
      </div>
      {rows.map((r) => {
        const leader = r.position === 1;
        const close = measure === "interval" && r.value != null && r.value < ATTACK_S;
        // A gap growing is dropping back; an interval shrinking is closing on the car ahead. Either way, down is good.
        const tone = r.change == null || Math.abs(r.change) < 0.05 ? "" : r.change < 0 ? " is-good" : " is-bad";
        const on = followed.includes(r.driver);
        return (
          <button key={r.driver} type="button" role="row" onClick={() => onFollow(r.driver)}
                  className={`lapbar${on ? " is-followed" : ""}`} aria-pressed={on}
                  title={`${r.code}, P${r.position}${r.value != null && !leader ? `: ${r.value.toFixed(3)} s ${measure === "gap" ? "behind the leader" : "behind the car ahead"}` : ""}${r.pit ? " · pit stop" : ""}`}>
            <span role="cell" className="num muted">{r.position}</span>
            <span role="cell" className="num code"><i className="team-bar" style={{ background: r.colour }} />{r.code}</span>
            <span role="cell" className="lapbar-track" style={grid}>
              {measure === "interval" && <b className="lapbar-attack" style={{ left: pct(ATTACK_S) }} />}
              {r.value != null && r.value > 0 && <span className="lapbar-fill" style={{ width: pct(r.value), background: r.colour }} />}
              {r.pit && <em className="lapbar-pit">PIT</em>}
            </span>
            <span role="cell" className={`num right strong${close ? " is-close" : ""}`}>
              {leader ? "Leader" : r.value == null ? "—" : `${r.value.toFixed(r.value >= 100 ? 0 : 1)}${measure === "interval" && r.value > top ? "+" : ""}`}
            </span>
            <span role="cell" className={`num right${tone}`}>{r.change == null ? "" : signed(r.change)}</span>
            {measure === "interval" && <span role="cell" className="right">{!leader && <Spark values={r.spark} colour={r.colour} />}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** Ten laps of interval, 0 to 5 s, with the 1 s line dashed: under it the car was attacking. */
function Spark({ values, colour }: { values: (number | null)[]; colour: string }) {
  const y = (v: number) => 16 - (Math.min(v, 5) / 5) * 14;
  let d = "";
  values.forEach((v, k) => { if (v != null) d += `${k > 0 && values[k - 1] != null ? "L" : "M"}${k * 7} ${y(v).toFixed(1)}`; });
  return (
    <svg className="lapbar-spark" viewBox="0 0 63 18" aria-hidden="true">
      <line x1="0" x2="63" y1={y(ATTACK_S)} y2={y(ATTACK_S)} className="lapbar-spark-line" />
      <path d={d} fill="none" stroke={colour} strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

/**
 * Race pace as a box per driver (D-035): the middle half of their green-flag
 * laps as the box, the typical lap as the white tick, whiskers and far-off
 * laps as Pit crews draws them. Quickest typical lap at the top.
 */
export function PaceBoxes({ rows, followed, onFollow }: { rows: PaceRow[]; followed: number[]; onFollow: (driver: number) => void }) {
  if (!rows.length) return <p className="panel-note">Not enough green-flag laps yet: each driver needs {MIN_PACE_LAPS}.</p>;
  const lo = Math.min(...rows.map((r) => r.low)) - 0.1;
  const hi = Math.max(...rows.map((r) => r.high)) + 0.1;
  const x = (v: number) => 3 + ((Math.min(Math.max(v, lo), hi) - lo) / (hi - lo)) * 94;
  const step = stepFor(hi - lo, [0.2, 0.5, 1, 2]);
  const first = Math.ceil(lo / step) * step;
  const ticks = Array.from({ length: Math.floor((hi - first) / step) + 1 }, (_, k) => first + k * step);
  const best = rows[0]!.typical;
  return (
    <div className="lapbars is-pace" role="table" aria-label="Race pace, a box of green-flag laps per driver">
      <div className="lapbar is-head cap" role="row">
        <span role="columnheader">#</span><span role="columnheader">Drv</span>
        <span role="columnheader" className="lapbar-track">
          {ticks.map((v) => <i key={v} className="num" style={{ left: `${x(v)}%` }}>{tickTime(v)}</i>)}
        </span>
        <span role="columnheader" className="right">Typical</span>
        <span role="columnheader" className="right" title="Typical lap against the quickest typical lap">To best</span>
        <span role="columnheader" className="right" title="Green-flag laps counted">Laps</span>
      </div>
      {rows.map((r, k) => {
        const on = followed.includes(r.driver);
        return (
          <button key={r.driver} type="button" role="row" onClick={() => onFollow(r.driver)} aria-pressed={on}
                  className={`lapbar${on ? " is-followed" : ""}`}
                  title={`${r.code}: typical ${formatLapTime(r.typical)}, middle half ${formatLapTime(r.q1)} to ${formatLapTime(r.q3)}, ${r.laps} green-flag laps, ${r.outliers.length} far off`}>
            <span role="cell" className="num muted">{k + 1}</span>
            <span role="cell" className="num code"><i className="team-bar" style={{ background: r.colour }} />{r.code}</span>
            <span role="cell" className="lapbar-track crew-range">
              <span className="crew-whisker" style={{ left: `${x(r.low)}%`, width: `${x(r.high) - x(r.low)}%` }} />
              <span className="crew-box" style={{ left: `${x(r.q1)}%`, width: `${Math.max(x(r.q3) - x(r.q1), 0.5)}%`, background: `${r.colour}55`, borderColor: r.colour }} />
              {r.outliers.map((v, j) => <i key={j} style={{ left: `${x(v)}%`, borderColor: r.colour }} />)}
              <b style={{ left: `${x(r.typical)}%` }} />
            </span>
            <span role="cell" className="num right strong">{formatLapTime(r.typical)}</span>
            <span role="cell" className="num right muted">{k === 0 ? "—" : `+${(r.typical - best).toFixed(3)}`}</span>
            <span role="cell" className="num right muted">{r.laps}</span>
          </button>
        );
      })}
    </div>
  );
}
