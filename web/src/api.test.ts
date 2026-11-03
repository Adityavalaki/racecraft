import { afterEach, describe, expect, it, vi } from "vitest";
import { api, clearAnswers, LIVE_KEY, prefetchSeason } from "./api";

afterEach(() => vi.unstubAllGlobals());

function serve(body: unknown = { drivers: [] }, ok = true) {
  const fetchMock = vi.fn(async () => ({ ok, status: ok ? 200 : 500, statusText: "x", json: async () => body }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("the season screens' shared answers", () => {
  it("fetches once however many ask, until new data clears them", async () => {
    const fetchMock = serve();
    await Promise.all([api.standings("2026_19_R", "before"), api.standings("2026_19_R", "before")]);
    await api.standings("2026_19_R", "before");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await api.standings("2026_19_R", "after");
    expect(fetchMock).toHaveBeenCalledTimes(2);                  // another moment is another answer
    clearAnswers();
    await api.standings("2026_19_R", "before");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("does not keep a failure", async () => {
    const fetchMock = serve({ detail: "no" }, false);
    await expect(api.pitCrews("2026_19_R", "before")).rejects.toThrow();
    await expect(api.pitCrews("2026_19_R", "before")).rejects.toThrow();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("lets one screen stop listening without cancelling it for the next", async () => {
    const fetchMock = serve({ pairs: [] });
    const leaving = new AbortController();
    const first = api.teammates("2026_19_R", "before", leaving.signal);
    leaving.abort();
    await expect(first).rejects.toMatchObject({ name: "AbortError" });
    await expect(api.teammates("2026_19_R", "before")).resolves.toEqual({ pairs: [] });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never keeps a live session's", async () => {
    const fetchMock = serve();
    await api.tyreSets(LIVE_KEY);
    await api.tyreSets(LIVE_KEY);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("stops fetching ahead when the session changes", async () => {
    const fetchMock = serve();
    const moved = new AbortController();
    const running = prefetchSeason("2026_19_R", moved.signal);
    moved.abort();
    await running;
    expect(fetchMock.mock.calls.length).toBeLessThanOrEqual(1);
  });

  it("fetches a race's screens ahead, each one once, and survives one failing", async () => {
    const fetchMock = serve();
    await prefetchSeason("2026_19_R");
    const urls = fetchMock.mock.calls.map((call) => String((call as unknown as [string])[0]));
    expect(urls).toContain("/api/sessions/2026_19_R/standings?moment=after");
    expect(new Set(urls).size).toBe(urls.length);
    await expect(api.title("2026_19_R", "after")).resolves.toBeDefined();
    expect(fetchMock).toHaveBeenCalledTimes(urls.length);        // already there when the screen opens
  });
});
