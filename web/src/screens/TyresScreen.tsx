import { useEffect, useState, type ReactNode } from "react";
import { api, COMPOUND_COLORS, type DegradationCurve, type TyreSets as TyreSetsAnswer } from "../api";
import { carAt, TyreSets } from "../panels/TyreSets";
import type { ScreenContext } from "./ScreenView";

const ORDER = ["SOFT", "MEDIUM", "HARD"];
/** The model has no cliff (strategy.py: wear past where teams pit is unmeasured), so a second lost is the marker. */
const LOST_MARK_S = 1.0;
/** The chart's ceiling: past this the curves are extrapolation nobody runs to. */
const MAX_LOST_S = 4;

/** Seconds lost at an age, read off the model's curve. */
export function lostAt(curve: DegradationCurve | undefined, age: number): number | null {
  if (!curve || !curve.points.length) return null;
  const points = curve.points;
  const after = points.findIndex((p) => p.age >= age);
  if (after <= 0) return after === 0 ? points[0]!.model_s : points[points.length - 1]!.model_s;
  const a = points[after - 1]!;
  const b = points[after]!;
  return a.model_s + ((b.model_s - a.model_s) * (age - a.age)) / (b.age - a.age || 1);
}

/** The age at which the model says a set has lost a second, or null if it never does in range. */
export function ageAtLost(curve: DegradationCurve | undefined, seconds = LOST_MARK_S): number | null {
  const hit = curve?.points.find((p) => p.model_s >= seconds);
  return hit ? hit.age : null;
}

/** Seconds a lap lost to wear at this age: the curve's slope over the last lap. */
function degAt(curve: DegradationCurve | undefined, age: number): number | null {
  const now = lostAt(curve, age);
  const before = lostAt(curve, Math.max(age - 1, 0));
  return now == null || before == null ? null : now - before;
}

/** Every car's dry sets, from the set tracker (TyreSets); null until it answers. */
function useSets(session: string) {
  const [answer, setAnswer] = useState<TyreSetsAnswer | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    setAnswer(null);
    // The strip is a summary: when the tracker cannot answer it is left out, and the sets tab says why.
    api.tyreSets(session, controller.signal).then(setAnswer).catch(() => undefined);
    return () => controller.abort();
  }, [session]);
  return answer;
}

/**
 * How fast each compound fades, and where every car sits on that curve, as
 * racecraft-ui.html draws it (D-025): a tile per compound, the curves, the
 * selected car's sets left, and every car's tyre now. The curves are the
 * strategy model's: fitted on this season's earlier races, never on this one.
 * They are a fit, not measured wear: the feed gives tyre age and compound,
 * nothing about temperature. What this race's laps did is hindsight, so it
 * shows only when asked for.
 */
