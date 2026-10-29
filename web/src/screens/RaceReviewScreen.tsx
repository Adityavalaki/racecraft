import { useEffect, useState, type ReactNode } from "react";
import { api, type RaceReview, type ReviewDriver, type ReviewStop, type StandingsMoment } from "../api";
import type { ScreenContext } from "./ScreenView";

const SHORT: Record<ReviewStop["kind"], string> = { green: "", "safety car": "SC", VSC: "VSC", "red flag": "red", penalty: "pen" };

/**
 * The last Grand Prix, driver by driver: overtakes made and lost on track, and
 * what each pit stop cost in places (see model/race_review.py). Consistency and
 * "pitted on the wrong lap" were tried and left out as not reliable (D-023).
 */
export function RaceReviewScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [data, setData] = useState<RaceReview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    api
      .raceReview(ctx.session, moment, controller.signal)
      .then((body) => (Array.isArray(body?.drivers) ? setData(body) : setError("The race review came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment]);

  const switcher = (
    <div className="segmented" role="radiogroup" aria-label="Which race">
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
        {!error && !data && <div className="panel-note">Reviewing the race…</div>}
        {data && (
          <>
            <p className="standings-basis">
              <b>{data.event_name ?? `${data.year} season`}</b>
              {data.green_stop_places !== null && ` · a normal pit stop here cost about ${Math.round(data.green_stop_places)} places`}
              <br />
              <b>Passed</b> and <b>passed by</b> count overtakes on track: green flag, neither car in the pits (lap 1 is on
              the Starts screen). Each pit stop shows its lap and how many cars that stayed out got past. A stop under
              a safety car (SC), VSC or red flag usually costs far fewer places: that is the luck.
            </p>
            <section className="panel standings-panel" aria-label="Race review">
              <ReviewTable drivers={data.drivers} />
            </section>
            {data.notes.length > 0 && (
              <ul className="prediction-notes">{data.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function ReviewTable({ drivers }: { drivers: ReviewDriver[] }) {
  if (drivers.length === 0) return <p className="panel-note">No Grand Prix to review yet.</p>;
  return (
    <div className="standings-table is-review" role="table" aria-label="Overtakes and pit stops">
      <div className="standings-row is-head" role="row">
        <span role="columnheader" className="num">Pos</span>
        <span role="columnheader" />
        <span role="columnheader">Driver</span>
        <span role="columnheader" className="num" title="Cars this driver overtook on track">Passed</span>
        <span role="columnheader" className="num" title="Times this driver was overtaken on track">Passed by</span>
        <span role="columnheader" className="num" title="All the places lost at pit stops">Lost in the pits</span>
        <span role="columnheader" className="stops" title="Lap of each stop, and places lost to cars that stayed out">Pit stops</span>
      </div>
      {drivers.map((d) => (
        <div key={d.abbreviation} role="row" className="standings-row">
          <span role="cell" className="num pos">{d.position ?? (d.status === "R" ? "DNF" : d.status)}</span>
          <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
          <span role="cell" className="who"><b className="code">{d.abbreviation}</b><small>{d.team}</small></span>
          <span role="cell" className={`num points${d.passes_made ? " is-quick" : ""}`}>{d.passes_made}</span>
          <span role="cell" className={`num points${d.passes_lost ? " is-slow" : ""}`}>{d.passes_lost}</span>
          <span role="cell" className="num gap">{d.stops.length ? d.pit_places : "—"}</span>
          <span role="cell" className="split stops">
            {d.stops.length
              ? d.stops.map((s, i) => (
                  <span key={s.lap}>{i > 0 && " · "}<span className={s.kind === "green" ? "" : "is-quick"}>{stopText(s)}</span></span>
                ))
              : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

/** "L24 −2", "L50 VSC −2", "L31 SC ±0": the lap, what the track was doing if not green, and the places lost. */
export function stopText(stop: ReviewStop): string {
  const kind = SHORT[stop.kind];
  return `L${stop.lap}${kind ? ` ${kind}` : ""} ${stop.places ? `−${stop.places}` : "±0"}`;
}
