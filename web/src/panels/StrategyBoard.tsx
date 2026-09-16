import { memo, useState } from "react";
import { COMPOUND_COLORS, type Insight, type Plan, type RiskyPlan, type StintRun } from "../api";
import { StintChart } from "./StintChart";

interface Props {
  insight: Insight | null;
  loading: boolean;
  error: string | null;
  /** What each car actually did, so the model can be read against the race. */
  actualStops: number | null;
}

type Mode = "green" | "risk";

/**
 * What the strategy model makes of this circuit, and what it cannot see.
 *
 * Two rankings, because they answer different questions rather than one
 * refining the other. *If green* is the arithmetic: tyres plus pit lane, no
 * luck. *Expected* simulates races that can be neutralised, where a stop costs
 * 61% of a green one — which usually rewards a longer first stint, since more
 * laps remain in which a cheap stop can arrive.
 *
 * The caveats sit beside the ranking rather than behind a link. A plan quoted
 * to a tenth while ignoring traffic and track position invites exactly the
 * confidence it has not earned: the model counts seconds, races are scored in
 * places.
 */
export const StrategyBoard = memo(function StrategyBoard({ insight, loading, error, actualStops }: Props) {
  const [mode, setMode] = useState<Mode>("green");

  if (loading) return <div className="panel-note">Fitting the season… this takes a few seconds the first time.</div>;
  if (error) return <div className="panel-note error">{error}</div>;
  if (!insight) return <div className="panel-note">No model for this session.</div>;

  const { pit_loss: pitLoss, safety_car: risk } = insight;
  const riskAvailable = insight.plans_with_risk.length > 0;
  const showRisk = mode === "risk" && riskAvailable;
  const best = showRisk ? insight.plans_with_risk[0] : insight.plans[0];

  return (
    <div className="strategy">
      <div className="constants">
        <Constant
          label="Pit lane"
          value={pitLoss ? `${pitLoss.seconds.toFixed(1)}s` : "—"}
          detail={pitLoss ? `±${pitLoss.spread_s.toFixed(1)} · ${pitLoss.stops} stops` : "too few green stops"}
        />
        <Constant
          label="Safety car"
          value={risk ? risk.probability.toFixed(2) : "—"}
          detail={risk ? `${risk.races} races · ${risk.median_laps_lost.toFixed(1)} laps` : "one season only"}
        />
        <Constant
          label="Distance"
          value={insight.total_laps ? `${insight.total_laps}` : "—"}
          detail="laps"
        />
        <Constant
          label="Model says"
          value={best ? `${best.stops} stop${best.stops === 1 ? "" : "s"}` : "—"}
          detail={actualStops === null ? "cheapest plan" : `race ran ${actualStops.toFixed(2)} avg`}
        />
      </div>

      {insight.plans.length > 0 ? (
        <>
          <div className="mode-switch" role="radiogroup" aria-label="How plans are costed">
            <button
              type="button"
              role="radio"
              aria-checked={!showRisk}
              className={!showRisk ? "mode is-active" : "mode"}
              onClick={() => setMode("green")}
            >
              If green
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={showRisk}
              className={showRisk ? "mode is-active" : "mode"}
              onClick={() => setMode("risk")}
              disabled={!riskAvailable}
            >
              Expected, with safety cars
            </button>
          </div>

          {showRisk ? (
            <div className="plan-table" role="table" aria-label="Plans costed with safety cars">
              <div className="plan-head plan-head-risk" role="row">
                <span role="columnheader">plan</span>
                <span role="columnheader">stop</span>
                <span role="columnheader">expected</span>
                <span role="columnheader">if green</span>
                <span role="columnheader">cheap stop</span>
              </div>
              {insight.plans_with_risk.map((plan) => (
                <RiskRow key={plan.plan} plan={plan} />
              ))}
            </div>
          ) : (
            <div className="plan-table" role="table" aria-label="Plans costed on a green race">
              <div className="plan-head" role="row">
                <span role="columnheader">plan</span>
                <span role="columnheader">stop</span>
                <span role="columnheader">cost</span>
                <span role="columnheader">where it goes</span>
              </div>
              {insight.plans.map((plan) => (
                <PlanRow key={plan.plan} plan={plan} worst={insight.plans[insight.plans.length - 1]!} />
              ))}
            </div>
          )}
        </>
      ) : (
        <p className="panel-note">{insight.plans_unavailable ?? "No plans for this session."}</p>
      )}

      <StintChart
        stints={insight.stints}
        totalLaps={insight.total_laps}
        modelStints={best ? planToStints(best.plan) : null}
        modelLabel={best ? best.plan : ""}
      />

      <div className="omissions">
        <h3>
          {showRisk
            ? "Safety cars are modelled. Still missing:"
            : "This counts seconds, not places. It leaves out:"}
        </h3>
        <ul>
          {insight.caveats
            .filter((caveat) => !(showRisk && caveat.startsWith("safety cars")))
            .map((caveat) => {
              const [term, rest] = splitCaveat(caveat);
              return (
                <li key={caveat}>
                  <b>{term}</b>
                  {rest}
                </li>
              );
            })}
        </ul>
      </div>
    </div>
  );
});

