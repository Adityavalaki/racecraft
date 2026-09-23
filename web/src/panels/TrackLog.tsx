import { memo } from "react";
import { formatClock, type RaceControlEvent } from "../api";

interface Props {
  /** What the server returns for `topic=track`: about 18 events a race. */
  events: RaceControlEvent[];
  start: number;
}

/**
 * What happened to the track, in race control's own words.
 *
 * Its own panel, apart from the stewards, because the two are read differently:
 * the stewards are scanned for a car, this is read top to bottom as a log. The
 * safety car, the flags, the pit exit, DRS, a slippery patch, a recovery vehicle.
 *
 * Blue flags and sector flags are not here: together 4,771 messages repeating a
 * state nobody reads a log for, and left in they bury the dozen or so events a
 * race actually has. `api/penalties.Event.topic` draws that line.
 */
export const TrackLog = memo(function TrackLog({ events, start }: Props) {
  // Defensive about the shape: this panel is on screen all session, and one
  // malformed response must not take the app down with it.
  const shown = Array.isArray(events) ? events.filter((event) => event && event.message) : [];
  if (shown.length === 0) {
    return <p className="empty">Nothing from race control yet.</p>;
  }
  return (
    <ol className="log-rows">
      {shown.map((event, index) => (
        <li key={`${event.t}-${index}`} className="log-row">
          <span className="log-when">
            {event.lap != null ? `L${event.lap}` : formatClock(event.t - start)}
          </span>
          <span className="log-text">{event.message}</span>
        </li>
      ))}
    </ol>
  );
});
