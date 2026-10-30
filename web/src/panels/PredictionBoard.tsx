import { useEffect, useState } from "react";
import { KpiRow } from "../shell/KpiRow";
import { WeatherForecast } from "./WeatherForecast";
import {
  api, type Prediction, type PredictionDriver, type PredictionKind, type PredictionScore, type WeekendInfo,
} from "../api";

interface Props {
  sessionKey: string;
  selected: number[];
  onSelect: (driver: number) => void;
}

const SESSION_NAMES: Record<string, string> = {
  FP1: "FP1", FP2: "FP2", FP3: "FP3", SQ: "sprint qualifying", SS: "sprint shootout", S: "the sprint", Q: "qualifying",
};
const SIGNAL_NAMES: Record<string, string> = {
  quali_gap_s: "qualifying", long_run_s: "long runs", sprint_s: "sprint", form_s: "form", carry_s: "last season",
};
/** The signals as the note about their worth names them, for each kind of prediction. */
const SIGNAL_WORDS: Record<PredictionKind, Record<string, string>> = {
  race: { quali_gap_s: "qualifying", long_run_s: "practice long runs", sprint_s: "the sprint",
          form_s: "recent race pace", carry_s: "last season's form" },
  sprint: { quali_gap_s: "sprint qualifying", long_run_s: "FP1 long runs", sprint_s: "the sprint",
            form_s: "recent race pace", carry_s: "last season's form" },
};
const SPRINT_SESSIONS = ["SQ", "SS", "S"];
const NO_WEEKEND: WeekendInfo = { sessions: [], sprint: false };

/**
 * The race, predicted from before it started; on a sprint weekend, the sprint too.
 *
 * Practice long runs, qualifying, the sprint and the season's earlier races
 * give each driver a race pace and how sure it is; the race simulator then runs
 * the race a thousand times from the real grid, with this circuit's pit lane,
 * overtaking and safety cars, and retirements at the season's rate. What comes
 * back is chances, not a call: who wins most often, and how often. The sprint
 * is the same from sprint qualifying, FP1 and the earlier races, over its own
 * distance with no stops, its signals weighed on past sprints.
 *
 * Each is saved the first time it is made, once its qualifying is in, and never
 * recomputed, so afterwards this is what was said beforehand, with the result
 * beside it and the same scores the replay of every race and sprint since 2023
 * uses, against simply finishing where you started.
 */
