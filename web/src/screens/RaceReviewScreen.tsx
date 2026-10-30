import { useEffect, useState, type ReactNode } from "react";
import { api, type RaceReview, type ReviewDriver, type ReviewStop, type StandingsMoment } from "../api";
import { KpiRow } from "../shell/KpiRow";
import type { ScreenContext } from "./ScreenView";

const SHORT: Record<ReviewStop["kind"], string> = { green: "", "safety car": "SC", VSC: "VSC", "red flag": "red", penalty: "pen" };
/** Stops made while the field was slowed: the cheap ones, shown in green. A penalty stop is not luck. */
const CHEAP = new Set<ReviewStop["kind"]>(["safety car", "VSC", "red flag"]);

type Filter = "all" | "neutral" | "green";
const FILTERS: [Filter, string][] = [["all", "All stops"], ["neutral", "Under SC / VSC"], ["green", "Green flag"]];
const keeps = (filter: Filter, stop: ReviewStop) => filter === "all" || (filter === "neutral" ? CHEAP.has(stop.kind) : !CHEAP.has(stop.kind));

/**
 * The last Grand Prix, driver by driver, chart first as racecraft-ui.html
 * draws it: each driver's pit stops along the race (a dot's size and number are
 * the places it cost, green when the field was slowed, the neutralised laps
 * shaded behind), overtakes made and lost on track, and the places lost in the
 * pits. Beside it the headline figures and one driver inspected. See
 * model/race_review.py; consistency and "pitted on the wrong lap" were tried
 * and left out as not reliable (D-023).
 */
