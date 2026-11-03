import { useEffect, useState, type ReactNode } from "react";
import { api, formatLapTime, type LapComparison, type QualiDriver, type QualiKind, type QualiLaps, type StandingsMoment } from "../api";
import { KpiRow } from "../shell/KpiRow";
import type { ScreenContext } from "./ScreenView";

const KINDS: [QualiKind, string][] = [["Q", "Qualifying"], ["SQ", "Sprint qualifying"]];
/** Team-mates share a colour: the rival's line goes grey so the two stay apart. */
const REFERENCE = "#9A9AA6";

/** Two best laps side by side. Each lap is asked for by number: left to itself the route picks the car's last lap, usually an in-lap. */
function useComparison(session: string | null, pole: QualiDriver | undefined, rival: QualiDriver | undefined) {
  const [answer, setAnswer] = useState<LapComparison | null>(null);
  const [failed, setFailed] = useState<string | null>(null);
  const ready = session && pole?.driver_number != null && pole.best_lap != null && rival?.driver_number != null && rival.best_lap != null;
  useEffect(() => {
    setAnswer(null);
    setFailed(null);
    if (!ready) return;
    const controller = new AbortController();
    api.compare(session!, rival!.driver_number!, pole!.driver_number!, { lap: rival!.best_lap!, refLap: pole!.best_lap! }, controller.signal)
      .then((next) => (next?.delta && next.subject && next.reference ? setAnswer(next) : setFailed("The laps came back in a shape this screen cannot read.")))
      .catch((e: Error) => {
        if (e.name !== "AbortError") setFailed(e.message);
      });
    return () => controller.abort();
  }, [ready, session, pole?.driver_number, pole?.best_lap, rival?.driver_number, rival?.best_lap]);
  return { answer, failed };
}

/**
 * The last qualifying, as racecraft-ui.html draws it (D-025): the classification
 * beside pole against a rival, by lap distance and sector by sector.
 *
 * "Left" is the time left on the table: each driver's best lap against their own
 * three best sectors added up (see model/quali_laps.py). Against their own
 * sectors, not the session's, so it measures the lap, not the car.
 */
export function QualifyingScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [moment, setMoment] = useState<StandingsMoment>("before");
  const [kind, setKind] = useState<QualiKind>("Q");
  const [picked, setPicked] = useState<string | null>(null);
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

  const drivers = data?.drivers ?? [];
  const timed = drivers.filter((d) => d.best_s !== null);
  const pole = timed[0];
  const rivals = timed.slice(1);
  const rival = rivals.find((d) => d.abbreviation === picked) ?? rivals[0];
  const { answer, failed } = useComparison(data?.session_key ?? null, pole, rival);

  const switcher = (
    <>
      {pole && rivals.length > 0 && (
        <>
          <span className="quali-vs num"><b>{pole.abbreviation}</b> v</span>
          <div className="segmented" role="radiogroup" aria-label={`Compare ${pole.abbreviation} with`}>
            {rivals.slice(0, 4).map((d) => (
              <button key={d.abbreviation} type="button" role="radio" aria-checked={d === rival} className={`num${d === rival ? " is-on" : ""}`}
                      onClick={() => setPicked(d.abbreviation)}>{d.abbreviation}</button>
            ))}
          </div>
        </>
      )}
      <div className="segmented" role="radiogroup" aria-label="Which qualifying">
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
      <main className="screen-body quali-body">
        {error && <div className="panel-note error">{error}</div>}
        {!error && !data && <div className="panel-note">Adding up sectors…</div>}
        {data && (
          <>
            <p className="standings-basis">
              <b>{data.event_name ? `${data.event_name}, ${kind === "Q" ? "qualifying" : "sprint qualifying"}` : `${data.year} season`}</b>
              {" · "}
              {data.sessions ? `${data.sessions} ${data.sessions === 1 ? "session" : "sessions"} this season` : "nothing run yet"}
            </p>
            <KpiRow tiles={qualiTiles(drivers)} />
            <div className="quali-grid">
              <section className="panel quali-panel" aria-label="Qualifying classification">
                <div className="panel-bar"><h2>Classification</h2>
                  <span className="panel-meta">red line: knocked out · left: best lap against own best sectors · purple: best in the session</span></div>
                <QualiTable drivers={drivers} rival={rival} onPick={setPicked} />
              </section>
              <div className="quali-side">
                <LapChart pole={pole} rival={rival} answer={answer} failed={failed} />
                <GapSources pole={pole} rival={rival} />
              </div>
            </div>
            {data.notes.length > 0 && (
              <ul className="prediction-notes quali-notes">{data.notes.map((note) => <li key={note}>{note}</li>)}</ul>
            )}
          </>
        )}
      </main>
    </div>
  );
}

