import { useEffect, useState, type ReactNode } from "react";
import { api, type CrewStanding, type PitCrews, type PitLaneTrip, type StandingsMoment } from "../api";
import { percent } from "../panels/PredictionBoard";
import { KpiRow } from "../shell/KpiRow";
import { useSeasonMoment } from "./moment";
import type { ScreenContext } from "./ScreenView";

/** Why a trip down the pit lane is not counted as a crew's stop, as the screen says it. */
const EXCLUDED: Record<string, string> = {
  "safety car": "under a safety car or VSC",
  "red flag": "in red flags",
  penalty: "serving penalties",
  garage: "taken into the garage",
  "no new tyres": "without new tyres",
};

/** The ranking's axis runs this far either side of a typical stop, in seconds. */
const AXIS_S = 2.5;

/**
 * Which teams turn a car round fastest.
 *
 * The timing gives when a car crossed the pit-lane entry and exit lines, not
 * how long it stood still, so each stop is its pit-lane time against the same
 * race's typical stop: the lane is the same for everyone there, and what
 * differs is the crew's work. Only green-flag stops with new tyres count (see
 * model/pit_crews.py for what is left out and why). Below the ranking, this
 * session's own stops, up to the replay clock.
 */
export function CrewsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useSeasonMoment(ctx);
  const [crews, setCrews] = useState<PitCrews | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setCrews(null);
    setError(null);
    api
      .pitCrews(ctx.session, moment, controller.signal)
      .then((body) => (Array.isArray(body?.teams) ? setCrews(body) : setError("The pit crews came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [ctx.session, moment]);

  const switcher = (
    <div className="segmented" role="radiogroup" aria-label="Which stops count">
      {([["before", "Going into this session"], ["after", "After it"]] as [StandingsMoment, string][]).map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={moment === key} className={moment === key ? "is-on" : ""}
                onClick={() => setMoment(key)}>{text}</button>
      ))}
    </div>
  );
  const sofar = crews?.session_stops.filter((trip) => trip.t <= ctx.t) ?? [];

  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body crews-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !crews && <div className="panel-note">Timing every pit stop of the season…</div>}
        {crews && (
          <>
            <p className="standings-basis">{basisLine(crews)}</p>
            <KpiRow tiles={crewTiles(crews)} />
            {/* As racecraft-ui.html lays it out (D-025): the season's crews beside this session's stops. */}
            <div className="crews-grid">
              <CrewTable teams={crews.teams} />
              <SessionStops trips={sofar} total={crews.session_stops.length} />
            </div>
            <ul className="prediction-notes crews-notes">
              <li>
                Pit-lane time, entry line to exit line, against the same race's typical stop: the lane is the same for
                everyone there, so the difference is the crew's work (and a car queued behind its team-mate). The feed
                does not say how long a car stood still.
              </li>
              {crews.notes.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}

function CrewTable({ teams }: { teams: CrewStanding[] }) {
  return (
    <section className="panel crews-panel" aria-label="Pit crews">
      <div className="panel-bar"><h2>Pit crews, fastest first</h2>
        <span className="panel-meta">every green-flag stop this season · white tick: the typical stop · over {AXIS_S} s away sits on the edge</span></div>
      <div className="standings-table is-crews crews-scroll" role="table" aria-label="Pit crew ranking">
        <div className="standings-row is-head" role="row">
          <span role="columnheader" className="num">Pos</span>
          <span role="columnheader" />
          <span role="columnheader">Team</span>
          <span role="columnheader" className="num" title="The team's median stop against each race's typical stop">Typical</span>
          <span role="columnheader" title={`The middle half of the team's stops, ${AXIS_S} s either side of a typical stop`}>
            Quicker · slower
          </span>
          <span role="columnheader" className="num" title="The middle half of its stops spans this many seconds: lower is steadier">Spread</span>
          <span role="columnheader" className="num" title="Stops more than 2 s slower than the race's typical one">Slow</span>
          <span role="columnheader" className="num">Stops</span>
        </div>
        {teams.map((t) => (
          <div key={t.team} role="row" className={`standings-row${t.thin ? " is-thin" : ""}`}>
            <span role="cell" className="num pos">{t.position}</span>
            <span role="cell" className="team-bar" style={{ background: `#${t.team_color ?? "555"}` }} />
            <span role="cell" className="who"><b>{t.team}</b></span>
            <span role="cell" className={`num points${t.typical_s < 0 ? " is-quick" : t.typical_s > 0 ? " is-slow" : ""}`}>
              {seconds(t.typical_s)}
            </span>
            <span role="cell" className="crew-range" aria-label={`middle half from ${seconds(t.q1_s)} to ${seconds(t.q3_s)}`}>
              {(t.stop_times_s ?? []).map((v, k) => <i key={k} style={{ left: `${axis(v)}%`, background: `#${t.team_color ?? "777"}` }} />)}
              <b style={{ left: `${axis(t.typical_s)}%` }} />
            </span>
            <span role="cell" className="num gap">{t.spread_s.toFixed(2)} s</span>
            <span role="cell" className="num">{percent(t.slow_share)}</span>
            <span role="cell" className="num gap">{t.stops}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function SessionStops({ trips, total }: { trips: PitLaneTrip[]; total: number }) {
  return (
    <section className="panel crews-panel" aria-label="This session's stops">
      <div className="panel-bar"><h2>This session's stops so far: {trips.length} of {total}</h2></div>
      {trips.length === 0 ? (
        <p className="panel-note">{total ? "Nobody has stopped yet at this point of the replay." : "No stops in this session."}</p>
      ) : (
        <div className="standings-table is-trips crews-scroll" role="table" aria-label="Stops in this session">
          <div className="standings-row is-head" role="row">
            <span role="columnheader" className="num">Lap</span>
            <span role="columnheader" />
            <span role="columnheader">Driver</span>
            <span role="columnheader" className="num" title="Entry line to exit line">In the lane</span>
            <span role="columnheader" className="num" title="Against this race's typical green-flag stop">Vs typical</span>
            <span role="columnheader" />
          </div>
          {[...trips].reverse().map((trip) => (
            <div key={`${trip.driver_number}-${trip.lap}`} role="row" className="standings-row">
              <span role="cell" className="num pos">{trip.lap}</span>
              <span role="cell" className="team-bar" style={{ background: `#${trip.team_color ?? "555"}` }} />
              <span role="cell" className="who">
                <b className="code">{trip.abbreviation ?? trip.driver_number}</b>
                <small>{trip.team ?? ""}</small>
              </span>
              <span role="cell" className="num points">{trip.lane_s.toFixed(1)} s</span>
              <span role="cell" className={`num${trip.excluded ? " gap" : (trip.vs_typical_s ?? 0) < 0 ? " is-quick" : " is-slow"}`}>
                {trip.vs_typical_s === null ? "—" : seconds(trip.vs_typical_s)}
              </span>
              <span role="cell" className="trip-note">{trip.excluded ? `not counted: ${EXCLUDED[trip.excluded] ?? trip.excluded}` : ""}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/** Seconds with a sign: −0.53 s quicker, +1.17 s slower. */
export function seconds(value: number): string {
  if (Math.abs(value) < 0.005) return "0.00 s";
  return `${value < 0 ? "−" : "+"}${Math.abs(value).toFixed(2)} s`;
}

function axis(value: number): number {
  return ((Math.max(-AXIS_S, Math.min(AXIS_S, value)) + AXIS_S) / (2 * AXIS_S)) * 100;
}

/** What the ranking rests on, and what it left out. */
export function basisLine(crews: PitCrews): string {
  if (crews.stops === 0) return `${crews.year} season · no stops yet`;
  const left = Object.entries(crews.excluded)
    .sort((a, b) => b[1] - a[1])
    .map(([why, n]) => `${n} ${EXCLUDED[why] ?? why}`);
  return `${crews.year} season · ${crews.stops} green-flag stops in ${crews.races} races and sprints`
    + (left.length ? `; left out: ${left.join(", ")}` : "");
}

/** "−0.42 s" quicker than a race's typical stop, "+0.31 s" slower. */
function versus(seconds: number): string {
  return `${seconds < 0 ? "−" : "+"}${Math.abs(seconds).toFixed(2)} s`;
}

/**
 * The crews' headline figures. The public timing gives pit-lane time, line to
 * line, not how long a car stood still, so every figure is a team's typical
 * stop against each race's typical stop (see model/pit_crews.py).
 */
export function crewTiles(crews: PitCrews) {
  const ranked = crews.teams.filter((t) => !t.thin);
  const quickest = ranked[0];
  const steadiest = [...ranked].sort((a, b) => a.spread_s - b.spread_s)[0];
  const slowest = [...ranked].sort((a, b) => b.slow_share - a.slow_share)[0];
  return [
    quickest && { label: "Quickest crew", value: `${quickest.team} · ${versus(quickest.typical_s)}`, note: "typical stop against the race's", tone: "good" as const },
    steadiest && { label: "Most consistent", value: `${steadiest.team} · ±${steadiest.spread_s.toFixed(2)} s`, note: "spread of its stops" },
    slowest && slowest.slow_share > 0 && { label: "Most slow stops", value: `${slowest.team} · ${percent(slowest.slow_share)}`, note: "of its stops went slow", tone: "bad" as const },
    crews.stops > 0 && { label: "Stops counted", value: String(crews.stops), note: `green flag, new tyres, ${crews.races} ${crews.races === 1 ? "race" : "races"}` },
  ];
}
