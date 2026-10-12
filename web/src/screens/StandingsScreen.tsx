import { useEffect, useState, type ReactNode } from "react";
import {
  api, type ConstructorStanding, type DriverStanding, type Standings, type StandingsFinish, type StandingsMoment,
} from "../api";
import type { ScreenContext } from "./ScreenView";

/**
 * The drivers' and constructors' championships of the session's season.
 *
 * By default as they stood when the session started, so opening a race does
 * not give away who won it; "After it" counts the session too. Points are the
 * feed's own, penalties and all; a result the feed sent without points is
 * scored from its positions, and a note says which. Click a driver to follow
 * them, as on every other screen.
 */
export function StandingsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [table, setTable] = useState<Standings | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setTable(null);
    setError(null);
    api
      .standings(ctx.session, moment, controller.signal)
      .then((body) => (isStandings(body) ? setTable(body) : setError("The standings came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment]);

  const switcher = (
    <div className="segmented" role="radiogroup" aria-label="Which results count">
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
        {!error && !table && <div className="panel-note">Adding up the season's points…</div>}
        {table && (
          <>
            <p className="standings-basis">
              <b>{table.year} season</b>
              {" · "}
              {table.last
                ? `after ${table.races} ${table.races === 1 ? "Grand Prix" : "Grands Prix"} and ${table.sprints} ${table.sprints === 1 ? "sprint" : "sprints"}, the latest the ${table.last.event_name}${table.last.session === "sprint" ? " sprint" : ""}`
                : "nothing run yet"}
            </p>
            {table.drivers.length > 0 && (
              <div className="standings">
                <DriversTable drivers={table.drivers} selected={ctx.selected} onSelect={ctx.onSelect} />
                <ConstructorsTable teams={table.constructors} />
              </div>
            )}
            {table.notes.length > 0 && (
              <ul className="prediction-notes">{table.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function DriversTable({ drivers, selected, onSelect }: {
  drivers: DriverStanding[];
  selected: number[];
  onSelect: (driver: number) => void;
}) {
  return (
    <section className="panel standings-panel" aria-label="Drivers' championship">
      <h2 className="card-label">Drivers' championship</h2>
      <div className="standings-table is-drivers" role="table" aria-label="Drivers' standings">
        <div className="standings-row is-head" role="row">
          <span role="columnheader" className="num">Pos</span>
          <span role="columnheader" />
          <span role="columnheader" />
          <span role="columnheader">Driver</span>
          <span role="columnheader" className="num">Pts</span>
          <span role="columnheader" className="num" title="Points behind the leader">Gap</span>
          <span role="columnheader" className="num" title="Grand Prix wins">Wins</span>
          <span role="columnheader" className="num" title="Grand Prix podiums">Pod.</span>
          <span role="columnheader" title="The latest Grand Prix finishes, oldest first">Form</span>
        </div>
        {drivers.map((d) => {
          const on = selected.includes(d.driver_number);
          return (
            <button key={d.abbreviation} type="button" role="row" aria-pressed={on}
                    className={`standings-row${on ? " is-selected" : ""}`} onClick={() => onSelect(d.driver_number)}
                    title={`${d.full_name ?? d.abbreviation}${d.sprint_wins ? `, ${d.sprint_wins} sprint ${d.sprint_wins === 1 ? "win" : "wins"}` : ""}`}>
              <span role="cell" className="num pos">{d.position}</span>
              <Change value={d.change} />
              <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
              <span role="cell" className="who">
                <b className="code">{d.abbreviation}</b>
                <small>{d.team_name ?? ""}</small>
              </span>
              <span role="cell" className="num points">{d.points}</span>
              <span role="cell" className="num gap">{d.gap ? `−${d.gap}` : "—"}</span>
              <span role="cell" className="num">{d.wins || "—"}</span>
              <span role="cell" className="num">{d.podiums || "—"}</span>
              <span role="cell" className="form" aria-label={formLabel(d.form)}>
                {d.form.map((f) => <Finish key={f.round} finish={f} />)}
              </span>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ConstructorsTable({ teams }: { teams: ConstructorStanding[] }) {
  const top = teams[0]?.points || 1;
  return (
    <section className="panel standings-panel" aria-label="Constructors' championship">
      <h2 className="card-label">Constructors' championship</h2>
      <div className="standings-table is-teams" role="table" aria-label="Constructors' standings">
        <div className="standings-row is-head" role="row">
          <span role="columnheader" className="num">Pos</span>
          <span role="columnheader" />
          <span role="columnheader">Team</span>
          <span role="columnheader" className="num">Pts</span>
          <span role="columnheader" className="num" title="Points behind the leader">Gap</span>
          <span role="columnheader" className="num" title="Grand Prix wins">Wins</span>
          <span role="columnheader" title="Who scored them">Drivers</span>
        </div>
        {teams.map((t) => (
          <div key={t.team} className="standings-row" role="row">
            <span role="cell" className="num pos">{t.position}</span>
            <span role="cell" className="team-bar" style={{ background: `#${t.team_color ?? "555"}` }} />
            <span role="cell" className="who">
              <b>{t.team}</b>
              <span className="share" aria-hidden="true">
                <i style={{ width: `${(t.points / top) * 100}%`, background: `#${t.team_color ?? "555"}` }} />
              </span>
            </span>
            <span role="cell" className="num points">{t.points}</span>
            <span role="cell" className="num gap">{t.gap ? `−${t.gap}` : "—"}</span>
            <span role="cell" className="num">{t.wins || "—"}</span>
            <span role="cell" className="split" title={t.drivers.map((d) => `${d.abbreviation} ${d.points}`).join(" · ")}>
              {t.drivers.map((d) => `${d.abbreviation} ${d.points}`).join(" · ")}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Change({ value }: { value: number | null }) {
  if (value === null || value === 0) return <span role="cell" className="change" aria-label="no change" />;
  const up = value > 0;
  return (
    <span role="cell" className={`change ${up ? "is-up" : "is-down"}`}
          aria-label={`${up ? "up" : "down"} ${Math.abs(value)} since the last weekend`}>
      {up ? "▲" : "▼"}{Math.abs(value)}
    </span>
  );
}

function Finish({ finish }: { finish: StandingsFinish }) {
  const place = finish.position;
  const tone = place === 1 ? " is-win" : place !== null && place <= 3 ? " is-podium"
    : place !== null && place <= 10 ? " is-points" : "";
  return (
    <i className={`finish${tone}`} title={`${finish.event_name}: ${place !== null ? `P${place}` : outcome(finish.status)}`}>
      {place ?? (finish.status || "–")}
    </i>
  );
}

/** The feed's codes for a finish without a place. */
function outcome(status: string | null): string {
  if (status === "R") return "retired";
  if (status === "D") return "disqualified";
  if (status === "W") return "withdrawn";
  if (status === "N") return "not classified";
  if (status === "E") return "excluded";
  if (status === "F") return "failed to qualify";
  return "no finish";
}

function formLabel(form: StandingsFinish[]): string {
  return `Latest finishes: ${form.map((f) => (f.position !== null ? `P${f.position}` : outcome(f.status))).join(", ")}`;
}

function isStandings(body: unknown): body is Standings {
  const value = body as Standings | null;
  return !!value && Array.isArray(value.drivers) && Array.isArray(value.constructors);
}
