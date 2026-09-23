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
export const WINDOW_S = 24;
const SAMPLE_HZ = 10;   // twice the old rate: less to invent between samples
const REFETCH_AT = 0.6; // fraction of the window consumed before fetching the next
const CHECK_MS = 120;
/** Seconds of already-played positions kept behind the clock when a window is joined. */
export const HISTORY_S = 5;

/**
 * Whether to fetch now, and from where. `replace` means the result should
 * replace the buffer (after a seek) rather than be joined onto its end.
 */
export function plan(held: Frames | null, now: number): { start: number; replace: boolean } | null {
  const covered = held !== null && held.t.length > 0;
  const first = covered ? held!.t[0]! : 0;
  const last = covered ? held!.t[held!.t.length - 1]! : 0;
  const outside = !covered || now < first - 1 || now > last;
  const consumed = covered && last > first ? (now - first) / (last - first) : 1;
  if (!outside && consumed < REFETCH_AT) return null;
  // Continue from the end of the buffer when merely running low, and start
  // fresh at the clock after a seek that landed outside it.
  return { start: outside ? now : last, replace: outside };
}

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
      const next = plan(buffer.current, clock.current);
      if (!next) return;
      const { start, replace: outside } = next;
      fetching.current = true;
      setLoading(true);
      api
        .frames(sessionKey, start, start + WINDOW_S, SAMPLE_HZ, controller.signal)
        .then((frames) => {
          if (stopped) return;
          const previous = buffer.current;
          buffer.current = !outside && previous
            ? mergeFrames(previous, frames, clock.current - HISTORY_S)
            : frames;
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

/**
 * Join a new window onto the tail of the old one, keeping the old samples from
 * `keepFrom` on — the caller passes a few seconds behind the clock.
 *
 * The history kept has to be measured from the clock, not from the end of the
 * old window. It used to be the old window's last five seconds, but the next
 * window is fetched with 40% of the old one still to play: the clock sat ten
 * seconds short of the end, so it fell before the joined buffer, every car was
 * pinned to the buffer's first sample — about 4.6 s of racing ahead — and the
 * next check found the clock outside the buffer, fetched afresh and snapped
 * every car back. At 5x that was a jump forward and back every three seconds.
 */
export function mergeFrames(a: Frames, b: Frames, keepFrom = -Infinity): Frames {
  const from = a.t.findIndex((value) => value >= keepFrom);
  // Everything is older than `keepFrom`: keep one sample so the join still
  // has a left-hand neighbour to curve from.
  const keep = from === -1 ? Math.max(0, a.t.length - 1) : from;
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

/**
 * Where every car is at `time`, interpolated between samples.
 *
 * Straight lines between samples make a car visibly corner in facets and
 * change speed at every sample. A Catmull-Rom curve through the surrounding
 * four points follows the arc instead, and because the curve passes exactly
 * through the real samples it smooths the path without inventing a different
 * one. Two samples are enough for a straight line if neighbours are missing.
 */
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
    const x1 = series.x[lo];
    const y1 = series.y[lo];
    if (x1 === null || y1 === null || x1 === undefined || y1 === undefined) continue;
    const x2 = series.x[hi];
    const y2 = series.y[hi];
    if (x2 === null || y2 === null || x2 === undefined || y2 === undefined) {
      out[Number(number)] = { x: x1, y: y1 };     // hold position rather than guess
      continue;
    }
    // At the ends of the buffer the missing neighbour is reflected rather than
    // duplicated: duplicating bends a straight line, so a car on a straight
    // would appear to slow down at the seam between two fetched windows.
    const x0 = valueOr(series.x[lo - 1], 2 * x1 - x2);
    const y0 = valueOr(series.y[lo - 1], 2 * y1 - y2);
    const x3 = valueOr(series.x[hi + 1], 2 * x2 - x1);
    const y3 = valueOr(series.y[hi + 1], 2 * y2 - y1);
    out[Number(number)] = {
      x: catmullRom(x0, x1, x2, x3, mix),
      y: catmullRom(y0, y1, y2, y3, mix),
    };
  }
  return out;
}

function valueOr(value: number | null | undefined, fallback: number): number {
  return value === null || value === undefined ? fallback : value;
}

/** Curve through p1 and p2, shaped by their neighbours. */
function catmullRom(p0: number, p1: number, p2: number, p3: number, t: number): number {
  const t2 = t * t;
  const t3 = t2 * t;
  return 0.5 * ((2 * p1)
    + (-p0 + p2) * t
    + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
    + (-p0 + 3 * p1 - 3 * p2 + p3) * t3);
}
