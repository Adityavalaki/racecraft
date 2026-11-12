import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, COMPOUND_COLORS, type DriverTiming, type PitWindows } from "../api";
import { StrategyBoard } from "../panels/StrategyBoard";
import { KpiRow } from "../shell/KpiRow";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Mode = "windows" | "whatif";
type Run = { compound: string; from: number; to: number; plan?: boolean };
const isAbort = (e: Error) => e.name === "AbortError";
/** Closer than this either side of the rejoin is traffic: the out-lap is spent behind or fending off that car. */
const TRAFFIC_S = 1.5;

/**
 * The pit windows, asked for again each time the leader starts a lap: the
 * answer moves with tyre age and the gaps, which change at the line.
 */
function usePitWindows(session: string, t: number, lap: number, enabled: boolean) {
  const [answer, setAnswer] = useState<PitWindows | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tRef = useRef(t);
  tRef.current = t;
  useEffect(() => {
    if (!enabled) return;
    const controller = new AbortController();
    api.pitWindows(session, tRef.current, controller.signal)
      .then((next) => {
        // An error body is JSON too: the shape is checked rather than assumed.
        if (next && Array.isArray(next.cars) && Array.isArray(next.undercuts) && next.model) {
          setAnswer(next);
          setError(null);
        } else {
          setError("The pit windows came back in a shape this screen cannot read.");
        }
      })
      .catch((e: Error) => {
        if (!isAbort(e)) setError(e.message);
      });
    return () => controller.abort();
  }, [session, lap, enabled]);
  useEffect(() => {
    setAnswer(null);
    setError(null);
  }, [session]);
  return { answer, error };
}

/**
 * Where `car` would come out if it pitted now: the lead-lap cars by gap to the
 * leader, `car` moved back by `loss` seconds. Assumes the gaps hold and nobody
 * else stops; each gap is from that car's last crossing of the line. Lapped
 * cars are behind every lead-lap car whatever happens, so they are left out.
 * Null when `car` has no gap to the leader (lapped, out, or not started).
 */
export function rejoin(drivers: DriverTiming[], car: number, loss: number) {
  const running = drivers
    .filter((d) => d.status === "racing" && d.laps_down === 0)
    .map((d) => ({ n: d.driver_number, color: d.team_color, gap: d.gap_to_leader_s ?? (d.position === 1 ? 0 : null) }))
    .filter((d): d is { n: number; color: string | null; gap: number } => d.gap !== null)
    .sort((a, b) => a.gap - b.gap);
  const me = running.find((d) => d.n === car);
  if (!me) return null;
  const gap = me.gap + loss;
  const others = running.filter((d) => d.n !== car);
  const after = others.findIndex((d) => d.gap > gap);
  const at = after < 0 ? others.length : after;
  const list = [...others.slice(0, at), { ...me, gap, me: true }, ...others.slice(at)];
  return { from: running.indexOf(me), to: at, gap, list, ahead: others[at - 1], behind: others[at] };
}

/**
 * One car's race as stints: the sets run so far (from its laps up to `lap`),
 * then the model's plan dashed: the current set to the most likely stop lap and
 * the next compound to the flag, or the current set to the flag when it needs
 * no more stops. Only the next stop is modelled, so a later one is not drawn.
 */
export function stintsFor(compounds: (string | null)[], laps: number[], pitIn: boolean[], lap: number, window: PitWindows["cars"][number]["window"], total: number): Run[] {
  const runs: Run[] = [];
  laps.forEach((l, i) => {
    if (l > lap) return;
    const c = compounds[i] ?? "UNKNOWN";
    const last = runs[runs.length - 1];
    if (last && last.compound === c && !pitIn[i - 1]) last.to = l;
    else runs.push({ compound: c, from: l, to: l });
  });
  const now = runs[runs.length - 1];
  if (!now || !window) return runs;
  const stop = window.no_stop ? total : Math.min(total, Math.max(window.most_likely_lap, now.to));
  if (stop > now.to) runs.push({ compound: now.compound, from: now.to + 1, to: stop, plan: true });
  if (!window.no_stop && stop < total) runs.push({ compound: window.next_compound, from: stop + 1, to: total, plan: true });
  return runs;
}

/**
 * When each car is likely to stop, and where it would come out, as
 * racecraft-ui.html draws it (D-025). Stints: every car's sets so far, solid,
 * and the strategy model's plan dashed, the selected car's window shaded and
 * the leader's lap marked. Beside it, where the selected car rejoins if it
 * pits this lap, at the model's pit loss or a quick or slow stop either side.
 * What if: the model's cheapest plans for the race, with and without safety
 * cars, and in places.
 */
