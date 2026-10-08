import { memo } from "react";
import { COMPOUND_COLORS, type DriverTiming } from "../api";
import { PenaltyChip } from "./PenaltyChip";

interface Props {
  drivers: DriverTiming[];
  selected: number[];
  onSelect: (driverNumber: number) => void;
  /** Goes to the full timing tower. */
  onOpenTower?: () => void;
  lap?: number;
}

/**
 * The running order beside the map: position, driver, gap, interval, tyre and
 * whether race control has anything against the car. It is the timing tower
 * cut to what reads at a glance; the whole tower (laps, sectors, pits) is its
 * own screen.
 *
 * An interval in the overtake colour is a car close enough to the one ahead
 * for overtake mode (2026 on), estimated from the timing gap.
 *
 * Click a driver to follow them (up to two): they are tagged on the map and
 * get a card under it.
 */
export const Leaderboard = memo(function Leaderboard({ drivers, selected, onSelect, onOpenTower, lap }: Props) {
  return (
    <div className="leaderboard">
      <div className="panel-bar">
        <h2>Timing tower</h2>
        {lap != null && <span className="panel-meta num">Lap {lap}</span>}
      </div>
      <div className="leaderboard-head">
        <span>Pos</span>
        <span />
        <span>Driver</span>
        <span>Gap</span>
        <span>Int</span>
        <span>Tyre</span>
        <span title="What race control has said about this car">Pen</span>
      </div>
      <div className="leaderboard-rows">
        {drivers.map((driver) => {
          const isSelected = selected.includes(driver.driver_number);
          const eligible = driver.overtake === "eligible";
          return (
            <button
              type="button"
              key={driver.driver_number}
              className={`leaderboard-row${isSelected ? " is-selected" : ""}${driver.status === "out" ? " is-out" : ""}`}
              onClick={() => onSelect(driver.driver_number)}
              aria-pressed={isSelected}
            >
              <span className="pos-chip num">{driver.position}</span>
              <span className="team-bar" style={{ background: `#${driver.team_color ?? "555"}` }} />
              <span className="code display">{driver.abbreviation ?? driver.driver_number}</span>
              <span className="num gap">
                {driver.status === "out" ? "OUT" : driver.gap_text || (driver.position === 1 ? "LEADER" : "—")}
              </span>
              <span className={`num int${eligible ? " is-eligible" : ""}`}
                    title={eligible ? "Overtake eligible, estimated from the timing gap" : undefined}>
                {driver.position === 1 ? "" : driver.interval_text}
              </span>
              <span className="tyre">
                {driver.compound ? (
                  <span className="tyre-chip" style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}
                        title={`${driver.compound}${driver.tyre_life != null ? `, ${driver.tyre_life} laps old` : ""}`}>
                    {driver.compound[0]}
                  </span>
                ) : <span className="tyre-age">—</span>}
              </span>
              <PenaltyChip against={driver.penalties} />
            </button>
          );
        })}
      </div>
      {onOpenTower && (
        <div className="leaderboard-foot">
          <button type="button" className="button-secondary" onClick={onOpenTower}>Full timing tower</button>
        </div>
      )}
    </div>
  );
});
