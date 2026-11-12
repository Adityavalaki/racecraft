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
          <FieldRing drivers={drivers} selected={ctx.selected} t={ctx.t} crossings={ctx.crossings} />
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

/** Where each car sits on the ring: degrees clockwise from the line, counted on so a lap more is 360 more. */
export interface RingCar { driver: DriverTiming; gap: number; angle: number }

/**
 * The ring's geometry: the leader goes round once a lap, at its share of the
 * current lap (between two of its crossings of the line); each car on the lead
 * lap sits its gap behind, converted to degrees at the leader's pace for that
 * lap. Angles keep counting past 360, so the ring only ever turns forward while
 * the replay plays. Before the first crossing the leader is on lap 1 from the
 * start; with no next crossing yet (live), the lap's length is the leader's last.
 */
export function ringCars(drivers: DriverTiming[], t: number, crossings: { laps: number[]; t: number[] } | null, tStart: number): {
  cars: RingCar[]; lapSeconds: number | null;
} {
  const cars = spread(drivers);
  const leader = cars.find((c) => c.gap === 0)?.driver;
  const times = crossings?.t ?? [];
  // The last crossing at or before t (crossings are in time order).
  let i = -1;
  while (i + 1 < times.length && times[i + 1]! <= t) i += 1;
  const from = i >= 0 ? times[i]! : tStart;
  const done = i >= 0 ? crossings!.laps[i]! : 0;
  const next = times[i + 1];
  const lapSeconds = next != null ? next - from : leader?.last_lap_s ?? null;
  if (!lapSeconds || lapSeconds <= 0) return { cars: cars.map((c) => ({ ...c, angle: 0 })), lapSeconds: null };
  const share = Math.min(Math.max((t - from) / lapSeconds, 0), 1);
  const lead = (done + share) * 360;
  return { cars: cars.map((c) => ({ ...c, angle: lead - (c.gap / lapSeconds) * 360 })), lapSeconds };
}

const RING_R = 104;
/** Two codes closer than this many degrees would overprint: the second is left to its dot. */
const LABEL_GAP_DEG = 11;

/**
 * The field on a ring (D-033, replacing a vertical ladder): one turn is one lap
 * at the leader's pace, the line at the top. The cars go round with the
 * replay, each its gap behind the leader, so a train is a cluster and a gap is
 * open track; the arc behind the leader runs to the last car on the lead lap.
 * Each dot turns with a 250 ms ease along the circle, matching how often the
 * figures tick; a code stays upright by turning back the other way. Lapped
 * cars are counted, not drawn: the timing gives them no gap.
 */
function FieldRing({ drivers, selected, t, crossings }: {
  drivers: DriverTiming[]; selected: number[]; t: number; crossings: { laps: number[]; t: number[] } | null;
}) {
  const { cars, lapSeconds } = ringCars(drivers, t, crossings, crossings?.t[0] != null ? Math.min(t, crossings.t[0]) : t);
  const lapped = drivers.filter((d) => onTrack(d) && d.laps_down > 0).length;
  const last = cars[cars.length - 1];
  const leadAngle = cars[0]?.angle ?? 0;
  // Codes: the leader, the followed, then any with room, nearest the leader first.
  const shown = new Set<number>();
  const taken: number[] = [];
  const room = (a: number) => taken.every((b) => Math.abs((((a - b) % 360) + 540) % 360 - 180) >= LABEL_GAP_DEG);
  for (const c of [...cars].sort((a, b) => Number(selected.includes(b.driver.driver_number)) - Number(selected.includes(a.driver.driver_number)))) {
    if (room(c.angle) || selected.includes(c.driver.driver_number)) { shown.add(c.driver.driver_number); taken.push(c.angle); }
  }
  const circumference = 2 * Math.PI * RING_R;
  const arc = last && lapSeconds ? Math.min(leadAngle - last.angle, 359.9) : 0;
  return (
    <section className="panel field-spread" aria-label="Field spread">
      <div className="panel-bar">
        <h2>Field spread</h2>
        <span className="panel-meta">one turn = one lap at the leader's pace{lapped ? ` · ${lapped} lapped` : ""}</span>
      </div>
      {cars.length === 0 || !lapSeconds ? <p className="panel-note">No gaps yet.</p> : (
        <div className="ring-wrap">
          <svg viewBox="-150 -150 300 300" className="ring" role="img"
               aria-label={`The field on one lap: ${cars.map((c) => `${c.driver.abbreviation} ${c.gap === 0 ? "leading" : `+${c.gap.toFixed(1)} s`}`).join(", ")}`}>
            <circle r={RING_R} className="ring-track" />
            {/* The arc from the last car on the lead lap round to the leader: how spread the field is. */}
            <g className="ring-turn" style={{ transform: `rotate(${last ? last.angle - 90 : 0}deg)` }}>
              <circle r={RING_R} className="ring-arc" strokeDasharray={`${(arc / 360) * circumference} ${circumference}`} />
            </g>
            {/* The line inside the ring, clear of the codes outside it. */}
            <line x1="0" x2="0" y1={-RING_R - 8} y2={-RING_R + 8} className="ring-line" />
            <text y={-RING_R + 20} className="ring-line-label">LINE</text>
            {[...cars].reverse().map((c) => {
              const followed = selected.includes(c.driver.driver_number);
              return (
                <g key={c.driver.driver_number} className="ring-turn" style={{ transform: `rotate(${c.angle}deg)` }}>
                  <circle cy={-RING_R} r={followed ? 7 : c.gap === 0 ? 6.5 : 5} fill={`#${c.driver.team_color ?? "8E959F"}`}
                          className={followed ? "ring-dot is-followed" : "ring-dot"} />
                  {shown.has(c.driver.driver_number) && (
                    <g transform={`translate(0 ${-RING_R - 19})`}>
                      <text className={`ring-code ring-turn${followed ? " is-followed" : ""}`} style={{ transform: `rotate(${-c.angle}deg)` }}>
                        {c.driver.abbreviation}
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
            <text y="-14" className="ring-centre-cap">LEADER TO LAST</text>
            <text y="12" className="ring-centre-value">{last && last.gap > 0 ? `+${last.gap.toFixed(1)} s` : "—"}</text>
            <text y="32" className="ring-centre-note">{cars.length} on the lead lap · lap {lapSeconds.toFixed(1)} s</text>
          </svg>
        </div>
      )}
    </section>
  );
}
