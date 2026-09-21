import { useEffect, useState } from "react";
import { api, type PlacesAnswer, type PlaceRow, type TyreStock } from "../api";
import { Omissions, PlanName } from "./planParts";

interface Props {
  sessionKey: string;
}

const GRID_SLOTS = Array.from({ length: 20 }, (_, index) => index + 1);
const DEFAULT_GRID = 8;

/**
 * Plans ranked by where they finish, not by how many seconds they lose.
 *
 * The other two views count seconds: tyres and pit lane, then the same with
 * safety cars. This one races each plan against the whole field — cars losing
 * time in each other's wake, passing only as often as this circuit allows — and
 * ranks by finishing position. It is the only view that can see a plan two
 * seconds quicker rejoining behind a car it cannot pass.
 *
 * It races the tyres the car had. The sets a car still held at the start of a
 * race are known from the weekend's earlier sessions, so the study stays held
 * out, and a plan it had no sets for is dropped rather than recommended. *New
 * sets* switches to the ideal case, which is what the difference between the
 * two is for.
 *
 * Three things on screen are there so that it cannot oversell itself. Plans
 * whose finishes cannot be told apart at these run counts are marked tied rather
 * than ranked. Every figure is held out: for a race that has happened, the model
 * was fitted only on races that started before it, and the panel says which.
 * And the headline is not "the best plan" but what track position costs — the
 * cheapest plan that is as good as the best, against the cheapest plan outright.
 *
 * It takes half a minute the first time for each race and grid slot, so it is
 * asked for only when this view is opened.
 */
export function PlacesBoard({ sessionKey }: Props) {
  const [grid, setGrid] = useState(DEFAULT_GRID);
  const [tyres, setTyres] = useState<"car" | "new">("car");
  const [answer, setAnswer] = useState<PlacesAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    api
      .places(sessionKey, grid, tyres, controller.signal)
      .then((next) => {
        setAnswer(next);
        setLoading(false);
      })
      .catch((e: Error) => {
        if (e.name === "AbortError") return;
        setError(String(e.message ?? e));
        setLoading(false);
      });
    return () => controller.abort();
  }, [sessionKey, grid, tyres]);

  return (
    <div className="places">
      <div className="places-controls">
        <label htmlFor="places-grid">Starting from</label>
        <select
          id="places-grid"
          value={grid}
          onChange={(event) => setGrid(Number(event.target.value))}
        >
          {GRID_SLOTS.map((slot) => (
            <option key={slot} value={slot}>
              P{slot}
            </option>
          ))}
        </select>

        <span className="places-tyres" role="radiogroup" aria-label="Which tyres the car races">
          <button
            type="button"
            role="radio"
            aria-checked={tyres === "car"}
            className={tyres === "car" ? "mode is-active" : "mode"}
            onClick={() => setTyres("car")}
          >
            Its own tyres
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={tyres === "new"}
            className={tyres === "new" ? "mode is-active" : "mode"}
            onClick={() => setTyres("new")}
          >
            New sets
          </button>
        </span>
      </div>

      {loading && (
        <p className="panel-note">
          Racing each plan against the field a few hundred times… about half a minute the first
          time for each grid slot.
        </p>
      )}
      {!loading && error && <p className="panel-note error">{error}</p>}
      {!loading && !error && answer && <Answer answer={answer} />}
    </div>
  );
}