/** The last part of qualifying the driver set a time in: 0 for none. */
const lastPart = (d: QualiDriver) => (d.q3_s !== null && d.q3_s !== undefined ? 3 : d.q2_s !== null && d.q2_s !== undefined ? 2 : d.q1_s !== null && d.q1_s !== undefined ? 1 : 0);

function QualiTable({ drivers, rival, onPick }: { drivers: QualiDriver[]; rival: QualiDriver | undefined; onPick: (code: string) => void }) {
  if (drivers.length === 0) return <p className="panel-note">No qualifying laps to add up yet.</p>;
  const pole = drivers.find((d) => d.best_s !== null);
  const bests = [0, 1, 2].map((k) => Math.min(...drivers.map((d) => d.sectors?.[k] ?? Infinity)));
  return (
    <div className="quali-table" role="table" aria-label="Qualifying classification">
      <div className="quali-row is-head cap" role="row">
        <span role="columnheader" className="right">P</span>
        <span role="columnheader" />
        <span role="columnheader">Drv</span>
        <span role="columnheader" />
        <span role="columnheader" className="right">Q1</span>
        <span role="columnheader" className="right">Q2</span>
        <span role="columnheader" className="right">Q3</span>
        <span role="columnheader" className="right" title="Best lap of the session, any part, against pole's">Gap</span>
        <span role="columnheader" className="right" title="Best lap minus the driver's own three best sectors added together">Left</span>
        {[1, 2, 3].map((n) => <span key={n} role="columnheader" className="mid" title="The driver's best in this sector, any lap">S{n}</span>)}
      </div>
      {drivers.map((d, i) => {
        const part = lastPart(d);
        const next = drivers[i + 1];
        const cut = next && lastPart(next) < part;
        const lost = d.sectors_left ? `\nLost in S1 · S2 · S3: ${d.sectors_left.map((v) => v.toFixed(3)).join(" · ")}` : "";
        const avg = d.season_left_s !== null ? `\nSeason average left: ${leftText(d.season_left_s)} over ${d.season_sessions}` : "";
        return (
          <button key={d.abbreviation} type="button" role="row" aria-pressed={d === rival}
                  className={`quali-row${d === rival ? " is-selected" : ""}${cut ? " is-cut" : ""}`} disabled={d === pole || d.best_s === null}
                  onClick={() => onPick(d.abbreviation)}
                  title={`${d.full_name ?? d.abbreviation}\nBest lap ${formatLapTime(d.best_s)}, perfect lap ${formatLapTime(d.ideal_s)}${lost}${avg}`}>
            <span role="cell" className="num right strong">{d.position ?? ""}</span>
            <span role="cell" className="team-bar" style={{ background: `#${d.team_color ?? "555"}` }} />
            <span role="cell" className="num strong">{d.abbreviation}</span>
            <span role="cell" className="panel-meta quali-team">{d.team}</span>
            {([d.q1_s, d.q2_s, d.q3_s] as (number | null | undefined)[]).map((q, k) => (
              <span key={k} role="cell" className={`num right${k + 1 === part ? " is-last" : " quali-dim"}${k === 2 && i === 0 ? " is-pole" : ""}`}>{q == null ? "—" : formatLapTime(q)}</span>
            ))}
            <span role="cell" className="num right quali-dim">{d.best_s === null ? "—" : d === pole ? "Pole" : `+${(d.best_s - pole!.best_s!).toFixed(3)}`}</span>
            <span role="cell" className={`num right${d.left_s !== null && d.left_s < 0.0005 ? " is-quick" : ""}`}>{leftText(d.left_s)}</span>
            {[0, 1, 2].map((k) => (
              <span key={k} role="cell" className="mid"><span className={`seg num${d.sectors?.[k] === bests[k] ? " is-purple" : ""}`}>{d.sectors ? d.sectors[k]!.toFixed(3) : "—"}</span></span>
            ))}
          </button>
        );
      })}
    </div>
  );
}

