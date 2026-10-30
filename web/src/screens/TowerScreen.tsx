import { useState, type ReactNode } from "react";
import { COMPOUND_COLORS, formatLapTime, formatSector, type DriverTiming, type SectorTime } from "../api";
import { KpiRow } from "../shell/KpiRow";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type GapRef = "leader" | "selected";

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
 * One word on where a car stands, most pressing first: disqualified, out,
 * finished, owing a penalty, under investigation, within a second of the car
 * ahead (overtake mode where the session has it), or simply running.
 */
export function carStatus(d: DriverTiming, hasOvertake: boolean): { text: string; tone: string } {
  const p = d.penalties;
  if (p?.disqualified) return { text: "Disqualified", tone: "bad" };
  if (d.status === "out") return { text: "Out", tone: "off" };
  if (d.status === "not_started") return { text: "Did not start", tone: "off" };
  if (d.status === "finished") return { text: "Finished", tone: "done" };
  if (p && (p.pending_s > 0 || p.stop_go > 0 || p.drive_through > 0)) {
    return { text: p.pending_s > 0 ? `Penalty +${p.pending_s}s` : "Penalty to serve", tone: "bad" };
  }
  if (p && p.under_investigation > 0) return { text: "Investigation", tone: "look" };
  if (hasOvertake ? d.overtake === "eligible" : d.interval_s != null && d.interval_s > 0 && d.interval_s < 1) {
    return { text: hasOvertake ? "Overtake on" : "Within 1 s", tone: "close" };
  }
  return { text: "Running", tone: "ok" };
}

/**
 * The gap column against the leader, or against the first followed driver:
 * minus is ahead of them, plus behind. Lapped cars keep the timing's own text,
 * a lap not being a distance on this scale.
 */
export function gapText(d: DriverTiming, ref: DriverTiming | undefined): string {
  if (d.status === "out") return "OUT";
  if (!ref) return d.gap_text || (d.position === 1 ? "LEADER" : "—");
  if (d.driver_number === ref.driver_number) return "Ref";
  const mine = d.position === 1 ? 0 : d.gap_to_leader_s;
  const theirs = ref.position === 1 ? 0 : ref.gap_to_leader_s;
  if (mine == null || theirs == null || d.laps_down > 0 || ref.laps_down > 0) return d.gap_text || "—";
  const g = mine - theirs;
  return `${g > 0 ? "+" : "−"}${Math.abs(g).toFixed(3)}`;
}

/**
 * The full timing, as the board lays it out: the classification on the left
 * (gap, interval, last and best lap, each car's last three sectors in timing
 * colours, tyre and its age, stops, status), and down the right the headline
 * figures, the sector bests and the field spread. Gaps are the timing's, exact
 * at each crossing of the line. Click a row to follow that driver.
 */
