import { useEffect, useState, type ReactNode } from "react";
import {
  api, type ConstructorStanding, type DriverStanding, type Standings, type StandingsFinish, type StandingsMoment,
  type TitleOdds,
} from "../api";
import { percent } from "../panels/PredictionBoard";
import { KpiRow } from "../shell/KpiRow";
import { useSeasonMoment } from "./moment";
import type { ScreenContext } from "./ScreenView";

/**
 * The drivers' and constructors' championships of the session's season.
 *
 * By default as they stood when the session started, so opening a race does
 * not give away who won it; "After it" counts the session too. Points are the
 * feed's own, penalties and all; a result the feed sent without points is
 * scored from its positions, and a note says which. Click a driver to follow
 * them, as on every other screen.
 *
 * Beside the points, each driver's and team's chance of the title: the rest of
 * the season simulated from these standings (see model/title.py). It loads
 * after the tables, since the first time for a season takes a few seconds.
 */
export function StandingsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useSeasonMoment(ctx);
  const [tab, setTab] = useState<"drivers" | "teams">("drivers");
  const [table, setTable] = useState<Standings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [odds, setOdds] = useState<TitleOdds | null>(null);
  const [oddsError, setOddsError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setOdds(null);
    setOddsError(null);
    api
      .title(ctx.session, moment, controller.signal)
      .then((body) => (Array.isArray(body?.drivers) ? setOdds(body) : setOddsError("The title odds came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setOddsError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment]);

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

  // The odds start from the table's notes and add their own, so each is said once.
  const notes = [...new Set([...(table?.notes ?? []), ...(odds?.notes ?? [])])];

  const switcher = (
    <>
      <div className="segmented" role="radiogroup" aria-label="Championship">
        {([["drivers", "Drivers"], ["teams", "Constructors"]] as const).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={tab === key} className={tab === key ? "is-on" : ""}
                  onClick={() => setTab(key)}>{text}</button>
        ))}
      </div>
      <div className="segmented" role="radiogroup" aria-label="Which results count">
        {([["before", "Going into this session"], ["after", "After it"]] as [StandingsMoment, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={moment === key} className={moment === key ? "is-on" : ""}
                  onClick={() => setMoment(key)}>{text}</button>
        ))}
      </div>
    </>
  );

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body standings-body">
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
            <p className="standings-basis" role="status">{oddsLine(odds, oddsError)}</p>
            <KpiRow tiles={standingsTiles(table, odds)} />
            {table.drivers.length > 0 && (
              <div className="standings">
                {tab === "drivers"
                  ? <DriversTable drivers={table.drivers} selected={ctx.selected} onSelect={ctx.onSelect} odds={odds} />
                  : <ConstructorsTable teams={table.constructors} odds={odds} />}
                <PointsChart rounds={table.rounds ?? []} drivers={table.drivers} selected={ctx.selected} />
              </div>
            )}
            {notes.length > 0 && (
              <ul className="prediction-notes">{notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function DriversTable({ drivers, selected, onSelect, odds }: {
  drivers: DriverStanding[];
  selected: number[];
  onSelect: (driver: number) => void;
  odds: TitleOdds | null;
}) {
  const chance = new Map(odds?.drivers.map((d) => [d.abbreviation, d]) ?? []);
  const contenders = odds?.drivers.filter((d) => d.alive).length ?? 0;
  return (
    <section className="panel standings-main" aria-label="Drivers' championship">
      <div className="panel-bar"><h2>Drivers</h2><span className="panel-meta">form: last five results, newest on the right</span></div>
      <div className="standings-table is-drivers standings-scroll" role="table" aria-label="Drivers' standings">
        <div className="standings-row is-head" role="row">
          <span role="columnheader" className="num">Pos</span>
          <span role="columnheader" />
          <span role="columnheader" />
          <span role="columnheader">Driver</span>
          <span role="columnheader" className="num">Pts</span>
          <span role="columnheader" className="num" title="Points behind the leader">Gap</span>
          <span role="columnheader" className="num" title="Grand Prix wins">Wins</span>
          <span role="columnheader" className="num" title="Grand Prix podiums">Pod.</span>
          <span role="columnheader" className="num" title="Chance of the championship, the rest of the season simulated">Title</span>
          <span role="columnheader" className="num" title={SECOND_OPINION}>Results only</span>
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
              <TitleCell odds={odds} entry={chance.get(d.abbreviation)} clinched={contenders === 1} />
              <SecondOpinionCell odds={odds} code={d.abbreviation} clinched={contenders === 1} />
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

function ConstructorsTable({ teams, odds }: { teams: ConstructorStanding[]; odds: TitleOdds | null }) {
  const chance = new Map(odds?.constructors.map((t) => [t.team, t]) ?? []);
  const contenders = odds?.constructors.filter((t) => t.alive).length ?? 0;
  return (
    <section className="panel standings-main" aria-label="Constructors' championship">
      <div className="panel-bar"><h2>Constructors</h2><span className="panel-meta">bar: how its drivers split the points</span></div>
      <div className="standings-table is-teams standings-scroll" role="table" aria-label="Constructors' standings">
        <div className="standings-row is-head" role="row">
          <span role="columnheader" className="num">Pos</span>
          <span role="columnheader" />
          <span role="columnheader">Team</span>
          <span role="columnheader" className="num">Pts</span>
          <span role="columnheader" className="num" title="Points behind the leader">Gap</span>
          <span role="columnheader" className="num" title="Grand Prix wins">Wins</span>
          <span role="columnheader" className="num" title="Chance of the championship, the rest of the season simulated">Title</span>
          <span role="columnheader" title="Who scored them">Drivers</span>
        </div>
        {teams.map((t) => (
          <div key={t.team} className="standings-row" role="row">
            <span role="cell" className="num pos">{t.position}</span>
            <span role="cell" className="team-bar" style={{ background: `#${t.team_color ?? "555"}` }} />
            <span role="cell" className="who"><b>{t.team}</b></span>
            <span role="cell" className="num points">{t.points}</span>
            <span role="cell" className="num gap">{t.gap ? `−${t.gap}` : "—"}</span>
            <span role="cell" className="num">{t.wins || "—"}</span>
            <TitleCell odds={odds} entry={chance.get(t.team)} clinched={contenders === 1} />
            <span role="cell" className="split" title={t.drivers.map((d) => `${d.abbreviation} ${d.points}`).join(" · ")}>
              <span className="split-bar" aria-hidden="true">
                {t.drivers.map((d, k) => (
                  <i key={d.abbreviation} style={{ flexGrow: d.points, background: `#${t.team_color ?? "555"}`, opacity: k ? 0.45 : 1 }} />
                ))}
              </span>
              <span className="split-text">{t.drivers.map((d) => `${d.abbreviation} ${d.points}`).join(" · ")}</span>
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

/**
 * The lines on the points chart: the top six and anyone followed, as running
 * totals. Team-mates share a colour, so the lower-placed one is dashed: the end
 * labels and the dash keep them apart without relying on colour.
 */
export function pointsLines(drivers: DriverStanding[], selected: number[]) {
  const seen = new Set<string>();
  const lines = drivers.filter((d, i) => i < 6 || selected.includes(d.driver_number)).map((d) => {
    const color = d.team_color ?? "777777";
    const dashed = seen.has(color);
    seen.add(color);
    let sum = 0;
    return { code: d.abbreviation, number: d.driver_number, color, dashed, totals: (d.points_by_round ?? []).map((p) => (sum += p)) };
  });
  const most = Math.max(1, ...lines.map((l) => l.totals.at(-1) ?? 0));
  return { lines, top: Math.ceil(most / 50) * 50 };
}

function PointsChart({ rounds, drivers, selected }: {
  rounds: { round: number; event_name: string }[];
  drivers: DriverStanding[];
  selected: number[];
}) {
  const { lines, top } = pointsLines(drivers, selected);
  const x = (k: number) => (k / Math.max(rounds.length - 1, 1)) * 100;
  const y = (v: number) => 100 - (v / top) * 100;
  // End labels, nudged apart so a tight fight stays readable.
  let last = -Infinity;
  const labels = [...lines].sort((a, b) => (b.totals.at(-1) ?? 0) - (a.totals.at(-1) ?? 0)).map((l) => {
    last = Math.max(y(l.totals.at(-1) ?? 0), last + 3.6);
    return { ...l, top: last };
  });
  return (
    <section className="panel standings-main" aria-label="Points by round">
      <div className="panel-bar"><h2>Points by round</h2><span className="panel-meta">running total, sprints included · top six and anyone followed · hover a round</span></div>
      {rounds.length < 2 ? <p className="empty">The chart starts after the second round.</p> : (
        <div className="points-wrap">
          <div className="points-plot">
            {[0, 0.25, 0.5, 0.75, 1].map((f) => (
              <span key={f} className="tyres-gl" style={{ top: `${y(f * top)}%` }}><i className="num">{Math.round(f * top)}</i></span>
            ))}
            {rounds.map((r, k) => (
              <span key={r.round} className="tyres-gv" style={{ left: `${x(k)}%` }}><i className="num">{r.round}</i></span>
            ))}
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label="Running points total by round for the leading drivers">
              {lines.map((l) => (
                <path key={l.code} d={l.totals.map((v, k) => `${k ? "L" : "M"}${x(k).toFixed(2)} ${y(v).toFixed(2)}`).join("")} fill="none" stroke={`#${l.color}`}
                      strokeWidth={selected.includes(l.number) ? 2.6 : 1.8} strokeDasharray={l.dashed ? "5 4" : undefined} vectorEffect="non-scaling-stroke" />
              ))}
            </svg>
            {labels.map((l) => (
              <span key={l.code} className="points-end num" style={{ top: `${l.top}%`, color: `#${l.color}` }}>{l.code} {l.totals.at(-1)}</span>
            ))}
            {rounds.map((r, k) => (
              <span key={r.round} className="points-hit" style={{ left: `${x(k)}%`, width: `${100 / rounds.length}%` }}
                    title={`Round ${r.round}, ${r.event_name}\n${labels.map((l) => `${l.code} ${l.totals[k] ?? 0}`).join("\n")}`} />
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

const SECOND_OPINION = "A second opinion: the same simulation with form read from finishing places alone, "
  + "not lap times. Tested on every season since 1950; on 2023-2025 it did as well as the Title column.";

/** The results-only chance beside the main one (D-018); blank when it could not be worked out. */
function SecondOpinionCell({ odds, code, clinched }: { odds: TitleOdds | null; code: string; clinched: boolean }) {
  if (!odds) return <span role="cell" className="num title-odds is-waiting">…</span>;
  const value = odds.second_opinion?.[code];
  if (value == null) return <span role="cell" className="num title-odds is-second">—</span>;
  return <span role="cell" className="num title-odds is-second">{titleChance(value, clinched)}</span>;
}

/** A title chance; "out" once a driver or team can no longer reach the leader. */
function TitleCell({ odds, entry, clinched }: {
  odds: TitleOdds | null;
  entry: { title: number; alive: boolean; max_points: number; expected_points: number } | undefined;
  clinched: boolean;
}) {
  if (!odds) return <span role="cell" className="num title-odds is-waiting">…</span>;
  if (!entry) return <span role="cell" className="num title-odds">—</span>;
  if (!entry.alive) {
    return <span role="cell" className="num title-odds is-out" title={`At most ${entry.max_points} points: cannot catch the leader`}>out</span>;
  }
  return (
    <span role="cell" className={`num title-odds${entry.title >= 0.5 ? " is-favourite" : ""}`}
          title={`Expected to finish on about ${Math.round(entry.expected_points)} points; at most ${entry.max_points}`}>
      {titleChance(entry.title, clinched)}
    </span>
  );
}

/**
 * A title chance as a whole percent. "100%" only once it is settled (nobody
 * else can still reach the leader): until then a near-certainty is ">99%",
 * because the arithmetic still leaves a way.
 */
export function titleChance(value: number, clinched: boolean): string {
  if (value >= 0.995) return clinched ? "100%" : ">99%";
  return percent(value);
}

/** The line that says what the title odds are and what they rest on. */
export function oddsLine(odds: TitleOdds | null, error: string | null): string {
  if (error) return `Title odds unavailable: ${error}`;
  if (!odds) return "Title odds: simulating the rest of the season…";
  if (odds.remaining.length === 0) return "Title odds: the season is over.";
  const races = odds.remaining.filter((e) => e.session !== "sprint").length;
  const sprints = odds.remaining.length - races;
  const left = [races ? `${races} ${races === 1 ? "Grand Prix" : "Grands Prix"}` : "", sprints ? `${sprints} ${sprints === 1 ? "sprint" : "sprints"}` : ""]
    .filter(Boolean).join(" and ");
  const most = races * 25 + sprints * 8;
  return `Title odds: the ${left} still to run simulated ${odds.runs.toLocaleString()} times from these standings, `
    + `up to ${most} points still on offer to each driver.`;
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

/**
 * The championships' headline figures: each leader and their margin, the
 * most wins, and the points a driver can still score (25 a Grand Prix and 8 a
 * sprint still to run, as the odds line counts them).
 */
export function standingsTiles(table: Standings, odds: TitleOdds | null) {
  const [d1, d2] = table.drivers;
  const [c1, c2] = table.constructors;
  const wins = Math.max(0, ...table.drivers.map((d) => d.wins));
  const winners = table.drivers.filter((d) => d.wins === wins).map((d) => d.abbreviation);
  const races = odds ? odds.remaining.filter((e) => e.session !== "sprint").length : null;
  const sprints = odds && races !== null ? odds.remaining.length - races : null;
  return [
    d1 && { label: "Drivers' leader", value: `${d1.abbreviation} · ${d1.points}`, note: d2 ? `${d1.points - d2.points} ahead of ${d2.abbreviation}` : "" },
    c1 && { label: "Constructors' leader", value: `${c1.team} · ${c1.points}`, note: c2 ? `${c1.points - c2.points} ahead of ${c2.team}` : "" },
    wins > 0 && { label: "Most wins", value: `${winners.join(", ")} · ${wins}`, note: "Grands Prix" },
    races !== null && sprints !== null && { label: "Points still to win", value: String(races * 25 + sprints * 8),
      note: `${races} ${races === 1 ? "Grand Prix" : "Grands Prix"}, ${sprints} ${sprints === 1 ? "sprint" : "sprints"} to run` },
  ];
}