/** Corners to label: a tight complex keeps its tick lines, but only the labels with room (3% of the lap) are drawn. */
export function spacedCorners<T extends { distance: number }>(corners: T[], length: number): T[] {
  let last = -Infinity;
  return corners.filter((c) => {
    if (c.distance - last < length * 0.03) return false;
    last = c.distance;
    return true;
  });
}

/** The two best laps by distance: speed, and the rival's time behind pole as it grows and shrinks. */
function LapChart({ pole, rival, answer, failed }: { pole: QualiDriver | undefined; rival: QualiDriver | undefined; answer: LapComparison | null; failed: string | null }) {
  const colourA = `#${pole?.team_color ?? "777"}`;
  const colourB = rival?.team_color && rival.team_color !== pole?.team_color ? `#${rival.team_color}` : REFERENCE;
  const title = pole && rival ? `${pole.abbreviation} v ${rival.abbreviation}` : "Best laps";
  const length = answer?.reference.length_m ?? 1;
  const x = (m: number) => (m / length) * 1000;
  const speeds = answer ? [...answer.reference.speed, ...answer.subject.speed] : [];
  const low = Math.min(...speeds);
  const high = Math.max(...speeds);
  const speedPath = (distance: number[], speed: number[]) =>
    distance.map((d, i) => `${i ? "L" : "M"}${x(d).toFixed(1)} ${(96 - ((speed[i]! - low) / Math.max(high - low, 1)) * 92).toFixed(1)}`).join("");
  const deltas = answer?.delta.delta_s ?? [];
  const reach = Math.max(0.05, ...deltas.map(Math.abs));
  const delta = answer ? answer.delta.distance.map((d, i) => `${i ? "L" : "M"}${x(d).toFixed(1)} ${(30 - (deltas[i]! / reach) * 26).toFixed(1)}`).join("") : "";
  return (
    <section className="panel quali-chart" aria-label="Pole lap comparison">
      <div className="panel-bar"><h2>{title}</h2><span className="panel-meta">by lap distance, each driver's best lap</span>
        {pole && rival && <span className="quali-chip num" style={{ color: colourB }}>{rival.abbreviation} +{(rival.best_s! - pole.best_s!).toFixed(3)} s</span>}
      </div>
      {!answer ? (
        <p className="panel-note">{failed ?? (rival ? "Loading both laps…" : "Nobody to compare yet.")}</p>
      ) : (
        <div className="quali-channels">
          <div className="quali-channel" style={{ flex: "2 1 0" }}>
            <div className="quali-channel-label"><span className="cap">Speed</span><span className="num">{Math.round(low)}–{Math.round(high)} km/h</span></div>
            <div className="quali-channel-plot">
              {answer.reference.corners.map((c) => <span key={c.number} className="quali-corner" style={{ left: `${x(c.distance) / 10}%` }} />)}
              <svg viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label={`Speed by distance, ${title}`}>
                <path d={speedPath(answer.subject.distance, answer.subject.speed)} fill="none" stroke={colourB} strokeWidth="1.5" vectorEffect="non-scaling-stroke" />
                <path d={speedPath(answer.reference.distance, answer.reference.speed)} fill="none" stroke={colourA} strokeWidth="1.7" vectorEffect="non-scaling-stroke" />
              </svg>
            </div>
          </div>
          <div className="quali-channel" style={{ flex: "1 1 0" }}>
            <div className="quali-channel-label"><span className="cap">Delta</span><span className="num">{rival?.abbreviation} behind ↑</span></div>
            <div className="quali-channel-plot">
              {answer.reference.corners.map((c) => <span key={c.number} className="quali-corner" style={{ left: `${x(c.distance) / 10}%` }} />)}
              <svg viewBox="0 0 1000 60" preserveAspectRatio="none" role="img" aria-label={`Time gap by distance, ${title}`}>
                <path d="M0 30H1000" stroke="#FFFFFF" strokeOpacity=".15" strokeDasharray="3 3" vectorEffect="non-scaling-stroke" />
                <path d={`${delta}L${x(answer.delta.distance.at(-1) ?? 0).toFixed(1)} 30L0 30Z`} fill={colourB} fillOpacity=".14" />
                <path d={delta} fill="none" stroke="#F2F3F5" strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
              </svg>
            </div>
          </div>
          <div className="quali-corners num">
            {spacedCorners(answer.reference.corners, length).map((c) => <span key={c.number} style={{ left: `${x(c.distance) / 10}%` }}>{c.number}{c.letter ?? ""}</span>)}
          </div>
        </div>
      )}
    </section>
  );
}