export function PredictionBoard({ sessionKey, selected, onSelect }: Props) {
  const [weekend, setWeekend] = useState<WeekendInfo | null>(null);
  const [kind, setKind] = useState<PredictionKind | null>(null);
  const [answer, setAnswer] = useState<Prediction | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Which weekend this is, to offer the sprint and to open on the one that is next.
  useEffect(() => {
    const controller = new AbortController();
    setWeekend(null);
    setKind(null);
    api
      .weekend(sessionKey, controller.signal)
      .then((body) => {
        const known = isWeekend(body) ? body : NO_WEEKEND;
        setWeekend(known);
        setKind(openingKind(sessionKey, known));
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setWeekend(NO_WEEKEND);
        setKind("race");
      });
    return () => controller.abort();
  }, [sessionKey]);

  useEffect(() => {
    if (!kind) return;
    const controller = new AbortController();
    setAnswer(null);
    setError(null);
    api
      .prediction(sessionKey, kind, controller.signal)
      .then(setAnswer)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [sessionKey, kind]);

  const shown: PredictionKind = kind ?? "race";
  const switcher = weekend?.sprint ? (
    <div className="segmented prediction-kind" role="radiogroup" aria-label="Which race">
      {([["race", "Grand Prix"], ["sprint", "Sprint"]] as [PredictionKind, string][]).map(([key, text]) => (
        <button key={key} type="button" role="radio" aria-checked={shown === key} className={shown === key ? "is-on" : ""}
                onClick={() => setKind(key)}>{text}</button>
      ))}
    </div>
  ) : null;

  if (error) return <div className="prediction">{switcher}<div className="panel-note error">{error}</div></div>;
  if (!answer) {
    return (
      <div className="prediction">
        {switcher}
        <div className="panel-note">
          {shown === "sprint"
            ? "Predicting the sprint: a thousand simulated sprints from sprint qualifying, FP1 and the season so far. About ten seconds the first time; saved after that."
            : "Predicting the race: a thousand simulated races from this weekend's running. About twenty seconds the first time; saved after that."}
        </div>
      </div>
    );
  }

  const sprint = (answer.kind ?? "race") === "sprint";
  const event = sprint ? "sprint" : "race";
  const finish = answer.result?.finish ?? null;
  const cars = answer.drivers.length;
  const worth = signalRanking(answer, sprint ? "sprint" : "race");
  // The inspector: the last car followed in the replay, or the favourite when none is in this field.
  const inspected = [...selected].reverse().map((n) => answer.drivers.find((d) => d.driver_number === n)).find(Boolean)
    ?? [...answer.drivers].sort((a, b) => b.win - a.win)[0];
  return (
    <div className="prediction">
      <div className="prediction-top">
        {switcher}
        <p className="prediction-basis">
          <b>{answer.before_race ? `Made before the ${event}` : `Rebuilt after the ${event}, from what was known before it`}</b>
          {" · "}from {answer.basis.sessions.map((code) => SESSION_NAMES[code] ?? code).join(", ")}
          {answer.basis.form_races.length > 0 && ` and ${answer.basis.form_races.length} earlier races`}
          {" · "}grid from {answer.basis.grid_source === "race" ? "the official starting grid"
            : `${sprint ? "sprint qualifying" : "qualifying"}, penalties not applied`}
        </p>
        <span className="prediction-runs num">{answer.basis.runs.toLocaleString()} simulated {event}s</span>
      </div>

      <KpiRow tiles={predictionTiles(answer, sprint)} />

      <div className="prediction-grid">
        <section className="panel prediction-main" aria-label="Finishing chances">
          <div className="panel-bar"><h2>Finishing chances</h2>
            <span className="panel-meta">click a driver · bar: the likely range if it finishes, mark at the median</span></div>
          <div className="prediction-scroll">
            <div className="prediction-table" role="table" aria-label="Predicted finishing order">
              <div className="prediction-row is-head cap" role="row">
                <span role="columnheader">Pos</span>
                <span role="columnheader" />
                <span role="columnheader">Driver</span>
                <span role="columnheader" className="num">Grid</span>
                <span role="columnheader">Win</span>
                <span role="columnheader">Podium</span>
                <span role="columnheader" title={sprint ? "Finishing in the top eight, who score in a sprint" : "Finishing in the top ten"}>Points</span>
                <span role="columnheader" className="num" title="Average simulated finish, retirements counted at the back">Exp.</span>
                <span role="columnheader" title="If it finishes: 10th to 90th percentile, and the median">Likely range, P1 to P{cars}</span>
                <span role="columnheader" className="num" title="Chance of not finishing">DNF</span>
                {finish && <span role="columnheader" className="num">Actual</span>}
              </div>
              {answer.drivers.map((driver, index) => (
                <Row key={driver.driver_number} driver={driver} position={index + 1} cars={cars}
                     actual={finish ? finish[String(driver.driver_number)] ?? null : undefined}
                     selected={selected.includes(driver.driver_number)} onSelect={onSelect} />
              ))}
            </div>
          </div>
        </section>

        <section className="panel prediction-side" aria-label="Selected driver">
          {inspected && <Inspector driver={inspected} cars={cars} event={event}
                                   actual={finish ? finish[String(inspected.driver_number)] ?? null : undefined} />}
          <div className="inspector-body prediction-side-foot">
            {answer.result && <Scorecard model={answer.result.scores.model} grid={answer.result.scores.grid} />}
            <div className="inspector-how">
              <span className="cap">How this is made</span>
              <ul className="prediction-notes">
                {sprint ? (
                  <li>
                    Each driver's chances come from {answer.basis.runs.toLocaleString()} simulated sprints
                    {answer.basis.laps ? ` of ${answer.basis.laps} laps` : ""}, with no stops. Retirements are drawn
                    at {Math.round(answer.basis.retire_rate * 100)}% a car, the season's rate scaled to the sprint's distance,
                    and safety cars at this circuit's; first-lap incidents, rain and team orders are not modelled.
                  </li>
                ) : (
                  <li>
                    Each driver's chances come from {answer.basis.runs.toLocaleString()} simulated races. Retirements are drawn
                    at {Math.round(answer.basis.retire_rate * 100)}% a car, the season's rate so far, and safety cars at this
                    circuit's; first-lap incidents, rain and team orders are not modelled.
                  </li>
                )}
                <li>
                  What each signal is worth was measured on {sprint ? "the sprints of " : ""}
                  {answer.basis.calibration.fitted_on.join(", ")}{worth ? `: ${worth}` : ""}.
                </li>
                {answer.basis.notes.map((note) => <li key={note}>{note}</li>)}
              </ul>
            </div>
            <WeatherForecast sessionKey={sessionKey} />
          </div>
        </section>
      </div>
    </div>
  );
}

/**
 * One driver's prediction: where it finishes if it finishes (the likely range
 * on the full field), its chances, and the readings its race pace came from.
 */
function Inspector({ driver, cars, event, actual }: {
  driver: PredictionDriver;
  cars: number;
  event: "race" | "sprint";
  actual: number | null | undefined;
}) {
  const at = (p: number) => `${((Math.min(Math.max(p, 1), cars) - 1) / Math.max(cars - 1, 1)) * 100}%`;
  const readings = Object.entries(driver.signals).filter((e): e is [string, number] => e[1] !== null);
  return (
    <>
      <div className="panel-bar inspector-head" style={{ ["--team" as string]: `#${driver.team_color ?? "777"}` }}>
        <span className="team-bar tall" style={{ background: `#${driver.team_color ?? "777"}` }} />
        <div className="inspector-name">
          <span className="card-code">{driver.abbreviation}</span>
          <span className="panel-meta">{driver.team_name ?? ""}{driver.grid < 99 ? ` · from P${driver.grid}` : " · from the pit lane"}</span>
        </div>
        <div className="inspector-pos"><span className="cap">Expected</span><b className="num">P{driver.expected.toFixed(1)}</b></div>
      </div>
      <div className="inspector-body">
        <div className="inspector-block">
          <span className="cap">Where {driver.abbreviation} finishes</span>
          <div className="pred-range" aria-label={`P${driver.p10} to P${driver.p90}, most likely P${driver.p50}`}>
            <span className="pred-range-track" />
            <span className="pred-range-band" style={{ left: at(driver.p10), width: `calc(${at(driver.p90)} - ${at(driver.p10)})` }} />
            <span className="pred-range-mark" style={{ left: at(driver.p50) }} />
            {actual != null && <span className="pred-range-actual num" style={{ left: at(actual) }}>P{actual}</span>}
          </div>
          <div className="race-strip-axis num"><span>P1</span><span>P{cars}</span></div>
          <p className="inspector-note">
            If it finishes: most likely P{driver.p50}, and P{driver.p10} to P{driver.p90} in eight {event}s out of ten.
            {actual !== undefined && (actual === null ? " It did not finish." : ` It finished P${actual}.`)}
          </p>
        </div>
        <div className="inspector-block">
          {([["Win", driver.win], ["Podium", driver.podium], ["Points", driver.points], ["Retires", driver.dnf]] as const).map(([label, value]) => (
            <div key={label} className="stop-bar-row">
              <span>{label}</span>
              <span className="stop-bar"><span style={{ width: `${Math.min(value, 1) * 100}%`, background: label === "Retires" ? "#FF6B6B" : `#${driver.team_color ?? "4C9AFF"}` }} /></span>
              <span className="num right">{percent(value)}</span>
            </div>
          ))}
        </div>
        <div className="inspector-block">
          <span className="cap">What moves it</span>
          <div className="pred-why">
            <span>Race pace against the field's median, a lap</span>
            <span className="num right strong">{signed(driver.pace_s)} s ±{driver.pace_sd.toFixed(2)}</span>
          </div>
          {readings.map(([name, value]) => (
            <div key={name} className="pred-why">
              <span>{SIGNAL_NAMES[name] ?? name}</span><span className="num right">{signed(value)} s</span>
            </div>
          ))}
        </div>
      </div>
    </>
  );
}

function Row({ driver, position, cars, actual, selected, onSelect }: {
  driver: PredictionDriver;
  position: number;
  cars: number;
  actual: number | null | undefined;
  selected: boolean;
  onSelect: (driver: number) => void;
}) {
  const readings = Object.entries(driver.signals)
    .filter(([, value]) => value !== null)
    .map(([name, value]) => `${SIGNAL_NAMES[name] ?? name} ${signed(value as number)}s`)
    .join(" · ");
  const span = Math.max(cars - 1, 1);
  const left = ((driver.p10 - 1) / span) * 100;
  const width = Math.max(((driver.p90 - driver.p10) / span) * 100, 1.5);
  // The median finish if it finishes, so the mark always sits inside the range; the
  // expected position beside it is the average with retirements counted at the back.
  const median = driver.p50 ?? Math.round(driver.expected);
  const mark = ((Math.min(Math.max(median, 1), cars) - 1) / span) * 100;
  return (
    <button type="button" role="row" className={`prediction-row${selected ? " is-selected" : ""}`}
            aria-pressed={selected} onClick={() => onSelect(driver.driver_number)}
            title={`Race pace ${signed(driver.pace_s)}s a lap against the field's median (±${driver.pace_sd.toFixed(2)}).`
                   + (readings ? ` Readings: ${readings}.` : "")}>
      <span role="cell" className="pos">{position}</span>
      <span role="cell" className="team-bar" style={{ background: `#${driver.team_color ?? "555"}` }} />
      <span role="cell" className="code">{driver.abbreviation}</span>
      <span role="cell" className="num">{driver.grid < 99 ? driver.grid : "PL"}</span>
      <Chance value={driver.win} kind="win" />
      <Chance value={driver.podium} kind="podium" />
      <Chance value={driver.points} kind="points" />
      <span role="cell" className="num">{driver.expected.toFixed(1)}</span>
      <span role="cell" className="range" aria-label={`P${driver.p10} to P${driver.p90}, most likely P${median}`}>
        <i style={{ left: `${left}%`, width: `${width}%` }} />
        <b style={{ left: `${mark}%` }} />
        <em>P{driver.p10}–P{driver.p90}</em>
      </span>
      <span role="cell" className="num dnf">{percent(driver.dnf)}</span>
      {actual !== undefined && (
        <span role="cell" className={`num actual${surprise(actual, driver)}`}
              title={actual === null ? undefined : surpriseTitle(actual, driver)}>
          {actual === null ? "—" : `P${actual}`}
        </span>
      )}
    </button>
  );
}

function Chance({ value, kind }: { value: number; kind: string }) {
  return (
    <span role="cell" className={`chance is-${kind}`}>
      <i style={{ width: `${Math.min(value, 1) * 100}%` }} />
      <b>{percent(value)}</b>
    </span>
  );
}

function Scorecard({ model, grid }: { model: PredictionScore; grid: PredictionScore }) {
  const rows: [string, (s: PredictionScore) => string, (a: PredictionScore, b: PredictionScore) => number][] = [
    ["Order (rank correlation)", (s) => s.rho.toFixed(2), (a, b) => a.rho - b.rho],
    ["Winner", (s) => (s.winner_hit ? "right" : "wrong"), (a, b) => Number(a.winner_hit) - Number(b.winner_hit)],
    ["Podium places named", (s) => `${s.podium_hits} of 3`, (a, b) => a.podium_hits - b.podium_hits],
    ["Win chances (Brier, lower is better)", (s) => s.brier_win.toFixed(2), (a, b) => b.brier_win - a.brier_win],
  ];
  const order = model.rho > grid.rho ? "The model ordered the field better than the grid did."
    : model.rho < grid.rho ? "The grid ordered the field better than the model did." : "Model and grid ordered the field as well as each other.";
  const chances = model.brier_win < grid.brier_win ? "The model gave the better win chances."
    : model.brier_win > grid.brier_win ? "The grid gave the better win chances." : "";
  return (
    <section className="score-card" aria-label="How it scored">
    <div className="prediction-score" role="table" aria-label="How the prediction did">
      <div className="score-row is-head" role="row">
        <span role="columnheader">Scored against the result</span>
        <span role="columnheader">Model</span>
        <span role="columnheader" title="Everyone finishes where they started">Grid</span>
      </div>
      {rows.map(([label, show, better]) => {
        const edge = better(model, grid);
        return (
          <div className="score-row" role="row" key={label}>
            <span role="cell">{label}</span>
            <span role="cell" className={`num${edge > 0 ? " is-ahead" : ""}`}>{show(model)}</span>
            <span role="cell" className={`num${edge < 0 ? " is-ahead" : ""}`}>{show(grid)}</span>
          </div>
        );
      })}
    </div>
    <p className="card-note">{order} {chances}</p>
    </section>
  );
}

/**
 * Coloured only when the result fell outside the likely range: inside it, the
 * prediction said as much. A retirement is classified at the back, so it reads
 * as worse unless the range already reached there.
 */
function surprise(actual: number | null, driver: PredictionDriver): string {
  if (actual === null) return "";
  if (actual < driver.p10) return " is-better";
  if (actual > driver.p90) return " is-worse";
  return "";
}

function surpriseTitle(actual: number, driver: PredictionDriver): string {
  if (actual < driver.p10) return `Better than the likely range (P${driver.p10}–P${driver.p90})`;
  if (actual > driver.p90) return `Worse than the likely range (P${driver.p10}–P${driver.p90}), or did not finish`;
  return `Inside the likely range (P${driver.p10}–P${driver.p90})`;
}

function isWeekend(body: unknown): body is WeekendInfo {
  const value = body as WeekendInfo | null;
  return !!value && Array.isArray(value.sessions) && typeof value.sprint === "boolean";
}

/**
 * Which prediction to open on: the sprint from its own sessions, and from
 * earlier in a sprint weekend before the Grand Prix's qualifying has run;
 * otherwise the Grand Prix.
 */
export function openingKind(sessionKey: string, weekend: WeekendInfo): PredictionKind {
  if (!weekend.sprint) return "race";
  const code = sessionKey.split("_")[2] ?? "";
  if (SPRINT_SESSIONS.includes(code)) return "sprint";
  return weekend.sessions.includes("Q") ? "race" : "sprint";
}

/**
 * What the measured weights say, in words: signals ranked by how much each
 * tells (its scale squared over its noise), as the calibration has them.
 */
export function signalRanking(answer: Prediction, kind: PredictionKind): string | null {
  const { scale, noise_sd: noise } = answer.basis.calibration;
  if (!scale || !noise) return null;
  const words = SIGNAL_WORDS[kind];
  const ranked = Object.keys(scale)
    .filter((name) => noise[name] && words[name])
    .sort((a, b) => (scale[b]! / noise[b]!) ** 2 - (scale[a]! / noise[a]!) ** 2)
    .map((name) => words[name]!);
  if (ranked.length < 2) return null;
  if (ranked.length === 2) return `${ranked[0]} counts most, then ${ranked[1]}`;
  return `${ranked[0]} counts most, then ${ranked.slice(1, -1).join(", then ")}; ${ranked[ranked.length - 1]} least`;
}

/** A chance as a whole percent, with "<1%" rather than a misleading 0 for the rare but possible. */
export function percent(value: number): string {
  if (value <= 0) return "—";
  if (value < 0.005) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function signed(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}

/**
 * The prediction's headline figures: the favourite, the closest fight for the win, the car most likely to retire, and how the
 * model has done when replayed over every race (or sprint) since 2023, each
 * predicted only from what was known before it (docs/TECHNICAL.md).
 */
export function predictionTiles(answer: Prediction, sprint: boolean) {
  const [first, second] = [...answer.drivers].sort((a, b) => b.win - a.win);
  const risk = [...answer.drivers].sort((a, b) => b.dnf - a.dnf)[0];
  const third = [...answer.drivers].sort((a, b) => b.win - a.win)[2];
  return [
    first && { label: "Favourite to win", value: `${first.abbreviation} ${percent(first.win)}`,
              note: second ? `then ${second.abbreviation} ${percent(second.win)}${third ? `, ${third.abbreviation} ${percent(third.win)}` : ""}` : "" },
    first && second && { label: "Closest fight", value: `${first.abbreviation} v ${second.abbreviation}`, note: `${percent(first.win)} against ${percent(second.win)} to win` },
    risk && risk.dnf > 0 && { label: "Most likely to retire", value: `${risk.abbreviation} · ${percent(risk.dnf)}`, note: "retirements at the season's rate", tone: "bad" as const },
    sprint
      ? { label: "Held-out accuracy", value: "Brier 0.53 v 0.59", note: "win chances against the grid, every sprint 2023-25" }
      : { label: "Held-out accuracy", value: "0.69 v 0.66", note: "order against the grid, every race 2023-25" },
  ];
}
