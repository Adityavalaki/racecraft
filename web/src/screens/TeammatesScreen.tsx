import { useEffect, useState, type ReactNode } from "react";
import { api, type StandingsMoment, type TeammateGap, type TeammatePair, type TeammateRound, type Teammates } from "../api";
import { useSeasonMoment } from "./moment";
import { ScreenFoot } from "../shell/ScreenFoot";
import type { ScreenContext } from "./ScreenView";

type Metric = "quali" | "race" | "practice";

const METRICS: [Metric, string][] = [["quali", "Qualifying"], ["race", "Race pace"], ["practice", "Practice"]];
const FIELD: Record<Metric, keyof TeammateRound> = { quali: "quali_gap_s", race: "race_gap_s", practice: "practice_gap_s" };
const CLIP_TIMES = 3;

/**
 * Each team's two drivers, head to head, in the same car, as racecraft-ui.html
 * draws it (D-025): one card a team, the qualifying score big, the race and the
 * points under it, and the gap round by round.
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
  const [moment, setMoment] = useSeasonMoment(ctx);
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
    <>
      <div className="segmented" role="radiogroup" aria-label="Gap the bars show" title="Which gap the bars show">
        {METRICS.map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={metric === key} className={metric === key ? "is-on" : ""}
                  onClick={() => setMetric(key)}>{text}</button>
        ))}
      </div>
      <div className="segmented" role="radiogroup" aria-label="Which sessions count">
        {([["before", "Going into this session"], ["after", "After it"]] as [StandingsMoment, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={moment === key} className={moment === key ? "is-on" : ""}
                  onClick={() => setMoment(key)}>{text}</button>
        ))}
      </div>
    </>
  );

  const pairs = [...(data?.pairs ?? [])].sort((x, y) => points(y) - points(x));
  const byScore = [...pairs].sort((x, y) => margin(x) - margin(y));
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Comparing teammates…</div>}
        {data && (
          <>
            <div className="teammates">
              {pairs.map((pair) => (
                <PairCard key={`${pair.team}-${pair.drivers.map((d) => d.abbreviation).join("-")}`} pair={pair} metric={metric} />
              ))}
              <section className="panel teammates-card" aria-label="How to read a card">
                <div className="panel-bar"><h2>How to read a card</h2></div>
                <div className="teammates-how">
                  <span>Big numbers: who out-qualified whom, round by round.</span>
                  <span>Bars: one a round. Up means the first driver was quicker, down the second. Hover one for the figure; an empty slot had nothing to compare.</span>
                  {byScore[0] && <span>Closest pair: <b className="num">{scoreText(byScore[0])}</b></span>}
                  {byScore.length > 1 && <span>Most one-sided: <b className="num">{scoreText(byScore[byScore.length - 1]!)}</b></span>}
                  {data.notes.map((note) => <span key={note} className="teammates-note">{note}</span>)}
                </div>
              </section>
            </div>
            <ScreenFoot>
              <p className="standings-basis">
                <b>{data.year} season</b>
                {" · "}
                {data.pairs.length ? `${data.rounds} ${data.rounds === 1 ? "round" : "rounds"} so far · every team head to head` : "nothing run yet"}
              </p>
            </ScreenFoot>
          </>
        )}
      </main>
    </div>
  );
}

const points = (pair: TeammatePair) => pair.results.points[0] + pair.results.points[1];
const margin = (pair: TeammatePair) => Math.abs(pair.qualifying.ahead[0] - pair.qualifying.ahead[1]);
const scoreText = (pair: TeammatePair) =>
  `${pair.drivers.map((d) => d.abbreviation).join(" v ")}, ${pair.qualifying.ahead[0]}–${pair.qualifying.ahead[1]}`;

function PairCard({ pair, metric }: { pair: TeammatePair; metric: Metric }) {
  const [da, db] = pair.drivers;
  const [a = "?", b = "?"] = pair.drivers.map((d) => d.abbreviation);
  const color = `#${pair.team_color ?? "8B8B96"}`;
  const q = pair.qualifying;
  const shown = q.ahead[0] + q.ahead[1];
  const line = metric === "race" ? pair.race_pace : metric === "practice" ? pair.practice : null;
  const gap = line ? line.gap_s : q.gap_s;
  const qualiGap = q.gap_s === null ? "no qualifying gap yet" : `${gapText(q.gap_s, a, b)}${q.pct === null ? "" : ` (${Math.abs(q.pct).toFixed(2)}%)`}`;
  const sprint = pair.sprint;
  return (
    <section className="panel teammates-card" aria-label={`${pair.team}: ${a} against ${b}`}>
      <div className="panel-bar teammates-head" style={{ ["--team" as string]: color }}>
        <span className="team-bar" style={{ background: color }} aria-hidden="true" />
        <h2>{pair.team}</h2>
        <span className="panel-meta num">{pair.rounds_together} {pair.rounds_together === 1 ? "round" : "rounds"} · {points(pair)} pts</span>
      </div>
      <div className="teammates-body">
        <div className="teammates-duo">
          <span className="teammates-name"><b className="num">{a}</b><small>{da?.full_name ?? ""}</small></span>
          <span className="cap">Quali</span>
          <span className="teammates-name is-right"><b className="num">{b}</b><small>{db?.full_name ?? ""}</small></span>
        </div>
        <div className="teammates-duo" title={qualiGap}>
          <span className={`teammates-big${q.ahead[0] >= q.ahead[1] ? " is-lead" : ""}`}>{q.ahead[0]}</span>
          <span />
          <span className={`teammates-big is-right${q.ahead[1] > q.ahead[0] ? " is-lead" : ""}`}>{q.ahead[1]}</span>
        </div>
        <div className="teammates-split" aria-hidden="true">
          <i style={{ width: `${shown ? (q.ahead[0] / shown) * 100 : 50}%`, background: color }} />
          <i style={{ flex: "1 1 auto", background: color, opacity: 0.35 }} />
        </div>
        <Score name="Race" counts={pair.results.ahead} title={`Grands Prix finished ahead, when both were classified; ${retired(pair.results.retired, a, b)}`} />
        <Score name="Points" counts={pair.results.points} title="Sprints included" />
        {(sprint.races > 0 || sprint.qualifying.sessions > 0) && (
          <Score name="Sprints" counts={sprint.ahead}
                 title={[`Sprints finished ahead; sprint qualifying ${sprint.qualifying.ahead[0]}–${sprint.qualifying.ahead[1]}`,
                          sprint.pace.gap_s === null ? "" : `pace ${gapText(sprint.pace.gap_s, a, b)}`].filter(Boolean).join(" · ")} />
        )}
        {line && <Score name={metric === "race" ? "Pace" : "Practice"} counts={line.faster} title={lapGap(line, a, b, metric === "race" ? "a lap" : "")} />}
        <GapBars rounds={pair.rounds} metric={metric} a={a} b={b} color={color} />
        <div className="teammates-foot num">
          <span>{a} ↑</span>
          <span>{gap === null ? "—" : gapText(gap, a, b, metric === "race" ? "a lap" : "")}</span>
          <span>↓ {b}</span>
        </div>
      </div>
    </section>
  );
}

function Score({ name, counts, title }: { name: string; counts: [number, number]; title: string }) {
  return (
    <div className="teammates-score num" title={title}>
      <span className={counts[0] > counts[1] ? "is-lead" : ""}>{counts[0]}</span>
      <span className="cap">{name}</span>
      <span className={`is-right${counts[1] > counts[0] ? " is-lead" : ""}`}>{counts[1]}</span>
    </div>
  );
}

/** "ANT 0.231 s quicker" from a first-minus-second gap; "level" when it rounds to nothing. */
export function gapText(gap: number, a: string, b: string, per = ""): string {
  if (Math.abs(gap) < 0.0005) return "level";
  return `${gap < 0 ? a : b} ${Math.abs(gap).toFixed(3)} s${per ? ` ${per}` : ""} quicker`;
}

