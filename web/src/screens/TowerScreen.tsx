import { useState, type ReactNode } from "react";
import { COMPOUND_COLORS, formatLapTime, formatSector, type DriverTiming, type SectorTime } from "../api";
import { BestSectors } from "../panels/BestSectors";
import { PenaltyChip } from "../panels/PenaltyChip";
import { KpiRow } from "../shell/KpiRow";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Order = "race" | "grid" | "best";

/** A timing screen's colours: purple fastest of all, green a personal best, yellow slower than their best. */
function sectorTone(state: SectorTime["state"]): string {
  if (state === "session_best") return "is-purple";
  if (state === "personal_best") return "is-green";
  if (state === "normal") return "is-yellow";
  return "";
}

function lastTone(driver: DriverTiming): string {
  if (driver.is_session_best) return "is-purple";
  if (driver.is_personal_best) return "is-green";
  return "";
}

/**
 * Every car, every lap and sector, in race order (or grid order, or by best
 * lap). Gaps and intervals are the timing's, exact at each crossing of the
 * line; sectors are the car's last lap's. Click a row to follow that driver.
 */
export function TowerScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [order, setOrder] = useState<Order>("race");
  const grid = new Map(ctx.info.drivers.map((d) => [d.driver_number, d.grid_position ?? 99]));
  const drivers = [...(ctx.state?.drivers ?? [])];
  if (order === "grid") drivers.sort((a, b) => (grid.get(a.driver_number) || 99) - (grid.get(b.driver_number) || 99));
  if (order === "best") drivers.sort((a, b) => (a.best_lap_s ?? Infinity) - (b.best_lap_s ?? Infinity));
  const hasOvertake = drivers.some((d) => d.overtake != null);
  const switcher = (
    <>
      <LapCounter lap={ctx.state?.leader_lap ?? 0} total={ctx.info.total_laps} />
      <div className="segmented" role="radiogroup" aria-label="Order">
        {([["race", "Race order"], ["grid", "Grid"], ["best", "Best laps"]] as [Order, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={order === key} className={order === key ? "is-on" : ""}
                  onClick={() => setOrder(key)}>{text}</button>
        ))}
      </div>
    </>
  );
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        <KpiRow tiles={towerTiles(drivers, ctx.state?.ideal_lap_s ?? null)} />
        <div className="timing-grid">
        <section className="panel tower" aria-label="Timing tower">
          <div className="tower-scroll">
            <table className="tower-table">
              <thead>
                <tr>
                  <th scope="col">Pos</th><th scope="col"><span className="visually-hidden">Team colour</span></th>
                  <th scope="col">Driver</th><th scope="col">Team</th>
                  <th scope="col" className="right">Gap</th><th scope="col" className="right">Interval</th>
                  <th scope="col" className="right">Last lap</th><th scope="col" className="right">Best lap</th>
                  <th scope="col" className="right">S1</th><th scope="col" className="right">S2</th><th scope="col" className="right">S3</th>
                  <th scope="col">Tyre</th><th scope="col" className="right">Pits</th>
                  {hasOvertake && <th scope="col">Overtake</th>}
                  <th scope="col">Pen</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d, index) => {
                  const followed = ctx.selected.includes(d.driver_number);
                  const out = d.status === "out";
                  const sectors = [1, 2, 3].map((n) => d.sectors.find((s) => s.sector === n));
                  return (
                    <tr key={d.driver_number} className={`${followed ? "is-followed" : ""}${out ? " is-out" : ""}`}
                        onClick={() => ctx.onSelect(d.driver_number)} aria-selected={followed}>
                      <td><span className="pos-chip num">{order === "race" ? d.position : index + 1}</span></td>
                      <td><span className="team-bar tall" style={{ background: `#${d.team_color ?? "555"}` }} /></td>
                      <th scope="row"><button type="button" className="row-pick display" aria-pressed={followed}
                                              onClick={(e) => { e.stopPropagation(); ctx.onSelect(d.driver_number); }}>
                        {d.abbreviation ?? d.driver_number}</button></th>
                      <td className="team">{d.team_name ?? ""}</td>
                      <td className="num right">{out ? "OUT" : d.gap_text || (d.position === 1 ? "LEADER" : "—")}</td>
                      <td className={`num right${d.overtake === "eligible" ? " is-overtake" : ""}`}>{d.position === 1 ? "" : d.interval_text}</td>
                      <td className={`num right strong ${lastTone(d)}`}>{formatLapTime(d.last_lap_s)}</td>
                      <td className="num right muted">{formatLapTime(d.best_lap_s)}</td>
                      {sectors.map((s, k) => (
                        <td key={k} className={`num right ${s ? sectorTone(s.state) : ""}`}>{formatSector(s?.seconds)}</td>
                      ))}
                      <td>
                        {d.compound ? (
                          <span className="tyre-cell">
                            <span className="tyre-chip" style={{ background: COMPOUND_COLORS[d.compound] ?? "#888" }}>{d.compound[0]}</span>
                            {d.tyre_life != null ? `${d.tyre_life} laps` : ""}
                          </span>
                        ) : "—"}
                      </td>
                      <td className="num right">{d.stops}</td>
                      {hasOvertake && <td className="overtake-cell">{d.overtake === "eligible" ? "Eligible" : ""}</td>}
                      <td><PenaltyChip against={d.penalties} /></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="map-legend tower-legend">
            <span><i style={{ background: "var(--purple)", height: 12, width: 12 }} />Fastest of everyone</span>
            <span><i style={{ background: "var(--green)", height: 12, width: 12 }} />Personal best</span>
            <span><i style={{ background: "var(--worse)", height: 12, width: 12 }} />Slower than their best</span>
            {hasOvertake && <span><i className="is-ring" />Overtake eligible, estimated from the interval</span>}
          </div>
        </section>
        <div className="timing-side">
          <section className="panel">
            <div className="panel-bar"><h2>Sector bests</h2><span className="panel-meta">and the lap they would make</span></div>
            <BestSectors sectors={ctx.state?.best_sectors ?? []} idealLap={ctx.state?.ideal_lap_s ?? null} fastestLap={ctx.sessionBest} />
          </section>
          <FieldSpread drivers={drivers} selected={ctx.selected} />
        </div>
        </div>
      </main>
    </div>
  );
}

