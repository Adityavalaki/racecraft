import { useEffect, useRef, useState } from "react";
import { api, type Frames } from "./api";

/**
 * Car positions for the track map, buffered ahead of the clock.
 *
 * Asking the server for every animation frame would mean dozens of requests a
 * second, so a window of positions is fetched at a fixed rate and the map
 * interpolates locally between samples.
 *
 * The fetching deliberately does not live in an effect keyed on the clock.
 * An earlier version did, and since the clock changes ~60 times a second, each
 * tick tore down the previous effect and aborted the request it had started:
 * the buffer never arrived and the cars sat still. Anything that re-rendered
 * the app — selecting a driver, for instance — froze the map the same way.
 * Instead a timer looks at the latest clock value held in a ref, and requests
 * are only aborted when the session changes or the component goes away.
 */
const WINDOW_S = 30;
const SAMPLE_HZ = 5;
const REFETCH_AT = 0.6; // fraction of the window consumed before fetching the next
const CHECK_MS = 120;

export interface Positions {
  at: (t: number) => Record<number, { x: number; y: number }>;
  loading: boolean;
}

export function usePositions(sessionKey: string | null, t: number, enabled: boolean): Positions {
  const buffer = useRef<Frames | null>(null);
  const clock = useRef(t);
  const fetching = useRef(false);
  const [, setVersion] = useState(0);
  const [loading, setLoading] = useState(false);
  clock.current = t;

  useEffect(() => {
    buffer.current = null;
    if (!sessionKey || !enabled) return;

    const controller = new AbortController();
    let stopped = false;

    const maybeFetch = () => {
      if (stopped || fetching.current) return;
      const held = buffer.current;
      const now = clock.current;
      const covered = held !== null && held.t.length > 0;
      const first = covered ? held!.t[0]! : 0;
      const last = covered ? held!.t[held!.t.length - 1]! : 0;
      const outside = !covered || now < first - 1 || now > last;
      const consumed = covered && last > first ? (now - first) / (last - first) : 1;
      if (!outside && consumed < REFETCH_AT) return;

      // Continue from the end of the buffer when merely running low, and
      // start fresh at the clock after a seek that landed outside it.
      const start = outside ? now : last;
      fetching.current = true;
      setLoading(true);
      api
        .frames(sessionKey, start, start + WINDOW_S, SAMPLE_HZ, controller.signal)
        .then((frames) => {
          if (stopped) return;
          const previous = buffer.current;
          buffer.current = !outside && previous ? mergeFrames(previous, frames) : frames;
          setVersion((v) => v + 1);
        })
        .catch((error) => {
          if (error.name !== "AbortError") console.error(error);
        })
        .finally(() => {
          fetching.current = false;
          if (!stopped) setLoading(false);
        });
    };

    maybeFetch();
    const timer = setInterval(maybeFetch, CHECK_MS);
    return () => {
      stopped = true;
      clearInterval(timer);
      controller.abort();
    };
  }, [sessionKey, enabled]);

  return {
    loading,
    at: (time: number) => sample(buffer.current, time),
  };
}

/** Join a new window onto the tail of the old one, keeping a little history. */
export function mergeFrames(a: Frames, b: Frames): Frames {
  const keep = Math.max(0, a.t.length - SAMPLE_HZ * 5);
  const overlap = b.t.length && a.t.length && b.t[0]! <= a.t[a.t.length - 1]! ? 1 : 0;
  const merged: Frames = { t: [...a.t.slice(keep), ...b.t.slice(overlap)], drivers: {} };
  for (const number of new Set([...Object.keys(a.drivers), ...Object.keys(b.drivers)])) {
    const left = a.drivers[number] ?? { x: [], y: [] };
    const right = b.drivers[number] ?? { x: [], y: [] };
    merged.drivers[number] = {
      x: [...left.x.slice(keep), ...right.x.slice(overlap)],
      y: [...left.y.slice(keep), ...right.y.slice(overlap)],
    };
  }
  return merged;
}

/** Linear interpolation between the two samples either side of `time`. */
export function sample(frames: Frames | null, time: number): Record<number, { x: number; y: number }> {
  const out: Record<number, { x: number; y: number }> = {};
  if (!frames || frames.t.length === 0) return out;

  let hi = frames.t.findIndex((value) => value >= time);
  if (hi === -1) hi = frames.t.length - 1;
  const lo = Math.max(0, hi - 1);
  const t0 = frames.t[lo]!;
  const t1 = frames.t[hi]!;
  const mix = t1 > t0 ? Math.min(1, Math.max(0, (time - t0) / (t1 - t0))) : 0;

  for (const [number, series] of Object.entries(frames.drivers)) {
    const x0 = series.x[lo];
    const y0 = series.y[lo];
    const x1 = series.x[hi];
    const y1 = series.y[hi];
    if (x0 === null || y0 === null || x0 === undefined || y0 === undefined) continue;
    const x = x1 === null || x1 === undefined ? x0 : x0 + (x1 - x0) * mix;
    const y = y1 === null || y1 === undefined ? y0 : y0 + (y1 - y0) * mix;
    out[Number(number)] = { x, y };
  }
  return out;
}
