import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The session clock: one time cursor the whole interface reads.
 *
 * Replay is this clock advancing; scrubbing is setting it. Panels never keep
 * their own notion of time, which is what keeps the timing tower, the track
 * map and the trace describing the same instant. Live mode, later, is the
 * same clock pinned to now.
 *
 * It advances from the animation frame's own timestamp rather than counting
 * frames, so a dropped frame costs no session time and playback speed stays
 * true when the tab is busy.
 */
export interface Clock {
  t: number;
  playing: boolean;
  speed: number;
  play: () => void;
  pause: () => void;
  toggle: () => void;
  seek: (t: number) => void;
  nudge: (seconds: number) => void;
  setSpeed: (speed: number) => void;
}

export function useClock(start: number, end: number): Clock {
  const [t, setT] = useState(start);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const frame = useRef<number>();
  const previous = useRef<number>();
  const bounds = useRef({ start, end });
  bounds.current = { start, end };

  useEffect(() => setT(start), [start]);

  useEffect(() => {
    if (!playing) {
      previous.current = undefined;
      return;
    }
    const step = (now: number) => {
      const last = previous.current ?? now;
      previous.current = now;
      const delta = ((now - last) / 1000) * speed;
      setT((current) => {
        const next = current + delta;
        if (next >= bounds.current.end) {
          setPlaying(false);
          return bounds.current.end;
        }
        return next;
      });
      frame.current = requestAnimationFrame(step);
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current !== undefined) cancelAnimationFrame(frame.current);
    };
  }, [playing, speed]);

  const seek = useCallback((next: number) => {
    const { start: lo, end: hi } = bounds.current;
    setT(Math.min(hi, Math.max(lo, next)));
  }, []);

  return {
    t,
    playing,
    speed,
    play: useCallback(() => setPlaying(true), []),
    pause: useCallback(() => setPlaying(false), []),
    toggle: useCallback(() => setPlaying((p) => !p), []),
    seek,
    nudge: useCallback((seconds: number) => {
      setT((current) => {
        const { start: lo, end: hi } = bounds.current;
        return Math.min(hi, Math.max(lo, current + seconds));
      });
    }, []),
    setSpeed,
  };
}