function PlanRow({ plan, worst }: { plan: Plan; worst: Plan }) {
  const span = Math.max(1, worst.seconds_lost);
  return (
    <div className="plan-row" role="row">
      <PlanName plan={plan.plan} orders={plan.orders} />
      <span className="plan-stop num" role="cell">
        {plan.stop_laps.join(", ") || "—"}
      </span>
      <span className="plan-cost num" role="cell">
        {plan.behind_best_s === 0 ? "best" : `+${plan.behind_best_s.toFixed(1)}s`}
      </span>
      <span className="plan-bar" role="cell" aria-label={`${plan.seconds_lost.toFixed(1)} seconds lost`}>
        <i className="bar-tyre" style={{ width: `${(plan.tyre_seconds / span) * 100}%` }} title="tyres" />
        <i className="bar-pit" style={{ width: `${(plan.pit_seconds / span) * 100}%` }} title="pit lane" />
        <b>{plan.seconds_lost.toFixed(1)}s</b>
      </span>
    </div>
  );
}

function RiskRow({ plan }: { plan: RiskyPlan }) {
  const saved = plan.green_s - plan.expected_s;
  return (
    <div className="plan-row plan-row-risk" role="row">
      <PlanName plan={plan.plan} orders={[]} />
      <span className="plan-stop num" role="cell">
        {plan.stop_laps.join(", ") || "—"}
      </span>
      <span className="plan-cost num" role="cell">
        {plan.behind_best_s === 0 ? "best" : `+${plan.behind_best_s.toFixed(1)}s`}
      </span>
      <span className="plan-green num" role="cell" title={`${plan.expected_s.toFixed(1)}s expected`}>
        {plan.green_s.toFixed(1)}
        <em>{saved >= 0.05 ? `−${saved.toFixed(1)}` : ""}</em>
      </span>
      <span className="plan-cheap" role="cell" aria-label={`${Math.round(plan.cheap_stop_share * 100)} percent`}>
        <i style={{ width: `${plan.cheap_stop_share * 100}%` }} />
        <b>{Math.round(plan.cheap_stop_share * 100)}%</b>
      </span>
    </div>
  );
}

function PlanName({ plan, orders }: { plan: string; orders: string[] }) {
  return (
    <span className="plan-name" role="cell">
      {plan.split(" > ").map((stint, index) => {
        const compound = (stint.split(" ")[0] ?? "").toUpperCase();
        return (
          <span key={index} className="plan-stint">
            <i className="swatch" style={{ background: COMPOUND_COLORS[compound] ?? "#a8b4c1" }} />
            {stint}
          </span>
        );
      })}
      {orders.length > 1 && <em title={orders.join("  ·  ")}>either order</em>}
    </span>
  );
}

function Constant({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="constant">
      <span className="constant-label">{label}</span>
      <span className="constant-value">{value}</span>
      <span className="constant-detail">{detail}</span>
    </div>
  );
}

/**
 * "soft 25 > medium 26" -> stints on the same shape the race data uses, so the
 * model's plan can be drawn on the same scale as what the cars actually ran.
 */
function planToStints(plan: string): StintRun[] {
  let lap = 1;
  return plan.split(" > ").map((part) => {
    const [compound = "", length = "0"] = part.split(" ");
    const laps = Number(length) || 0;
    const stint = { compound: compound.toUpperCase(), laps, first_lap: lap, last_lap: lap + laps - 1 };
    lap += laps;
    return stint;
  });
}

/** "traffic: a car released into a queue…" -> bold term, plain rest. */
function splitCaveat(caveat: string): [string, string] {
  const at = caveat.indexOf(":");
  return at === -1 ? [caveat, ""] : [caveat.slice(0, at), caveat.slice(at)];
}
