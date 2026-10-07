import { memo } from "react";
import { COMPOUND_COLORS, type DriverTiming } from "../api";
import { PenaltyChip } from "./PenaltyChip";

interface Props {
  drivers: DriverTiming[];
  selected: number[];
  onSelect: (driverNumber: number) => void;
  /** Opens the full timing tower, in its own window. */
  onOpenTower?: () => void;
}

/**
 * The running order beside the map: position, driver, gap, tyre and whether
 * race control has anything against the car. It is the timing tower cut to
 * what reads at a glance; the whole tower (laps, sectors, pits) is a click
 * away in its own window, so the map can have the room.
 *
 * Click a driver to pick them (up to three): they are ringed on the map and
 * get a card on the left.
 */
export const Leaderboard = memo(function Leaderboard({ drivers, selected, onSelect, onOpenTower }: Props) {
  return (
    <div className="leaderboard">
      <div className="leaderboard-head">
        <span>POS</span>
        <span />
        <span>DRIVER</span>
        <span>GAP</span>
        <span>TYRE</span>
        <span title="what race control has said about this car">PEN</span>
      </div>
      <div className="leaderboard-rows">
        {drivers.map((driver) => {
          const isSelected = selected.includes(driver.driver_number);
          return (
            <button
              type="button"
              key={driver.driver_number}
              className={`leaderboard-row${isSelected ? " is-selected" : ""}${driver.status === "out" ? " is-out" : ""}`}
              onClick={() => onSelect(driver.driver_number)}
              aria-pressed={isSelected}
            >
              <span className="pos">{driver.position}</span>
              <span className="team-bar" style={{ background: `#${driver.team_color ?? "555"}` }} />
              <span className="code">{driver.abbreviation ?? driver.driver_number}</span>
              <span className="num gap">
                {driver.status === "out" ? "OUT" : driver.gap_text || (driver.position === 1 ? "LEADER" : "—")}
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
        <button type="button" className="open-feature" onClick={onOpenTower}>
          Full timing tower ↗
        </button>
      )}
    </div>
  );
});
