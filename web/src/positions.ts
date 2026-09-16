import { useEffect, useRef, useState } from "react";
import { api, type Frames } from "./api";

/**
 * Car positions for the track map, buffered ahead of the clock.
 *
 * Asking the server for every animation frame would mean dozens of requests a
 * second. Instead a window of positions is fetched at a fixed rate and the map
 * interpolates between samples locally; the next window is fetched once the
 * clock passes most of the way through the current one. Scrubbing far away
 * throws the buffer out and starts again.
 */
const WINDOW_S = 30;
const SAMPLE_HZ = 5;
const REFETCH_AT = 0.7; // fraction of the window consumed before fetching the next

export interface Positions {
  at: (t: number) => Record<number, { x: number; y: number }>;
  loading: boolean;
}

export function usePositions(sessionKey: string | null, t: number, enabled: boolean): Positions {
  const buffer = useRef<Frames | null>(null);
  const pending = useRef<{ start: number; end: number } | null>(null);
  const [, setVersion] = useState(0);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    buffer.current = null;
    pending.current = null;
  }, [sessionKey]);

  useEffect(() => {
    if (!sessionKey || !enabled) return;
    const current = buffer.current;
    const covered = current && current.t.length > 0;
    const first = covered ? current.t[0]! : 0;
    const last = covered ? current.t[current.t.length - 1]! : 0;
    const consumed = covered ? (t - first) / Math.max(1e-6, last - first) : 1;
    const needsMore = !covered || t < first || t > last || consumed > REFETCH_AT;
    if (!needsMore) return;

    const start = !covered || t < first || t > last ? t : last;
    if (pending.current && pending.current.start === start) return;
    pending.current = { start, end: start + WINDOW_S };

    const controller = new AbortController();
    setLoading(true);
    api
      .frames(sessionKey, start, start + WINDOW_S, SAMPLE_HZ, controller.signal)
      .then((frames) => {
        const previous = buffer.current;
        // Keep the tail of the old window so the map does not blink while the
        // clock crosses the seam between two fetches.
        buffer.current =
          previous && previous.t.length && start === previous.t[previous.t.length - 1]
            ? mergeFrames(previous, frames)
            : frames;
        setVersion((v) => v + 1);
      })
      .catch((error) => {
        if (error.name !== "AbortError") console.error(error);
      })
      .finally(() => {
        pending.current = null;
        setLoading(false);
      });
    return () => controller.abort();
  }, [sessionKey, t, enabled]);

  return {
    loading,
    at: (time: number) => sample(buffer.current, time),
  };
}

function mergeFrames(a: Frames, b: Frames): Frames {
  const keep = Math.max(0, a.t.length - SAMPLE_HZ * 5); // about five seconds of history
  const merged: Frames = { t: [...a.t.slice(keep), ...b.t], drivers: {} };
  for (const number of new Set([...Object.keys(a.drivers), ...Object.keys(b.drivers)])) {
    const left = a.drivers[number] ?? { x: [], y: [] };
    const right = b.drivers[number] ?? { x: [], y: [] };
    merged.drivers[number] = {
      x: [...left.x.slice(keep), ...right.x],
      y: [...left.y.slice(keep), ...right.y],
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
