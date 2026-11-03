import { useEffect, useState, type ReactNode } from "react";
import { api, type DriverStarts, type StandingsMoment, type StartKind, type StartRace, type StartRecord, type Starts } from "../api";
import { KpiRow } from "../shell/KpiRow";
import type { ScreenContext } from "./ScreenView";

const KINDS: [StartKind, string][] = [["races", "Races"], ["sprints", "Sprints"], ["both", "Both"]];
const CODES: Record<StartKind, string[]> = { races: ["R"], sprints: ["S"], both: ["R", "S"] };

/**
 * Places each driver gained or lost on lap 1, as racecraft-ui.html draws it
 * (D-025): one start, grid to the end of lap 1, beside the season.
 *
 * Raw places gained mostly says where a driver qualified (from pole you can
 * only lose), so the season is ranked by "vs normal": each start against the
 * average for that grid slot over every start in the lake (see model/starts.py).
 * Cars out on lap 1 are counted apart; pit-lane starts are left out.
 */
export function StartsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [kind, setKind] = useState<StartKind>("races");
  const [picked, setPicked] = useState<string | null>(null);
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

  const drivers = data?.drivers[kind] ?? [];
  const sessions = data?.sessions[kind] ?? 0;
  const races = (data?.races ?? []).filter((r) => CODES[kind].includes(r.code));
  const race = races.find((r) => r.session_key === picked) ?? races[races.length - 1] ?? null;

  const switcher = (
    <>
      {races.length > 0 && (
        <label className="pick">
          <span className="cap">Race</span>
          <select value={race?.session_key ?? ""} onChange={(e) => setPicked(e.target.value)} aria-label="Race">
            {[...races].reverse().map((r) => <option key={r.session_key} value={r.session_key}>{shortName(r.event_name)}</option>)}
          </select>
        </label>
      )}
      <div className="segmented" role="radiogroup" aria-label="Which starts">
        {KINDS.map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={kind === key} className={kind === key ? "is-on" : ""}
                  onClick={() => setKind(key)}>{text}</button>
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

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body starts-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Counting starts…</div>}
        {data && (
          <>
            <KpiRow tiles={startsTiles(drivers, race)} />
            <div className="starts-grid">
              <SlopeChart race={race} />
              <section className="panel starts-season" aria-label="Lap 1 across the season">
                <div className="panel-bar"><h2>Lap 1 across the season</h2>
                  <span className="panel-meta">{data.year}, {sessions} {sessions === 1 ? "start" : "starts"} · bar and rating: places against what that grid slot usually gains</span></div>
                <StartsTable drivers={drivers} />
              </section>
            </div>
            {data.notes.length > 0 && (
              <ul className="prediction-notes starts-notes">{data.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

const shortName = (event: string) => event.replace(" Grand Prix", "");
const gainText = (gain: number) => (gain > 0 ? `+${gain}` : gain < 0 ? `−${-gain}` : "=");
const gainTone = (gain: number) => (gain > 0 ? " is-up" : gain < 0 ? " is-down" : "");

/** Grid slot on the left, place after lap 1 on the right, a line between; a car out on lap 1 has no line or right label. */
function SlopeChart({ race }: { race: StartRace | null }) {
  if (!race) {
    return (
      <section className="panel starts-slope" aria-label="Grid to the end of lap 1">
        <div className="panel-bar"><h2>Grid to end of lap 1</h2></div>
        <p className="panel-note">No starts to show yet.</p>
      </section>
    );
  }
  const rows = Math.max(...race.cars.flatMap((c) => [c.grid, c.lap1 ?? 0]), 1);
  const y = (place: number) => ((place - 0.5) / rows) * 100;
  const out = race.cars.filter((c) => c.lap1 === null);
  return (
    <section className="panel starts-slope" aria-label="Grid to the end of lap 1">
      <div className="panel-bar"><h2>Grid to end of lap 1</h2>
        <span className="panel-meta">{shortName(race.event_name)} · green gained places, red lost them{out.length ? ` · out on lap 1: ${out.map((c) => c.abbreviation).join(", ")}` : ""}</span></div>
      <div className="slope-heads cap"><span>Grid</span><span>End of lap 1</span></div>
      <div className="slope">
        <span className="slope-axis" style={{ left: 0 }} />
        <span className="slope-axis" style={{ right: 0 }} />
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
          {race.cars.filter((c) => c.lap1 !== null).map((c) => {
            const gain = c.grid - c.lap1!;
            return (
              <line key={c.abbreviation} x1="0" x2="100" y1={y(c.grid)} y2={y(c.lap1!)} vectorEffect="non-scaling-stroke"
                    className={`slope-line${gainTone(gain)}`} strokeWidth={Math.abs(gain) >= 2 ? 2.4 : 1.4} />
            );
          })}
        </svg>
        {race.cars.map((c) => (
          <span key={c.abbreviation} className="slope-label is-left num" style={{ top: `${y(c.grid)}%` }}>
            <i>P{c.grid}</i>{c.abbreviation}<b style={{ background: `#${c.team_color ?? "555"}` }} />
          </span>
        ))}
        {race.cars.filter((c) => c.lap1 !== null).map((c) => (
          <span key={c.abbreviation} className="slope-label is-right num" style={{ top: `${y(c.lap1!)}%` }}>
            <i>P{c.lap1}</i>{c.abbreviation}<em className={gainTone(c.grid - c.lap1!)}>{gainText(c.grid - c.lap1!)}</em>
          </span>
        ))}
      </div>
    </section>
  );
}

function StartsTable({ drivers }: { drivers: DriverStarts[] }) {
  if (drivers.length === 0) return <p className="panel-note">No starts to count yet.</p>;
  const reach = Math.max(0.01, ...drivers.map((d) => Math.abs(d.vs_normal ?? 0)));
  return (
    <div className="starts-table" role="table" aria-label="Places gained on lap 1">
      <div className="starts-row is-head cap" role="row">
        <span role="columnheader" className="right">#</span>
        <span role="columnheader" />
        <span role="columnheader">Drv</span>
        <span role="columnheader" />
        <span role="columnheader" className="mid">Worse · better</span>
        <span role="columnheader" className="right" title="Places gained on lap 1, on average, compared with other drivers starting from the same spots">Rating</span>
        <span role="columnheader" className="right" title="Places gained on lap 1, on average">Avg</span>
        <span role="columnheader" className="right" title="The most places gained in one start">Best</span>
      </div>
      {drivers.map((d, i) => {
        const w = ((Math.abs(d.vs_normal ?? 0)) / reach) * 50;
        return (
          <div key={d.abbreviation} role="row" className="starts-row"
               title={`${d.starts} starts: gained ${d.up}, kept ${d.same}, lost ${d.down}${d.out_lap1 ? `; out on lap 1 ${d.out_lap1}` : ""}\nBest ${startText(d.best)}\nWorst ${startText(d.worst)}`}>
            <span role="cell" className="num right strong">{d.vs_normal === null ? "" : i + 1}</span>
            <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
            <span role="cell" className="num strong">{d.abbreviation}</span>
            <span role="cell" className="panel-meta starts-team">{d.team}</span>
            <span role="cell" className="starts-div" aria-hidden="true">
              {d.vs_normal !== null && <i className={tone(d.vs_normal)} style={{ left: `${d.vs_normal >= 0 ? 50 : 50 - w}%`, width: `${w}%` }} />}
            </span>
            <span role="cell" className={`num right strong${tone(d.vs_normal)}`}>{places(d.vs_normal)}</span>
            <span role="cell" className="num right starts-dim">{places(d.gained)}</span>
            <span role="cell" className="num right starts-dim">{d.best ? gainText(d.best.gain) : "—"}</span>
          </div>
        );
      })}
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
  return start ? `P${start.grid} → P${start.lap1}, ${shortName(start.event_name)}` : "—";
}

function tone(value: number | null): string {
  return value === null || Math.abs(value) < 0.005 ? "" : value > 0 ? " is-quick" : " is-slow";
}

/**
 * The headline figures: the chosen start's best and worst lap 1 and how many
 * cars changed place, and the season's best starter against the slot's normal.
 */
export function startsTiles(drivers: DriverStarts[], race: StartRace | null) {
  const ran = (race?.cars ?? []).filter((c) => c.lap1 !== null).map((c) => ({ ...c, gain: c.grid - c.lap1! }));
  const best = [...ran].sort((a, b) => b.gain - a.gain)[0];
  const worst = [...ran].sort((a, b) => a.gain - b.gain)[0];
  const name = race ? shortName(race.event_name) : "";
  const out = (race?.cars.length ?? 0) - ran.length;
  const season = drivers.find((d) => d.vs_normal !== null);
  // Several cars often share the figure: the tile names one and says so.
  const tied = (gain: number) => { const others = ran.filter((r) => r.gain === gain).length - 1; return others ? `, level with ${others} more` : ""; };
  return [
    best && { label: `Best launch at ${name}`, value: `${best.abbreviation} ${gainText(best.gain)}`, note: `P${best.grid} to P${best.lap1}${tied(best.gain)}`, tone: best.gain > 0 ? "good" as const : undefined },
    worst && { label: `Worst lap 1 at ${name}`, value: `${worst.abbreviation} ${gainText(worst.gain)}`, note: `P${worst.grid} to P${worst.lap1}${tied(worst.gain)}`, tone: worst.gain < 0 ? "bad" as const : undefined },
    season && { label: "Season's best starter", value: `${season.abbreviation} ${places(season.vs_normal)}`, note: "places a start against the grid slot's normal" },
    race && { label: "Places changed on lap 1", value: `${ran.filter((c) => c.gain !== 0).length} cars`, note: `at ${name}${out ? `, ${out} out on lap 1` : ", all cars"}` },
  ];
}
