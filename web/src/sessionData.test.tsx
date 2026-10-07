import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { defaultSession, lapStartTime, useSession } from "./sessionData";

/**
 * The shared reading of a session, tested on its own. The replay window and
 * every feature window go through these hooks, so what is pinned here holds in
 * all of them: a model fit for a session no longer shown never lands, and a
 * failed fit is asked for again the next time something wants it.
 */

interface Held {
  url: string;
  answer: (body: unknown, status?: number) => void;
}

/** A server the test answers by hand, for the insight route; everything else at once. */
function server(info: (key: string) => unknown) {
  const held: Held[] = [];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    calls.push(url);
    const respond = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, statusText: "", json: async () => body }) as Response;
    if (!url.includes("/insight")) {
      const key = url.split("/")[3] ?? "";
      return Promise.resolve(respond(url.endsWith("/laps") ? { drivers: [], leader_crossings: { laps: [], t: [] } }
                                                          : info(key)));
    }
    return new Promise<Response>((resolve, reject) => {
      let aborted = false;
      held.push({ url, answer: (body, status) => !aborted && resolve(respond(body, status)) });
      init?.signal?.addEventListener("abort", () => {
        aborted = true;
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
    });
  }));
  const take = (url: string) => {
    const index = held.findIndex((h) => h.url === url);
    if (index === -1) throw new Error(`nothing held for ${url}`);
    return held.splice(index, 1)[0]!;
  };
  return { calls, take, waiting: (url: string) => held.some((h) => h.url === url) };
}

const info = (key: string) => ({ session: { event_name: key, session_name: "Race", location: key },
                                 t_start: 0, t_end: 100, total_laps: 50, drivers: [], outline: [], bounds: {},
                                 has_position_data: false });
const fit = (seconds: number) => ({ pit_loss: { seconds } });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("useSession and the model fit", () => {
  it("does not ask for a fit until something wants one", async () => {
    const api = server(info);
    const { result } = renderHook(() => useSession("2024_01_R", false));
    await waitFor(() => expect(result.current.info).not.toBeNull());
    expect(api.calls.some((url) => url.includes("/insight"))).toBe(false);
  });

  it("a late fit for the previous session does not replace this session's", async () => {
    const api = server(info);
    const { result, rerender } = renderHook(({ key }) => useSession(key, true), { initialProps: { key: "2024_01_R" } });
    await waitFor(() => expect(api.waiting("/api/sessions/2024_01_R/insight")).toBe(true));
    const late = api.take("/api/sessions/2024_01_R/insight");

    rerender({ key: "2024_02_R" });
    await waitFor(() => expect(api.waiting("/api/sessions/2024_02_R/insight")).toBe(true));
    await act(async () => api.take("/api/sessions/2024_02_R/insight").answer(fit(22.4)));
    await waitFor(() => expect(result.current.insight).toEqual(fit(22.4)));

    await act(async () => late.answer(fit(30.1)));
    expect(result.current.insight).toEqual(fit(22.4));
  });

  it("asks again for a fit that failed, the next time one is wanted", async () => {
    const api = server(info);
    const { result, rerender } = renderHook(({ wants }) => useSession("2024_01_R", wants),
                                            { initialProps: { wants: true } });
    await waitFor(() => expect(api.waiting("/api/sessions/2024_01_R/insight")).toBe(true));
    await act(async () => api.take("/api/sessions/2024_01_R/insight").answer({ detail: "the fit fell over" }, 500));
    await waitFor(() => expect(result.current.insightError).toBe("the fit fell over"));

    rerender({ wants: false });
    rerender({ wants: true });
    await waitFor(() => expect(api.waiting("/api/sessions/2024_01_R/insight")).toBe(true));
    await act(async () => api.take("/api/sessions/2024_01_R/insight").answer(fit(22.4)));
    await waitFor(() => expect(result.current.insight).toEqual(fit(22.4)));
    expect(result.current.insightError).toBeNull();
  });

  it("keeps a fit that worked rather than asking again", async () => {
    const api = server(info);
    const { result, rerender } = renderHook(({ wants }) => useSession("2024_01_R", wants),
                                            { initialProps: { wants: true } });
    await waitFor(() => expect(api.waiting("/api/sessions/2024_01_R/insight")).toBe(true));
    await act(async () => api.take("/api/sessions/2024_01_R/insight").answer(fit(22.4)));
    await waitFor(() => expect(result.current.insight).toEqual(fit(22.4)));

    rerender({ wants: false });
    rerender({ wants: true });
    expect(api.calls.filter((url) => url.includes("/insight"))).toHaveLength(1);
  });
});

describe("helpers", () => {
  const summary = (key: string, session: string) => ({ session_key: key, session }) as never;

  it("opens live first, then the newest race, then whatever there is", () => {
    expect(defaultSession([summary("2024_02_Q", "Q"), summary("live", "LIVE"), summary("2024_01_R", "R")])).toBe("live");
    expect(defaultSession([summary("2024_02_Q", "Q"), summary("2024_01_R", "R")])).toBe("2024_01_R");
    expect(defaultSession([summary("2024_02_Q", "Q")])).toBe("2024_02_Q");
    expect(defaultSession([])).toBeNull();
  });

  it("starts a lap at the leader's crossing of the lap before it", () => {
    const crossings = { laps: [1, 2, 3], t: [1090, 1182, 1275] };
    expect(lapStartTime(3, crossings, 1000)).toBe(1182);
    expect(lapStartTime(1, crossings, 1000)).toBe(1000);   // no lap 0 crossing: the start
    expect(lapStartTime(9, crossings, 1000)).toBe(1000);   // never completed: the start
    expect(lapStartTime(3, null, 1000)).toBe(1000);
  });
});
