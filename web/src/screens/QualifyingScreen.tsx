import { useEffect, useState, type ReactNode } from "react";
import { api, formatLapTime, type QualiDriver, type QualiKind, type QualiLaps, type StandingsMoment } from "../api";
import type { ScreenContext } from "./ScreenView";

const KINDS: [QualiKind, string][] = [["Q", "Qualifying"], ["SQ", "Sprint qualifying"]];

/**
 * Time left on the table in the last qualifying: each driver's best lap against
 * their own three best sectors added up (see model/quali_laps.py). Against their
 * own sectors, not the session's, so it measures the lap, not the car.
 */
export function QualifyingScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [kind, setKind] = useState<QualiKind>("Q");
  const [data, setData] = useState<QualiLaps | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    api
      .qualifying(ctx.session, moment, kind, controller.signal)
      .then((body) => (Array.isArray(body?.drivers) ? setData(body) : setError("Qualifying came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment, kind]);

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
        {!error && !data && <div className="panel-note">Adding up sectors…</div>}
        {data && (
          <>
            <div className="teammates-bar">
              <p className="standings-basis">
                <b>{data.event_name ? `${data.event_name}, ${kind === "Q" ? "qualifying" : "sprint qualifying"}` : `${data.year} season`}</b>
                {" · "}
                {data.sessions ? `${data.sessions} ${data.sessions === 1 ? "session" : "sessions"} this season` : "nothing run yet"}
                <br />
                How close did each driver get to their perfect lap? Their perfect lap is their own three best sectors
                added together. Time left is how much quicker their best lap could have been; <b className="is-quick">perfect</b> means
                they put it all together. Laps deleted for track limits do not count.
              </p>
              <div className="segmented" role="radiogroup" aria-label="Which qualifying">
                {KINDS.map(([key, text]) => (
                  <button key={key} type="button" role="radio" aria-checked={kind === key} className={kind === key ? "is-on" : ""}
                          onClick={() => setKind(key)}>{text}</button>
                ))}
              </div>
            </div>
            <section className="panel standings-panel" aria-label="Qualifying laps">
              <QualiTable drivers={data.drivers} />
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

function QualiTable({ drivers }: { drivers: QualiDriver[] }) {
  if (drivers.length === 0) return <p className="panel-note">No qualifying laps to add up yet.</p>;
  return (
    <div className="standings-table is-quali" role="table" aria-label="Time left on the table">
      <div className="standings-row is-head" role="row">
        <span role="columnheader" className="num">Pos</span>
        <span role="columnheader" />
        <span role="columnheader">Driver</span>
        <span role="columnheader" className="num" title="Best lap of the whole session, any part">Best lap</span>
        <span role="columnheader" className="num" title="The driver's own three best sectors added together">Perfect lap</span>
        <span role="columnheader" className="num" title="Best lap minus perfect lap">Time left</span>
        <span role="columnheader" className="mid" title="Where the time went: the best lap's sectors against the driver's best">Lost in S1 · S2 · S3</span>
        <span role="columnheader" className="num" title="Average time left over this season's sessions">Season average</span>
      </div>
      {drivers.map((d) => (
        <div key={d.abbreviation} role="row" className="standings-row">
          <span role="cell" className="num pos">{d.position ?? ""}</span>
          <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
          <span role="cell" className="who"><b className="code">{d.abbreviation}</b><small>{d.team}</small></span>
          <span role="cell" className="num gap">{formatLapTime(d.best_s)}</span>
          <span role="cell" className="num gap">{formatLapTime(d.ideal_s)}</span>
          <span role="cell" className={`num points${d.left_s !== null && d.left_s < 0.0005 ? " is-quick" : ""}`}>{leftText(d.left_s)}</span>
          <span role="cell" className="mid split">
            {d.sectors_left
              ? d.sectors_left.map((v, i) => (
                  <span key={i}>{i > 0 && " · "}{v === Math.max(...d.sectors_left!) && v > 0 ? <b>{v.toFixed(3)}</b> : v.toFixed(3)}</span>
                ))
              : "—"}
          </span>
          <span role="cell" className="num gap">{leftText(d.season_left_s)}</span>
        </div>
      ))}
    </div>
  );
}

/** "+0.130" seconds left; "perfect" when the best lap is the perfect lap; a dash for no lap. */
export function leftText(value: number | null): string {
  if (value === null) return "—";
  return value < 0.0005 ? "perfect" : `+${value.toFixed(3)}`;
}