function lapGap(line: TeammateGap, a: string, b: string, per: string): string {
  if (line.gap_s === null) return "no gap yet";
  return `${gapText(line.gap_s, a, b, per)} · ${line.sessions} ${line.sessions === 1 ? "session" : "sessions"}`;
}

function retired(counts: [number, number], a: string, b: string): string {
  return counts[0] || counts[1] ? `retirements: ${a} ${counts[0]}, ${b} ${counts[1]}` : "no retirements";
}

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
function GapBars({ rounds, metric, a, b, color }: { rounds: TeammateRound[]; metric: Metric; a: string; b: string; color: string }) {
  const values = rounds.map((r) => r[FIELD[metric]] as number | null);
  const known = values.filter((v): v is number => v !== null);
  const name = METRICS.find(([key]) => key === metric)![1];
  if (known.length === 0) return <p className="teammates-empty">No {name.toLowerCase()} gap to chart yet.</p>;
  const reach = chartReach(known);
  return (
    <div className="teammates-bars" style={{ gridTemplateColumns: `repeat(${rounds.length}, minmax(0, 1fr))` }} role="img"
         aria-label={`${name} gap by round: ${a} quicker in ${known.filter((v) => v < 0).length}, ${b} in ${known.filter((v) => v > 0).length}`}>
      {rounds.map((r, i) => {
        const value = values[i] ?? null;
        const pct = metric === "quali" && r.quali_pct !== null ? ` (${Math.abs(r.quali_pct).toFixed(2)}%)` : "";
        const h = value === null ? 0 : Math.max(2, (Math.min(Math.abs(value), reach) / reach) * 50);
        const clipped = value !== null && Math.abs(value) > reach;
        return (
          <div key={r.round} title={`Round ${r.round}, ${r.event_name}: ${value === null ? "nothing to compare" : `${gapText(value, a, b)}${pct}`}`}>
            {value !== null && (
              <span className={`${value < 0 ? "is-up" : "is-down"}${clipped ? " is-clipped" : ""}`}
                    style={{ height: `${h}%`, ...(value < 0 ? { bottom: "50%", background: color } : { top: "50%" }) }} />
            )}
          </div>
        );
      })}
    </div>
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