/** Still running, or past the chequered flag: a car that has not retired or failed to start. */
const onTrack = (d: DriverTiming) => d.status === "racing" || d.status === "finished";

/**
 * The tower's headline figures, all from the timing at the clock's moment:
 * the fastest lap so far and who set it, the ideal lap (the session's best
 * sectors strung together), the spread from leader to last car running, and
 * how many cars are within a second of the one ahead.
 */
export function towerTiles(drivers: DriverTiming[], idealLap: number | null) {
  const timed = drivers.filter((d) => d.best_lap_s != null);
  const fastest = timed.reduce<DriverTiming | null>((a, d) => (a && a.best_lap_s! <= d.best_lap_s! ? a : d), null);
  const running = drivers.filter((d) => onTrack(d) && d.laps_down === 0 && (d.position === 1 || d.gap_to_leader_s != null));
  const last = running[running.length - 1];
  const close = drivers.filter((d) => onTrack(d) && d.interval_s != null && d.interval_s > 0 && d.interval_s < 1).length;
  return [
    fastest && { label: "Fastest lap", value: formatLapTime(fastest.best_lap_s), note: fastest.abbreviation ?? String(fastest.driver_number) },
    idealLap != null && { label: "Ideal lap", value: formatLapTime(idealLap), note: "the session's best sectors together" },
    last && running.length > 1 && last.gap_to_leader_s != null && { label: "Leader to last", value: `+${last.gap_to_leader_s.toFixed(3)}`, note: `${running.length} cars on the lead lap` },
    drivers.length > 0 && { label: "Within 1 s", value: `${close} ${close === 1 ? "car" : "cars"}`, note: "of the car ahead" },
  ];
}

/** The cars on the lead lap with a gap to place: the leader at 0, then each by its gap. */
export function spread(drivers: DriverTiming[]): { driver: DriverTiming; gap: number }[] {
  return drivers
    .filter((d) => onTrack(d) && d.laps_down === 0 && (d.position === 1 || d.gap_to_leader_s != null))
    .map((d) => ({ driver: d, gap: d.position === 1 ? 0 : d.gap_to_leader_s! }));
}

/**
 * The field on one line: every car on the lead lap placed by its gap to the
 * leader, so trains and gaps show at a glance. Lapped cars are counted, not
 * drawn: their gap is a lap, not a distance on this scale.
 */
function FieldSpread({ drivers, selected }: { drivers: DriverTiming[]; selected: number[] }) {
  const cars = spread(drivers);
  const lapped = drivers.filter((d) => onTrack(d) && d.laps_down > 0).length;
  const reach = Math.max(1, ...cars.map((c) => c.gap));
  return (
    <section className="panel field-spread" aria-label="Field spread">
      <div className="panel-bar">
        <h2>Field spread</h2>
        <span className="panel-meta">gap to leader, s{lapped ? ` · ${lapped} lapped` : ""}</span>
      </div>
      {cars.length === 0 ? <p className="panel-note">No gaps yet.</p> : (
        <ol className="spread-list" aria-label="Gap to the leader">
          {cars.map((c) => (
            <li key={c.driver.driver_number} className={selected.includes(c.driver.driver_number) ? "is-followed" : ""}>
              <span className="num spread-code">{c.driver.abbreviation}</span>
              <span className="spread-bar"><i style={{ width: `${(c.gap / reach) * 100}%`, background: `#${c.driver.team_color ?? "8E959F"}` }} /></span>
              <span className="num spread-gap">{c.gap === 0 ? "—" : `+${c.gap.toFixed(1)}`}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
