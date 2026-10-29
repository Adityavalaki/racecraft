import { useEffect, useState, type ReactNode } from "react";
import { api, type StandingsMoment, type TeammateGap, type TeammatePair, type TeammateRound, type Teammates } from "../api";
import type { ScreenContext } from "./ScreenView";

type Metric = "quali" | "race" | "practice";

const METRICS: [Metric, string][] = [["quali", "Qualifying"], ["race", "Race pace"], ["practice", "Practice"]];
const FIELD: Record<Metric, keyof TeammateRound> = { quali: "quali_gap_s", race: "race_gap_s", practice: "practice_gap_s" };

/**
 * Each team's two drivers, head to head, in the same car.
 *
 * Qualifying is compared in the last part both reached; race pace only on laps
 * both ran clean, on the same lap and the same compound; practice by each
 * session's best lap on the softest compound both ran, which ignores fuel and
 * so is the noisiest line. A driver change mid-season makes a pair of its own,
 * over the rounds they drove together (see model/teammates.py). Gaps from the
 * server are first driver minus second; the screen says who was quicker
 * instead of showing a sign.
 */
export function TeammatesScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [metric, setMetric] = useState<Metric>("quali");
  const [data, setData] = useState<Teammates | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    api
      .teammates(ctx.session, moment, controller.signal)
      .then((body) => (Array.isArray(body?.pairs) ? setData(body) : setError("The teammates came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment]);

  const switcher = (
    <div className="segmented" role="radiogroup" aria-label="Which sessions count">
      {([["before", "Going into this session"], ["after", "After it"]] as [StandingsMoment, string][]).map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={moment === key} className={moment === key ? "is-on" : ""}
                onClick={() => setMoment(key)}>{text}</button>
      ))}
    </div>
  );

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Comparing teammates…</div>}
        {data && (
          <>
            <div className="teammates-bar">
              <p className="standings-basis">
                <b>{data.year} season</b>
                {" · "}
                {data.pairs.length ? `${data.rounds} ${data.rounds === 1 ? "round" : "rounds"} so far` : "nothing run yet"}
                <br />
                Each card is one team: two drivers in the same car. Each row counts how often each beat the other
                (the winner in <b>bold</b>) and says by how much. The chart goes round by round: a coloured bar up when
                the first driver was quicker, a grey bar down when the second was.
              </p>
              <div className="segmented" role="radiogroup" aria-label="Gap the charts show" title="Which gap the charts show">
                {METRICS.map(([key, text]) => (
                  <button key={key} type="button" role="radio" aria-checked={metric === key} className={metric === key ? "is-on" : ""}
                          onClick={() => setMetric(key)}>{text}</button>
                ))}
              </div>
            </div>
            <div className="teammates">
              {data.pairs.map((pair) => (
                <PairCard key={`${pair.team}-${pair.drivers.map((d) => d.abbreviation).join("-")}`} pair={pair} metric={metric} />
              ))}
            </div>
            {data.notes.length > 0 && (
              <ul className="prediction-notes">{data.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function PairCard({ pair, metric }: { pair: TeammatePair; metric: Metric }) {
  const [a = "?", b = "?"] = pair.drivers.map((d) => d.abbreviation);
  const color = `#${pair.team_color ?? "8B8B96"}`;
  const q = pair.qualifying;
  const sprint = pair.sprint;
  const label = `${pair.team}: ${a} against ${b}`;
  return (
    <section className="panel teammates-panel" aria-label={label}>
      <h2 className="teammates-title">
        <span className="team-bar" style={{ background: color }} aria-hidden="true" />
        <span>{pair.team}</span>
        <small>{a} v {b} · {pair.rounds_together} {pair.rounds_together === 1 ? "round" : "rounds"} together</small>
      </h2>
      <div className="teammates-table" role="table" aria-label={`${label}, head to head`}>
        <div className="teammates-row is-head" role="row">
          <span role="columnheader" />
          <span role="columnheader" className="num">{a}</span>
          <span role="columnheader" className="num">{b}</span>
          <span role="columnheader">By how much</span>
        </div>
        <Row name="Qualified ahead" title="Who qualified ahead; the gap in the last part both reached"
             counts={q.ahead} gap={q.gap_s === null ? "—" : `${gapText(q.gap_s, a, b)}${q.pct === null ? "" : ` (${Math.abs(q.pct).toFixed(2)}%)`}`} />
        <Row name="Faster in races" title="Races each was quicker in, on laps both ran clean on the same tyre"
             counts={pair.race_pace.faster} gap={lapGap(pair.race_pace, a, b, "a lap")} />
        <Row name="Faster in practice" title="Sessions each was quicker in: best laps on the softest tyre both ran. Fuel is unknown, so it is the noisiest line"
             counts={pair.practice.faster} gap={lapGap(pair.practice, a, b, "")} />
        <Row name="Finished ahead" title="Grands Prix each finished ahead in, when both were classified"
             counts={pair.results.ahead} gap={retired(pair.results.retired, a, b)} />
        <Row name="Points" title="Sprints included" counts={pair.results.points} gap="includes sprints" />
        {(sprint.races > 0 || sprint.qualifying.sessions > 0) && (
          <Row name="Sprints ahead" title="Sprints each finished ahead in; sprint qualifying and pace beside"
               counts={sprint.ahead}
               gap={[`qualifying ${sprint.qualifying.ahead[0]}–${sprint.qualifying.ahead[1]}`,
                     sprint.pace.gap_s === null ? "" : `pace ${gapText(sprint.pace.gap_s, a, b)}`].filter(Boolean).join(" · ")} />
        )}
      </div>
      <GapChart rounds={pair.rounds} metric={metric} a={a} b={b} color={color} />
    </section>
  );
}

function Row({ name, title, counts, gap }: { name: string; title: string; counts: [number, number]; gap: string }) {
  const lead = counts[0] === counts[1] ? -1 : counts[0] > counts[1] ? 0 : 1;
  return (
    <div className="teammates-row" role="row" title={title}>
      <span role="cell" className="line">{name}</span>
      {counts.map((count, side) => (
        <span key={side} role="cell" className={`num count${lead === side ? " is-lead" : ""}`}>{count}</span>
      ))}
      <span role="cell" className="gap">{gap}</span>
    </div>
  );
}

/** "ANT 0.231 s quicker" from a first-minus-second gap; "level" when it rounds to nothing. */
export function gapText(gap: number, a: string, b: string, per = ""): string {
  if (Math.abs(gap) < 0.0005) return "level";
  return `${gap < 0 ? a : b} ${Math.abs(gap).toFixed(3)} s${per ? ` ${per}` : ""} quicker`;
}

function lapGap(line: TeammateGap, a: string, b: string, per: string): string {
  if (line.gap_s === null) return "—";
  return `${gapText(line.gap_s, a, b, per)} · ${line.sessions} ${line.sessions === 1 ? "session" : "sessions"}`;
}

function retired(counts: [number, number], a: string, b: string): string {
  return counts[0] || counts[1] ? `retirements: ${a} ${counts[0]}, ${b} ${counts[1]}` : "no retirements";
}

const WIDTH = 640;
const HEIGHT = 150;
const LEFT = 78;          // room for the "quicker" labels
const TOP = 10;
const BOTTOM = 18;        // room for the round numbers
const CLIP_TIMES = 3;

/**
 * The gap round by round: a bar up when the first driver was quicker, down
 * when the second was, so who led and how the season moved read at a glance.
 * A round with nothing to compare (no shared clean laps, a missed session) is
 * left empty. Hover a bar for the round and the figure.
 *
 * One bad round (a driver out in Q1 with a problem) would flatten every other
 * bar, so the scale reaches CLIP_TIMES the typical gap at most; a bar past it
 * is drawn to the edge with a line across its end, its figure in the hover.
 */
function GapChart({ rounds, metric, a, b, color }: { rounds: TeammateRound[]; metric: Metric; a: string; b: string; color: string }) {
  const values = rounds.map((r) => r[FIELD[metric]] as number | null);
  const known = values.filter((v): v is number => v !== null);
  const name = METRICS.find(([key]) => key === metric)![1];
  if (known.length === 0) return <p className="panel-note">No {name.toLowerCase()} gap to chart yet.</p>;
  const reach = chartReach(known);
  const half = (HEIGHT - TOP - BOTTOM) / 2;
  const zero = TOP + half;
  const band = (WIDTH - LEFT - 8) / rounds.length;
  const bar = Math.min(16, band * 0.6);
  const scale = `${reach.toFixed(reach < 0.1 ? 2 : 1)} s`;
  return (
    <svg className="teammates-chart" viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img"
         aria-label={`${name} gap by round: ${a} quicker in ${known.filter((v) => v < 0).length}, ${b} in ${known.filter((v) => v > 0).length}`}>
      <line x1={LEFT} x2={WIDTH - 8} y1={TOP} y2={TOP} className="grid" />
      <line x1={LEFT} x2={WIDTH - 8} y1={HEIGHT - BOTTOM} y2={HEIGHT - BOTTOM} className="grid" />
      <line x1={LEFT} x2={WIDTH - 8} y1={zero} y2={zero} className="axis" />
      <text x={LEFT - 8} y={TOP + 4} className="tick">{scale}</text>
      <text x={LEFT - 8} y={zero - 8} className="side">{a} quicker</text>
      <text x={LEFT - 8} y={zero + 16} className="side">{b} quicker</text>
      <text x={LEFT - 8} y={HEIGHT - BOTTOM + 4} className="tick">{scale}</text>
      {rounds.map((r, i) => {
        const value = values[i] ?? null;
        const x = LEFT + band * i + (band - bar) / 2;
        const pct = metric === "quali" && r.quali_pct !== null ? ` (${Math.abs(r.quali_pct).toFixed(2)}%)` : "";
        const clipped = value !== null && Math.abs(value) > reach;
        const h = value === null ? 0 : Math.max(1.5, (Math.min(Math.abs(value), reach) / reach) * half);
        const end = value !== null && value < 0 ? zero - h : zero + h;
        return (
          <g key={r.round}>
            <title>{`Round ${r.round}, ${r.event_name}: ${value === null ? "nothing to compare" : `${gapText(value, a, b)}${pct}`}`}</title>
            <rect x={LEFT + band * i} y={TOP} width={band} height={HEIGHT - TOP - BOTTOM} className="hit" />
            {value !== null && (
              <rect x={x} y={value < 0 ? zero - h : zero} width={bar} height={h} rx={2}
                    fill={value < 0 ? color : "var(--ink-faint)"} />
            )}
            {clipped && <line x1={x - 2} x2={x + bar + 2} y1={end} y2={end} className="clip" />}
            <text x={x + bar / 2} y={HEIGHT - 4} className="round">{r.round}</text>
          </g>
        );
      })}
    </svg>
  );
}

/** The chart's reach: the biggest gap, or CLIP_TIMES the median one if that is less, rounded up nicely. */
export function chartReach(gaps: number[]): number {
  const sizes = gaps.map(Math.abs).sort((x, y) => x - y);
  const mid = sizes.length % 2 ? sizes[(sizes.length - 1) / 2]! : (sizes[sizes.length / 2 - 1]! + sizes[sizes.length / 2]!) / 2;
  return niceCeiling(Math.min(sizes[sizes.length - 1]!, CLIP_TIMES * mid || Infinity));
}

/** A reach rounded up to 1, 2 or 5 of its power of ten. */
export function niceCeiling(value: number): number {
  if (value <= 0) return 0.1;
  const power = 10 ** Math.floor(Math.log10(value));
  return ([1, 2, 5, 10].find((step) => step * power >= value) ?? 10) * power;
}