export function TowerScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [gapRef, setGapRef] = useState<GapRef>("leader");
  const drivers = ctx.state?.drivers ?? [];
  const names = new Map(ctx.info.drivers.map((d) => [d.driver_number, d.full_name ?? ""]));
  const hasOvertake = drivers.some((d) => d.overtake != null);
  const ref = gapRef === "selected" ? drivers.find((d) => d.driver_number === ctx.selected[0]) : undefined;
  const switcher = (
    <>
      <LapCounter lap={ctx.state?.leader_lap ?? 0} total={ctx.info.total_laps} />
      <div className="segmented" role="radiogroup" aria-label="Gap reference">
        {([["leader", "Gap to leader"], ["selected", "Gap to selected"]] as [GapRef, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={gapRef === key} className={gapRef === key ? "is-on" : ""}
                  disabled={key === "selected" && !ctx.selected.length}
                  title={key === "selected" && !ctx.selected.length ? "Follow a driver first: click a row" : undefined}
                  onClick={() => setGapRef(key)}>{text}</button>
        ))}
      </div>
    </>
  );
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        <div className="timing-grid">
        <section className="panel tower" aria-label="Timing tower">
          <div className="panel-bar">
            <h2>Classification</h2>
            <span className="panel-meta">{drivers.length} cars · sector colours: purple overall best, green personal best</span>
            <span className="seg-key" aria-hidden="true">
              <i className="seg is-purple" />Overall<i className="seg is-green" />Personal<i className="seg is-yellow" />Other
            </span>
          </div>
          <div className="tower-scroll">
            <table className="tower-table">
              <thead>
                <tr>
                  <th scope="col" className="right">P</th><th scope="col"><span className="visually-hidden">Team colour</span></th>
                  <th scope="col">Driver</th>
                  <th scope="col" className="right">{ref ? `To ${ref.abbreviation ?? ref.driver_number}` : "Gap"}</th>
                  <th scope="col" className="right">Int</th>
                  <th scope="col" className="right">Last lap</th><th scope="col" className="right">Best</th>
                  <th scope="col" className="center">S1</th><th scope="col" className="center">S2</th><th scope="col" className="center">S3</th>
                  <th scope="col">Tyre</th><th scope="col" className="right">Pit</th><th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {drivers.map((d) => {
                  const followed = ctx.selected.includes(d.driver_number);
                  const sectors = [1, 2, 3].map((n) => d.sectors.find((s) => s.sector === n));
                  const status = carStatus(d, hasOvertake);
                  const close = d.overtake === "eligible" || (d.interval_s != null && d.interval_s > 0 && d.interval_s < 1);
                  return (
                    <tr key={d.driver_number} className={`${followed ? "is-followed" : ""}${d.status === "out" ? " is-out" : ""}`}
                        onClick={() => ctx.onSelect(d.driver_number)} aria-selected={followed}>
                      <td className="num right strong muted-pos">{d.position}</td>
                      <td><span className="team-bar tall" style={{ background: `#${d.team_color ?? "555"}` }} /></td>
                      <th scope="row" className="who">
                        <button type="button" className="row-pick" aria-pressed={followed}
                                onClick={(e) => { e.stopPropagation(); ctx.onSelect(d.driver_number); }}>
                          {d.abbreviation ?? d.driver_number}</button>
                        <span className="who-name">{names.get(d.driver_number)}</span>
                      </th>
                      <td className="num right">{gapText(d, ref)}</td>
                      <td className={`num right${close ? " is-overtake" : ""}`}>{d.position === 1 ? "—" : d.interval_text}</td>
                      <td className={`num right strong ${lastTone(d)}`}>{formatLapTime(d.last_lap_s)}</td>
                      <td className="num right muted">{formatLapTime(d.best_lap_s)}</td>
                      {sectors.map((s, k) => (
                        <td key={k} className="center">
                          <span className={`seg num ${s ? sectorTone(s.state) : ""}`}>{formatSector(s?.seconds)}</span>
                        </td>
                      ))}
                      <td>
                        {d.compound ? (
                          <span className="tyre-cell">
                            <span className="tyre-chip" style={{ background: COMPOUND_COLORS[d.compound] ?? "#888" }}>{d.compound[0]}</span>
                            <span className="num muted">{d.tyre_life ?? ""}</span>
                          </span>
                        ) : "—"}
                      </td>
                      <td className="num right">{d.stops}</td>
                      <td><span className={`car-status is-${status.tone}`}><i />{status.text}</span></td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </section>
        <div className="timing-side">
          <KpiRow tiles={towerTiles(drivers, ctx.state?.ideal_lap_s ?? null)} />
          <SectorBests ctx={ctx} />
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
 * sectors strung together), how many cars are within a second of the one
 * ahead, and the spread from leader to last car on the lead lap.
 */
export function towerTiles(drivers: DriverTiming[], idealLap: number | null) {
  const timed = drivers.filter((d) => d.best_lap_s != null);
  const fastest = timed.reduce<DriverTiming | null>((a, d) => (a && a.best_lap_s! <= d.best_lap_s! ? a : d), null);
  const running = drivers.filter((d) => onTrack(d) && d.laps_down === 0 && (d.position === 1 || d.gap_to_leader_s != null));
  const last = running[running.length - 1];
  const close = drivers.filter((d) => onTrack(d) && d.interval_s != null && d.interval_s > 0 && d.interval_s < 1).length;
  return [
    fastest && { label: "Fastest lap", value: formatLapTime(fastest.best_lap_s), note: fastest.abbreviation ?? String(fastest.driver_number) },
    idealLap != null && { label: "Ideal lap", value: formatLapTime(idealLap), note: "best sectors combined" },
    drivers.length > 0 && { label: "Within 1 s", value: `${close} ${close === 1 ? "car" : "cars"}`, note: "of the car ahead" },
    last && running.length > 1 && last.gap_to_leader_s != null && { label: "Leader to last", value: `+${last.gap_to_leader_s.toFixed(1)} s`, note: `${running.length} cars on the lead lap` },
  ];
}

/** Who holds each sector, and the ideal lap they make: the quickest sectors strung together. */
function SectorBests({ ctx }: { ctx: ScreenContext }) {
  const sectors = ctx.state?.best_sectors ?? [];
  const ideal = ctx.state?.ideal_lap_s ?? null;
  const colours = new Map((ctx.state?.drivers ?? []).map((d) => [d.driver_number, d.team_color]));
  const untapped = ideal != null && ctx.sessionBest != null ? ctx.sessionBest - ideal : null;
  return (
    <section className="panel sector-bests" aria-label="Sector bests">
      <div className="panel-bar"><h2>Sector bests</h2></div>
      {sectors.map((s) => (
        <div key={s.sector} className="sb-row">
          <span className="cap">S{s.sector}</span>
          <span className="team-bar" style={{ background: `#${(s.driver_number != null && colours.get(s.driver_number)) || "555"}` }} />
          <span className="num strong">{s.driver ?? "—"}</span>
          <span />
          <span className="num right is-purple">{formatSector(s.seconds)}</span>
        </div>
      ))}
      <div className="sb-row is-ideal">
        <span className="cap">Ideal</span><span /><span />
        <span className="panel-meta">{untapped != null && untapped > 0.0005 ? `${untapped.toFixed(3)} s under the fastest lap` : "on the fastest lap"}</span>
        <span className="num right">{formatLapTime(ideal)}</span>
      </div>
    </section>
  );
}

/** The cars on the lead lap with a gap to place: the leader at 0, then each by its gap. */
export function spread(drivers: DriverTiming[]): { driver: DriverTiming; gap: number }[] {
  return drivers
    .filter((d) => onTrack(d) && d.laps_down === 0 && (d.position === 1 || d.gap_to_leader_s != null))
    .map((d) => ({ driver: d, gap: d.position === 1 ? 0 : d.gap_to_leader_s! }));
}

/**
 * The field down one axis: every car on the lead lap placed by its gap to the
 * leader, so trains and gaps show at a glance. Codes go in two columns so
 * close cars do not overprint; a code with no room is left to its dot. Lapped
 * cars are counted, not drawn: their gap is a lap, not a distance here.
 */
function FieldSpread({ drivers, selected }: { drivers: DriverTiming[]; selected: number[] }) {
  const cars = spread(drivers);
  const lapped = drivers.filter((d) => onTrack(d) && d.laps_down > 0).length;
  const max = Math.max(10, Math.ceil(Math.max(0, ...cars.map((c) => c.gap)) / 10) * 10);
  const lastY: [number, number] = [-99, -99];
  const ladder = cars.map((c) => {
    const y = (c.gap / max) * 100;
    const col: -1 | 0 | 1 = y - lastY[0] > 4.4 ? 0 : y - lastY[1] > 4.4 ? 1 : -1;
    if (col !== -1) lastY[col] = y;
    return { ...c, y, col };
  });
  return (
    <section className="panel field-spread" aria-label="Field spread">
      <div className="panel-bar">
        <h2>Field spread</h2>
        <span className="panel-meta">gap to leader, s{lapped ? ` · ${lapped} lapped` : ""}</span>
      </div>
      {cars.length === 0 ? <p className="panel-note">No gaps yet.</p> : (
        <div className="ladder-wrap">
          <div className="ladder">
            <span className="ladder-ax" aria-hidden="true" />
            {[0, 1, 2, 3, 4, 5].map((k) => (
              <span key={k} className="ladder-tick num" style={{ top: `${k * 20}%` }} aria-hidden="true">+{Math.round((max * k) / 5)}</span>
            ))}
            <ol aria-label="Gap to the leader">
              {ladder.map((c) => (
                <li key={c.driver.driver_number} style={{ top: `${c.y}%` }}
                    className={selected.includes(c.driver.driver_number) ? "is-followed" : ""}
                    aria-label={`${c.driver.abbreviation}, ${c.gap === 0 ? "leader" : `+${c.gap.toFixed(1)} s`}`}>
                  <span className="ladder-dot" style={{ background: `#${c.driver.team_color ?? "8E959F"}` }} />
                  {c.col >= 0 && <span className={`ladder-code num${c.col ? " is-far" : ""}`}>{c.driver.abbreviation}</span>}
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
    </section>
  );
}
