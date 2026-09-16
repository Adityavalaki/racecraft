import { memo } from "react";
import { COMPOUND_COLORS, formatLapTime, formatSector, type DriverTiming } from "../api";

interface Props {
  drivers: DriverTiming[];
  selected: number[];
  onSelect: (driverNumber: number) => void;
  sessionBest: number | null;
}

/**
 * The timing tower. Order, gap, interval, last lap, tyre.
 *
 * Colour carries meaning and nothing else: purple is the session's fastest
 * lap, green a driver's own best, and the tyre chip uses Pirelli's compound
 * colours. Team colour is a bar, never text, so it never fights the numbers.
 */
export const TimingTower = memo(function TimingTower({ drivers, selected, onSelect, sessionBest }: Props) {
  return (
    <div className="tower">
      <div className="tower-head">
        <span>POS</span>
        <span />
        <span>DRIVER</span>
        <span className="num">GAP</span>
        <span className="num">INT</span>
        <span className="num">LAST LAP</span>
        <span className="num">S1</span>
        <span className="num">S2</span>
        <span className="num">S3</span>
        <span>TYRE</span>
        <span className="num">PIT</span>
      </div>
      <div className="tower-rows">
        {drivers.map((driver) => {
          const isSelected = selected.includes(driver.driver_number);
          const lastIsSessionBest =
            driver.last_lap_s !== null && sessionBest !== null && driver.last_lap_s <= sessionBest;
          return (
            <button
              key={driver.driver_number}
              className={`tower-row${isSelected ? " is-selected" : ""}${
                driver.status === "out" ? " is-out" : ""
              }`}
              onClick={() => onSelect(driver.driver_number)}
              aria-pressed={isSelected}
            >
              <span className="pos">{driver.position}</span>
              <span className="team-bar" style={{ background: `#${driver.team_color ?? "555"}` }} />
              <span className="code">{driver.abbreviation ?? driver.driver_number}</span>
              <span className="num gap">{driver.status === "out" ? "OUT" : driver.gap_text || "LEADER"}</span>
              <span className="num int">{driver.interval_text}</span>
              <span
                className={`num last${lastIsSessionBest ? " is-session-best" : driver.is_personal_best ? " is-personal-best" : ""}`}
              >
                {formatLapTime(driver.last_lap_s)}
              </span>
              {[1, 2, 3].map((number) => {
                const sector = driver.sectors?.find((s) => s.sector === number);
                return (
                  <span key={number} className={`num sector is-${sector?.state ?? "none"}`}>
                    {formatSector(sector?.seconds)}
                  </span>
                );
              })}
              <span className="tyre">
                {driver.compound ? (
                  <>
                    <span
                      className="tyre-chip"
                      style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}
                      title={driver.compound}
                    >
                      {driver.compound[0]}
                    </span>
                    <span className="tyre-age">{driver.tyre_life ?? "—"}</span>
                  </>
                ) : (
                  <span className="tyre-age">—</span>
                )}
              </span>
              <span className="num stops">{driver.stops}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
});
