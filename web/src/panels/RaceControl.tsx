import { memo, useState } from "react";
import { formatClock, type RaceControlEvent } from "../api";
import { verdictLabel } from "./Stewards";

interface Props {
  /** The stewards' verdicts and the track log, as the server splits them. */
  stewards: RaceControlEvent[];
  trackLog: RaceControlEvent[];
  start: number;
  codes: Record<number, string>;
}

const INVESTIGATIONS = new Set(["under_investigation", "investigate_after_race"]);
const PENALTIES = new Set(["time_penalty", "stop_go", "drive_through", "disqualified"]);
// Kept in capitals when the rest of a message is put in sentence case.
const ACRONYMS = new Set(["DRS", "VSC", "SC", "FIA", "F1", "DNF", "TV"]);

/** Race control writes in capitals; this reads it as a sentence, keeping codes and acronyms. */
export function sentence(message: string): string {
  const lowered = message.toLowerCase().replace(/\s+/g, " ").trim();
  const words = lowered.split(" ").map((word) => {
    const bare = word.replace(/[^a-z0-9]/g, "").toUpperCase();
    return ACRONYMS.has(bare) ? word.toUpperCase() : word;
  });
  const joined = words.join(" ").replace(/\(([a-z]{3})\)/g, (_, code: string) => `(${code.toUpperCase()})`);
  return joined.charAt(0).toUpperCase() + joined.slice(1);
}

/** The colour of a message's dot: what kind of news it is, at a glance. */
export function tone(event: RaceControlEvent): "red" | "amber" | "yellow" | "green" | "plain" {
  if (event.stewards || event.topic === "stewards") {
    if (PENALTIES.has(event.kind)) return "red";
    if (INVESTIGATIONS.has(event.kind)) return "yellow";
    return "plain";
  }
  const text = event.message.toUpperCase();
  if (text.includes("RED FLAG") || text.includes("CLOSED")) return "red";
  if (text.includes("SAFETY CAR") || text.includes("VSC")) return "amber";
  if (text.includes("YELLOW")) return "yellow";
  if (text.includes("GREEN") || text.includes("CLEAR") || text.includes("ENABLED") || text.includes("OPEN")) return "green";
  return "plain";
}

type Filter = "all" | "flags" | "stewards" | "other";

/** Which list a message belongs in: the stewards', the flags and safety cars, or everything else. */
export function groupOf(event: RaceControlEvent): Exclude<Filter, "all"> {
  if (event.stewards || event.topic === "stewards") return "stewards";
  if (event.category === "Flag" || event.category === "SafetyCar") return "flags";
  const text = event.message.toUpperCase();
  if (/FLAG|SAFETY CAR|\bVSC\b|TRACK CLEAR/.test(text)) return "flags";
  return "other";
}

/** A message's category, as the board labels it. */
export function categoryOf(event: RaceControlEvent): string {
  if (event.stewards || event.topic === "stewards") return "Stewards";
  const c = event.category ?? "";
  return ({ Flag: "Flag", SafetyCar: "Safety car", Drs: "DRS", CarEvent: "Car" } as Record<string, string>)[c]
    ?? (groupOf(event) === "flags" ? "Flag" : "Track");
}

const TONE_COLOURS = { red: "#EF4444", amber: "#F59E0B", yellow: "#EAB308", green: "#22C55E", plain: "#8E959F" } as const;

/**
 * Race control in one list, newest first: the stewards' verdicts and what
 * happened to the track, side by side in time, filtered by kind. An
 * investigation with no verdict since is marked open; the full story, by
 * car, is the Stewards screen.
 */
export const RaceControl = memo(function RaceControl({ stewards, trackLog, start, codes }: Props) {
  const [filter, setFilter] = useState<Filter>("all");
  const all = [...(Array.isArray(stewards) ? stewards : []), ...(Array.isArray(trackLog) ? trackLog : [])]
    .filter((event) => event && event.message && event.kind !== "lap_deleted")
    .sort((a, b) => b.t - a.t);
  // Open: an investigation with no verdict since on the same incident (or, without one, the same cars).
  const key = (e: RaceControlEvent) => e.incident ?? [...e.cars].sort().join(",");
  const open = new Set<string>();
  for (const e of [...all].reverse()) {
    if (INVESTIGATIONS.has(e.kind)) open.add(key(e));
    else if (e.stewards && e.kind !== "noted") open.delete(key(e));
  }
  const counts = { flags: 0, stewards: 0, other: 0 };
  for (const e of all) counts[groupOf(e)] += 1;
  const shown = filter === "all" ? all : all.filter((e) => groupOf(e) === filter);
  return (
    <section className="panel race-control" aria-label="Race control">
      <div className="panel-bar">
        <h2>Race control</h2>
        <span className="panel-meta num">{all.length}</span>
        {open.size > 0 && <span className="rc-open"><span className="live-pip" aria-hidden="true" />{open.size} open</span>}
      </div>
      <div className="rc-filters">
        <div className="segmented" role="tablist" aria-label="Messages shown">
          {([["all", "All"], ["flags", "Flags"], ["stewards", "Stewards"], ["other", "Other"]] as [Filter, string][]).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={filter === k} className={filter === k ? "is-on" : ""}
                    onClick={() => setFilter(k)}>
              {label}{k !== "all" && <span className="tab-count num">{counts[k]}</span>}
            </button>
          ))}
        </div>
      </div>
      {shown.length === 0 ? (
        <p className="empty">{all.length === 0 ? "Nothing from race control yet." : "Nothing of this kind yet."}</p>
      ) : (
        <ol className="rc-rows">
          {shown.map((event, index) => {
            const isVerdict = event.stewards || event.topic === "stewards";
            const who = event.cars.map((car) => codes[car] ?? car).join(", ");
            const text = isVerdict && who && event.reason ? `${who}: ${sentence(event.reason)}` : sentence(event.message);
            const colour = TONE_COLOURS[tone(event)];
            const isOpen = INVESTIGATIONS.has(event.kind) && open.has(key(event));
            return (
              <li key={`${event.t}-${index}`} className="rc-row">
                <span className="rc-when">
                  <b className="num">{event.lap != null ? `L${event.lap}` : "—"}</b>
                  <small className="num">{formatClock(event.t - start)}</small>
                </span>
                <span className="rc-body">
                  <span className="rc-cat">
                    <i style={{ background: colour, boxShadow: `0 0 6px ${colour}` }} aria-hidden="true" />{categoryOf(event)}
                    {isOpen && <span className="rc-chip">Under investigation</span>}
                    {isVerdict && !isOpen && <span className={`rc-tag is-${tone(event)}`}>{verdictLabel(event)}</span>}
                  </span>
                  <span className="rc-text">{text}</span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
});
