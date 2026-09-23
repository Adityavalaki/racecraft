import { memo } from "react";
import { formatClock, type RaceControlEvent } from "../api";

interface Props {
  /** Verdicts only: what the server returns for `topic=stewards`. */
  events: RaceControlEvent[];
  start: number;
  /** Driver codes by car number, so a message names who rather than what number. */
  codes: Record<number, string>;
  selected: number[];
  onSelect: (driverNumber: number) => void;
}

/**
 * Verdicts the panel leaves to the tower.
 *
 * A deleted lap time is **47% of every steward message** in the lake — 1,533 of
 * 3,257 — and in a race it is a track-limits tick rather than news: what matters
 * is how many a car has collected, because that is what earns a black-and-white
 * flag and then a penalty. The tower's PEN column already carries that count per
 * car, and its tooltip spells it out, so repeating each one here would fill half
 * the panel with the one thing already shown elsewhere.
 *
 * Nothing is lost: the messages are still served by the API, still counted
 * against the driver, and still in the tooltip. Empty this set to show them.
 */
const HIDDEN = new Set(["lap_deleted"]);

/**
 * What the stewards have said, as of wherever the clock is.
 *
 * Its own panel beside the map rather than a tab, because it is watched rather
 * than consulted: a penalty is news, and news behind a tab is news nobody sees.
 *
 * Only the stewards: what happened to the track is its own panel, `TrackLog`,
 * below this one, because the two are read differently. This one is scanned for
 * a car, so it follows the tower's selection, and it has no control of its own.
 *
 * What counts as the stewards' is decided server-side by whether the message
 * carries a verdict, not by its `FIA STEWARDS:` prefix — only 971 of the 3,257
 * in the lake have one. See `api/penalties.Event.stewards`.
 */
export const Stewards = memo(function Stewards({
  events,
  start,
  codes,
  selected,
  onSelect,
}: Props) {
  // Defensive about the shape, not about the data: this panel is on screen for
  // the whole session, and a response that arrives without `cars` — a schema
  // change, a truncated body, an error object — must not take the app down with
  // it. Anything unreadable is simply not shown.
  const readable = Array.isArray(events)
    ? events.filter((event) => event && Array.isArray(event.cars))
    : [];
  const all = readable.filter((event) => !HIDDEN.has(event.kind));
  const shown = selected.length
    ? all.filter((event) => event.cars.some((car) => selected.includes(car)))
    : all;

  if (shown.length === 0) {
    return (
      <p className="empty">
        {selected.length ? "Nothing about these cars yet." : "The stewards have said nothing yet."}
      </p>
    );
  }
  return (
    <ol className="stw-rows">
      {shown.map((event, index) => (
        <li key={`${event.t}-${index}`} className={`stw-row is-${weight(event.kind)}`}>
          <span className="stw-when">{when(event, start)}</span>
          <span className="stw-body">
            <span className="stw-line">
              {event.cars.length === 0 ? (
                <span className="stw-nocar" title="no car named">–</span>
              ) : (
                event.cars.map((car) => (
                  <button
                    key={car}
                    className={`rc-car${selected.includes(car) ? " is-selected" : ""}`}
                    onClick={() => onSelect(car)}
                    aria-pressed={selected.includes(car)}
                    aria-label={`Select ${codes[car] ?? car}`}
                  >
                    {codes[car] ?? car}
                  </button>
                ))
              )}
              <span className="stw-verdict">{verdictLabel(event)}</span>
            </span>
            {event.reason && (
              <span className="stw-reason" title={event.message}>
                {event.reason}
              </span>
            )}
          </span>
        </li>
      ))}
    </ol>
  );
});

/**
 * The verdict in as few characters as carry its meaning.
 *
 * `served` is spelled out rather than shown as the amount, because a served
 * penalty and an awarded one of the same size are opposite news and reading the
 * number alone would lose that.
 */
export function verdictLabel(event: RaceControlEvent): string {
  switch (event.kind) {
    case "time_penalty":
      return event.seconds != null ? `+${event.seconds}s PENALTY` : "TIME PENALTY";
    case "stop_go":
      return event.seconds != null ? `${event.seconds}s STOP/GO` : "STOP/GO";
    case "drive_through":
      return "DRIVE THROUGH";
    case "served":
      return "SERVED";
    case "disqualified":
      return "BLACK FLAG";
    case "under_investigation":
      return "INVESTIGATING";
    case "investigate_after_race":
      return "AFTER RACE";
    case "no_further_action":
      return "NO ACTION";
    case "noted":
      return "NOTED";
    case "lap_deleted":
      return "LAP DELETED";
    case "black_and_white":
      return "BLACK/WHITE";
    case "reprimand":
      return "REPRIMAND";
    case "warning":
      return "WARNING";
    default:
      return event.kind.replace(/_/g, " ").toUpperCase();
  }
}

/** The lap if the feed gave one, otherwise the session clock. */
function when(event: RaceControlEvent, start: number): string {
  return event.lap != null ? `L${event.lap}` : formatClock(event.t - start);
}

/** Three weights, because a log where everything is emphasised emphasises nothing. */
function weight(kind: string): "loud" | "mid" | "quiet" {
  if (kind === "time_penalty" || kind === "stop_go" || kind === "drive_through" || kind === "disqualified") {
    return "loud";
  }
  if (kind === "under_investigation" || kind === "investigate_after_race" || kind === "served") {
    return "mid";
  }
  return "quiet";
}

/** Who the stewards' panel is currently narrowed to, for its heading. */
export function filterLabel(selected: number[], codes: Record<number, string>): string | null {
  if (!selected.length) return null;
  return `${selected.map((car) => codes[car] ?? car).join(" · ")} only`;
}
