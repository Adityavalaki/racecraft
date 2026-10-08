import { useMemo, useState, type ReactNode } from "react";
import { formatClock, type RaceControlEvent } from "../api";
import { sentence, tone } from "../panels/RaceControl";
import { verdictLabel } from "../panels/Stewards";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Filter = "all" | "incidents" | "track";

export interface Explanation {
  kind: string;
  title: string;
  body: string;
  status: string;
  effect: string;
}

/**
 * What a race control message means, in plain words. Written from the kind of
 * verdict the server reads out of the message, so every message gets one,
 * and nothing is claimed that the message does not say.
 */
export function explain(event: RaceControlEvent, who: string): Explanation {
  const reason = event.reason ? sentence(event.reason).replace(/\.$/, "") : null;
  const title = reason && who ? `${who}, ${reason.charAt(0).toLowerCase()}${reason.slice(1)}` : sentence(event.message);
  const seconds = event.seconds != null ? `${event.seconds}-second` : "";
  switch (event.kind) {
    case "time_penalty":
      return { kind: "Penalty", title, status: "Awarded",
        body: `The stewards have given ${who || "the car"} a ${seconds || "time"} penalty. It is served at the next stop, or added to the race time if there is none.`,
        effect: `${event.seconds ?? "Time"} s added` };
    case "stop_go":
      return { kind: "Penalty", title, status: "Awarded",
        body: `${who || "The car"} must come into the pit lane and stop for ${seconds || "the set"} time without work being done.`,
        effect: "Stop-go in the pit lane" };
    case "drive_through":
      return { kind: "Penalty", title, status: "Awarded",
        body: `${who || "The car"} must drive through the pit lane at the speed limit without stopping.`, effect: "Drive-through" };
    case "served":
      return { kind: "Penalty", title, status: "Served", body: `${who || "The car"} has served its penalty; it no longer hangs over the result.`, effect: "Done" };
    case "under_investigation":
      return { kind: "Investigation", title, status: "Under investigation",
        body: "The stewards are looking at the incident now and may decide during the race.", effect: "Possible penalty" };
    case "investigate_after_race":
      return { kind: "Investigation", title, status: "After the race",
        body: "The stewards will decide after the finish. Until then the result is provisional for this driver.", effect: "Possible time penalty" };
    case "noted":
      return { kind: "Incident, noted", title, status: "Noted",
        body: "Race control has recorded the incident. Most noted incidents go no further; a few are investigated later.", effect: "None yet" };
    case "no_further_action":
      return { kind: "Decision", title, status: "No further action", body: "The stewards looked at it and are taking no action.", effect: "None" };
    case "reprimand":
      return { kind: "Decision", title, status: "Reprimand",
        body: "A reprimand: no time penalty, but they count towards a grid penalty across a season.", effect: "None in this race" };
    case "warning":
      return { kind: "Decision", title, status: "Warning", body: "A formal warning: no penalty now.", effect: "None" };
    case "black_and_white":
      return { kind: "Flag", title, status: "Shown", body: "The black and white flag: a warning for unsporting driving, the last step before a penalty.", effect: "None yet" };
    case "disqualified":
      return { kind: "Penalty", title, status: "Black flag", body: `${who || "The car"} has been shown the black flag and is out of the race.`, effect: "Disqualified" };
    default: {
      const text = event.message.toUpperCase();
      const isTrack = event.topic === "track";
      const effect = text.includes("SAFETY CAR") || text.includes("VSC") ? "The field slows; a stop is cheaper"
        : text.includes("RED FLAG") ? "The race is stopped"
          : text.includes("CLOSED") ? "No stops until it opens" : "None";
      return { kind: isTrack ? "Track" : "Message", title: sentence(event.message),
        body: isTrack ? "From race control's log of the track: flags, the safety car, the pit exit and conditions." : "A message from race control.",
        status: "Information", effect };
    }
  }
}

const PERIODS: Record<string, { label: string; className: string }> = {
  "2": { label: "Yellow flag", className: "is-yellow" },
  "4": { label: "Safety car", className: "is-sc" },
  "5": { label: "Red flag", className: "is-red" },
  "6": { label: "Virtual safety car", className: "is-vsc" },
  "7": { label: "Virtual safety car", className: "is-vsc" },
};

/**
 * Every race control message, with what it means for the result. The list is
 * in feed order; picking one explains it. Under it, the flags and the safety
 * car across the race, read off the timeline. Following a driver narrows the
 * verdicts to them.
 */
