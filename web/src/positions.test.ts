import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HISTORY_S, WINDOW_S, mergeFrames, plan, sample, usePositions } from "./positions";
import type { Frames } from "./api";

const frames: Frames = {
  t: [10, 11, 12],
  drivers: {
    "1": { x: [0, 100, 200], y: [0, 0, 0] },
    "44": { x: [0, null, 200], y: [0, null, 0] },
  },
};

describe("sample", () => {
  it("interpolates between the samples either side of the time", () => {
    expect(sample(frames, 10.5)["1"]).toEqual({ x: 50, y: 0 });
    expect(sample(frames, 11)["1"]).toEqual({ x: 100, y: 0 });
  });

  it("holds the last known point rather than jumping when a sample is missing", () => {
    // A gap in the feed must not teleport the car or drop it off the map.
    expect(sample(frames, 11)["44"]).toEqual({ x: 0, y: 0 });
  });

  it("clamps outside the window instead of extrapolating off the circuit", () => {
    expect(sample(frames, 99)["1"]).toEqual({ x: 200, y: 0 });
    expect(sample(frames, 0)["1"]).toEqual({ x: 0, y: 0 });
  });

  it("returns nothing when there is no buffer yet", () => {
    expect(sample(null, 10)).toEqual({});
  });
});

describe("mergeFrames", () => {
  it("joins a new window onto the old one without repeating the seam sample", () => {
    const a: Frames = { t: [10, 11], drivers: { "1": { x: [0, 10], y: [0, 0] } } };
    const b: Frames = { t: [11, 12], drivers: { "1": { x: [10, 20], y: [0, 0] } } };
    const merged = mergeFrames(a, b);
    expect(merged.t).toEqual([10, 11, 12]);
    expect(merged.drivers["1"]!.x).toEqual([0, 10, 20]);
  });
});

