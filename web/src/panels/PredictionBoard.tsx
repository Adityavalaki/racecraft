import { useEffect, useState } from "react";
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
  return (
    <div className="prediction">
      {switcher}
      <p className="prediction-basis">
        <b>{answer.before_race ? `Made before the ${event}` : `Rebuilt after the ${event}, from what was known before it`}</b>
        {" · "}from {answer.basis.sessions.map((code) => SESSION_NAMES[code] ?? code).join(", ")}
        {answer.basis.form_races.length > 0 && ` and ${answer.basis.form_races.length} earlier races`}
        {" · "}grid from {answer.basis.grid_source === "race" ? "the official starting grid"
          : `${sprint ? "sprint qualifying" : "qualifying"}, penalties not applied`}
      </p>

      <Headline answer={answer} event={event} />

      <div className="prediction-table" role="table" aria-label="Predicted finishing order">
        <div className="prediction-row is-head" role="row">
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

/**
 * The race in three cards: the favourite and how often they win, the podium
 * chances, and (after the race) how the prediction scored against the grid.
 */
function Headline({ answer, event }: { answer: Prediction; event: "race" | "sprint" }) {
  const favourite = [...answer.drivers].sort((a, b) => b.win - a.win)[0];
  const podium = [...answer.drivers].sort((a, b) => b.podium - a.podium).slice(0, 4);
  if (!favourite) return null;
  const segments = 20;
  const lit = Math.round(favourite.win * segments);
  return (
    <div className="prediction-cards">
      <section className="panel favourite" aria-label="Favourite">
        <span className="card-label">Favourite to win</span>
        <div className="favourite-name">
          <span className="team-bar tall" style={{ background: `#${favourite.team_color ?? "777"}` }} />
          <span className="display">{favourite.abbreviation}</span>
          <span className="favourite-team">{favourite.team_name ?? ""}{favourite.grid < 99 ? ` · from P${favourite.grid}` : ""}</span>
        </div>
        <div className="favourite-chance display">{Math.round(favourite.win * 100)}<small>%</small></div>
        <div className="segments" aria-hidden="true">
          {Array.from({ length: segments }, (_, k) => <span key={k} className={k < lit ? "is-lit" : ""} />)}
        </div>
        <span className="card-note">Wins {percent(favourite.win)} of {answer.basis.runs.toLocaleString()} simulated {event}s.</span>
      </section>
      <section className="panel podium-card" aria-label="Podium chances">
        <span className="card-label">Podium chances</span>
        {podium.map((d) => (
          <div key={d.driver_number} className="podium-row">
            <span className="team-bar tall" style={{ background: `#${d.team_color ?? "777"}` }} />
            <span className="display">{d.abbreviation}</span>
            <span className="podium-bar"><i style={{ width: `${d.podium * 100}%` }} /></span>
            <span className="num">{percent(d.podium)}</span>
          </div>
        ))}
      </section>
      {answer.result ? <Scorecard model={answer.result.scores.model} grid={answer.result.scores.grid} />
        : (
          <section className="panel score-card" aria-label="How it scored">
            <span className="card-label">Scored against the result</span>
            <p className="card-note">After the {event}, the result goes beside each driver and the prediction is scored against the grid.</p>
          </section>
        )}
    </div>
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
    <section className="panel score-card" aria-label="How it scored">
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
