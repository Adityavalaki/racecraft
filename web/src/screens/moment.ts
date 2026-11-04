import { useState } from "react";
import type { StandingsMoment } from "../api";
import type { ScreenContext } from "./ScreenView";

/**
 * Which results a season screen counts. Going into the session, so opening a
 * race gives nothing away, until the replay reaches the end of the race: then
 * it counts, with no click. Scrubbing back undoes that.
 * A choice the reader makes holds until the session changes.
 */
export function useSeasonMoment(ctx: Pick<ScreenContext, "session" | "state">): [StandingsMoment, (moment: StandingsMoment) => void] {
  const [picked, setPicked] = useState<{ session: string; moment: StandingsMoment } | null>(null);
  const racing = /_(R|S)$/.test(ctx.session);
  // Every car home, not any: a classified car that stopped early reads "finished" from then on, up to
  // 11 minutes before the winner. The last car is home within 2 minutes of the winner (55 races measured).
  const drivers = ctx.state?.drivers ?? [];
  const finished = racing && drivers.length > 0 && drivers.every((d) => d.status === "finished" || d.status === "out");
  const moment = picked?.session === ctx.session ? picked.moment : finished ? "after" : "before";
  return [moment, (next) => setPicked({ session: ctx.session, moment: next })];
}