export function RaceReviewScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [data, setData] = useState<RaceReview | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The driver open in the inspector, by code: kept across a moment switch if they raced both.
  const [picked, setPicked] = useState<string | null>(null);
  const [filter, setFilter] = useState<Filter>("all");
  const [query, setQuery] = useState("");

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

  const inspected = data?.drivers.find((d) => d.abbreviation === picked) ?? data?.drivers[0] ?? null;
  const q = query.trim().toLowerCase();
  const shown = (data?.drivers ?? []).filter((d) =>
    (filter === "all" || d.stops.some((s) => keeps(filter, s)))
    && (!q || d.abbreviation.toLowerCase().includes(q) || (d.team ?? "").toLowerCase().includes(q) || (d.full_name ?? "").toLowerCase().includes(q)));
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body review-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Reviewing the race…</div>}
        {data && data.drivers.length === 0 && <p className="panel-note">{data.notes[0] ?? "No Grand Prix to review yet."}</p>}
        {data && data.drivers.length > 0 && (
          <div className="review-grid">
            <section className="panel review-chart" aria-label="Overtakes and pit stops by driver">
              <div className="panel-bar">
                <h2>Overtakes and pit stops</h2>
                <label className="review-filter">
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></svg>
                  <span className="visually-hidden">Filter drivers</span>
                  <input type="text" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Filter drivers or teams" />
                </label>
                <div className="segmented" role="radiogroup" aria-label="Which stops">
                  {FILTERS.map(([key, text]) => (
                    <button key={key} type="button" role="radio" aria-checked={filter === key} className={filter === key ? "is-on" : ""}
                            onClick={() => setFilter(key)}>{text}</button>
                  ))}
                </div>
                <span className="panel-meta" style={{ marginLeft: "auto" }}>{data.event_name} · {shown.length} of {data.drivers.length} drivers</span>
              </div>
              <ReviewChart data={data} drivers={shown} filter={filter} picked={inspected?.abbreviation ?? null}
                           onPick={(code) => setPicked(code)} />
              <div className="map-legend">
                <span><i className="review-dot-key" />Green-flag stop: size and number are the places lost</span>
                <span><i className="review-dot-key is-cheap" />Stop under SC / VSC</span>
                {(data.neutralised?.length ?? 0) > 0 && <span><i className="review-band-key" />Safety car / VSC laps</span>}
              </div>
            </section>
            <div className="review-side">
              <KpiRow tiles={reviewTiles(data)} />
              {inspected && <Inspector driver={inspected} data={data} />}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

function ReviewChart({ data, drivers, filter, picked, onPick }: {
  data: RaceReview; drivers: ReviewDriver[]; filter: Filter; picked: string | null; onPick: (code: string) => void;
}) {
  const laps = Math.max(2, data.laps ?? Math.max(2, ...data.drivers.flatMap((d) => d.stops.map((s) => s.lap + 1))));
  const pct = (lap: number) => `${((lap - 1) / (laps - 1)) * 100}%`;
  const ticks = [1, ...[10, 20, 30, 40, 50, 60, 70].filter((l) => l < laps - 4), laps];
  const bands = (data.neutralised ?? []).map((b) => (
    <span key={`${b.from}-${b.kind}`} className={`review-band${b.kind === "red flag" ? " is-red" : ""}`} title={`${b.kind}, lap ${b.from}${b.to > b.from ? `–${b.to}` : ""}`}
          style={{ left: `${((b.from - 1.5) / (laps - 1)) * 100}%`, width: `${((b.to - b.from + 1) / (laps - 1)) * 100}%` }} />
  ));
  return (
    <div className="review-scroll">
      <div className="review-table" role="table" aria-label="Overtakes and pit stops">
        <div className="review-row is-head cap" role="row">
          <span role="columnheader" className="right">Pos</span><span role="columnheader" />
          <span role="columnheader">Driver</span>
          <span role="columnheader" className="review-plot-head" aria-label="Pit stops by lap">
            {ticks.map((l, i) => (
              <span key={l} className="num" style={{ left: pct(l), transform: `translate(${i === 0 ? "0" : i === ticks.length - 1 ? "-100%" : "-50%"}, -50%)` }}>L{l}</span>
            ))}
          </span>
          <span role="columnheader" className="right" title="Cars this driver overtook on track">Passed</span>
          <span role="columnheader" className="right" title="Times this driver was overtaken on track">Passed by</span>
          <span role="columnheader" className="right" title="All the places lost at pit stops">Pit loss</span>
        </div>
        {drivers.map((d) => (
          <div key={d.abbreviation} role="row" className={`review-row${picked === d.abbreviation ? " is-selected" : ""}`}
               onClick={() => onPick(d.abbreviation)}>
            <span role="cell" className="num right strong muted-pos">{d.position ?? (d.status === "R" ? "DNF" : d.status)}</span>
            <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
            <span role="cell" className="who">
              <button type="button" className="row-pick" aria-pressed={picked === d.abbreviation}
                      aria-label={`Inspect ${d.abbreviation}`} onClick={(e) => { e.stopPropagation(); onPick(d.abbreviation); }}>
                {d.abbreviation}
              </button>
              <small>{d.team}</small>
            </span>
            <span role="cell" className="review-plot">
              {bands}
              <span className="review-track" />
              {d.stops.filter((s) => keeps(filter, s)).map((s) => (
                <span key={s.lap} className={`review-dot num${CHEAP.has(s.kind) ? " is-cheap" : s.kind === "penalty" ? " is-penalty" : ""}`}
                      style={{ left: pct(s.lap), width: 16 + s.places * 3, height: 16 + s.places * 3 }} title={stopSentence(s, null)}>
                  {s.places}
                </span>
              ))}
            </span>
            <span role="cell" className={`num right strong${d.passes_made ? " is-good" : " muted"}`}>{d.passes_made}</span>
            <span role="cell" className={`num right strong${d.passes_lost ? " is-bad" : " muted"}`}>{d.passes_lost}</span>
            <span role="cell" className="num right strong">{d.stops.length ? d.pit_places : "—"}</span>
          </div>
        ))}
      </div>
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
    data.green_stop_places !== null && { label: "A normal stop cost", value: placesText(Math.round(data.green_stop_places)), note: "median, green-flag stops" },
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
 * One driver of the review: where they finished, the counts, each stop
 * against the race's median, their stops drawn along the race, and each stop
 * in a sentence.
 */
function Inspector({ driver, data }: { driver: ReviewDriver; data: RaceReview }) {
  const laps = Math.max(2, data.laps ?? Math.max(2, ...driver.stops.map((s) => s.lap + 1)));
  const pct = (lap: number) => `${((lap - 1) / (laps - 1)) * 100}%`;
  const maxLost = Math.max(1, ...data.drivers.flatMap((d) => d.stops.map((s) => s.places)));
  const median = data.green_stop_places;
  const colour = `#${driver.team_color ?? "555555"}`;
  return (
    <aside className="panel review-inspector" aria-label={`${driver.abbreviation} in detail`} style={{ ["--team" as string]: colour }}>
      <div className="panel-bar inspector-head">
        <span className="card-team-bar" />
        <span className="card-who"><span className="card-code">{driver.abbreviation}</span><span className="card-team">{driver.full_name ?? driver.team}</span></span>
        <span className="inspector-pos"><span className="cap">Finished</span>
          <b>{driver.position ? `P${driver.position}` : driver.status === "R" ? "DNF" : driver.status}</b></span>
      </div>
      <div className="inspector-figures">
        <div><span className="cap">Passed</span><b className={`num${driver.passes_made ? " is-good" : ""}`}>{driver.passes_made}</b></div>
        <div><span className="cap">Passed by</span><b className={`num${driver.passes_lost ? " is-bad" : ""}`}>{driver.passes_lost}</b></div>
        <div><span className="cap">Pit loss</span><b className="num">{driver.stops.length ? driver.pit_places : "—"}</b></div>
      </div>
      <div className="inspector-body">
        {driver.stops.length > 0 && (
          <div className="inspector-block">
            <div className="inspector-line"><span className="cap">Each stop against the median</span>
              {median !== null && <span className="num muted">median {placesText(Math.round(median))}</span>}</div>
            {driver.stops.map((s) => (
              <div key={s.lap} className="stop-bar-row">
                <span className={`num strong${CHEAP.has(s.kind) ? " is-good" : ""}`}>L{s.lap}{SHORT[s.kind] ? ` ${SHORT[s.kind]}` : ""}</span>
                <span className="stop-bar">
                  <span style={{ width: `${Math.max(2, (s.places / maxLost) * 100)}%`,
                                 background: CHEAP.has(s.kind) ? "#4ADE80" : median !== null && s.places > median ? "#FF6B6B" : "#D6DAE0" }} />
                  {median !== null && <i style={{ left: `${(median / maxLost) * 100}%` }} />}
                </span>
                <span className="num strong right">−{s.places}</span>
              </div>
            ))}
          </div>
        )}
        <div className="inspector-block">
          <span className="cap">Through the race</span>
          <div className="race-strip" role="img" aria-label={`Stops for ${driver.abbreviation}: ${driver.stops.map((s) => stopText(s)).join(", ") || "none"}`}>
            <span className="race-strip-track" />
            {(data.neutralised ?? []).map((b) => (
              <span key={`${b.from}-${b.kind}`} className="race-strip-band"
                    style={{ left: `${((b.from - 1.5) / (laps - 1)) * 100}%`, width: `${((b.to - b.from + 1) / (laps - 1)) * 100}%` }} />
            ))}
            {driver.stops.map((s) => (
              <span key={s.lap} className={`review-dot num${CHEAP.has(s.kind) ? " is-cheap" : s.kind === "penalty" ? " is-penalty" : ""}`}
                    style={{ left: pct(s.lap), width: 20, height: 20 }}>{s.places}</span>
            ))}
          </div>
          <div className="race-strip-axis num"><span>L1</span><span>L{laps}</span></div>
        </div>
        {driver.stops.length === 0
          ? <p className="inspector-note">No pit stop counted: none made, or only on lap 1 or at a retirement.</p>
          : driver.stops.map((s) => <p key={s.lap} className="inspector-note">{stopSentence(s, median)}</p>)}
        <div className="inspector-block inspector-how">
          <span className="cap">How this is measured</span>
          <p>A pass is two cars swapping places between green laps, neither in the pits. Places lost at a stop are cars that
            stayed out and got past. A stop under a safety car, VSC or red flag usually costs far fewer: that is the luck.
            Lap 1 is on the Starts screen.</p>
          {data.notes.map((note) => <p key={note}>{note}</p>)}
        </div>
      </div>
    </aside>
  );
}
