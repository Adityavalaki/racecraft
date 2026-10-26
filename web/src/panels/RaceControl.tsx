import { memo } from "react";
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

/**
 * Race control in one list, newest first: the stewards' verdicts and what
 * happened to the track, side by side in time. A verdict carries its tag
 * (after the race, a time penalty); the full story, filtered by car, is the
 * Stewards screen.
 */
export const RaceControl = memo(function RaceControl({ stewards, trackLog, start, codes }: Props) {
  const all = [...(Array.isArray(stewards) ? stewards : []), ...(Array.isArray(trackLog) ? trackLog : [])]
    .filter((event) => event && event.message && event.kind !== "lap_deleted")
    .sort((a, b) => b.t - a.t);
  const investigations = all.filter((event) => INVESTIGATIONS.has(event.kind)).length;
  return (
    <section className="panel race-control" aria-label="Race control">
      <div className="panel-bar">
        <h2>Race control</h2>
        {investigations > 0 && (
          <span className="panel-meta">{investigations} investigation{investigations === 1 ? "" : "s"}</span>
        )}
      </div>
      {all.length === 0 ? (
        <p className="empty">Nothing from race control yet.</p>
      ) : (
        <ol className="rc-rows">
          {all.map((event, index) => {
            const isVerdict = event.stewards || event.topic === "stewards";
            const who = event.cars.map((car) => codes[car] ?? car).join(", ");
            const text = isVerdict && who && event.reason
              ? `${who}: ${sentence(event.reason)}`
              : sentence(event.message);
            return (
              <li key={`${event.t}-${index}`} className="rc-row">
                <span className="rc-when num">{event.lap != null ? `L${event.lap}` : formatClock(event.t - start)}</span>
                <span className={`rc-dot is-${tone(event)}`} aria-hidden="true" />
                <span className="rc-text">
                  {text}
                  {isVerdict && <span className={`rc-tag is-${tone(event)}`}>{verdictLabel(event)}</span>}
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
});
