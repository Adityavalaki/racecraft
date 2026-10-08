import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SCREENS, featureById, featureUrl, openFeature, type FeatureId } from "./features";
import { FakeChannel } from "./testing/fakeChannel";
import { CLOCK_INTERVAL_MS, SILENCE_MS, useFollowedClock, useReplayBroadcast, type ClockState } from "./sync";

const settle = () => act(async () => {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
});

const clock = (over: Partial<ClockState> = {}): ClockState => ({
  session: "2024_01_R", t: 1200, playing: false, speed: 1, following: false, selected: [], ...over,
});

const handlers = () => ({ seek: vi.fn(), toggle: vi.fn(), select: vi.fn() });

beforeEach(() => {
  FakeChannel.reset();
  vi.stubGlobal("BroadcastChannel", FakeChannel);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the replay window and a feature window", () => {
  it("a feature window opened later learns where the replay is at once", async () => {
    renderHook(() => useReplayBroadcast(clock({ t: 1500 }), handlers()));
    await settle();
    const { result } = renderHook(() => useFollowedClock());   // says hello on opening
    await settle();
    expect(result.current.state).toEqual(clock({ t: 1500 }));
    expect(result.current.connected).toBe(true);
  });

  it("follows every change: pause, scrub, speed, session, picked drivers", async () => {
    const { rerender } = renderHook(({ state }) => useReplayBroadcast(state, handlers()),
                                    { initialProps: { state: clock() } });
    const { result } = renderHook(() => useFollowedClock());
    await settle();
    for (const next of [clock({ t: 1300 }), clock({ t: 1300, speed: 5 }), clock({ session: "2024_02_R" }),
                        clock({ selected: [1, 44] })]) {
      rerender({ state: next });
      await settle();
      expect(result.current.state).toEqual(next);
    }
  });

  it("speaks ten times a second while playing, and stops when paused", async () => {
    vi.useFakeTimers();
    const { rerender } = renderHook(({ state }) => useReplayBroadcast(state, handlers()),
                                    { initialProps: { state: clock({ playing: true }) } });
    FakeChannel.posted = [];
    act(() => vi.advanceTimersByTime(CLOCK_INTERVAL_MS * 10));
    expect(FakeChannel.posted.length).toBe(10);

    rerender({ state: clock({ playing: false }) });
    FakeChannel.posted = [];
    act(() => vi.advanceTimersByTime(CLOCK_INTERVAL_MS * 10));
    expect(FakeChannel.posted.length).toBe(0);
  });

  it("carries out what a feature window asks: seek, play/pause, pick a driver", async () => {
    const replay = handlers();
    renderHook(() => useReplayBroadcast(clock(), replay));
    const { result } = renderHook(() => useFollowedClock());
    await settle();
    act(() => {
      result.current.seek(1777);
      result.current.toggle();
      result.current.select(16);
    });
    await settle();
    expect(replay.seek).toHaveBeenCalledWith(1777);
    expect(replay.toggle).toHaveBeenCalledTimes(1);
    expect(replay.select).toHaveBeenCalledWith(16);
  });

  it("ignores requests that are not well formed", async () => {
    const replay = handlers();
    renderHook(() => useReplayBroadcast(clock(), replay));
    const stranger = new FakeChannel("racecraft");
    stranger.postMessage({ type: "seek", t: "soon" });
    stranger.postMessage("not even an object");
    stranger.postMessage({ type: "select", driver: Number.NaN });
    await settle();
    expect(replay.seek).not.toHaveBeenCalled();
    expect(replay.select).not.toHaveBeenCalled();
  });

  it("says so when the replay window has gone quiet", async () => {
    vi.useFakeTimers();
    const replay = renderHook(() => useReplayBroadcast(clock(), handlers()));
    const { result } = renderHook(() => useFollowedClock());
    await settle();
    expect(result.current.connected).toBe(true);
    replay.unmount();                                          // the replay window closed
    act(() => vi.advanceTimersByTime(SILENCE_MS + 1100));
    expect(result.current.connected).toBe(false);
  });
});

describe("opening a feature", () => {
  it("lets the desktop app make the window when it can", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200 }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    await expect(openFeature("strategy", "2024_01_R")).resolves.toBe("app");
    expect(fetchMock).toHaveBeenCalledWith("/api/app/window?feature=strategy&session=2024_01_R", { method: "POST" });
    expect(opened).not.toHaveBeenCalled();
  });

  it("opens a named browser window when there is no app to ask", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 }) as Response));
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    await expect(openFeature("tower", "live")).resolves.toBe("browser");
    expect(opened).toHaveBeenCalledWith("/?feature=tower&session=live", "racecraft-tower", "width=1280,height=860");
  });

  it("still opens it when the server cannot be reached at all", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("network down");
    }));
    const opened = vi.spyOn(window, "open").mockReturnValue(null);
    await openFeature("trace", "2024_01_R");
    expect(opened).toHaveBeenCalledTimes(1);
  });

  it("has a URL for every screen that can pop out, and only those", () => {
    // Every screen but the replay and settings can have a window of its own.
    const poppable = SCREENS.filter((screen) => screen.poppable).map((screen) => screen.id);
    expect(poppable).toEqual(["tower", "trace", "pedals", "strategy", "tyres", "prediction", "stewards"]);
    for (const id of poppable) expect(featureUrl(id as FeatureId, "x")).toBe(`/?feature=${id}&session=x`);
    expect(featureById("replay")).toBeUndefined();
    expect(featureById("settings")).toBeUndefined();
  });
});
