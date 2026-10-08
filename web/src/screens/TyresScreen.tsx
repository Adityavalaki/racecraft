import { useState, type ReactNode } from "react";
import { COMPOUND_COLORS, type DegradationCurve } from "../api";
import { TyreSets } from "../panels/TyreSets";
import type { ScreenContext } from "./ScreenView";

const ORDER = ["SOFT", "MEDIUM", "HARD"];
const LOST_MARK_S = 1.0;
const CHART_H = 300;

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

/**
 * How fast each compound fades, and where every car sits on that curve.
 *
 * The curves are the strategy model's: fitted on this season's earlier races,
 * never on this one, at the scale the plans use. They are a fit, not measured
 * wear: the feed gives tyre age and compound, and nothing about temperature or
 * how many sets are left.
 */
export function TyresScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [only, setOnly] = useState<"all" | "followed">("all");
  // What this race's tyres actually did: hindsight, so off until asked for.
  const [observed, setObserved] = useState(false);
  const insight = ctx.insight;
  const curves = new Map((insight?.degradation_curve ?? []).map((c) => [c.compound, c]));
  const compounds = ORDER.filter((c) => curves.has(c));
  const maxAge = Math.max(30, ...compounds.map((c) => curves.get(c)!.points.at(-1)?.age ?? 0));
  const maxLost = Math.max(2.5, ...compounds.map((c) => Math.min(lostAt(curves.get(c), maxAge) ?? 0, 4)));
  const x = (age: number) => (age / maxAge) * 1000;
  const y = (s: number) => CHART_H - (Math.min(s, maxLost) / maxLost) * CHART_H;
  const drivers = (ctx.state?.drivers ?? []).filter((d) => only === "all" || ctx.selected.includes(d.driver_number));
  const followed = (ctx.state?.drivers ?? []).filter((d) => ctx.selected.includes(d.driver_number) && d.compound && d.tyre_life != null);
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
      <main className="screen-body">
        <p className="screen-caveat"><span className="tag">Modelled</span>
          Curves are the strategy model's fit on {insight.fitted_on_count} earlier race{insight.fitted_on_count === 1 ? "" : "s"},
          never this one. The feed gives tyre age and compound; temperatures and sets left are not public.</p>
        <div className="tyres-top">
          <section className="panel" aria-label="Tyre wear model">
            <div className="panel-bar">
              <h2>Lap time lost by tyre age</h2>
              <span className="panel-meta">Compared with a fresh tyre on the same fuel load.</span>
              {!insight.observed_unavailable && (
                <button type="button" className={`toggle${observed ? " is-on" : ""}`} aria-pressed={observed}
                        style={{ marginLeft: "auto" }} onClick={() => setObserved((on) => !on)}
                        title="Hindsight: what this race's laps showed at each tyre age, to read the model against">
                  What this race did
                </button>
              )}
            </div>
            <div className="wear-chart">
              <div className="wear-y num">
                {[0, 0.5, 1, 1.5, 2, 2.5].filter((v) => v <= maxLost).map((v) => (
                  <span key={v} style={{ top: `${(y(v) / CHART_H) * 100}%` }}>{v} s</span>
                ))}
              </div>
              <div className="wear-plot">
                <svg viewBox={`0 0 1000 ${CHART_H}`} preserveAspectRatio="none" role="img"
                     aria-label="Modelled lap time lost against tyre age for each compound">
                  <line x1="0" x2="1000" y1={y(LOST_MARK_S)} y2={y(LOST_MARK_S)} stroke="#62626E" strokeDasharray="6 5" vectorEffect="non-scaling-stroke" />
                  {compounds.map((c) => (
                    <path key={c} d={curves.get(c)!.points.map((p, k) => `${k ? "L" : "M"}${x(p.age).toFixed(1)} ${y(p.model_s).toFixed(1)}`).join("")}
                          fill="none" stroke={COMPOUND_COLORS[c]} strokeWidth="2.4" vectorEffect="non-scaling-stroke" />
                  ))}
                  {observed && compounds.map((c) => (
                    <path key={`${c}-seen`} fill="none" stroke={COMPOUND_COLORS[c]} strokeWidth="1.6" strokeDasharray="2 5"
                          strokeLinecap="round" vectorEffect="non-scaling-stroke"
                          d={curves.get(c)!.points.filter((p) => p.observed_s != null)
                            .map((p, k) => `${k ? "L" : "M"}${x(p.age).toFixed(1)} ${y(p.observed_s!).toFixed(1)}`).join("")} />
                  ))}
                </svg>
                {followed.map((d) => {
                  const lost = lostAt(curves.get(d.compound!), d.tyre_life!);
                  if (lost == null) return null;
                  return (
                    <span key={d.driver_number} className="wear-car"
                          style={{ left: `${x(d.tyre_life!) / 10}%`, top: `${(y(lost) / CHART_H) * 100}%` }}>
                      <i style={{ background: `#${d.team_color ?? "777"}` }} /><b className="display">{d.abbreviation}</b>
                    </span>
                  );
                })}
                <span className="wear-mark num" style={{ top: `${(y(LOST_MARK_S) / CHART_H) * 100}%` }}>1 s lost</span>
              </div>
              <div />
              <div className="wear-x num">
                {Array.from({ length: Math.floor(maxAge / 5) + 1 }, (_, k) => k * 5).map((age) => (
                  <span key={age} style={{ left: `${x(age) / 10}%` }}>{age}</span>
                ))}
              </div>
            </div>
            <div className="axis-caption">Tyre age in laps{observed ? ". Dotted: what this race's laps showed, in hindsight." : ""}</div>
          </section>
          <div className="compound-cards">
            {compounds.map((c) => {
              const curve = curves.get(c);
              const at10 = lostAt(curve, 10);
              const at9 = lostAt(curve, 9);
              const mark = ageAtLost(curve);
              return (
                <section key={c} className="panel compound-card" aria-label={`${c.toLowerCase()} tyre`}>
                  <div className="compound-head">
                    <span className="tyre-chip big" style={{ background: COMPOUND_COLORS[c] }}>{c[0]}</span>
                    <h2>{c.charAt(0) + c.slice(1).toLowerCase()}</h2>
                    {insight.compounds && <span className="panel-meta">{insight.compounds[c as "SOFT"]}</span>}
                  </div>
                  <dl>
                    <dt>Lost per lap at age 10</dt><dd className="num">{at10 != null && at9 != null ? `${(at10 - at9).toFixed(3)} s` : "—"}</dd>
                    <dt>Age at 1 s lost</dt><dd className="num">{mark != null ? `${mark} laps` : `over ${maxAge} laps`}</dd>
                    <dt>Slower than a soft, new</dt><dd className="num">{insight.compound_offset_s[c] != null ? `${insight.compound_offset_s[c]!.toFixed(2)} s` : "—"}</dd>
                  </dl>
                </section>
              );
            })}
          </div>
        </div>

        <section className="panel" aria-label="Tyres on track now">
          <div className="panel-bar"><h2>On track now</h2><span className="panel-meta">Lap {ctx.state?.leader_lap ?? 0}. Yellow is a tyre already past a second lost.</span></div>
          <table className="tyre-table">
            <thead><tr>
              <th scope="col"><span className="visually-hidden">Team</span></th><th scope="col">Driver</th><th scope="col">Tyre</th>
              <th scope="col" className="right">Age</th><th scope="col">Set</th><th scope="col" className="right">Time lost now</th>
              <th scope="col">Age against 1 s lost</th><th scope="col" className="right">Laps left to 1 s</th>
            </tr></thead>
            <tbody>
              {drivers.map((d) => {
                const curve = d.compound ? curves.get(d.compound) : undefined;
                const lost = d.tyre_life != null ? lostAt(curve, d.tyre_life) : null;
                const mark = ageAtLost(curve);
                const past = lost != null && lost >= LOST_MARK_S;
                const left = mark != null && d.tyre_life != null ? mark - d.tyre_life : null;
                return (
                  <tr key={d.driver_number} className={d.status === "out" ? "is-out" : ""} onClick={() => ctx.onSelect(d.driver_number)}>
                    <td><span className="team-bar tall" style={{ background: `#${d.team_color ?? "555"}` }} /></td>
                    <th scope="row" className="display">{d.abbreviation}</th>
                    <td>{d.compound ? <span className="tyre-cell"><span className="tyre-chip" style={{ background: COMPOUND_COLORS[d.compound] ?? "#888" }}>{d.compound[0]}</span>{d.compound.toLowerCase()}</span> : "—"}</td>
                    <td className="num right">{d.tyre_life ?? "—"}</td>
                    <td>{ordinal(d.stops + 1)} set</td>
                    <td className={`num right${past ? " is-worse" : ""}`}>{lost != null ? `${lost.toFixed(2)} s` : "—"}</td>
                    <td>
                      <span className="age-bar">
                        <i className={past ? "is-past" : ""} style={{ width: `${mark && d.tyre_life != null ? Math.min(d.tyre_life / mark, 1) * 100 : 0}%` }} />
                      </span>
                    </td>
                    <td className="num right">{left == null ? "—" : left <= 0 ? "past" : left}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </section>

        <section className="panel">
          <div className="panel-bar"><h2>Every car's sets</h2><span className="panel-meta">New sets filled, used ones ringed with their laps. Follows the clock.</span></div>
          <TyreSets sessionKey={ctx.session} t={ctx.state?.t ?? ctx.info.t_start} drivers={ctx.state?.drivers ?? []}
                    selected={ctx.selected} onSelect={ctx.onSelect} insight={ctx.insight} />
        </section>
      </main>
    </div>
  );
}

function ordinal(n: number): string {
  const words = ["First", "Second", "Third", "Fourth", "Fifth", "Sixth"];
  return words[n - 1] ?? `${n}th`;
}
