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
    api.lap(sessionKey, driver, { lap, orEarlier: true }, controller.signal)
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

/** The trace under a card shows this many seconds behind the clock. */
export const TRACE_SECONDS = 30;
const CHECK_MS = 150;
const SAMPLE_HZ = 8;
/** Seconds of telemetry fetched ahead of the clock, at 1x; more at faster replay speeds. */
const AHEAD_S = 15;
const MAX_FETCH_S = 120;

/** A car's telemetry over a stretch of the session, by absolute session time. */
interface Buffer {
  key: string;
  t: number[];
  speed: (number | null)[];
  throttle: (number | null)[];
  brake: (boolean | null)[];
  gear: (number | null)[];
}

/** The car at one instant, between samples: speed and throttle blend, gear and brake hold. */
export interface CarNow {
  speed: number | null;
  throttle: number | null;
  brake: boolean | null;
  gear: number | null;
}

function lowerBound(values: number[], target: number): number {
  let lo = 0;
  let hi = values.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (values[mid]! < target) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** The car at `t`, read off the buffer: what the card's figures show, every frame. */
export function carAt(buffer: Pick<Buffer, "t" | "speed" | "throttle" | "brake" | "gear">, t: number): CarNow | null {
  const n = buffer.t.length;
  if (n < 2 || t < buffer.t[0]! || t > buffer.t[n - 1]!) return null;
  const hi = Math.min(Math.max(lowerBound(buffer.t, t), 1), n - 1);
  const lo = hi - 1;
  const span = buffer.t[hi]! - buffer.t[lo]!;
  const mix = span > 0 ? (t - buffer.t[lo]!) / span : 0;
  const blend = (a: number | null, b: number | null) => (a == null || b == null ? a ?? b : a + (b - a) * mix);
  return {
    speed: blend(buffer.speed[lo] ?? null, buffer.speed[hi] ?? null),
    throttle: blend(buffer.throttle[lo] ?? null, buffer.throttle[hi] ?? null),
    brake: buffer.brake[lo] ?? null,
    gear: buffer.gear[lo] ?? null,
  };
}

/** The last `seconds` before `t`, as a trace relative to `t`: what the card draws. */
export function windowAt(buffer: Buffer, t: number, seconds = TRACE_SECONDS): RecentTrace | null {
  const from = lowerBound(buffer.t, t - seconds);
  const to = lowerBound(buffer.t, t);
  if (to - from < 2) return null;
  return {
    driver_number: 0,
    seconds,
    t: buffer.t.slice(from, to).map((time) => time - t),
    speed: buffer.speed.slice(from, to),
    throttle: buffer.throttle.slice(from, to),
    brake: buffer.brake.slice(from, to),
    gear: buffer.gear.slice(from, to),
  };
}

/**
 * One car's telemetry around the clock, for its card: a half-minute behind
 * and a stretch ahead, fetched in one go and slid along every frame, so the
 * trace scrolls and the speed and gear move smoothly instead of jumping each
 * time an answer lands. It asks again when the clock nears either end, and
 * starts afresh after a seek. As with the map, fetching runs off a timer
 * reading the clock from a ref, so the clock ticking never cancels a request.
 */
export function useTelemetry(sessionKey: string | null, driver: number | null, t: number, speed = 1) {
  const buffer = useRef<Buffer | null>(null);
  const clock = useRef(t);
  const pace = useRef(speed);
  const fetching = useRef(false);
  const [, setVersion] = useState(0);
  const [error, setError] = useState<string | null>(null);
  clock.current = t;
  pace.current = speed;

  useEffect(() => {
    buffer.current = null;
    setError(null);
    setVersion((v) => v + 1);
    if (!sessionKey || driver == null || sessionKey === LIVE_KEY) return;
    const key = `${sessionKey}:${driver}`;
    const controller = new AbortController();
    let stopped = false;

    const maybeFetch = () => {
      if (stopped || fetching.current) return;
      const now = clock.current;
      const held = buffer.current;
      const ahead = Math.min(AHEAD_S * Math.max(1, pace.current), MAX_FETCH_S - TRACE_SECONDS - 5);
      const first = held?.t[0] ?? Infinity;
      const last = held?.t[held.t.length - 1] ?? -Infinity;
      // Enough behind the clock to draw the trace, and enough ahead to keep playing.
      const covered = held !== null && first <= now - TRACE_SECONDS + 1 && last >= now + Math.min(ahead / 3, 10);
      if (covered) return;
      fetching.current = true;
      const end = now + ahead;
      const seconds = TRACE_SECONDS + ahead + 2;
      api.recent(sessionKey, driver, end, seconds, controller.signal)
        .then((next) => {
          if (stopped) return;
          if (!isRecent(next)) {
            setError("The telemetry came back in a shape the card cannot read.");
            return;
          }
          buffer.current = { key, t: next.t.map((offset) => end + offset), speed: next.speed, throttle: next.throttle,
                             brake: next.brake, gear: next.gear };
          setError(null);
          setVersion((v) => v + 1);
        })
        .catch((e: Error) => {
          if (!stopped && !isAbort(e)) setError(e.message);
        })
        .finally(() => {
          fetching.current = false;
        });
    };
    maybeFetch();
    const timer = setInterval(maybeFetch, CHECK_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
      controller.abort();
      fetching.current = false;
    };
  }, [sessionKey, driver]);

  const held = buffer.current;
  return {
    trace: held ? windowAt(held, t) : null,
    now: held ? carAt(held, t) : null,
    error,
    hz: SAMPLE_HZ,
  };
}
