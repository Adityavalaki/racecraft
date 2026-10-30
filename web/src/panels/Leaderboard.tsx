import { memo, useState } from "react";
import { COMPOUND_COLORS, formatSector, type DriverTiming, type SectorTime } from "../api";
import { PenaltyChip } from "./PenaltyChip";

interface Props {
  drivers: DriverTiming[];
  selected: number[];
  onSelect: (driverNumber: number) => void;
  /** Goes to the full timing tower. */
  onOpenTower?: () => void;
  /** The leader's lap: the session bar shows it, so the tower no longer does. */
  lap?: number;
}

type View = "tower" | "sectors" | "tyres";
const VIEWS: [View, string][] = [["tower", "Tower"], ["sectors", "Sectors"], ["tyres", "Tyres"]];

/** A timing screen's colours: purple fastest of all, green a personal best, yellow slower than their best. */
function sectorTone(state: SectorTime["state"]): string {
  return state === "session_best" ? " is-purple" : state === "personal_best" ? " is-pb" : state === "normal" ? " is-slower" : "";
}

/**
 * The running order beside the map, three ways: the tower (gap, interval,
 * tyre and its age, and whether race control has anything against the car),
 * each car's last three sectors in timing colours, or its tyres (compound,
 * age, laps in the stint, stops). The whole tower is its own screen.
 *
 * An interval in cyan is a car within a second of the one ahead: overtake
 * mode (2026 on) is estimated from it. Click a driver to follow them (up to
 * two): they are tagged on the map and get a dashboard.
 */
export const Leaderboard = memo(function Leaderboard({ drivers, selected, onSelect, onOpenTower }: Props) {
  const [view, setView] = useState<View>("tower");
  return (
    <div className="leaderboard">
      <div className="panel-bar">
        <h2>Timing</h2>
        <div className="segmented" role="tablist" aria-label="Timing view">
          {VIEWS.map(([key, text]) => (
            <button key={key} type="button" role="tab" aria-selected={view === key} className={view === key ? "is-on" : ""}
                    onClick={() => setView(key)}>{text}</button>
          ))}
        </div>
        {onOpenTower && (
          <button type="button" className="pop-out lb-open" onClick={onOpenTower} aria-label="Open the full timing tower"
                  title="Open the full timing tower">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <path d="M14 4h6v6M20 4l-8 8M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
            </svg>
          </button>
        )}
      </div>
      <div className="leaderboard-rows">
        <div className={`leaderboard-head is-${view}`}>
          <span>P</span><span /><span>Drv</span>
          {view === "tower" && <><span>Gap</span><span>Int</span><span>Tyre</span><span title="What race control has said about this car">Pen</span></>}
          {view === "sectors" && <><span>S1</span><span>S2</span><span>S3</span></>}
          {view === "tyres" && <><span>Tyre</span><span>Stint</span><span>Stops</span></>}
        </div>
        {drivers.map((driver) => {
          const isSelected = selected.includes(driver.driver_number);
          const eligible = driver.overtake === "eligible" || (driver.interval_s != null && driver.interval_s > 0 && driver.interval_s < 1);
          const tyre = driver.compound ? (
            <span className="tyre">
              <span className="tyre-chip" style={{ background: COMPOUND_COLORS[driver.compound] ?? "#888" }}
                    title={`${driver.compound}${driver.tyre_life != null ? `, ${driver.tyre_life} laps old` : ""}`}>
                {driver.compound[0]}
              </span>
              {driver.tyre_life != null && <span className="tyre-age num">{driver.tyre_life}</span>}
            </span>
          ) : <span className="tyre"><span className="tyre-age">—</span></span>;
          return (
            <button
              type="button"
              key={driver.driver_number}
              className={`leaderboard-row is-${view}${isSelected ? " is-selected" : ""}${driver.status === "out" ? " is-out" : ""}`}
              onClick={() => onSelect(driver.driver_number)}
              aria-pressed={isSelected}
            >
              <span className="pos-chip num">{driver.position}</span>
              <span className="team-bar" style={{ background: `#${driver.team_color ?? "555"}` }} />
              <span className="code">{driver.abbreviation ?? driver.driver_number}</span>
              {view === "tower" && (
                <>
                  <span className="num gap">
                    {driver.status === "out" ? "OUT" : driver.gap_text || (driver.position === 1 ? "LEADER" : "—")}
                  </span>
                  <span className={`num int${eligible ? " is-eligible" : ""}`}
                        title={driver.overtake === "eligible" ? "Overtake eligible, estimated from the timing gap" : undefined}>
                    {driver.position === 1 ? "" : driver.interval_text}
                  </span>
                  {tyre}
                  <PenaltyChip against={driver.penalties} />
                </>
              )}
              {view === "sectors" && [1, 2, 3].map((n) => {
                const s = driver.sectors.find((x) => x.sector === n);
                return <span key={n} className={`num sector${s ? sectorTone(s.state) : ""}`}>{formatSector(s?.seconds)}</span>;
              })}
              {view === "tyres" && (
                <>
                  {tyre}
                  <span className="num stint">{driver.laps_in_stint != null ? `${driver.laps_in_stint} L` : "—"}</span>
                  <span className="num stops">{driver.stops}</span>
                </>
              )}
            </button>
          );
        })}
      </div>
      <div className="leaderboard-foot">
        <span className="lb-key"><i className="is-following" />Following</span>
        <span className="lb-key"><b className="num">+0.8</b>within 1 s</span>
        <span className="lb-key"><i className="is-investigation" />Investigation</span>
        <span className="bar-spacer" />
        <span className="num" title={`${drivers.length} cars`}>{drivers.length}</span>
      </div>
    </div>
  );
});
