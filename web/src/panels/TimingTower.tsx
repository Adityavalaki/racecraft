import { memo } from "react";
import { COMPOUND_COLORS, formatLapTime, formatSector, type DriverTiming } from "../api";
import { PenaltyChip } from "./PenaltyChip";

interface Props {
  drivers: DriverTiming[];
  selected: number[];
  onSelect: (driverNumber: number) => void;
}

/**
 * The timing tower. Order, gap, interval, best lap, last lap, sectors, tyre.
 *
 * Colour carries meaning and nothing else: purple is the session's fastest
 * lap, shown in BEST against the car that holds it; green in LAST is a lap that
 * was the driver's own best when it was set. LAST is never purple, so the
 * fastest lap is read in one place. The tyre chip uses Pirelli's compound
 * colours. Team colour is a bar, never text, so it never fights the numbers.
 *
 * "Fastest" means fastest as of the clock's time: BEST takes the server's
 * `is_session_best`, which is worked out at `t`, so scrubbing back never shows
 * a lap set later in the session as the one to beat.
 *
 * PEN is what race control has said about the car as of the clock's current
 * time, which is the same `t` the gap beside it was computed at — so the two can
 * never describe different moments, however the clock got here.
 */
export const TimingTower = memo(function TimingTower({ drivers, selected, onSelect }: Props) {
  return (
    <div className="tower">
      <div className="tower-head">
        <span>POS</span>
        <span />
        <span>DRIVER</span>
        <span>GAP</span>
        <span>INT</span>
        <span title="the car's fastest lap so far; purple if it is the session's fastest">BEST</span>
        <span>LAST</span>
        <span>S1</span>
        <span>S2</span>
        <span>S3</span>
        <span>TYRE</span>
        <span>PIT</span>
        <span title="what race control has said about this car">PEN</span>
      </div>
      <div className="tower-rows">
        {drivers.map((driver) => {
          const isSelected = selected.includes(driver.driver_number);
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
              <span className="num gap">
                {driver.status === "out" ? "OUT" : driver.gap_text || (driver.position === 1 ? "LEADER" : "—")}
              </span>
              <span className="num int">{driver.interval_text}</span>
              <span className={`num best${driver.is_session_best ? " is-session-best" : ""}`}>
                {formatLapTime(driver.best_lap_s)}
              </span>
              <span className={`num last${driver.is_personal_best ? " is-personal-best" : ""}`}>
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
              <PenaltyChip against={driver.penalties} />
            </button>
          );
        })}
      </div>
    </div>
  );
});
