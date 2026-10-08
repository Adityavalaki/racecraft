import { useEffect, useRef, useState } from "react";
import { api, LIVE_KEY, type LapTrace, type RecentTrace } from "./api";

const isAbort = (e: Error) => e.name === "AbortError";

const isLapTrace = (value: unknown): value is LapTrace =>
  typeof value === "object" && value !== null && Array.isArray((value as LapTrace).distance)
  && Array.isArray((value as LapTrace).x) && Array.isArray((value as LapTrace).brake);

const isRecent = (value: unknown): value is RecentTrace =>
  typeof value === "object" && value !== null && Array.isArray((value as RecentTrace).t)
  && Array.isArray((value as RecentTrace).speed);

/**
 * One finished lap of one car, by distance. Each lap is fetched once and kept:
 * a finished lap never changes, and the pedal map asks again every time the
 * car crosses the line.
 */
const lapCache = new Map<string, LapTrace>();

export function useLapTrace(sessionKey: string | null, driver: number | null, lap: number | null) {
  const [trace, setTrace] = useState<LapTrace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    if (!sessionKey || driver == null || lap == null || lap < 1 || sessionKey === LIVE_KEY) {
      setTrace(null);
      return;
    }
    const key = `${sessionKey}:${driver}:${lap}`;
    const cached = lapCache.get(key);
    if (cached) {
      setTrace(cached);
      return;
    }
    const controller = new AbortController();
    api.lap(sessionKey, driver, { lap }, controller.signal)
      .then((next) => {
        // An error body is JSON too: the shape is checked rather than assumed.
        if (!isLapTrace(next)) {
          setTrace(null);
          setError("This lap came back in a shape the map cannot read.");
          return;
        }
        lapCache.set(key, next);
        setTrace(next);
      })
      .catch((e: Error) => {
        if (isAbort(e)) return;
        setTrace(null);
        setError(e.message);
      });
    return () => controller.abort();
  }, [sessionKey, driver, lap]);

  return { trace, error };
}

/** How far the clock may move before the half-minute behind a card is fetched again. */
export const RECENT_STEP_S = 0.5;

/**
 * The last half-minute of one car, following the clock. While the clock runs
 * it asks again every time it has moved half a second, never with a request
 * already in flight; scrubbing lands on the newest position.
 */
export function useRecent(sessionKey: string | null, driver: number | null, t: number, seconds = 30) {
  const [trace, setTrace] = useState<RecentTrace | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Bumped when an answer lands with the clock already elsewhere, so the
  // newest position is asked for even if the clock has stopped there.
  const [catchUp, setCatchUp] = useState(0);
  const asked = useRef<{ key: string; t: number } | null>(null);
  const inFlight = useRef(false);
  // Which session and driver an answer is for. The clock ticking must not drop
  // an answer in flight, or a playing replay would never show one.
  const generation = useRef(0);
  const latest = useRef(t);
  latest.current = t;

  useEffect(() => {
    generation.current += 1;
    inFlight.current = false;
    setTrace(null);
    setError(null);
    asked.current = null;
  }, [sessionKey, driver]);

  useEffect(() => {
    if (!sessionKey || driver == null || sessionKey === LIVE_KEY || inFlight.current) return;
    const key = `${sessionKey}:${driver}`;
    const now = latest.current;
    if (asked.current?.key === key && Math.abs(asked.current.t - now) < RECENT_STEP_S) return;
    asked.current = { key, t: now };
    inFlight.current = true;
    const mine = generation.current;
    const current = () => generation.current === mine;
    api.recent(sessionKey, driver, now, seconds)
      .then((next) => {
        if (current()) {
          setTrace(isRecent(next) ? next : null);
          setError(isRecent(next) ? null : "The telemetry came back in a shape the card cannot read.");
        }
      })
      .catch((e: Error) => {
        if (current() && !isAbort(e)) setError(e.message);
      })
      .finally(() => {
        if (!current()) return;
        inFlight.current = false;
        if (Math.abs(latest.current - now) >= RECENT_STEP_S) setCatchUp((n) => n + 1);
      });
  }, [sessionKey, driver, t, seconds, catchUp]);

  return { trace, error };
}
