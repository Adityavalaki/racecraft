import { memo, useEffect, useMemo, useState } from "react";
import {
  COMPOUND_COLORS, LIVE_KEY, api,
  type CarPlanChecks, type CarSets, type DriverTiming, type Insight, type TyreSets as TyreSetsAnswer,
} from "../api";
import { PlanName } from "./planParts";

const COMPOUNDS = ["SOFT", "MEDIUM", "HARD"] as const;
/** A live session gains sets as it runs, so it is asked for again. */
const LIVE_REFRESH_MS = 30_000;
/** Within this long of its last lap a car still counts as out on that set. */
const ON_TRACK_GRACE_S = 120;

interface Props {
  sessionKey: string;
  /** Session time the panel describes: the replay clock, as the tower last saw it. */
  t: number;
  /** Running order, for the rows, and team colours. */
  drivers: DriverTiming[];
  /** Selected in the tower; the last one is the car whose plans are checked. */
  selected: number[];
  onSelect: (driverNumber: number) => void;
  insight: Insight | null;
}

export interface SetView {
  set: number;
  laps: number;
  /** On track on this set at the moment shown. */
  fitted: boolean;
  /** Raced although the tracker thought it went back to Pirelli. */
  doubtful: boolean;
}

export interface CompoundView {
  fresh: number;
  used: SetView[];
}

/**
 * One car's sets at session time `t`: what it held at the start, moved on by
 * everything fitted since. A new set becomes a used one when it leaves the pit
 * lane, and its count climbs by one at the end of each lap.
 */
export function carAt(car: CarSets, t: number): Record<string, CompoundView> {
  const out: Record<string, CompoundView> = {};
  const lapsBy = new Map<number, number>();
  let fitted: number | null = null;
  let fittedFrom = -Infinity;

  for (const s of car.this_session) {
    let done = 0;
    for (const run of s.runs) {
      done += run.lap_end_t.filter((end) => end <= t).length;
      const last = run.lap_end_t.length ? Math.max(...run.lap_end_t) : run.start_t ?? -Infinity;
      if (run.start_t !== null && run.start_t <= t && t <= last + ON_TRACK_GRACE_S && run.start_t > fittedFrom) {
        fitted = s.set;
        fittedFrom = run.start_t;
      }
    }
    lapsBy.set(s.set, done);
  }

  for (const compound of COMPOUNDS) {
    const start = car.at_start[compound] ?? { new: 0, used: [] };
    const here = car.this_session.filter((s) => s.compound === compound);
    const opened = here.filter((s) => s.new_at_start && started(s, t));
    const used: SetView[] = start.used.map((held) => ({
      set: held.set,
      laps: held.laps + (lapsBy.get(held.set) ?? 0),
      fitted: fitted === held.set,
      doubtful: false,
    }));
    for (const s of here) {
      if (!started(s, t)) continue;
      if (s.new_at_start || s.thought_returned) {
        used.push({
          set: s.set,
          laps: s.laps_at_start + (lapsBy.get(s.set) ?? 0),
          fitted: fitted === s.set,
          doubtful: s.thought_returned,
        });
      }
    }
    used.sort((a, b) => a.laps - b.laps || a.set - b.set);
    out[compound] = { fresh: Math.max(0, start.new - opened.length), used };
  }
  return out;
}

function started(s: CarSets["this_session"][number], t: number): boolean {
  return s.runs.some((run) => run.start_t !== null && run.start_t <= t);
}

/**
 * Every car's dry tyre sets, moving with the replay.
 *
 * The feed never numbers a set, so everything here is reconstructed: each
 * stint is joined to the set whose lap count it continues, and the sets that go
 * back to Pirelli after each practice session are inferred from Article 30 —
 * how many is the rule, which ones is a guess, and the guesses are marked. A set
 * the tracker had handed back that then appears on a car is drawn as doubtful
 * rather than quietly moved.
 *
 * Selecting a car answers the question the count exists for: can it run the
 * strategy model's plans on what it has, and what do used sets cost it?
 */
