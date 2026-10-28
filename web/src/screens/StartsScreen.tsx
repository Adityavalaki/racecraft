import { useEffect, useState, type ReactNode } from "react";
import { api, type DriverStarts, type StandingsMoment, type StartKind, type StartRecord, type Starts } from "../api";
import type { ScreenContext } from "./ScreenView";

const KINDS: [StartKind, string][] = [["races", "Races"], ["sprints", "Sprints"], ["both", "Both"]];

/**
 * Places each driver gained or lost on lap 1 this season.
 *
 * Raw places gained mostly says where a driver qualified (from pole you can
 * only lose), so the table is ranked by "vs normal": each start against the
 * average for that grid slot over every start in the lake (see model/starts.py).
 * Cars out on lap 1 are counted apart; pit-lane starts are left out.
 */
export function StartsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [kind, setKind] = useState<StartKind>("races");
  const [data, setData] = useState<Starts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setData(null);
    setError(null);
    api
      .starts(ctx.session, moment, controller.signal)
      .then((body) => (body?.drivers && Array.isArray(body.drivers.races) ? setData(body) : setError("The starts came back in a shape this screen cannot read.")))
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

  const drivers = data?.drivers[kind] ?? [];
  const sessions = data?.sessions[kind] ?? 0;
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Counting starts…</div>}
        {data && (
          <>
            <div className="teammates-bar">
              <p className="standings-basis">
                <b>{data.year} season</b>
                {" · "}
                {sessions ? `${sessions} ${sessions === 1 ? "start" : "starts"} so far` : "nothing run yet"}
                <br />
                Who makes the best starts? <b className="is-quick">Green</b> means the driver usually gains more places
                on the first lap than others starting from the same spot; <b className="is-slow">red</b> means they lose more.
              </p>
              <div className="segmented" role="radiogroup" aria-label="Which starts">
                {KINDS.map(([key, text]) => (
                  <button key={key} type="button" role="radio" aria-checked={kind === key} className={kind === key ? "is-on" : ""}
                          onClick={() => setKind(key)}>{text}</button>
                ))}
              </div>
            </div>
            <section className="panel standings-panel" aria-label="Starts">
              <StartsTable drivers={drivers} />
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

function StartsTable({ drivers }: { drivers: DriverStarts[] }) {
  if (drivers.length === 0) return <p className="panel-note">No starts to count yet.</p>;
  return (
    <div className="standings-table is-starts" role="table" aria-label="Places gained on lap 1">
      <div className="standings-row is-head" role="row">
        <span role="columnheader" className="num">Pos</span>
        <span role="columnheader" />
        <span role="columnheader">Driver</span>
        <span role="columnheader" className="num" title="Places gained on lap 1, on average, compared with other drivers starting from the same spots">Start rating</span>
        <span role="columnheader" className="num" title="Places gained on lap 1, on average">Avg gained</span>
        <span role="columnheader" className="mid" title="How many starts the driver gained, kept or lost places">Gained · kept · lost</span>
        <span role="columnheader">Best start</span>
        <span role="columnheader">Worst start</span>
        <span role="columnheader" className="num" title="Out of the race on lap 1: not counted as places lost">Crashed lap 1</span>
        <span role="columnheader" className="num">Starts</span>
      </div>
      {drivers.map((d, i) => (
        <div key={d.abbreviation} role="row" className="standings-row">
          <span role="cell" className="num pos">{d.vs_normal === null ? "" : i + 1}</span>
          <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
          <span role="cell" className="who"><b className="code">{d.abbreviation}</b><small>{d.team}</small></span>
          <span role="cell" className={`num points${tone(d.vs_normal)}`}>{places(d.vs_normal)}</span>
          <span role="cell" className="num gap">{places(d.gained)}</span>
          <span role="cell" className="mid split">{d.up} · {d.same} · {d.down}</span>
          <span role="cell" className="split">{startText(d.best)}</span>
          <span role="cell" className="split">{startText(d.worst)}</span>
          <span role="cell" className="num gap">{d.out_lap1 || ""}</span>
          <span role="cell" className="num gap">{d.starts}</span>
        </div>
      ))}
    </div>
  );
}

/** "+1.29" or "−0.40", places a start; a dash when there is nothing to average. */
export function places(value: number | null): string {
  if (value === null) return "—";
  if (Math.abs(value) < 0.005) return "0.00";
  return `${value > 0 ? "+" : "−"}${Math.abs(value).toFixed(2)}`;
}

/** "P14 → P7, Chinese" (a sprint keeps its "sprint") */
export function startText(start: StartRecord | null): string {
  return start ? `P${start.grid} → P${start.lap1}, ${start.event_name.replace(" Grand Prix", "")}` : "—";
}

function tone(value: number | null): string {
  return value === null || Math.abs(value) < 0.005 ? "" : value > 0 ? " is-quick" : " is-slow";
}