/** Best sector against best sector: a bar right where pole was quicker, left where the rival was. */
function GapSources({ pole, rival }: { pole: QualiDriver | undefined; rival: QualiDriver | undefined }) {
  if (!pole?.sectors || !rival?.sectors) return null;
  const a = pole.sectors;
  const b = rival.sectors;
  const gaps = [0, 1, 2].map((k) => b[k]! - a[k]!);
  const reach = Math.max(0.05, ...gaps.map(Math.abs));
  const colourA = `#${pole.team_color ?? "777"}`;
  const colourB = rival.team_color && rival.team_color !== pole.team_color ? `#${rival.team_color}` : REFERENCE;
  return (
    <section className="panel quali-sources" aria-label="Where the gap comes from">
      <div className="panel-bar"><h2>Where the gap comes from</h2><span className="panel-meta">best sectors, {rival.abbreviation} against {pole.abbreviation}</span></div>
      <div className="quali-sources-body">
        {gaps.map((g, k) => {
          const w = (Math.abs(g) / reach) * 50;
          return (
            <div key={k} className="quali-sector">
              <span className="cap">S{k + 1}</span>
              <span className="quali-sector-bar"><i style={{ left: `${g >= 0 ? 50 : 50 - w}%`, width: `${w}%`, background: g >= 0 ? colourA : colourB }} /></span>
              <span className="num right strong">{g >= 0 ? "+" : "−"}{Math.abs(g).toFixed(3)}</span>
            </div>
          );
        })}
        <div className="inspector-figures">
          <div><span className="cap">{pole.abbreviation} lap</span><b className="num stewards-fact">{formatLapTime(pole.best_s)}</b></div>
          <div><span className="cap">{rival.abbreviation} lap</span><b className="num stewards-fact">{formatLapTime(rival.best_s)}</b></div>
          <div><span className="cap">{rival.abbreviation} perfect lap</span><b className="num stewards-fact">{formatLapTime(rival.ideal_s)}</b></div>
        </div>
      </div>
    </section>
  );
}

/** "+0.130" seconds left; "perfect" when the best lap is the perfect lap; a dash for no lap. */
export function leftText(value: number | null): string {
  if (value === null) return "—";
  return value < 0.0005 ? "perfect" : `+${value.toFixed(3)}`;
}

/** Qualifying's headline figures: pole, the most left on the table, the perfect laps, and the season's tidiest. */
export function qualiTiles(drivers: QualiDriver[]) {
  const pole = drivers.find((d) => d.position === 1 && d.best_s !== null);
  const timed = drivers.filter((d) => d.left_s !== null);
  const loosest = [...timed].sort((a, b) => b.left_s! - a.left_s!)[0];
  const perfect = timed.filter((d) => d.left_s! < 0.0005).map((d) => d.abbreviation);
  const tidiest = drivers.filter((d) => d.season_left_s !== null && d.season_sessions >= 3)
    .sort((a, b) => a.season_left_s! - b.season_left_s!)[0];
  return [
    pole && { label: "Pole", value: `${pole.abbreviation} · ${formatLapTime(pole.best_s)}`, note: pole.left_s ? `left ${leftText(pole.left_s)} on the table` : "a perfect lap" },
    loosest && loosest.left_s! >= 0.0005 && { label: "Most left on the table", value: `${loosest.abbreviation} · ${leftText(loosest.left_s)}`, note: "best lap against own best sectors", tone: "bad" as const },
    timed.length > 0 && { label: "Perfect laps", value: String(perfect.length), note: perfect.join(", ") || "nobody put it all together", tone: perfect.length ? "good" as const : undefined },
    tidiest && { label: "Tidiest this season", value: `${tidiest.abbreviation} · ${leftText(tidiest.season_left_s)}`, note: `average over ${tidiest.season_sessions} sessions` },
  ];
}
