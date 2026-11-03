import { useState } from "react";
import type { StandingsMoment } from "../api";
import type { ScreenContext } from "./ScreenView";

/**
 * Which results a season screen counts. Going into the session, so opening a
 * race gives nothing away, until the replay reaches the chequered flag: then
 * the race is over and it counts, with no click. Scrubbing back undoes that.
 * A choice the reader makes holds until the session changes.
 */
export function useSeasonMoment(ctx: Pick<ScreenContext, "session" | "state">): [StandingsMoment, (moment: StandingsMoment) => void] {
  const [picked, setPicked] = useState<{ session: string; moment: StandingsMoment } | null>(null);
  const racing = /_(R|S)$/.test(ctx.session);
  const finished = racing && (ctx.state?.drivers ?? []).some((d) => d.status === "finished");
  const moment = picked?.session === ctx.session ? picked.moment : finished ? "after" : "before";
  return [moment, (next) => setPicked({ session: ctx.session, moment: next })];
}