function Answer({ answer }: { answer: PlacesAnswer }) {
  const { inputs, study, verdict } = answer;
  const [low, high] = study.field_stop_window;
  const cutoff = inputs.cutoff ? new Date(inputs.cutoff) : null;

  return (
    <>
      <p className="places-scope">
        {inputs.held_out && cutoff
          ? `Fitted only on races before ${cutoff.toLocaleDateString(undefined, {
              day: "numeric", month: "short", year: "numeric",
            })} — none of this race, nor anything after it.`
          : "Not run yet this season, so every race that has finished is used."}{" "}
        The rest of the field stops between laps {low} and {high}, redrawn {study.field_draws}{" "}
        times so that no one guess about them decides this.
      </p>

      {answer.stock ? (
        <Garage stock={answer.stock} dropped={study.dropped} />
      ) : (
        <p className="places-scope">
          Every stint starts on a new set. {answer.tyres === "new"
            ? "That is the ideal case; “its own tyres” races what the car actually had left."
            : "The sets this car had are not in the lake, so they cannot be raced."}
        </p>
      )}

      <div className="plan-table" role="table" aria-label="Plans ranked by where they finish">
        <div className="plan-head plan-head-places" role="row">
          <span role="columnheader">plan</span>
          <span role="columnheader">stop</span>
          <span role="columnheader">expected</span>
          <span role="columnheader" title="laps on the set each stint starts on">sets</span>
          <span role="columnheader">finish</span>
          <span role="columnheader">behind</span>
          <span role="columnheader">points</span>
        </div>
        {study.plans.map((row) => (
          <PlaceRowView key={row.plan} row={row} />
        ))}
      </div>

      <div className="places-verdict">
        {verdict.price ? (
          <p>
            <b>{verdict.price.plan}</b> is as good as the best in places and costs{" "}
            <b>{verdict.price.extra_seconds.toFixed(1)}s</b> more than {verdict.price.instead_of},
            for <b>{verdict.price.places_gained.toFixed(2)} places</b>. That is the price of track
            position here.
          </p>
        ) : verdict.cheapest_in_seconds === verdict.best_in_places ? (
          <p>The seconds model and the places model agree on the best plan here.</p>
        ) : (
          <p>
            A different plan tops this ranking, but {verdict.cheapest_in_seconds} is inside its
            error bar. On this evidence the two models agree.
          </p>
        )}
        {verdict.bad_plan && (
          <p>
            Where they really differ is how bad a bad plan is: <b>{verdict.bad_plan.plan}</b> costs{" "}
            {verdict.bad_plan.extra_seconds.toFixed(1)}s more in seconds and{" "}
            <b>{verdict.bad_plan.places_lost.toFixed(2)} places</b> more here.
          </p>
        )}
        {inputs.notes.map((note) => (
          <p key={note} className="places-note">
            {note}
          </p>
        ))}
      </div>

      <Omissions heading="Traffic and track position are modelled. Still missing:" items={answer.omissions} />
    </>
  );
}

/** What the car has in the garage, and the plans that rules out. */
function Garage({ stock, dropped }: { stock: TyreStock; dropped: { plan: string; reason: string }[] }) {
  const held = Object.entries(stock.left)
    .map(([compound, held]) => {
      const parts = [];
      if (held.new) parts.push(`${held.new} new`);
      if (held.used.length) parts.push(`${held.used.join(", ")} laps`);
      return parts.length ? `${compound.toLowerCase()}: ${parts.join(" · ")}` : null;
    })
    .filter(Boolean);
  return (
    <p className="places-scope places-garage">
      Racing <b>{stock.driver}</b>&rsquo;s own tyres, as they were at the start
      {stock.grid ? ` from P${stock.grid}` : ""} — {stock.sets} sets: {held.join("; ")}.
      {dropped.length > 0 && (
        <>
          {" "}
          Ruled out: {dropped.map((d) => `${d.plan} (${d.reason})`).join("; ")}.
        </>
      )}
      {stock.notes.map((note) => (
        <span key={note} className="places-note"> {note}</span>
      ))}
    </p>
  );
}

function PlaceRowView({ row }: { row: PlaceRow }) {
  return (
    <div className={`plan-row plan-row-places${row.within_noise ? " is-tied" : ""}`} role="row">
      <PlanName plan={row.plan} orders={[]} />
      <span className="plan-stop num" role="cell">
        {row.stop_laps.join(", ") || "—"}
      </span>
      <span className="plan-green num" role="cell">
        {row.expected_s !== undefined ? `${row.expected_s.toFixed(1)}s` : "—"}
      </span>
      <span className="plan-sets" role="cell">
        {row.on_used_sets
          ? row.start_ages.map((age) => (age === 0 ? "new" : `${age}`)).join(" · ")
          : ""}
      </span>
      <span className="plan-finish num" role="cell" title={`${row.best}–${row.worst} across all runs`}>
        P{row.mean_finish.toFixed(2)}
        <em>±{row.std_error.toFixed(2)}</em>
      </span>
      <span className="plan-cost num" role="cell">
        {row.behind_best === 0 ? "best" : `+${row.behind_best.toFixed(2)}`}
        {row.within_noise && row.behind_best > 0 && <i className="tied">tied</i>}
      </span>
      <span className="plan-green num" role="cell">
        {Math.round(row.points_share * 100)}%
      </span>
    </div>
  );
}