export function TyresScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [only, setOnly] = useState<"all" | "followed">("all");
  const [tab, setTab] = useState<"now" | "sets">("now");
  // What this race's tyres actually did: hindsight, so off until asked for.
  const [observed, setObserved] = useState(false);
  const sets = useSets(ctx.session);
  const insight = ctx.insight;
  const curves = new Map((insight?.degradation_curve ?? []).map((c) => [c.compound, c]));
  const compounds = ORDER.filter((c) => curves.has(c));
  const maxAge = Math.max(30, ...compounds.map((c) => curves.get(c)!.points.at(-1)?.age ?? 0));
  const maxLost = Math.min(MAX_LOST_S, Math.max(2, ...compounds.map((c) => Math.ceil(lostAt(curves.get(c), maxAge) ?? 0))));
  const x = (age: number) => (age / maxAge) * 100;
  const y = (s: number) => 100 - (Math.min(s, maxLost) / maxLost) * 100;
  const all = ctx.state?.drivers ?? [];
  const drivers = all.filter((d) => only === "all" || ctx.selected.includes(d.driver_number));
  const setsFor = all.find((d) => d.driver_number === ctx.selected.at(-1)) ?? all[0];
  const setsCar = sets?.cars.find((c) => c.driver_number === setsFor?.driver_number);
  const left = setsCar ? carAt(setsCar, ctx.state?.t ?? ctx.info.t_start) : null;

  const filter = (
    <div className="segmented" role="radiogroup" aria-label="Filter">
      {([["all", "All drivers"], ["followed", "Followed"]] as const).map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={only === key} className={only === key ? "is-on" : ""}
                onClick={() => setOnly(key)}>{text}</button>
      ))}
    </div>
  );

  if (!insight) {
    return (
      <div className="screen">
        {header(filter)}
        <main className="screen-body">
          <p className="panel-note">{ctx.insightError ?? "Fitting the season's tyre wear: a few seconds the first time."}</p>
        </main>
      </div>
    );
  }
  return (
    <div className="screen">
      {header(filter)}
      <main className="screen-body tyres-body">
        <div className="tyres-grid">
          <div className="tyres-left">
            <div className="tyres-kpis" role="list" aria-label="Headline figures">
              {compounds.map((c) => {
                const curve = curves.get(c);
                const deg = degAt(curve, 10);
                const mark = ageAtLost(curve);
                return (
                  <div key={c} className="kpi tyres-kpi" role="listitem" aria-label={`${c.toLowerCase()} tyre`}>
                    <span className="tyre-chip big" style={{ background: COMPOUND_COLORS[c] }}>{c[0]}</span>
                    <div>
                      <span className="cap">{c.charAt(0) + c.slice(1).toLowerCase()}{insight.compounds ? ` ${insight.compounds[c as "SOFT"]}` : ""}</span>
                      <b className="num">{deg != null ? `${deg.toFixed(3)} s/lap` : "—"}</b>
                      <span className="kpi-note">{mark != null ? `1 s lost by lap ${mark}` : `under 1 s to lap ${maxAge}`} · {all.filter((d) => d.status === "racing" && d.compound === c).length} cars on it</span>
                    </div>
                  </div>
                );
              })}
            </div>
            <section className="panel tyres-chart" aria-label="Tyre wear model">
              <div className="panel-bar">
                <h2>Degradation</h2>
                <span className="panel-meta">seconds lost to a new tyre by its age in laps · the model, fitted on {insight.fitted_on_count} earlier race{insight.fitted_on_count === 1 ? "" : "s"} · each car at its tyre's age{observed ? " · dots: this race, in hindsight" : ""}</span>
                {!insight.observed_unavailable && (
                  <button type="button" className={`toggle${observed ? " is-on" : ""}`} aria-pressed={observed}
                          style={{ marginLeft: "auto" }} onClick={() => setObserved((on) => !on)}
                          title="Hindsight: what this race's laps showed at each tyre age, to read the model against">
                    What this race did
                  </button>
                )}
              </div>
              {/* One chart per compound (D-033): the three curves overlapped into one; apart, each shows its own cars. */}
              <div className="tyres-multiples">
                {compounds.map((c) => {
                  const curve = curves.get(c)!;
                  const mark = ageAtLost(curve);
                  const on = drivers.filter((d) => d.status === "racing" && d.compound === c && d.tyre_life != null);
                  // Cars on the same age stack their codes upward from the one dot.
                  const byAge = new Map<number, typeof on>();
                  for (const d of on) byAge.set(d.tyre_life!, [...(byAge.get(d.tyre_life!) ?? []), d]);
                  return (
                    <div key={c} className="tyres-multiple" aria-label={`${c.toLowerCase()}: ${on.length} cars`}>
                      <div className="tyres-multiple-head">
                        <span className="tyre-chip" style={{ background: COMPOUND_COLORS[c] }}>{c[0]}</span>
                        <b>{c.charAt(0) + c.slice(1).toLowerCase()}</b>
                        <span className="panel-meta">{on.length} {on.length === 1 ? "car" : "cars"}</span>
                      </div>
                      <div className="tyres-plot">
                        {Array.from({ length: maxLost + 1 }, (_, v) => (
                          <span key={`y${v}`} className="tyres-gl" style={{ top: `${y(v)}%` }}><i className="num">+{v}</i></span>
                        ))}
                        {Array.from({ length: Math.floor(maxAge / 10) + 1 }, (_, k) => k * 10).map((age) => (
                          <span key={`x${age}`} className="tyres-gv" style={{ left: `${x(age)}%` }}><i className="num">{age}</i></span>
                        ))}
                        {mark != null && (
                          <span className="tyres-mark" style={{ left: `${x(mark)}%`, borderColor: COMPOUND_COLORS[c] }}>
                            <i className="num" style={{ color: COMPOUND_COLORS[c] }}>1 s · L{mark}</i>
                          </span>
                        )}
                        <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={`Modelled lap time lost against tyre age, ${c.toLowerCase()}`}>
                          <path d={curve.points.map((p, k) => `${k ? "L" : "M"}${x(p.age).toFixed(2)} ${y(p.model_s).toFixed(2)}`).join("")}
                                fill="none" stroke={COMPOUND_COLORS[c]} strokeWidth="2.2" vectorEffect="non-scaling-stroke" />
                        </svg>
                        {observed && curve.points.filter((p) => p.observed_s != null).map((p) => (
                          <span key={`o${p.age}`} className="tyres-dot" title={`age ${p.age}: +${p.observed_s!.toFixed(2)} s over ${p.laps} laps`}
                                style={{ left: `${x(p.age)}%`, top: `${y(p.observed_s!)}%`, background: COMPOUND_COLORS[c] }} />
                        ))}
                        {[...byAge].map(([age, cars]) => {
                          const lost = lostAt(curve, age) ?? 0;
                          return (
                            <span key={`c${age}`} className="tyres-car" style={{ left: `${x(Math.min(age, maxAge))}%`, top: `${y(lost)}%` }}
                                  title={`${cars.map((d) => d.abbreviation).join(", ")}: ${age} laps old, +${lost.toFixed(2)} s`}>
                              <i style={{ borderColor: COMPOUND_COLORS[c] }} />
                              {cars.length > 1 && <em className="num">{cars.length}</em>}
                            </span>
                          );
                        })}
                      </div>
                      <ul className="tyres-ages" aria-label={`${c.toLowerCase()} cars by tyre age`}>
                        {[...byAge].sort((a, b) => b[0] - a[0]).map(([age, cars]) => (
                          <li key={age}>
                            <span className="num muted">{age} laps</span>
                            {cars.map((d) => (
                              <b key={d.driver_number} className={`num${ctx.selected.includes(d.driver_number) ? " is-followed" : ""}`}
                                 style={{ color: `#${d.team_color ?? "AEB4BD"}` }}>{d.abbreviation}</b>
                            ))}
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
              {left && setsFor && (
                <div className="tyres-alloc">
                  <span className="cap">Sets left · {setsFor.abbreviation}</span>
                  <div>
                    {ORDER.map((c) => (
                      <div key={c}>
                        <span className="tyre-chip" style={{ background: COMPOUND_COLORS[c] }}>{c[0]}</span>
                        <span className="num strong">{left[c]?.fresh ?? 0} new</span>
                        <span className="panel-meta">{left[c]?.used.length ?? 0} used</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </section>
          </div>

          <section className="panel tyres-now" aria-label="Tyres on every car now">
            <div className="panel-bar">
              <div className="segmented" role="radiogroup" aria-label="Tyre view">
                {([["now", "On every car now"], ["sets", "Every car's sets"]] as const).map(([key, text]) => (
                  <button key={key} type="button" role="radio" aria-checked={tab === key} className={tab === key ? "is-on" : ""}
                          onClick={() => setTab(key)}>{text}</button>
                ))}
              </div>
              <span className="panel-meta">{tab === "now" ? `lap ${ctx.state?.leader_lap ?? 0} · race order` : "new filled, used ringed with their laps"}</span>
            </div>
            {tab === "sets" ? (
              <div className="tyres-scroll">
                <TyreSets sessionKey={ctx.session} t={ctx.state?.t ?? ctx.info.t_start} drivers={all}
                          selected={ctx.selected} onSelect={ctx.onSelect} insight={ctx.insight} />
              </div>
            ) : (
              <div className="tyres-scroll">
                <div className="tyres-row is-head cap">
                  <span className="right">P</span><span /><span>Drv</span><span>Tyre</span><span>Life to 1 s</span>
                  <span className="right">To 1 s</span><span className="right">Deg now</span><span className="right">Vs new</span>
                </div>
                {drivers.map((d) => {
                  const curve = d.compound ? curves.get(d.compound) : undefined;
                  const age = d.tyre_life;
                  const lost = age != null ? lostAt(curve, age) : null;
                  const mark = ageAtLost(curve);
                  const used = mark && age != null ? Math.min(age / mark, 1) : null;
                  const toMark = mark != null && age != null ? mark - age : null;
                  const deg = age != null ? degAt(curve, age) : null;
                  return (
                    <button key={d.driver_number} type="button" aria-pressed={ctx.selected.includes(d.driver_number)}
                            className={`tyres-row${d.status === "out" ? " is-out" : ""}${ctx.selected.includes(d.driver_number) ? " is-selected" : ""}`}
                            onClick={() => ctx.onSelect(d.driver_number)}>
                      <span className="num right strong">{d.status === "out" ? "OUT" : d.position}</span>
                      <span className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
                      <span className="num strong">{d.abbreviation}</span>
                      <span className="tyre-cell">
                        {d.compound ? <span className="tyre-chip" style={{ background: COMPOUND_COLORS[d.compound] ?? "#888" }}>{d.compound[0]}</span> : "—"}
                        <span className="num">{age ?? ""}</span>
                      </span>
                      <span className="tyres-life">
                        {used != null && <i className={used > 0.85 ? "is-bad" : used > 0.6 ? "is-warn" : ""} style={{ width: `${used * 100}%` }} />}
                      </span>
                      <span className={`num right${toMark != null && toMark <= 3 ? " is-bad" : ""}`}>{toMark == null ? "—" : toMark > 0 ? `${toMark} lap${toMark === 1 ? "" : "s"}` : "past it"}</span>
                      <span className="num right">{deg != null ? deg.toFixed(3) : "—"}</span>
                      <span className="num right is-loss">{lost != null ? `+${lost.toFixed(2)} s` : "—"}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </section>
        </div>
      </main>
    </div>
  );
}
