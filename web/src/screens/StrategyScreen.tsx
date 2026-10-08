import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, COMPOUND_COLORS, type PitWindows } from "../api";
import { StrategyBoard } from "../panels/StrategyBoard";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Mode = "windows" | "whatif";
const isAbort = (e: Error) => e.name === "AbortError";
const STATUS_BANDS = new Set(["4", "6", "7"]);

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
 * When each car is likely to stop, and who can jump a place.
 *
 * Pit windows: for each running car, the stop lap that loses least over the
 * rest of the race under the strategy model, and the laps within two seconds
 * of it. The undercut watch: for each car within three seconds of the one
 * ahead, the chance stopping first gets the place. The stint map: every car's
 * race so far, set by set, with its window ahead. What if: the model's
 * cheapest plans for the race, with and without safety cars, and in places.
 */
export function StrategyScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [mode, setMode] = useState<Mode>("windows");
  const lap = ctx.state?.leader_lap ?? 0;
  const { answer, error } = usePitWindows(ctx.session, ctx.t, lap, mode === "windows" && lap > 0);
  const total = answer?.total_laps ?? ctx.info.total_laps ?? 1;
  const codeOf = (n: number) => ctx.driverCodes[n] ?? String(n);
  const pct = (l: number) => `${(Math.min(Math.max(l, 0), total) / total) * 100}%`;
  const followed = ctx.selected.length ? ctx.selected : (ctx.state?.drivers ?? []).slice(0, 2).map((d) => d.driver_number);

  // Each car's sets so far, from the laps it had finished: compound runs in lap order.
  const stints = useMemo(() => {
    const out = new Map<number, { compound: string; from: number; to: number }[]>();
    for (const s of ctx.laps) {
      const runs: { compound: string; from: number; to: number }[] = [];
      s.laps.forEach((l, i) => {
        if (l > lap) return;
        const c = s.compound[i] ?? "UNKNOWN";
        const last = runs[runs.length - 1];
        if (last && last.compound === c && !s.pit_in[i - 1]) last.to = l;
        else runs.push({ compound: c, from: l, to: l });
      });
      out.set(s.driver_number, runs);
    }
    return out;
  }, [ctx.laps, lap]);

  const bands = useMemo(() => {
    const statuses = [...(ctx.info.track_status ?? [])].sort((a, b) => a.t - b.t);
    const crossings = ctx.crossings;
    if (!crossings?.t.length) return [];
    const lapAt = (time: number) => {
      const k = crossings.t.findIndex((end) => end >= time);
      return k < 0 ? total : crossings.laps[k]!;
    };
    return statuses.flatMap((change, i) => {
      if (!STATUS_BANDS.has(change.status) || change.t > ctx.t) return [];
      return [{ from: lapAt(change.t), to: lapAt(Math.min(statuses[i + 1]?.t ?? ctx.info.t_end, ctx.t)) }];
    });
  }, [ctx.info, ctx.crossings, ctx.t, total]);

  const switcher = (
    <>
      <LapCounter lap={lap} total={ctx.info.total_laps} />
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

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        {error && <p className="panel-note error">{error}</p>}
        {!answer && !error && (
          <p className="panel-note">{lap > 0 ? "Working out the pit windows: the first time for a season fits the tyre model, about half a minute."
            : "Pit windows start once the race is under way."}</p>
        )}
        {answer && (
          <>
            <p className="screen-caveat"><span className="tag">Modelled</span>
              From the strategy model: tyre wear fitted on {answer.model.fitted_on_count ?? "earlier"} earlier races, never this one;
              a stop costs {answer.model.pit_loss_s.toFixed(1)} s here. {answer.notes[1]}</p>
            <div className="strategy-top">
              {followed.map((n) => {
                const car = answer.cars.find((c) => c.driver_number === n);
                if (!car) return null;
                const w = car.window;
                return (
                  <section key={n} className="panel pit-card" aria-label={`${codeOf(n)} pit stop estimate`}>
                    <div className="pit-card-head">
                      <span className="team-bar tall" style={{ background: `#${car.team_color ?? "777"}` }} />
                      <span className="display code">{codeOf(n)}</span>
                      {car.compound && (
                        <span className="tyre-cell"><span className="tyre-chip" style={{ background: COMPOUND_COLORS[car.compound] ?? "#888" }}>{car.compound[0]}</span>
                          {car.age} laps old</span>
                      )}
                    </div>
                    {w ? (
                      <>
                        <div className="pit-card-big">
                          <span className="display">{w.no_stop ? "—" : w.laps_until}</span>
                          <span>{w.no_stop ? "Runs to the flag on this set" : w.laps_until === 0 ? "Stop now" : "laps until the stop"}</span>
                        </div>
                        <div className="pit-lane-bar" aria-hidden="true">
                          <span className="done" style={{ width: pct(car.laps_completed) }} />
                          {!w.no_stop && <span className="window" style={{ left: pct(w.window[0] - 1), width: pct(w.window[1] - w.window[0] + 1) }} />}
                          {!w.no_stop && <span className="likely" style={{ left: pct(w.most_likely_lap - 0.5) }} />}
                        </div>
                        <div className="pit-card-foot">
                          {w.no_stop ? <span>The rules are met; stopping again costs more than the tyres lose.</span> : (
                            <>
                              <span>Window <b className="num">L{w.window[0]}–{w.window[1]}</b></span>
                              <span>Most likely <b className="num">L{w.most_likely_lap}</b></span>
                              <span>Then <b>{w.next_compound.toLowerCase()}</b></span>
                            </>
                          )}
                        </div>
                      </>
                    ) : <p className="panel-note">{car.status === "out" ? "Out of the race." : "Nothing to decide: too few laps left, or no wear model for this tyre."}</p>}
                  </section>
                );
              })}
              <section className="panel undercut" aria-label="Undercut watch">
                <div className="panel-bar"><h2>Undercut watch</h2><span className="panel-meta">Chance that stopping first gets the place.</span></div>
                {answer.undercuts.length === 0 ? <p className="empty">No car within three seconds of the one ahead.</p> : (
                  <ul className="undercut-list">
                    {answer.undercuts.slice(0, 8).map((u) => (
                      <li key={`${u.chaser}-${u.target}`}>
                        <span className="display">{codeOf(u.chaser)}</span>
                        <svg width="16" height="10" viewBox="0 0 16 10" aria-label="chasing"><path d="M1 5h13M10 1l4 4-4 4" stroke="currentColor" fill="none" strokeWidth="1.5" /></svg>
                        <span className="display">{codeOf(u.target)}</span>
                        <span className="num gap">+{u.gap_s.toFixed(3)}</span>
                        <span className="chance-bar"><i style={{ width: `${u.chance * 100}%` }} /></span>
                        <span className="num chance">{Math.round(u.chance * 100)}%</span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            </div>

            <section className="panel" aria-label="Stint map">
              <div className="panel-bar"><h2>Stint map</h2><span className="panel-meta">One row per driver: the sets run so far, and the window ahead dashed.</span></div>
              <div className="stint-map">
                <div className="stint-axis num">
                  <span />
                  <div>
                    {Array.from({ length: Math.floor(total / 10) + 1 }, (_, k) => k * 10).map((l) => (
                      <span key={l} style={{ left: pct(l) }}>{l}</span>
                    ))}
                    <span className="now" style={{ left: pct(lap) }}>Lap {lap}</span>
                  </div>
                </div>
                <div className="stint-rows">
                  <div className="stint-bands" aria-hidden="true">
                    {bands.map((b, k) => <span key={k} style={{ left: pct(b.from - 1), width: pct(Math.max(b.to - b.from + 1, 0.4)) }} />)}
                    <span className="stint-now" style={{ left: pct(lap) }} />
                  </div>
                  {answer.cars.map((car) => {
                    const runs = stints.get(car.driver_number) ?? [];
                    const w = car.window;
                    return (
                      <div key={car.driver_number} className={`stint-row${car.status === "out" ? " is-out" : ""}`}>
                        <span className="stint-code"><i style={{ background: `#${car.team_color ?? "777"}` }} /><span className="display">{codeOf(car.driver_number)}</span></span>
                        <div className="stint-lane">
                          {runs.map((r, k) => (
                            <span key={k} className="stint" title={`${r.compound.toLowerCase()}, laps ${r.from}–${r.to}`}
                                  style={{ left: pct(r.from - 1), width: pct(r.to - r.from + 1), background: COMPOUND_COLORS[r.compound] ?? "#3A3A42" }} />
                          ))}
                          {w && !w.no_stop && (
                            <span className="stint-window" style={{ left: pct(w.window[0] - 1), width: pct(w.window[1] - w.window[0] + 1) }}>
                              <span className="num">L{w.window[0]}–{w.window[1]}</span>
                            </span>
                          )}
                          {car.status === "out" && <span className="stint-note">Out</span>}
                        </div>
                      </div>
                    );
                  })}
                </div>
                <div className="map-legend">
                  <span><i style={{ background: COMPOUND_COLORS.SOFT }} />Soft</span>
                  <span><i style={{ background: COMPOUND_COLORS.MEDIUM }} />Medium</span>
                  <span><i style={{ background: COMPOUND_COLORS.HARD }} />Hard</span>
                  <span><i className="is-window" />Estimated pit window</span>
                  {bands.length > 0 && <span><i style={{ background: "rgba(255, 162, 58, 0.5)" }} />Safety car or VSC, already run</span>}
                </div>
              </div>
            </section>
          </>
        )}
      </main>
    </div>
  );
}
