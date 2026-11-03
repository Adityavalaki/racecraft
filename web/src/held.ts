import { useEffect, useRef, useState } from "react";

/** How long a readout holds a figure: long enough to read it, at every replay speed. */
export const HOLD_MS = 1000;

/**
 * A fast-moving value as a number a person can read: the latest one, once a
 * real second, however fast the replay runs. Nothing is held back from showing
 * at first: a value appearing where there was none shows straight away.
 *
 * For readouts only. The bars beside them, and states that are wrong when late
 * (gear, brake on or off), stay live.
 */
export function useHeld<T>(value: T, ms = HOLD_MS): T {
  const [shown, setShown] = useState(value);
  const latest = useRef(value);
  latest.current = value;
  useEffect(() => {
    const timer = setInterval(() => setShown(latest.current), ms);
    return () => clearInterval(timer);
  }, [ms]);
  useEffect(() => {
    if (shown == null && value != null) setShown(value);
  }, [shown, value]);
  return shown;
}
