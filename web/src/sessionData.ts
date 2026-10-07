import { useCallback, useEffect, useRef, useState } from "react";
import {
  HttpError,
  LIVE_KEY,
  api,
  type Insight,
  type LapSeries,
  type RaceControlEvent,
  type SessionInfo,
  type SessionState,
  type SessionSummary,
} from "./api";

/**
 * Reading a session from the server: the session list, the session itself,
 * the running order at the clock's time, and race control.
 *
 * Shared by the replay window and every feature window, so the protections
 * built up here apply in all of them: a slow answer for a session no longer
 * shown never lands, an older live refresh never replaces a newer one, live
 * waits for its recording rather than failing, and a model fit is asked for
 * only when something on screen needs it.
 */

/** How often the running order refreshes while playing. Positions animate separately and far more often. */
export const STATE_INTERVAL_MS = 400;

/**
 * How often a live session is re-read. The server re-parses its recording at
 * the same cadence, and a lap takes over a minute, so this is far finer than
 * the data changes and far coarser than re-parsing on every poll would be.
 */
export const LIVE_INTERVAL_MS = 10_000;

/** Where reading the session list has got. An empty list is an answer, not a failure. */
export type ListState = { status: "loading" } | { status: "loaded" } | { status: "failed"; message: string };

/**
 * The session to open when none is chosen yet. Live first when there is one: a
 * recording exists only because someone started it, which is as clear a
 * statement of intent as the interface is going to get. Otherwise the newest
 * race (the list is newest first), otherwise whatever there is.
 */
export function defaultSession(all: SessionSummary[]): string | null {
  const opening = all.find((s) => s.session_key === LIVE_KEY)
    ?? all.find((s) => s.session === "R")
    ?? all[0];
  return opening?.session_key ?? null;
}

/**
 * When a lap began: the leader's crossing of the lap before it, or the start
 * of the session for the first lap (or one the leader never completed).
 */
export function lapStartTime(lap: number, crossings: { laps: number[]; t: number[] } | null,
                             tStart: number): number {
  if (!crossings) return tStart;
  const index = crossings.laps.indexOf(lap - 1);
  return index === -1 ? tStart : crossings.t[index] ?? tStart;
}

/** Live answers 409 until it has a recording to read and something in it. */
export function isNotReady(error: unknown): boolean {
  return error instanceof HttpError && error.status === 409;
}

function reportUnlessAborted(setError: (message: string) => void) {
  return (error: Error) => {
    if (error.name !== "AbortError") setError(String(error.message ?? error));
  };
}

/** The sessions in the lake (and live), and which one is open. */
export function useSessionList() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [listState, setListState] = useState<ListState>({ status: "loading" });
  const [sessionKey, setSessionKey] = useState<string | null>(null);

  // A list that arrives picks a session only if none is open: the first sync
  // on a new install fills an empty picker, and a later one leaves the session
  // being viewed alone.
  const takeSessions = useCallback((all: SessionSummary[]) => {
    setSessions(all);
    setListState({ status: "loaded" });
    setSessionKey((current) => current ?? defaultSession(all));
  }, []);

  // Every read of the list is numbered, and one older than the list already
  // shown is dropped: a slow first read must not replace the list a later sync
  // brought, nor pick a session over it.
  const listRequest = useRef(0);
  const listShown = useRef(0);
  const takeNewestSessions = useCallback((request: number, all: SessionSummary[]) => {
    if (request < listShown.current) return;
    listShown.current = request;
    takeSessions(all);
  }, [takeSessions]);

  // After a sync writes new sessions, the list is read again so they appear in
  // the picker. A failure here keeps the list already shown.
  const reloadSessions = useCallback(() => {
    const request = ++listRequest.current;
    api.sessions().then((all) => takeNewestSessions(request, all)).catch(() => undefined);
  }, [takeNewestSessions]);

  useEffect(() => {
    let active = true;
    const request = ++listRequest.current;
    api.sessions()
      .then((all) => {
        if (active) takeNewestSessions(request, all);
      })
      .catch((e) => {
        if (active && listShown.current === 0) {
          setListState({ status: "failed", message: String(e.message ?? e) });
        }
      });
    return () => {
      active = false;
    };
  }, [takeNewestSessions]);

  return { sessions, listState, sessionKey, setSessionKey, reloadSessions };
}

export interface LoadedSession {
  info: SessionInfo | null;
  laps: LapSeries[];
  crossings: { laps: number[]; t: number[] } | null;
  error: string | null;
  /** Live is open but its recording has nothing to show yet. */
  waiting: boolean;
  insight: Insight | null;
  insightError: string | null;
}

