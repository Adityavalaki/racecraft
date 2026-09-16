import { describe, expect, it } from "vitest";
import { sample } from "./positions";
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
