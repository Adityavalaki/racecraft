import { useEffect, useState } from "react";
import { api, type Prediction, type PredictionDriver, type PredictionScore } from "../api";

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

/**
 * The race, predicted from before it started.
 *
 * Practice long runs, qualifying, the sprint and the season's earlier races
 * give each driver a race pace and how sure it is; the race simulator then runs
 * the race a thousand times from the real grid, with this circuit's pit lane,
 * overtaking and safety cars, and retirements at the season's rate. What comes
 * back is chances, not a call: who wins most often, and how often.
 *
 * It is saved the first time it is made, once qualifying is in, and never
 * recomputed, so after the race this is what was said on Saturday night, with
 * the result beside it and the same scores the replay of every race since 2023
 * uses, against simply finishing where you started.
 */
export function PredictionBoard({ sessionKey, selected, onSelect }: Props) {
  const [answer, setAnswer] = useState<Prediction | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setAnswer(null);
    setError(null);
    api
      .prediction(sessionKey, controller.signal)
      .then(setAnswer)
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(String(e.message ?? e));
      });
    return () => controller.abort();
  }, [sessionKey]);

  if (error) return <div className="panel-note error">{error}</div>;
  if (!answer) {
    return (
      <div className="panel-note">
        Predicting the race: a thousand simulated races from this weekend's running. About twenty
        seconds the first time; saved after that.
      </div>
    );
  }

  const finish = answer.result?.finish ?? null;
  const cars = answer.drivers.length;
  return (
    <div className="prediction">
      <p className="prediction-basis">
        <b>{answer.before_race ? "Made before the race" : "Rebuilt after the race, from what was known before it"}</b>
        {" · "}from {answer.basis.sessions.map((code) => SESSION_NAMES[code] ?? code).join(", ")}
        {answer.basis.form_races.length > 0 && ` and ${answer.basis.form_races.length} earlier races`}
        {" · "}grid from {answer.basis.grid_source === "race" ? "the official starting grid" : "qualifying, penalties not applied"}
      </p>

      <div className="prediction-table" role="table" aria-label="Predicted finishing order">
        <div className="prediction-row is-head" role="row">
          <span role="columnheader">POS</span>
          <span role="columnheader" />
          <span role="columnheader">DRIVER</span>
          <span role="columnheader" className="num">GRID</span>
          <span role="columnheader">WIN</span>
          <span role="columnheader">PODIUM</span>
          <span role="columnheader">POINTS</span>
          <span role="columnheader" className="num" title="Average simulated finish, retirements counted at the back">EXP</span>
          <span role="columnheader" title="If it finishes: 10th to 90th percentile, and the median">LIKELY RANGE</span>
          <span role="columnheader" className="num" title="Chance of not finishing">DNF</span>
          {finish && <span role="columnheader" className="num">ACTUAL</span>}
        </div>
        {answer.drivers.map((driver, index) => (
          <Row key={driver.driver_number} driver={driver} position={index + 1} cars={cars}
               actual={finish ? finish[String(driver.driver_number)] ?? null : undefined}
               selected={selected.includes(driver.driver_number)} onSelect={onSelect} />
        ))}
      </div>

      {answer.result && <Scorecard model={answer.result.scores.model} grid={answer.result.scores.grid} />}

      <ul className="prediction-notes">
        <li>
          Each driver's chances come from {answer.basis.runs.toLocaleString()} simulated races. Retirements are drawn
          at {Math.round(answer.basis.retire_rate * 100)}% a car, the season's rate so far, and safety cars at this
          circuit's; first-lap incidents, rain and team orders are not modelled.
        </li>
        <li>
          What each signal is worth was measured on {answer.basis.calibration.fitted_on.join(", ")}: recent race
          pace counts most, then qualifying; practice long runs least, since fuel loads are unknown.
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

function Scorecard({ model, grid }: { model: PredictionScore; grid: PredictionScore }) {
  const rows: [string, (s: PredictionScore) => string, (a: PredictionScore, b: PredictionScore) => number][] = [
    ["Order (rank correlation)", (s) => s.rho.toFixed(2), (a, b) => a.rho - b.rho],
    ["Winner", (s) => (s.winner_hit ? "right" : "wrong"), (a, b) => Number(a.winner_hit) - Number(b.winner_hit)],
    ["Podium places named", (s) => `${s.podium_hits} of 3`, (a, b) => a.podium_hits - b.podium_hits],
    ["Win chances (Brier, lower is better)", (s) => s.brier_win.toFixed(2), (a, b) => b.brier_win - a.brier_win],
  ];
  return (
    <div className="prediction-score" role="table" aria-label="How the prediction did">
      <div className="score-row is-head" role="row">
        <span role="columnheader">Against the result</span>
        <span role="columnheader">Prediction</span>
        <span role="columnheader" title="Everyone finishes where they started">Grid order</span>
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

/** A chance as a whole percent, with "<1%" rather than a misleading 0 for the rare but possible. */
export function percent(value: number): string {
  if (value <= 0) return "—";
  if (value < 0.005) return "<1%";
  return `${Math.round(value * 100)}%`;
}

function signed(value: number): string {
  return `${value > 0 ? "+" : value < 0 ? "−" : ""}${Math.abs(value).toFixed(2)}`;
}
