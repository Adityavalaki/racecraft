import { useEffect, useState, type ReactNode } from "react";
import { api, type RaceReview, type ReviewDriver, type ReviewStop, type StandingsMoment } from "../api";
import { KpiRow } from "../shell/KpiRow";
import type { ScreenContext } from "./ScreenView";

const SHORT: Record<ReviewStop["kind"], string> = { green: "", "safety car": "SC", VSC: "VSC", "red flag": "red", penalty: "pen" };
/** Stops made while the field was slowed: the cheap ones, shown in green. A penalty stop is not luck. */
const CHEAP = new Set<ReviewStop["kind"]>(["safety car", "VSC", "red flag"]);

/**
 * The last Grand Prix, driver by driver: overtakes made and lost on track, and
 * what each pit stop cost in places (see model/race_review.py). Consistency and
 * "pitted on the wrong lap" were tried and left out as not reliable (D-023).
 */
export function RaceReviewScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [data, setData] = useState<RaceReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The driver open in the inspector, by code: kept across a moment switch if they raced both.
  const [picked, setPicked] = useState<string | null>(null);

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

  const inspected = data?.drivers.find((d) => d.abbreviation === picked) ?? null;
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
              {data.green_stop_places !== null && ` · a normal pit stop here cost about ${placesText(Math.round(data.green_stop_places))}`}
              <br />
              <b>Passed</b> and <b>passed by</b> count overtakes on track: green flag, neither car in the pits (lap 1 is on
              the Starts screen). Each pit stop shows its lap and how many cars that stayed out got past. A stop under
              a safety car (SC), VSC or red flag usually costs far fewer places: that is the luck.
            </p>
            <KpiRow tiles={reviewTiles(data)} />
            <div className={`review-grid${inspected ? " has-inspector" : ""}`}>
              <section className="panel standings-panel" aria-label="Race review">
                <ReviewTable drivers={data.drivers} picked={inspected?.abbreviation ?? null}
                             onPick={(code) => setPicked(picked === code ? null : code)} />
              </section>
              {inspected && <Inspector driver={inspected} data={data} onClose={() => setPicked(null)} />}
            </div>
            {data.notes.length > 0 && (
              <ul className="prediction-notes">{data.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

function ReviewTable({ drivers, picked, onPick }: { drivers: ReviewDriver[]; picked: string | null; onPick: (code: string) => void }) {
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
        <div key={d.abbreviation} role="row" className={`standings-row is-pickable${picked === d.abbreviation ? " is-selected" : ""}`}
             onClick={() => onPick(d.abbreviation)}>
          <span role="cell" className="num pos">{d.position ?? (d.status === "R" ? "DNF" : d.status)}</span>
          <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
          <span role="cell" className="who">
            <button type="button" className="row-pick code" aria-pressed={picked === d.abbreviation}
                    aria-label={`Inspect ${d.abbreviation}`} onClick={(e) => { e.stopPropagation(); onPick(d.abbreviation); }}>
              {d.abbreviation}
            </button>
            <small>{d.team}</small>
          </span>
          <span role="cell" className={`num points${d.passes_made ? " is-quick" : ""}`}>{d.passes_made}</span>
          <span role="cell" className={`num points${d.passes_lost ? " is-slow" : ""}`}>{d.passes_lost}</span>
          <span role="cell" className="num gap">{d.stops.length ? d.pit_places : "—"}</span>
          <span role="cell" className="split stops">
            {d.stops.length
              ? d.stops.map((s, i) => (
                  <span key={s.lap}>{i > 0 && " · "}<span className={CHEAP.has(s.kind) ? "is-quick" : ""}>{stopText(s)}</span></span>
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

/** "1 place", "3 places". */
export function placesText(n: number): string {
  return `${n} ${n === 1 ? "place" : "places"}`;
}

/** The leaders of one count: "RUS, HAD · 6", ties named together; nothing when nobody scored. */
function leaders(drivers: ReviewDriver[], count: (d: ReviewDriver) => number): string {
  const top = Math.max(0, ...drivers.map(count));
  if (!top) return "";
  return `${drivers.filter((d) => count(d) === top).map((d) => d.abbreviation).join(", ")} · ${top}`;
}

/** Race review's headline figures, from the review itself. */
export function reviewTiles(data: RaceReview) {
  const cheap = data.drivers.flatMap((d) => d.stops.filter((s) => CHEAP.has(s.kind)).map(() => d.abbreviation));
  return [
    data.green_stop_places !== null && { label: "A normal stop cost", value: placesText(Math.round(data.green_stop_places)), note: "median of green-flag stops" },
    { label: "Most passes made", value: leaders(data.drivers, (d) => d.passes_made), note: "on track, green flag" },
    { label: "Most times passed", value: leaders(data.drivers, (d) => d.passes_lost), note: "on track, green flag", tone: "bad" as const },
    cheap.length > 0 && { label: "Stops under SC / VSC", value: `${cheap.length}`, note: [...new Set(cheap)].join(", "), tone: "good" as const },
  ];
}

/** A plain sentence on one stop: what it cost, and against what. */
export function stopSentence(stop: ReviewStop, normal: number | null): string {
  const cost = stop.places ? `cost ${placesText(stop.places)}` : "cost no places";
  const under = { green: "", "safety car": " under the safety car", VSC: " under the VSC", "red flag": " under the red flag",
                  penalty: " with a penalty served" }[stop.kind];
  const against = normal !== null && stop.kind !== "green" ? `, against about ${placesText(Math.round(normal))} for a normal stop` : "";
  return `Lap ${stop.lap}${under}: ${cost}${against}.`;
}

/**
 * One driver of the review, opened from the table: where they finished, the
 * counts, their stops drawn along the race, and each stop in a sentence.
 */
function Inspector({ driver, data, onClose }: { driver: ReviewDriver; data: RaceReview; onClose: () => void }) {
  const laps = data.laps ?? Math.max(1, ...driver.stops.map((s) => s.lap + 1));
  const x = (lap: number) => (lap / laps) * 300;
  return (
    <aside className="panel review-inspector" aria-label={`${driver.abbreviation} in detail`}>
      <div className="panel-bar">
        <span className="team-bar tall" style={{ background: `#${driver.team_color ?? "555"}` }} />
        <h2>{driver.abbreviation}</h2>
        <span className="panel-meta">{driver.full_name ?? driver.team}</span>
        <button type="button" className="card-close" onClick={onClose} aria-label="Close the inspector">
          <svg width="10" height="10" viewBox="0 0 10 10" aria-hidden="true"><path d="M2 2l6 6M8 2l-6 6" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" /></svg>
        </button>
      </div>
      <div className="inspector-figures">
        <div><span className="cap">Finished</span><b className="num">{driver.position ? `P${driver.position}` : driver.status === "R" ? "DNF" : driver.status}</b></div>
        <div><span className="cap">Passed</span><b className={`num${driver.passes_made ? " is-good" : ""}`}>{driver.passes_made}</b></div>
        <div><span className="cap">Passed by</span><b className={`num${driver.passes_lost ? " is-bad" : ""}`}>{driver.passes_lost}</b></div>
        <div><span className="cap">Lost in pits</span><b className="num">{driver.stops.length ? driver.pit_places : "—"}</b></div>
      </div>
      <div className="inspector-body">
        <span className="cap">Stops through the race</span>
        <svg viewBox="0 0 300 54" role="img" className="stop-timeline"
             aria-label={`Stops for ${driver.abbreviation}: ${driver.stops.map((s) => stopText(s)).join(", ") || "none"}`}>
          <rect x="0" y="26" width="300" height="6" rx="3" fill="#20242B" />
          {driver.stops.map((s) => (
            <g key={s.lap}>
              <circle cx={x(s.lap)} cy="29" r="6" fill={CHEAP.has(s.kind) ? "#4ADE80" : s.kind === "penalty" ? "#FBBF24" : "#E8EAED"} />
              <text x={x(s.lap)} y="14" textAnchor="middle" className="stop-label">{stopText(s)}</text>
            </g>
          ))}
          <text x="0" y="50" className="stop-axis">L1</text>
          <text x="300" y="50" textAnchor="end" className="stop-axis">L{laps}</text>
        </svg>
        {driver.stops.length === 0
          ? <p className="inspector-note">No pit stop counted: none made, or only on lap 1 or at a retirement.</p>
          : driver.stops.map((s) => <p key={s.lap} className="inspector-note">{stopSentence(s, data.green_stop_places)}</p>)}
      </div>
    </aside>
  );
}