describe("usePositions", () => {
  it("keeps buffering while the clock ticks, instead of aborting its own requests", async () => {
    // The bug this covers: fetching used to live in an effect keyed on the
    // clock, so each of the ~60 re-renders a second aborted the request the
    // previous one had started. The buffer never arrived and the cars froze,
    // and selecting a driver froze them the same way.
    // A real request takes time and honours its abort signal, which is what
    // made the old implementation fail: it aborted on every clock tick.
    const fetchMock = vi.fn(
      (_url: string, options?: { signal?: AbortSignal }) =>
        new Promise<Response>((resolve, reject) => {
          const timer = setTimeout(
            () =>
              resolve({
                ok: true,
                json: async () => ({
                  t: [0, 1, 2, 3], drivers: { "1": { x: [0, 10, 20, 30], y: [0, 0, 0, 0] } },
                }),
              } as Response),
            30,
          );
          options?.signal?.addEventListener("abort", () => {
            clearTimeout(timer);
            const error = new Error("aborted");
            error.name = "AbortError";
            reject(error);
          });
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const { result, rerender } = renderHook(({ t }) => usePositions("2024_01_R", t, true), {
      initialProps: { t: 0 },
    });

    // Keep the clock running throughout, as playback does. The old version
    // only ever settled once the ticking stopped.
    let frame = 0;
    const ticking = setInterval(() => rerender({ t: (frame += 1) * 0.016 }), 16);
    try {
      await waitFor(() => expect(Object.keys(result.current.at(1)).length).toBeGreaterThan(0), {
        timeout: 2000,
      });
    } finally {
      clearInterval(ticking);
    }

    expect(result.current.at(1)["1"]).toEqual({ x: 10, y: 0 });
    expect(fetchMock).toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});

describe("curved interpolation", () => {
  const curve: Frames = {
    t: [0, 1, 2, 3],
    drivers: { "1": { x: [0, 10, 20, 30], y: [0, 10, 0, -10] } },
  };

  it("passes exactly through the real samples", () => {
    // Smoothing must not move a car away from where the feed says it was.
    expect(sample(curve, 1)["1"]!.x).toBeCloseTo(10, 6);
    expect(sample(curve, 1)["1"]!.y).toBeCloseTo(10, 6);
    expect(sample(curve, 2)["1"]!.y).toBeCloseTo(0, 6);
  });

  it("follows the arc between samples rather than cutting across it", () => {
    // Straight-line interpolation would put y at exactly 5 halfway; a curve
    // through the neighbouring points bulges towards the outside.
    expect(sample(curve, 1.5)["1"]!.y).toBeGreaterThan(5.1);
  });

  it("still moves steadily along a straight line", () => {
    const straight: Frames = { t: [0, 1, 2, 3], drivers: { "1": { x: [0, 10, 20, 30], y: [0, 0, 0, 0] } } };
    expect(sample(straight, 1.5)["1"]!.x).toBeCloseTo(15, 6);
    expect(sample(straight, 1.5)["1"]!.y).toBeCloseTo(0, 6);
  });

  it("keeps a straight line straight at the edge of the buffer", () => {
    // The seam between two fetched windows must not look like a hesitation.
    const edge: Frames = { t: [10, 11, 12], drivers: { "1": { x: [0, 100, 200], y: [0, 0, 0] } } };
    expect(sample(edge, 10.5)["1"]!.x).toBeCloseTo(50, 6);
    expect(sample(edge, 11.5)["1"]!.x).toBeCloseTo(150, 6);
  });
});

describe("playback across window joins", () => {
  // A car at constant speed: x = 100 * t. The server's windows, at the rate and
  // length the hook really uses, so the join happens where it does in the app.
  const SPEED = 100;
  const window = (start: number, end: number, hz = 10): Frames => {
    const count = Math.round((end - start) * hz) + 1;
    const t = Array.from({ length: count }, (_, i) => +(start + i / hz).toFixed(2));
    return { t, drivers: { "1": { x: t.map((v) => v * SPEED), y: t.map(() => 0) } } };
  };

  it.each([1, 2, 5, 10, 30])("never moves a car backwards while playing at %ix", (speed) => {
    // The bug: joining a new window kept the last five seconds of the old one,
    // counted back from its end, while the clock was still ten seconds short
    // of that end. The clock fell before the buffer, every car was pinned to
    // its first sample — about 4.6 s of racing ahead — and the next check saw
    // the clock outside the buffer, fetched afresh and snapped every car back.
    let buffer: Frames | null = null;
    let pending: { due: number; frames: Frames; replace: boolean } | null = null;
    let previousX = -Infinity;
    let now = 600;
    const fps = 60;
    const latencyFrames = 6;               // ~100 ms for a frames request
    for (let frame = 0; frame < fps * 60; frame += 1) {  // a minute of real time
      now += speed / fps;
      if (pending && frame >= pending.due) {
        buffer = pending.replace || !buffer
          ? pending.frames
          : mergeFrames(buffer, pending.frames, now - HISTORY_S);
        pending = null;
      }
      if (!pending && frame % 7 === 0) {                 // the hook checks every 120 ms
        const next = plan(buffer, now);
        if (next) {
          pending = {
            due: frame + latencyFrames,
            frames: window(next.start, next.start + WINDOW_S),
            replace: next.replace,
          };
        }
      }
      const car = sample(buffer, now)["1"];
      if (!car) continue;
      expect(car.x).toBeGreaterThanOrEqual(previousX - 1e-6);
      // Never more than a frame's travel away from where the car really is.
      expect(Math.abs(car.x - now * SPEED)).toBeLessThan((speed / fps) * SPEED + 1);
      previousX = car.x;
    }
  });

  it("keeps the history that covers the clock when it joins a window", () => {
    const merged = mergeFrames(window(600, 624), window(624, 648), 614.4 - HISTORY_S);
    expect(merged.t[0]!).toBeLessThanOrEqual(614.4);
    expect(merged.t[merged.t.length - 1]!).toBe(648);
  });
});
