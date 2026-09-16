import { renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { mergeFrames, sample, usePositions } from "./positions";
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
