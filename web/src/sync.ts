import { useCallback, useEffect, useRef, useState } from "react";

/**
 * The replay window and the feature windows, kept on one clock.
 *
 * The replay window owns the clock. It tells every feature window where it is
 * — the session, the time, playing or not, the speed, the drivers picked —
 * ten times a second while playing and at once on any change. A feature
 * window follows that, and sends its own requests back (seek, play/pause,
 * pick a driver) for the replay window to carry out, so there is only ever
 * one clock and every window agrees with it.
 *
 * It runs over a BroadcastChannel: every window of the desktop app shares one
 * WebView2 profile, and every tab of a browser shares its own, so the windows
 * reach each other without the server. Checked in the desktop app: messages
 * cross at full rate, and a replay window covered by a feature window keeps
 * its timers and animation frames running at full speed.
 */

export interface ClockState {
  session: string;
  t: number;
  playing: boolean;
  speed: number;
  following: boolean;
  selected: number[];
}

export type SyncMessage =
  | { type: "clock"; state: ClockState }
  | { type: "hello" }
  | { type: "seek"; t: number }
  | { type: "toggle" }
  | { type: "select"; driver: number };

export const CHANNEL = "racecraft";

/** How often the replay window speaks while playing. */
export const CLOCK_INTERVAL_MS = 100;

/** A feature window that has heard nothing for this long says so. */
export const SILENCE_MS = 3000;

function openChannel(): BroadcastChannel | null {
  return typeof BroadcastChannel === "undefined" ? null : new BroadcastChannel(CHANNEL);
}

export interface ReplayHandlers {
  seek: (t: number) => void;
  toggle: () => void;
  select: (driver: number) => void;
}

/**
 * The replay window's side: tell the feature windows where the clock is, and
 * carry out what they ask.
 */
export function useReplayBroadcast(state: ClockState | null, handlers: ReplayHandlers): void {
  const channel = useRef<BroadcastChannel | null>(null);
  const latest = useRef(state);
  latest.current = state;
  const act = useRef(handlers);
  act.current = handlers;

  const post = useCallback(() => {
    if (channel.current && latest.current) {
      channel.current.postMessage({ type: "clock", state: latest.current } satisfies SyncMessage);
    }
  }, []);

  useEffect(() => {
    const opened = openChannel();
    if (!opened) return;
    channel.current = opened;
    opened.onmessage = (event: MessageEvent<SyncMessage>) => {
      const message = event.data;
      if (!message || typeof message !== "object") return;
      if (message.type === "hello") post();
      else if (message.type === "seek" && Number.isFinite(message.t)) act.current.seek(message.t);
      else if (message.type === "toggle") act.current.toggle();
      else if (message.type === "select" && Number.isFinite(message.driver)) act.current.select(message.driver);
    };
    post();                                         // windows already open learn at once
    return () => {
      opened.close();
      channel.current = null;
    };
  }, [post]);

  // Anything but the time changing is news at once; the time itself is sent on
  // a beat while playing, and at once while paused (someone is scrubbing).
  const selectedKey = state?.selected.join(",");
  useEffect(post, [post, state?.session, state?.playing, state?.speed, state?.following, selectedKey]);
  useEffect(() => {
    if (state && !state.playing) post();
  }, [post, state?.t, state?.playing]);
  useEffect(() => {
    if (!state?.playing) return;
    const timer = setInterval(post, CLOCK_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [post, state?.playing]);
}

export interface FollowedClock {
  /** Where the replay window is; null until it has spoken. */
  state: ClockState | null;
  /** False once the replay window has been silent for SILENCE_MS. */
  connected: boolean;
  seek: (t: number) => void;
  toggle: () => void;
  select: (driver: number) => void;
}

/** A feature window's side: follow the replay window's clock, and ask it for changes. */
export function useFollowedClock(): FollowedClock {
  const channel = useRef<BroadcastChannel | null>(null);
  const [state, setState] = useState<ClockState | null>(null);
  const [connected, setConnected] = useState(true);
  const heardAt = useRef(Date.now());

  useEffect(() => {
    const opened = openChannel();
    if (!opened) {
      setConnected(false);
      return;
    }
    channel.current = opened;
    opened.onmessage = (event: MessageEvent<SyncMessage>) => {
      const message = event.data;
      if (message?.type !== "clock") return;
      heardAt.current = Date.now();
      setConnected(true);
      setState(message.state);
    };
    opened.postMessage({ type: "hello" } satisfies SyncMessage);
    const watch = setInterval(() => {
      if (Date.now() - heardAt.current > SILENCE_MS) setConnected(false);
    }, 1000);
    return () => {
      clearInterval(watch);
      opened.close();
      channel.current = null;
    };
  }, []);

  const send = useCallback((message: SyncMessage) => channel.current?.postMessage(message), []);
  return {
    state,
    connected,
    seek: useCallback((t: number) => send({ type: "seek", t }), [send]),
    toggle: useCallback(() => send({ type: "toggle" }), [send]),
    select: useCallback((driver: number) => send({ type: "select", driver }), [send]),
  };
}
