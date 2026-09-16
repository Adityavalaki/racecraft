import { memo } from "react";
import { COMPOUND_COLORS, type DriverStints, type StintRun } from "../api";

interface Props {
  stints: DriverStints[];
  totalLaps: number | null;
  /** The model's cheapest plan, drawn on the same scale for comparison. */
  modelStints: StintRun[] | null;
  modelLabel: string;
}

/**
 * What every car actually ran, against what the model would have run.
 *
 * This is the panel that keeps the rest of the strategy tab honest. A ranking
 * of plans in seconds is easy to believe; the same ranking drawn against
 * twenty real strategies on the same lap scale shows immediately whether the
 * model is describing this sport or a tidier one. Where the model's bar is the
 * odd one out, it is wrong, and no amount of decimal places changes that.
 *
 * Drivers are ordered by how many stops they made, so the field's split — the
 * one-stoppers against the two — reads at a glance rather than by counting.
 */
export const StintChart = memo(function StintChart({ stints, totalLaps, modelStints, modelLabel }: Props) {
  if (stints.length === 0) return null;

  const laps = totalLaps ?? Math.max(...stints.map((d) => lastLap(d.stints)));
  if (laps <= 0) return null;

  const ordered = [...stints].sort((a, b) => a.stops - b.stops || a.driver.localeCompare(b.driver));

  return (
    <div className="stint-chart">
      <h3>
        What the field ran <small>{stints.length} cars · {laps} laps</small>
      </h3>

      {modelStints && (
        <div className="stint-row is-model">
          <span className="stint-driver">MODEL</span>
          <span className="stint-bars" title={modelLabel}>
            {modelStints.map((stint, index) => (
              <Bar key={index} stint={stint} laps={laps} />
            ))}
          </span>
        </div>
      )}

      {ordered.map((driver) => (
        <div className="stint-row" key={driver.driver_number}>
          <span className="stint-driver">{driver.driver}</span>
          <span className="stint-bars">
            {driver.stints.map((stint, index) => (
              <Bar key={index} stint={stint} laps={laps} />
            ))}
          </span>
        </div>
      ))}

      <div className="stint-axis" aria-hidden="true">
        <span>1</span>
        <span>{Math.round(laps / 2)}</span>
        <span>{laps}</span>
      </div>
    </div>
  );
});

function Bar({ stint, laps }: { stint: StintRun; laps: number }) {
  const width = (stint.laps / laps) * 100;
  return (
    <i
      className="stint-bar"
      style={{
        width: `${width}%`,
        background: COMPOUND_COLORS[stint.compound] ?? "#a8b4c1",
      }}
      title={`${stint.compound.toLowerCase()} · laps ${stint.first_lap}–${stint.last_lap} (${stint.laps})`}
    >
      {width > 9 && <b>{stint.laps}</b>}
    </i>
  );
}

function lastLap(stints: StintRun[]): number {
  return stints.length === 0 ? 0 : (stints[stints.length - 1]?.last_lap ?? 0);
}
