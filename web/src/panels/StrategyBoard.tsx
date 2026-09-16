import { memo } from "react";
import { COMPOUND_COLORS, type Insight, type Plan } from "../api";

interface Props {
  insight: Insight | null;
  loading: boolean;
  error: string | null;
  /** What each car actually did, so the model can be read against the race. */
  actualStops: number | null;
}

/**
 * What the strategy model makes of this circuit, and what it cannot see.
 *
 * The caveats are rendered beside the ranking rather than tucked behind a
 * link, because a plan quoted to a tenth while ignoring traffic and track
 * position invites exactly the confidence it has not earned. The model counts
 * seconds; races are scored in places.
 */
export const StrategyBoard = memo(function StrategyBoard({ insight, loading, error, actualStops }: Props) {
  if (loading) return <div className="panel-note">Fitting the season… this takes a few seconds the first time.</div>;
  if (error) return <div className="panel-note error">{error}</div>;
  if (!insight) return <div className="panel-note">No model for this session.</div>;

  const { pit_loss: pitLoss, safety_car: risk } = insight;
  const best = insight.plans[0];

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
        <div className="plan-table" role="table" aria-label="Cheapest plans">
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
      ) : (
        <p className="panel-note">{insight.plans_unavailable ?? "No plans for this session."}</p>
      )}

      <div className="omissions">
        <h3>This counts seconds, not places. It leaves out:</h3>
        <ul>
          {insight.caveats.map((caveat) => {
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
      <span className="plan-name" role="cell">
        {plan.plan.split(" > ").map((stint, index) => {
          const compound = (stint.split(" ")[0] ?? "").toUpperCase();
          return (
            <span key={index} className="plan-stint">
              <i className="swatch" style={{ background: COMPOUND_COLORS[compound] ?? "#a8b4c1" }} />
              {stint}
            </span>
          );
        })}
        {plan.orders.length > 1 && <em title={plan.orders.join("  ·  ")}>either order</em>}
      </span>
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

function Constant({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="constant">
      <span className="constant-label">{label}</span>
      <span className="constant-value">{value}</span>
      <span className="constant-detail">{detail}</span>
    </div>
  );
}

/** "traffic: a car released into a queue…" -> bold term, plain rest. */
function splitCaveat(caveat: string): [string, string] {
  const at = caveat.indexOf(":");
  return at === -1 ? [caveat, ""] : [caveat.slice(0, at), caveat.slice(at)];
}