export function StewardsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [picked, setPicked] = useState<string | null>(null);
  const codeOf = (car: number) => ctx.driverCodes[car] ?? String(car);
  const all = useMemo(() => [...(ctx.stewards ?? []), ...(ctx.trackLog ?? [])]
    .filter((e) => e && e.message && e.kind !== "lap_deleted")
    .sort((a, b) => a.t - b.t), [ctx.stewards, ctx.trackLog]);
  const shown = all.filter((e) => {
    const verdict = e.stewards || e.topic === "stewards";
    if (filter === "incidents" && !verdict) return false;
    if (filter === "track" && verdict) return false;
    if (verdict && ctx.selected.length && !e.cars.some((c) => ctx.selected.includes(c))) return false;
    return true;
  });
  const keyOf = (e: RaceControlEvent) => `${e.t}:${e.message}`;
  const current = shown.find((e) => keyOf(e) === picked) ?? shown[shown.length - 1] ?? null;
  const who = current ? current.cars.map(codeOf).join(", ") : "";
  const detail = current ? explain(current, who) : null;

  // Flag and safety-car periods, in laps, from the status changes and the leader's crossings.
  const total = ctx.info.total_laps ?? Math.max(1, ctx.state?.leader_lap ?? 1);
  const periods = useMemo(() => {
    const statuses = [...(ctx.info.track_status ?? [])].sort((a, b) => a.t - b.t);
    const crossings = ctx.crossings;
    const lapAt = (t: number) => {
      if (!crossings?.t.length) return null;
      const k = crossings.t.findIndex((end) => end >= t);
      return k < 0 ? total : crossings.laps[k]!;
    };
    const out: { from: number; to: number; status: string }[] = [];
    statuses.forEach((change, i) => {
      if (!PERIODS[change.status] || change.t > (ctx.state?.t ?? Infinity)) return;
      const from = lapAt(change.t);
      const to = lapAt(statuses[i + 1]?.t ?? ctx.info.t_end);
      if (from == null || to == null) return;
      // Several changes of the same flag on the same laps (the feed repeats them) read as one period.
      const last = out[out.length - 1];
      if (last && last.status === change.status && from <= last.to + 1) last.to = Math.max(last.to, to);
      else out.push({ from, to: Math.max(to, from), status: change.status });
    });
    return out;
  }, [ctx.info, ctx.crossings, ctx.state?.t, total]);

  const switcher = (
    <>
      <LapCounter lap={ctx.state?.leader_lap ?? 0} total={ctx.info.total_laps} />
      <div className="segmented" role="radiogroup" aria-label="Filter">
        {([["all", "All"], ["incidents", "Incidents"], ["track", "Track"]] as [Filter, string][]).map(([key, text]) => (
          <button key={key} type="button" role="radio" aria-checked={filter === key} className={filter === key ? "is-on" : ""}
                  onClick={() => setFilter(key)}>{text}</button>
        ))}
      </div>
    </>
  );
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body">
        <div className="stewards-grid">
          <section className="panel" aria-label="Race control messages">
            <div className="panel-bar">
              <h2>Messages</h2>
              <span className="panel-meta">In feed order{ctx.selected.length ? `; verdicts for ${ctx.selected.map(codeOf).join(" and ")} only` : ""}.</span>
            </div>
            {shown.length === 0 ? <p className="empty">Nothing from race control yet.</p> : (
              <div className="message-list">
                {shown.map((e) => {
                  const verdict = e.stewards || e.topic === "stewards";
                  const names = e.cars.map(codeOf).join(", ");
                  const on = current != null && keyOf(e) === keyOf(current);
                  return (
                    <button key={keyOf(e)} type="button" aria-pressed={on} className={`message${on ? " is-on" : ""}`}
                            onClick={() => setPicked(keyOf(e))}>
                      <span className={`rc-dot is-${tone(e)}`} aria-hidden="true" />
                      <span className="num message-when">{e.lap != null ? `L${e.lap}` : formatClock(e.t - ctx.info.t_start)}</span>
                      <span className="message-text">{verdict && names && e.reason ? `${names}: ${sentence(e.reason)}` : sentence(e.message)}</span>
                      {verdict && <span className={`rc-tag is-${tone(e)}`}>{verdictLabel(e)}</span>}
                    </button>
                  );
                })}
              </div>
            )}
          </section>
          <section className="panel message-detail" aria-label="Message detail" aria-live="polite">
            {detail && current ? (
              <>
                <div className="detail-tags">
                  <span className="tag">{detail.kind}</span>
                  <span className="tag">{current.lap != null ? `Lap ${current.lap}` : formatClock(current.t - ctx.info.t_start)}</span>
                </div>
                <p className="display detail-title">{detail.title}</p>
                <p className="detail-body">{detail.body}</p>
                <dl className="detail-facts">
                  <div><dt>Applies to</dt><dd className="display">{who || "All cars"}</dd></div>
                  <div><dt>Status</dt><dd>{detail.status}</dd></div>
                  <div><dt>Effect on the race</dt><dd>{detail.effect}</dd></div>
                </dl>
                <p className="detail-source">In race control's words: <q>{current.message}</q></p>
              </>
            ) : <p className="empty">Pick a message to see what it means.</p>}
          </section>
        </div>

        <section className="panel" aria-label="Flags and safety car">
          <div className="panel-bar"><h2>Flags and safety car</h2><span className="panel-meta">Up to now, read off the race timeline: laps are the leader's.</span></div>
          <div className="flag-lane">
            <div className="flag-track">
              {periods.map((p, k) => (
                <span key={k} className={`flag-band ${PERIODS[p.status]!.className}`} title={PERIODS[p.status]!.label}
                      style={{ left: `${((p.from - 1) / Math.max(total, 1)) * 100}%`, width: `${Math.max((p.to - p.from + 1) / Math.max(total, 1), 0.006) * 100}%` }} />
              ))}
            </div>
            <div className="flag-axis num">
              {Array.from({ length: Math.floor(total / 10) + 1 }, (_, k) => k * 10).map((lap) => (
                <span key={lap} style={{ left: `${(lap / Math.max(total, 1)) * 100}%` }}>{lap}</span>
              ))}
            </div>
            {periods.length === 0 ? <p className="empty">No flags or safety car so far.</p> : (
              <ul className="flag-list">
                {periods.map((p, k) => (
                  <li key={k}><span className={`flag-swatch ${PERIODS[p.status]!.className}`} />{PERIODS[p.status]!.label}
                    <span className="num">{p.from === p.to ? `L${p.from}` : `L${p.from}–${p.to}`}</span></li>
                ))}
              </ul>
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
