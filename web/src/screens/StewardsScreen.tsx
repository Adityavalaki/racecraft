import { useMemo, useState, type ReactNode } from "react";
import { KpiRow } from "../shell/KpiRow";
import { formatClock, type RaceControlEvent } from "../api";
import { sentence, tone } from "../panels/RaceControl";
import { verdictLabel } from "../panels/Stewards";
import { LapCounter } from "../shell/ScreenHeader";
import type { ScreenContext } from "./ScreenView";

type Filter = "all" | "open" | "decided" | "track";

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

/** One incident: every stewards' message about the same incident (or, without one, the same cars), oldest first. */
interface Incident { id: string; msgs: RaceControlEvent[]; latest: RaceControlEvent; cars: number[]; track: boolean }

/** An incident still waiting on the stewards: its latest message is an investigation or a note. */
const OPEN_KINDS = new Set(["under_investigation", "investigate_after_race", "noted"]);

/**
 * Race control as incidents, as racecraft-ui.html draws it (D-025): the
 * stewards' messages grouped by incident, newest first, each standing where its
 * latest message left it; track messages each stand alone. Picking one shows
 * the cars, the offence, the outcome and every message about it. Following a
 * driver narrows the incidents to them. The feed carries no penalty points, so
 * none are shown.
 */
export function StewardsScreen({ ctx, header }: { ctx: ScreenContext; header: (children?: ReactNode) => ReactNode }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [picked, setPicked] = useState<string | null>(null);
  const codeOf = (car: number) => ctx.driverCodes[car] ?? String(car);
  const incidents = useMemo(() => {
    const groups = new Map<string, Incident>();
    const events = [...(ctx.stewards ?? []), ...(ctx.trackLog ?? [])]
      .filter((e) => e && e.message && e.kind !== "lap_deleted").sort((a, b) => a.t - b.t);
    for (const e of events) {
      const track = !(e.stewards || e.topic === "stewards");
      const id = track ? `t:${e.t}:${e.message}` : `s:${e.incident ?? [...e.cars].sort().join(",")}`;
      const group = groups.get(id);
      if (group) {
        group.msgs.push(e);
        group.latest = e;
        group.cars = [...new Set([...group.cars, ...e.cars])];
      } else groups.set(id, { id, msgs: [e], latest: e, cars: [...e.cars], track });
    }
    return [...groups.values()].sort((a, b) => b.latest.t - a.latest.t);
  }, [ctx.stewards, ctx.trackLog]);
  const isOpen = (i: Incident) => !i.track && OPEN_KINDS.has(i.latest.kind);
  const tests: Record<Filter, (i: Incident) => boolean> = {
    all: () => true, open: isOpen, decided: (i) => !i.track && !isOpen(i), track: (i) => i.track,
  };
  const mine = incidents.filter((i) => i.track || !ctx.selected.length || i.cars.some((c) => ctx.selected.includes(c)));
  const shown = mine.filter(tests[filter]);
  const current = shown.find((i) => i.id === picked) ?? shown[0] ?? null;
  const who = current ? current.cars.map(codeOf).join(", ") : "";
  const detail = current ? explain(current.latest, who) : null;
  const offence = current?.msgs.find((m) => m.reason)?.reason;
  const driverOf = (n: number) => ctx.info.drivers?.find((d) => d.driver_number === n);
  const lapOf = (e: RaceControlEvent) => (e.lap != null ? `L${e.lap}` : formatClock(e.t - ctx.info.t_start));

  const switcher = (
    <>
      <LapCounter lap={ctx.state?.leader_lap ?? 0} total={ctx.info.total_laps} />
      <div className="segmented" role="radiogroup" aria-label="Filter">
        {([["all", "All"], ["open", "Open"], ["decided", "Decided"], ["track", "Track"]] as [Filter, string][]).map(([f, text]) => (
          <button key={f} type="button" role="radio" aria-checked={filter === f} aria-label={text} className={filter === f ? "is-on" : ""}
                  onClick={() => setFilter(f)}>{text} <span className="num">{mine.filter(tests[f]).length}</span></button>
        ))}
      </div>
    </>
  );
  return (
    <div className="screen">
      {header(switcher)}
      <main className="screen-body stewards-body">
        <KpiRow tiles={stewardsTiles(ctx.stewards ?? [])} />
        <div className="stewards-grid">
          <section className="panel" aria-label="Incidents">
            <div className="panel-bar">
              <h2>Incidents</h2>
              <span className="panel-meta">newest first · click one for the details{ctx.selected.length ? ` · ${ctx.selected.map(codeOf).join(" and ")} only` : ""}</span>
            </div>
            {shown.length === 0 ? <p className="empty">Nothing from race control here yet.</p> : (
              <div className="stewards-list">
                {shown.map((i) => (
                  <button key={i.id} type="button" aria-pressed={current?.id === i.id}
                          className={`stewards-inc${current?.id === i.id ? " is-selected" : ""}`} onClick={() => setPicked(i.id)}>
                    <span className="stewards-when"><b className="num">{lapOf(i.latest)}</b><span className="num">{formatClock(i.latest.t - ctx.info.t_start)}</span></span>
                    <span className="stewards-what">
                      <b>{sentence(i.track ? i.latest.message : i.msgs.find((m) => m.reason)?.reason ?? i.latest.message)}</b>
                      {i.cars.length > 0 && (
                        <span className="stewards-cars">
                          {i.cars.map((c) => <span key={c} className="num"><i style={{ background: `#${driverOf(c)?.team_color ?? "777"}` }} />{codeOf(c)}</span>)}
                        </span>
                      )}
                    </span>
                    {i.track ? <span className={`rc-dot is-${tone(i.latest)}`} aria-hidden="true" />
                      : <span className={`rc-tag is-${tone(i.latest)}`}>{verdictLabel(i.latest)}</span>}
                  </button>
                ))}
              </div>
            )}
          </section>
          <section className="panel" aria-label="Incident details" aria-live="polite">
            {detail && current ? (
              <>
                <div className="panel-bar">
                  {!current.track && <span className={`rc-tag is-${tone(current.latest)}`}>{verdictLabel(current.latest)}</span>}
                  <h2 className="stewards-title">{detail.title}</h2>
                  <span className="panel-meta">{current.latest.lap != null ? `Lap ${current.latest.lap}` : formatClock(current.latest.t - ctx.info.t_start)}</span>
                </div>
                <div className="stewards-detail">
                  {current.cars.length > 0 && (
                    <div className="inspector-block">
                      <span className="cap">Cars involved</span>
                      <div className="stewards-chips">
                        {current.cars.map((c) => (
                          <span key={c} className="stewards-chip">
                            <i style={{ background: `#${driverOf(c)?.team_color ?? "777"}` }} /><b className="num">{codeOf(c)}</b>
                            <span className="panel-meta">#{c} {driverOf(c)?.full_name ?? ""}</span>
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="inspector-figures">
                    <div><span className="cap">{current.track ? "Kind" : "Offence"}</span><b className="stewards-fact">{current.track ? detail.kind : offence ? sentence(offence) : "Not given"}</b></div>
                    <div><span className="cap">Outcome</span><b className="stewards-fact">{detail.status}</b></div>
                    <div><span className="cap">Effect on the race</span><b className="stewards-fact">{detail.effect}</b></div>
                  </div>
                  <p className="inspector-note">{detail.body}</p>
                  <div className="inspector-block">
                    <span className="cap">Race control messages</span>
                    <ol className="stewards-timeline">
                      {current.msgs.map((m) => (
                        <li key={`${m.t}:${m.message}`} className={`is-${tone(m)}`}>
                          <span className="num">{lapOf(m)} · {formatClock(m.t - ctx.info.t_start)}</span>
                          <q>{m.message}</q>
                        </li>
                      ))}
                    </ol>
                  </div>
                </div>
              </>
            ) : <p className="empty">Pick an incident to see what it means.</p>}
          </section>
        </div>
      </main>
    </div>
  );
}

const PENALTY_KINDS = new Set(["time_penalty", "stop_go", "drive_through", "disqualified"]);
const VERDICT_KINDS = new Set([...PENALTY_KINDS, "no_further_action", "reprimand", "warning", "served"]);

/**
 * The stewards' headline figures as of the clock: incidents still open (an
 * investigation with no verdict since, matched by the incident or, without
 * one, by the cars), penalties given, no further action, and lap times deleted.
 */
export function stewardsTiles(events: RaceControlEvent[]) {
  const key = (e: RaceControlEvent) => e.incident ?? [...e.cars].sort().join(",");
  const open = new Set<string>();
  for (const e of [...events].sort((a, b) => a.t - b.t)) {
    if (e.kind === "under_investigation" || e.kind === "investigate_after_race") open.add(key(e));
    else if (VERDICT_KINDS.has(e.kind)) open.delete(key(e));
  }
  const count = (test: (e: RaceControlEvent) => boolean) => events.filter(test).length;
  return [
    { label: "Under investigation", value: String(open.size), note: "no verdict yet", tone: open.size ? "bad" as const : undefined },
    { label: "Penalties", value: String(count((e) => PENALTY_KINDS.has(e.kind))), note: "time, stop/go, drive-through" },
    { label: "No further action", value: String(count((e) => e.kind === "no_further_action")), note: "investigated and cleared" },
    { label: "Lap times deleted", value: String(count((e) => e.kind === "lap_deleted")), note: "track limits, mostly" },
  ];
}