/**
 * One session: its info and lap chart, re-read while live, and the models'
 * fit when `wantsInsight` (fitting a season costs seconds, so it is asked for
 * only when something on screen needs it, and then kept).
 */
export function useSession(sessionKey: string | null, wantsInsight: boolean): LoadedSession {
  const [info, setInfo] = useState<SessionInfo | null>(null);
  const [laps, setLaps] = useState<LapSeries[]>([]);
  const [crossings, setCrossings] = useState<{ laps: number[]; t: number[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  // The models' answer, and why there is none, each kept with the session it
  // is for: another session's result or failure must not stand in for, or
  // hold back, this one's.
  const [insightEntry, setInsightEntry] = useState<{ key: string; insight: Insight } | null>(null);
  const [insightFailure, setInsightFailure] = useState<{ key: string; message: string } | null>(null);
  // Bumped when a live session moves on, so a fit asked for before is dropped.
  const [insightGeneration, setInsightGeneration] = useState(0);
  const insight = insightEntry?.key === sessionKey ? insightEntry.insight : null;
  const insightError = insightFailure?.key === sessionKey ? insightFailure.message : null;
  // Live is selected before it has anything to show: the recorder may not have
  // started, or the server may have restarted and let go of the recording.
  // Waiting is that state, shown as such rather than as an error.
  const [waiting, setWaiting] = useState(false);
  const waitingRef = useRef(false);
  waitingRef.current = waiting;
  const isLive = sessionKey === LIVE_KEY;

  // Info and laps are asked for by the first load and again by every live
  // refresh. Each request is numbered, and a response older than one already
  // shown is dropped, so a slow early answer cannot move the live edge back.
  const infoRequest = useRef(0);
  const shown = useRef({ info: 0, laps: 0 });
  const newest = useCallback((kind: "info" | "laps", request: number) => {
    if (request < shown.current[kind]) return false;
    shown.current[kind] = request;
    return true;
  }, []);

  useEffect(() => {
    if (!sessionKey) return;
    // Aborting stops the requests; `active` also stops any answer that arrives
    // anyway, success or failure, once another session has been picked.
    let active = true;
    const controller = new AbortController();
    const current = () => active && !controller.signal.aborted;
    setInfo(null);
    setLaps([]);
    setCrossings(null);
    setError(null);
    setInsightEntry(null);
    setInsightFailure(null);
    setWaiting(false);
    // Not ready yet is waiting, for live; anything else is an error.
    const report = reportUnlessAborted(setError);
    const fail = (failure: Error) => {
      if (!current()) return;
      if (sessionKey === LIVE_KEY && isNotReady(failure)) setWaiting(true);
      else report(failure);
    };
    const load = () => {
      const request = ++infoRequest.current;
      api
        .info(sessionKey, controller.signal)
        .then((next) => {
          if (current() && newest("info", request)) setInfo(next);
        })
        .catch(fail);
      api
        .laps(sessionKey, controller.signal)
        .then((chart) => {
          if (!current() || !newest("laps", request)) return;
          setLaps(chart.drivers);
          setCrossings(chart.leader_crossings);
        })
        .catch(fail);
    };
    // Live is served from whatever recording the server is attached to, and a
    // server that has just started is attached to none: attach, then read.
    if (sessionKey === LIVE_KEY) {
      api
        .liveAttach(controller.signal)
        .then(() => {
          if (current()) load();
        })
        .catch(fail);
    } else {
      load();
    }
    return () => {
      active = false;
      controller.abort();
    };
  }, [sessionKey, newest]);

  // A failed fit is asked for again when a model view is opened again, rather
  // than showing the old failure until another session is picked. A fit that
  // worked is kept, and shared by every model view.
  const wantedInsight = useRef(wantsInsight);
  useEffect(() => {
    if (wantsInsight && !wantedInsight.current) setInsightFailure(null);
    wantedInsight.current = wantsInsight;
  }, [wantsInsight]);

  useEffect(() => {
    if (!sessionKey || !wantsInsight || insight || insightError) return;
    let active = true;
    const controller = new AbortController();
    api
      .insight(sessionKey, controller.signal)
      .then((next) => {
        if (active) setInsightEntry({ key: sessionKey, insight: next });
      })
      .catch((failure: Error) => {
        if (active && failure.name !== "AbortError") {
          setInsightFailure({ key: sessionKey, message: String(failure.message ?? failure) });
        }
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [sessionKey, wantsInsight, insight, insightError, insightGeneration]);

  // A historic session is fetched once. A live one has to be asked again: its
  // end moves every lap, and the lap chart gains a row. While waiting it is
  // attached again first, which is how it recovers once the recording has
  // something in it, or after the server restarted and let go of it.
  useEffect(() => {
    if (!isLive || !sessionKey) return;
    let active = true;
    let inFlight = false;
    const pull = async () => {
      if (inFlight || !active) return;
      inFlight = true;
      try {
        if (waitingRef.current) await api.liveAttach();
        if (!active) return;
        const request = ++infoRequest.current;
        const [nextInfo, nextLaps] = await Promise.allSettled([api.info(sessionKey), api.laps(sessionKey)]);
        if (!active) return;
        if (nextInfo.status === "fulfilled" && newest("info", request)) setInfo(nextInfo.value);
        if (nextLaps.status === "fulfilled" && newest("laps", request)) {
          setLaps(nextLaps.value.drivers);
          setCrossings(nextLaps.value.leader_crossings);
        }
        if (nextInfo.status === "fulfilled" && nextLaps.status === "fulfilled") {
          setWaiting(false);
          setError(null);
        } else if ([nextInfo, nextLaps].some((r) => r.status === "rejected" && isNotReady(r.reason))) {
          setWaiting(true);
        }
      } catch (failure) {
        if (active && isNotReady(failure)) setWaiting(true);
      } finally {
        inFlight = false;
      }
      if (!active) return;
      // Dropping the models makes an open model view refetch them; a closed one
      // pays nothing, which is why this clears rather than fetches. The
      // generation also drops a fit still on its way, asked for before this.
      setInsightEntry(null);
      setInsightFailure(null);
      setInsightGeneration((g) => g + 1);
    };
    const timer = setInterval(pull, LIVE_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [isLive, sessionKey, newest]);

  return { info, laps, crossings, error, waiting, insight, insightError };
}

/**
 * The running order at the clock's time. Polled on a timer rather than on
 * every tick: it only changes when a car crosses the line, and a request per
 * frame would be waste.
 */
export function useStateAt(sessionKey: string | null, info: SessionInfo | null, t: number): SessionState | null {
  const [state, setState] = useState<SessionState | null>(null);
  const latest = useRef({ key: sessionKey, t });
  latest.current = { key: sessionKey, t };

  useEffect(() => setState(null), [sessionKey]);
  useEffect(() => {
    if (!sessionKey || !info) return;
    let active = true;
    let inFlight = false;
    let lastT: number | null = null;
    const fetchState = () => {
      if (inFlight || !active) return;
      const { key, t: now } = latest.current;
      if (!key) return;
      if (lastT !== null && Math.abs(now - lastT) < 0.05) return;   // paused and nothing moved
      inFlight = true;
      lastT = now;
      api.state(key, now)
        .then((next) => active && setState(next))
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    };
    fetchState();
    const timer = setInterval(fetchState, STATE_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [sessionKey, info]);

  return state;
}

/**
 * Race control up to the clock's time: the stewards' verdicts and the track
 * log, as two lists. Polled half as often as the running order, because a
 * verdict arrives a few times a race and the rows are a few dozen. Two
 * requests, because the limit applies after the filter: each list gets its own
 * newest rather than sharing one budget. The PEN column does not depend on
 * this — it arrives with the running order, at the same `t`.
 */
export function useMessagesAt(sessionKey: string | null, info: SessionInfo | null, t: number, enabled = true) {
  const [stewards, setStewards] = useState<RaceControlEvent[]>([]);
  const [trackLog, setTrackLog] = useState<RaceControlEvent[]>([]);
  const latest = useRef({ key: sessionKey, t });
  latest.current = { key: sessionKey, t };

  useEffect(() => {
    setStewards([]);
    setTrackLog([]);
  }, [sessionKey]);
  useEffect(() => {
    if (!sessionKey || !info || !enabled) return;
    let active = true;
    let inFlight = false;
    const pull = () => {
      if (inFlight || !active) return;
      const { key, t: now } = latest.current;
      if (!key) return;
      inFlight = true;
      Promise.all([
        api.messages(key, now, 60, "stewards"),
        api.messages(key, now, 25, "track"),
      ])
        // An error body is JSON too, so the shape is checked rather than assumed.
        .then(([verdicts, log]) => {
          if (!active) return;
          setStewards(Array.isArray(verdicts) ? verdicts : []);
          setTrackLog(Array.isArray(log) ? log : []);
        })
        .catch(() => undefined)
        .finally(() => {
          inFlight = false;
        });
    };
    pull();
    const timer = setInterval(pull, STATE_INTERVAL_MS * 2);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [sessionKey, info, enabled]);

  return { stewards, trackLog };
}