export function StrategyScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [mode, setMode] = useState<Mode>("windows");
  const [picked, setPicked] = useState<number | null>(null);
  const [lossPick, setLossPick] = useState(1);
  const lap = ctx.state?.leader_lap ?? 0;
  const { answer, error } = usePitWindows(ctx.session, ctx.t, lap, mode === "windows" && lap > 0);
  const total = answer?.total_laps ?? ctx.info.total_laps ?? 1;
  const codeOf = (n: number) => ctx.driverCodes[n] ?? String(n);
  const pct = (l: number) => `${(Math.min(Math.max(l, 0), total) / total) * 100}%`;

  // The three pit losses: the model's figure, and its median absolute deviation either side (a quick or a slow stop).
  const losses = answer
    ? [...new Set([-1, 0, 1].map((k) => Math.round((answer.model.pit_loss_s + k * answer.model.pit_spread_s) * 10) / 10))]
    : [];
  const loss = losses[Math.min(lossPick, losses.length - 1)] ?? 0;
  const cars = answer?.cars ?? [];
  const sel = cars.find((c) => c.driver_number === picked)?.driver_number
    ?? cars.find((c) => c.driver_number === ctx.selected[0])?.driver_number
    ?? cars.find((c) => c.status === "racing")?.driver_number;
  const selCar = cars.find((c) => c.driver_number === sel);
  const selCode = sel === undefined ? "" : codeOf(sel);
  const w = selCar?.window && !selCar.window.no_stop ? selCar.window : null;
  const pits = sel === undefined ? null : rejoin(ctx.state?.drivers ?? [], sel, loss);
  const threat = answer?.undercuts.find((u) => u.target === sel);

  const stints = useMemo(() => {
    const out = new Map<number, Run[]>();
    for (const s of ctx.laps) {
      const car = answer?.cars.find((c) => c.driver_number === s.driver_number);
      out.set(s.driver_number, stintsFor(s.compound, s.laps, s.pit_in, lap, car?.status === "racing" ? car.window : null, total));
    }
    return out;
  }, [ctx.laps, lap, answer, total]);

  const switcher = (
    <>
      <LapCounter lap={lap} total={ctx.info.total_laps} />
      {mode === "windows" && losses.length > 1 && (
        <div className="segmented" role="radiogroup" aria-label="Pit loss">
          {losses.map((v, i) => (
            <button key={v} type="button" role="radio" aria-checked={loss === v} className={`num${loss === v ? " is-on" : ""}`}
                    onClick={() => setLossPick(i)}>{v.toFixed(1)} s</button>
          ))}
        </div>
      )}
      <div className="segmented" role="radiogroup" aria-label="Mode">
        {([["windows", "Pit windows"], ["whatif", "What if"]] as [Mode, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={mode === key} className={mode === key ? "is-on" : ""}
                  onClick={() => setMode(key)}>{text}</button>
        ))}
      </div>
    </>
  );

  if (mode === "whatif") {
    return (
      <div className="screen">
        {header(switcher)}
        <main className="screen-body">
          <section className="panel">
            <StrategyBoard insight={ctx.insight} loading={!ctx.insight && !ctx.insightError} error={ctx.insightError}
                           actualStops={ctx.actualStops} sessionKey={ctx.session} />
          </section>
        </main>
      </div>
    );
  }

  const ticks = [1, ...Array.from({ length: Math.floor((total - 1) / 10) }, (_, k) => (k + 1) * 10).filter((l) => total - l >= 4), total];
  const summary = pits && (
    `${selCode} is P${pits.from + 1}. Pitting this lap costs ${loss.toFixed(1)} s, so ${selCode} would rejoin P${pits.to + 1}`
    + (pits.ahead ? `, ${(pits.gap - pits.ahead.gap).toFixed(1)} s behind ${codeOf(pits.ahead.n)}` : "")
    + (pits.behind ? ` and ${(pits.behind.gap - pits.gap).toFixed(1)} s ahead of ${codeOf(pits.behind.n)}` : "") + ".");

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body strat-body">
        {error && <p className="panel-note error">{error}</p>}
        {!answer && !error && (
          <p className="panel-note">{lap > 0 ? "Working out the pit windows: the first time for a season fits the tyre model, about half a minute."
            : "Pit windows start once the race is under way."}</p>
        )}
        {answer && (
          <>
            {/* Always four tiles: the row's columns line up with the panels below. */}
            <KpiRow tiles={[
              { label: "Pit loss (model)", value: `${answer.model.pit_loss_s.toFixed(1)} s`,
                note: `lane time plus stationary, from ${answer.model.fitted_on_count ?? "earlier"} earlier races` },
              { label: `${selCode} best window`,
                value: w ? `L${w.window[0]}–L${w.window[1]}` : selCar?.window?.no_stop ? "To the flag" : "—",
                note: w ? `from the tyre model, ${selCar?.compound?.toLowerCase() ?? "this set"} to ${w.next_compound.toLowerCase()}`
                  : selCar?.window?.no_stop ? "no more stops needed on this set" : "out, or no wear model for this tyre" },
              { label: `If ${selCode} pits now`, value: pits ? `P${pits.from + 1} → P${pits.to + 1}` : "—",
                note: !pits ? "not on the lead lap" : pits.ahead ? `${(pits.gap - pits.ahead.gap).toFixed(1)} s behind ${codeOf(pits.ahead.n)}` : "clear air" },
              { label: "Undercut threat", value: threat ? `${codeOf(threat.chaser)} +${threat.gap_s.toFixed(1)}` : "None",
                tone: threat ? "bad" : undefined,
                note: threat ? `${Math.round(threat.chance * 100)}% chance stopping first gets the place` : "no car close enough behind to undercut" },
            ]} />
            <div className="strat-grid">
              <section className="panel strat-stints" aria-label="Stints">
                <div className="panel-bar">
                  <h2>Stints</h2><span className="panel-meta">bars: run so far · ahead, brighter green: a cheaper lap to stop · tick: the cheapest · click a driver</span>
                  <span className="strat-legend">
                    {(["SOFT", "MEDIUM", "HARD"] as const).map((c) => <span key={c} className="tyre-chip" style={{ background: COMPOUND_COLORS[c] }}>{c[0]}</span>)}
                    <i className="strat-win-key" />{selCode} window
                  </span>
                </div>
                <div className="strat-scroll">
                  <div className="strat-row is-head cap">
                    <span className="right">P</span><span /><span>Drv</span>
                    <span className="strat-ticks">
                      {ticks.map((l, i) => (
                        <span key={l} className="num" style={{ left: pct(l === 1 ? 0 : l), transform: `translate(${i === 0 ? "0" : i === ticks.length - 1 ? "-100%" : "-50%"}, -50%)` }}>L{l}</span>
                      ))}
                    </span>
                    <span className="right">Done+plan</span>
                  </div>
                  <div className="strat-rows">
                    {cars.map((car) => {
                      const runs = (stints.get(car.driver_number) ?? []).filter((r) => !r.plan);
                      const strip = car.status === "racing" ? car.window : null;
                      const done = car.stops ?? Math.max(runs.filter((r) => !r.plan).length - 1, 0);
                      const planned = car.status === "racing" && car.window && !car.window.no_stop ? 1 : 0;
                      return (
                        <button key={car.driver_number} type="button" aria-pressed={car.driver_number === sel}
                                className={`strat-row${car.driver_number === sel ? " is-selected" : ""}${car.status === "out" ? " is-out" : ""}`}
                                onClick={() => setPicked(car.driver_number)}>
                          <span className="num right strong">{car.status === "out" ? "OUT" : car.position ?? ""}</span>
                          <span className="team-bar" style={{ background: `#${car.team_color ?? "777"}` }} />
                          <span className="num strong">{codeOf(car.driver_number)}</span>
                          <span className="strat-lane">
                            {runs.map((r, k) => (
                              <span key={k} className="strat-stint" title={`${r.compound.toLowerCase()}, laps ${r.from}–${r.to}`}
                                    style={{ left: pct(r.from - 1), width: pct(r.to - r.from + 1), ["--tyre" as string]: COMPOUND_COLORS[r.compound] ?? "#3A3A42" }}>
                                {r.compound[0]}
                              </span>
                            ))}
                            {/* The rest of the race (D-033): each lap shaded by what stopping on it costs, brightest
                                where cheapest; the white tick is the cheapest lap, with the tyre it would go to. */}
                            {strip?.costs?.map(([stopLap, extra]) => (
                              <span key={stopLap} className="strat-cost" title={`stop on lap ${stopLap}: ${extra === 0 ? "the cheapest" : `+${extra.toFixed(1)} s`}`}
                                    style={{ left: pct(stopLap - 1), width: pct(1), opacity: costShade(extra) }} />
                            ))}
                            {strip && !strip.no_stop && (
                              <span className="strat-best" style={{ left: pct(strip.most_likely_lap - 0.5) }}
                                    title={`cheapest stop: lap ${strip.most_likely_lap}, onto ${strip.next_compound.toLowerCase()}`}>
                                <i className="tyre-chip" style={{ background: COMPOUND_COLORS[strip.next_compound] ?? "#888" }}>{strip.next_compound[0]}</i>
                              </span>
                            )}
                            {strip?.no_stop && <span className="strat-flag panel-meta" style={{ left: pct(lap) }}>no stop needed</span>}
                          </span>
                          <span className="num right">{done}+{planned}</span>
                        </button>
                      );
                    })}
                    <div className="strat-row strat-overlay" aria-hidden="true">
                      <span /><span /><span />
                      <span className="strat-lane">
                        {w && <span className="strat-win" style={{ left: pct(w.window[0] - 1), width: pct(w.window[1] - w.window[0] + 1) }} />}
                        <span className="strat-now" style={{ left: pct(lap) }} />
                      </span>
                      <span />
                    </div>
                  </div>
                </div>
              </section>
              <section className="panel strat-rejoin" aria-label="Rejoin if the selected driver pits now">
                <div className="panel-bar"><h2>Pit now: rejoin</h2><span className="panel-meta num">{selCode} · +{loss.toFixed(1)} s</span></div>
                <p className="strat-summary">{summary ?? `${selCode || "This car"} is not on the lead lap, so there is no gap to rejoin by.`}</p>
                {pits && <RejoinLine pits={pits} codeOf={codeOf} />}
                <div className="strat-rejoin-list">
                  {pits?.list.slice(Math.max(0, pits.to - 4), pits.to + 5).map((o) => {
                    const rel = o.gap - pits.gap;
                    const mine = "me" in o;
                    const traffic = !mine && Math.abs(rel) < TRAFFIC_S;
                    return (
                      <div key={o.n} className={`strat-rj${mine ? " is-me" : ""}`}>
                        <span className="num right strong">{pits.list.indexOf(o) + 1}</span>
                        <span className="team-bar" style={{ background: `#${o.color ?? "777"}` }} />
                        <span className="num strong">{codeOf(o.n)}</span>
                        <span className="panel-meta">{mine ? "after the stop" : traffic ? "traffic" : ""}</span>
                        <span className={`num right${traffic ? " is-traffic" : ""}`}>
                          {mine ? `new +${o.gap.toFixed(1)}` : `${rel > 0 ? "+" : "−"}${Math.abs(rel).toFixed(1)}`}
                        </span>
                      </div>
                    );
                  })}
                </div>
                <p className="strat-foot">Gaps at each car's last time over the line; assumes nobody else stops. Windows from
                  tyre wear fitted on {answer.model.fitted_on_count ?? "earlier"} earlier races, never this one. {answer.notes[1]}</p>
              </section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

/** How bright a lap of the cost strip is: the cheapest full, fading to faint at 8 s or more. */
export function costShade(extra: number): number {
  return Math.max(0.08, 1 - Math.min(Math.max(extra, 0), 8) / 8);
}

/** Seconds either side of the rejoin point the gap line shows. */
const REJOIN_SPAN_S = 12;

/**
 * Where the selected car comes out, as a line of gaps (D-033): the car after
 * its stop is the ring at the centre, every other car on the lead lap a dot at
 * its gap, ahead to the left. The band is traffic, within 1.5 s either way.
 * Cars further away than the span are left to the list below.
 */
function RejoinLine({ pits, codeOf }: {
  pits: NonNullable<ReturnType<typeof rejoin>>; codeOf: (n: number) => string;
}) {
  const x = (rel: number) => 50 + (Math.max(-REJOIN_SPAN_S, Math.min(REJOIN_SPAN_S, rel)) / REJOIN_SPAN_S) * 46;
  const near = pits.list.filter((o) => !("me" in o) && Math.abs(o.gap - pits.gap) <= REJOIN_SPAN_S);
  return (
    <div className="rejoin-line" role="img"
         aria-label={`Rejoining: ${near.map((o) => `${codeOf(o.n)} ${(o.gap - pits.gap).toFixed(1)} s`).join(", ")}`}>
      <span className="rejoin-traffic" style={{ left: `${x(-TRAFFIC_S)}%`, width: `${x(TRAFFIC_S) - x(-TRAFFIC_S)}%` }} />
      <span className="rejoin-axis" />
      {[-10, -5, 5, 10].map((s) => (
        <span key={s} className="rejoin-tick num" style={{ left: `${x(s)}%` }}>{s > 0 ? `+${s}` : `−${-s}`}</span>
      ))}
      {near.map((o, k) => (
        <span key={o.n} className={`rejoin-car${k % 2 ? " is-low" : ""}`} style={{ left: `${x(o.gap - pits.gap)}%` }}>
          <i style={{ background: `#${o.color ?? "777"}` }} />
          <b className="num">{codeOf(o.n)}</b>
        </span>
      ))}
      <span className="rejoin-car is-me" style={{ left: "50%" }}><i /><b className="num">{codeOf(pits.list.find((o) => "me" in o)!.n)}</b></span>
      <span className="rejoin-caption cap"><span>ahead</span><span>behind</span></span>
    </div>
  );
}

