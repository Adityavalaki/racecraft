import type { DriverPenalties } from "../api";

/**
 * One car's standing with the stewards, in the tower's narrowest column.
 *
 * This column answers one question — **does this car still owe something?** — and
 * an earlier version tried to answer five, with eight different marks (`DSQ`,
 * `S/G`, `D/T`, `+5s`, `?`, `·`, `✓5s`, `✗3`) that had to be learned before the
 * column meant anything. A glance cannot decode a vocabulary, so it now shows
 * three things and nothing else:
 *
 *   `DSQ`   out of the race
 *   `+5s`   time or a stop still to serve, in seconds where there is a number
 *   `•`     the stewards are looking at this car
 *   `–`     nothing outstanding
 *
 * Everything else the feed said — penalties already served, deleted laps, a
 * black-and-white flag, a reprimand — is settled, changes no decision, and lives
 * in the tooltip and in the Stewards panel beside the map.
 */
export function PenaltyChip({ against }: { against: DriverPenalties | null }) {
  if (!against) return <span className="pen is-none">–</span>;

  const detail = describe(against);

  if (against.disqualified) {
    return <span className="pen is-out" title={detail}>DSQ</span>;
  }
  // A stop/go and a drive-through both cost a trip down the pit lane. Showing
  // the seconds where the feed gave a number and "STOP" where it did not keeps
  // one column meaning one thing: time this car has yet to hand back.
  if (against.pending_s > 0) {
    return <span className="pen is-owed" title={detail}>+{format(against.pending_s)}</span>;
  }
  if (against.stop_go > 0 || against.drive_through > 0) {
    return <span className="pen is-owed" title={detail}>STOP</span>;
  }
  if (against.under_investigation > 0) {
    return <span className="pen is-looking" title={detail}>•</span>;
  }
  return <span className="pen is-none" title={detail}>–</span>;
}

/** 5 -> "5s", 7.5 -> "7.5s". Whole seconds are the normal case. */
function format(seconds: number): string {
  return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)}s`;
}

/**
 * Everything race control has said about this car, as one tooltip.
 *
 * Written out in full: the column is for glancing at, this is for when the
 * glance raised a question. Plain sentences rather than abbreviations, because
 * nothing here needs to be short.
 */
export function describe(against: DriverPenalties): string {
  const lines: string[] = [];
  if (against.disqualified) lines.push("Disqualified — black flag");
  if (against.pending_s > 0) lines.push(`${format(against.pending_s)} still to serve`);
  if (against.stop_go > 0) lines.push(`${against.stop_go} stop/go penalty to serve`);
  if (against.drive_through > 0) lines.push(`${against.drive_through} drive-through to serve`);
  if (against.served_s > 0) lines.push(`${format(against.served_s)} already served`);
  if (against.under_investigation > 0) lines.push(`${against.under_investigation} under investigation`);
  if (against.noted > 0) lines.push(`${against.noted} noted`);
  if (against.cleared > 0) lines.push(`${against.cleared} cleared, no further action`);
  if (against.laps_deleted > 0) {
    lines.push(`${against.laps_deleted} lap time${against.laps_deleted > 1 ? "s" : ""} deleted`);
  }
  if (against.black_and_white > 0) lines.push(`${against.black_and_white} black-and-white flag`);
  if (against.reprimands > 0) lines.push(`${against.reprimands} reprimand`);
  if (against.warnings > 0) lines.push(`${against.warnings} warning`);

  // The offences themselves, so the tooltip says what for and not only how many.
  for (const incident of against.incidents) {
    if (incident.stage === "noted" || incident.stage === "investigating") {
      lines.push(`  ${incident.stage}: ${incident.reason ?? "no reason given"}`);
    }
  }
  return lines.length ? lines.join("\n") : "Nothing from race control";
}
