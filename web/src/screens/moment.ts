import { useState } from "react";
import type { StandingsMoment } from "../api";
import type { ScreenContext } from "./ScreenView";

/**
 * Which results a season screen counts. Going into the session, so opening a
 * race gives nothing away, until the replay reaches the end of the race: then
 * it counts, with no click. Scrubbing back undoes that.
 * A choice the reader makes holds until the session changes.
 */
export function useSeasonMoment(ctx: Pick<ScreenContext, "session" | "state" | "info">): [StandingsMoment, (moment: StandingsMoment) => void] {
  const [picked, setPicked] = useState<{ session: string; moment: StandingsMoment } | null>(null);
  const racing = /_(R|S)$/.test(ctx.session);
  // The winner home, at the flag (BUG-017): the car first has finished, with the full distance done.
  // Waiting for every car cost a median 90 s, up to 165 s (113 races and sprints measured).
  // Not any car home: a classified car that stopped early reads "finished" from then on, up to 11
  // minutes before the winner, but it is never first then. The distance check is for red flags: in
  // 2023_03_R the timing ranks SAR first, 57 of 58 laps done, 35 minutes before the flag.
  // A race stopped short of its distance still counts once every car is home, as before.
  const drivers = ctx.state?.drivers ?? [];
  const leader = drivers.find((d) => d.position === 1);
  const distance = ctx.info?.total_laps;
  const winnerHome = leader?.status === "finished" && distance != null && leader.laps_completed >= distance;
  const allHome = drivers.length > 0 && drivers.every((d) => d.status === "finished" || d.status === "out");
  const finished = racing && (winnerHome || allHome);
  const moment = picked?.session === ctx.session ? picked.moment : finished ? "after" : "before";
  return [moment, (next) => setPicked({ session: ctx.session, moment: next })];
}