export const TyreSets = memo(function TyreSets({ sessionKey, t, drivers, selected, onSelect, insight }: Props) {
  const [answer, setAnswer] = useState<TyreSetsAnswer | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setAnswer(null);
    setError(null);
    const pull = () =>
      api
        .tyreSets(sessionKey, controller.signal)
        .then((next) => {
          setAnswer(next);
          setError(null);
        })
        .catch((e: Error) => {
          if (e.name !== "AbortError") setError(String(e.message ?? e));
        });
    pull();
    const timer = sessionKey === LIVE_KEY ? setInterval(pull, LIVE_REFRESH_MS) : null;
    return () => {
      controller.abort();
      if (timer) clearInterval(timer);
    };
  }, [sessionKey]);

  const order = useMemo(() => {
    const byNumber = new Map(drivers.map((d) => [d.driver_number, d]));
    const cars = answer?.cars ?? [];
    return [...cars].sort((a, b) => {
      const pa = byNumber.get(a.driver_number)?.position ?? 99;
      const pb = byNumber.get(b.driver_number)?.position ?? 99;
      return pa - pb || a.driver_number - b.driver_number;
    });
  }, [answer, drivers]);

  if (error) return <div className="panel-note error">{error}</div>;
  if (!answer) return <div className="panel-note">Following every set through the weekend…</div>;

  const colours = new Map(drivers.map((d) => [d.driver_number, d.team_color]));
  const focus = [...selected].reverse().find((n) => answer.cars.some((c) => c.driver_number === n)) ?? null;
  const focusCar = answer.cars.find((c) => c.driver_number === focus) ?? null;

  return (
    <div className="sets">
      <Rules answer={answer} />

      <div className="sets-table" role="table" aria-label="Dry tyre sets per car">
        <div className="sets-head" role="row">
          <span role="columnheader">car</span>
          {COMPOUNDS.map((c) => (
            <span key={c} role="columnheader">{c.toLowerCase()}</span>
          ))}
          <span role="columnheader" title="handed back to Pirelli before this session">back</span>
        </div>
        {order.map((car) => (
          <CarRow
            key={car.driver_number}
            car={car}
            view={carAt(car, t)}
            colour={colours.get(car.driver_number) ?? null}
            focused={car.driver_number === focus}
            onSelect={onSelect}
          />
        ))}
      </div>

      <Legend />

      {focusCar ? (
        <Focus car={focusCar} checks={insight?.tyre_sets?.cars?.[String(focusCar.driver_number)] ?? null}
               insight={insight} session={answer.session} />
      ) : (
        <p className="panel-note">Select a car to check the strategy model's plans against its tyres.</p>
      )}

      {answer.notes.length > 0 && (
        <ul className="sets-notes">
          {answer.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
});

function Rules({ answer }: { answer: TyreSetsAnswer }) {
  const { rules } = answer;
  const total = Object.values(rules.allocation).reduce((a, b) => a + b, 0);
  const parts = COMPOUNDS.map((c) => `${rules.allocation[c]} ${c.toLowerCase()}`).join(", ");
  const back = rules.returns.map((r) => `${r.sets} after ${r.after}`).join(", ");
  return (
    <p className="sets-rules">
      <b>{rules.name}</b>: {total} dry sets each ({parts}).{" "}
      {rules.hand_backs_known
        ? <>Handed back: {back}{rules.q3_returns_soft ? ", and a soft after qualifying for Q3 cars" : ""}.</>
        : "Hand-backs at this format are not modelled."}{" "}
      Shown at the moment on the clock.
    </p>
  );
}

const CarRow = memo(function CarRow({
  car, view, colour, focused, onSelect,
}: {
  car: CarSets;
  view: Record<string, CompoundView>;
  colour: string | null;
  focused: boolean;
  onSelect: (n: number) => void;
}) {
  const back = car.returned.length + Object.values(car.new_returned).reduce((a, b) => a + b, 0);
  const backTitle = [
    ...car.returned.map((r) => `${r.compound.toLowerCase()}, ${r.laps} laps, after ${r.after}`),
    ...Object.entries(car.new_returned).map(([c, n]) => `${n} new ${c.toLowerCase()} (a guess)`),
  ].join("\n");
  return (
    <div
      className={focused ? "sets-row is-focused" : "sets-row"}
      role="row"
      onClick={() => onSelect(car.driver_number)}
    >
      <span className="sets-driver" role="cell">
        <i style={{ background: colour ? `#${colour}` : "var(--ink-soft)" }} />
        {car.driver}
        {car.stand_ins.length > 0 && <small title={`also driven by ${car.stand_ins.join(", ")}`}>+</small>}
      </span>
      {COMPOUNDS.map((compound) => (
        <SetChips key={compound} compound={compound} view={view[compound]!} />
      ))}
      <span className="sets-back num" role="cell" title={backTitle}>
        {back || "—"}
      </span>
    </div>
  );
});

function SetChips({ compound, view }: { compound: string; view: CompoundView }) {
  const colour = COMPOUND_COLORS[compound] ?? "#888";
  return (
    <span className="set-chips" role="cell" aria-label={`${view.fresh} new ${compound.toLowerCase()}, ${view.used.length} used`}>
      {Array.from({ length: view.fresh }, (_, i) => (
        <i key={`n${i}`} className="chip chip-new" style={{ background: colour }} title="new" />
      ))}
      {view.used.map((s) => (
        <i
          key={s.set}
          className={`chip chip-used${s.fitted ? " is-fitted" : ""}${s.doubtful ? " is-doubtful" : ""}`}
          style={{ borderColor: colour }}
          title={`${s.laps} laps${s.fitted ? " · on the car" : ""}${s.doubtful ? " · the tracker thought this went back" : ""}`}
        >
          {s.laps}
        </i>
      ))}
    </span>
  );
}

function Legend() {
  return (
    <p className="sets-legend">
      <i className="chip chip-new" style={{ background: "var(--ink-soft)" }} /> new
      <i className="chip chip-used" style={{ borderColor: "var(--ink-soft)" }}>4</i> used, laps on it
      <i className="chip chip-used is-fitted" style={{ borderColor: "var(--ink-soft)" }}>4</i> on the car
    </p>
  );
}

function Focus({
  car, checks, insight, session,
}: { car: CarSets; checks: CarPlanChecks | null; insight: Insight | null; session: string }) {
  if (session !== "R") {
    return (
      <p className="panel-note">
        {car.driver}: plans are checked against a car's tyres at the start of the race. Open the race
        to see them.
      </p>
    );
  }
  if (!insight) return <p className="panel-note">Checking {car.driver}'s plans…</p>;
  if (!checks) {
    return <p className="panel-note">{insight.tyre_sets?.unavailable ?? "No plans to check for this race."}</p>;
  }
  return (
    <div className="sets-focus">
      <h3>
        Can {car.driver} run the model's plans? <small>on the sets held at the start of the race</small>
      </h3>
      <div className="plan-table" role="table" aria-label={`Plans for ${car.driver}`}>
        {checks.plans.map((check) => (
          <div key={check.plan} className={check.feasible ? "plan-row sets-check" : "plan-row sets-check is-out"} role="row">
            <PlanName plan={check.plan} orders={[]} />
            <span className="sets-verdict" role="cell">
              {!check.feasible
                ? `can't: ${check.reason}`
                : check.extra_s === 0
                  ? "on new sets"
                  : `+${check.extra_s.toFixed(1)}s · ${usedSummary(check)}`}
            </span>
          </div>
        ))}
      </div>
      <p className="sets-caveat">
        Extra seconds are the wear line carried on from where each used set already is. The feed counts
        out-laps and cool-down laps, so a set from qualifying is fresher than its count and the figure is
        an upper bound.
      </p>
    </div>
  );
}

function usedSummary(check: { stints: { compound: string; set_laps: number }[] }): string {
  return check.stints
    .filter((s) => s.set_laps > 0)
    .map((s) => `${s.compound.toLowerCase()} with ${s.set_laps} laps`)
    .join(", ");
}
