import { COMPOUND_COLORS } from "../api";

/*
 * Pieces the two plan views share, so a plan reads the same way whether it was
 * ranked in seconds or in places.
 */

export function PlanName({ plan, orders }: { plan: string; orders: string[] }) {
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

export /** "traffic: a car released into a queue…" -> bold term, plain rest. */
function splitCaveat(caveat: string): [string, string] {
  const at = caveat.indexOf(":");
  return at === -1 ? [caveat, ""] : [caveat.slice(0, at), caveat.slice(at)];
}

/** What a ranking cannot see, set beside it rather than behind a link. */
export function Omissions({ heading, items }: { heading: string; items: string[] }) {
  return (
    <div className="omissions">
      <h3>{heading}</h3>
      <ul>
        {items.map((item) => {
          const [term, rest] = splitCaveat(item);
          return (
            <li key={item}>
              <b>{term}</b>
              {rest}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
