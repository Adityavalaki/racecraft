import { describe, expect, it } from "vitest";
import type { LapComparison, LapTrace } from "../api";
import { cornerRows } from "./PedalsScreen";

/** A 1 km lap every 10 m, turns at 300 m and 700 m, with speed and throttle given by distance. */
function lap(speed: (m: number) => number, throttle: (m: number) => number, brakeFrom: number[], length = 1000): LapTrace {
  const distance = Array.from({ length: length / 10 + 1 }, (_, k) => k * 10);
  return {
    driver_number: 1, abbreviation: "AAA", lap: 10, lap_time_s: 80, compound: "SOFT", tyre_life: 5, start_t: 0,
    length_m: length, step_m: 10, distance, t: distance.map((m) => m / 50),
    speed: distance.map(speed), throttle: distance.map(throttle), brake: distance.map(() => false),
    gear: distance.map(() => 7), x: distance.map(() => null), y: distance.map(() => null),
    brake_zones: brakeFrom.map((start) => ({ start_m: start, end_m: start + 60, duration_s: 1.5, entry_speed: 300, min_speed: 150 })),
    corners: [{ number: 1, letter: null, distance: 300 }, { number: 2, letter: null, distance: 700 }],
    summary: { top_speed: 300, min_speed: 100, full_throttle_share: 0.8, braking_share: 0.1, brake_zones: brakeFrom.length },
  };
}

describe("cornerRows (BUG-018)", () => {
  // The subject brakes for T1 at 220 m and lifts for T2; the reference brakes later for T1 and takes T2 flat.
  const subject = lap((m) => (Math.abs(m - 310) <= 40 ? 100 : Math.abs(m - 700) <= 30 ? 200 : 300),
                      (m) => (m >= 230 && m <= 310 ? 0 : m >= 650 && m <= 690 ? 80 : 100), [220]);
  const reference = lap((m) => (Math.abs(m - 300) <= 40 ? 110 : Math.abs(m - 700) <= 30 ? 250 : 300),
                        (m) => (m >= 250 && m <= 300 ? 0 : 100), [240]);
  // The subject loses 0.05 s over the first half of the lap, nothing after.
  const distance = subject.distance;
  const delta = { distance, delta_s: distance.map((m) => Math.min(m, 500) / 10000), final_s: 0.05 };
  const rows = cornerRows({ subject, reference, delta } satisfies LapComparison);

  it("has one row per turn, braked or not", () => {
    expect(rows.map((r) => r.turn)).toEqual(["T1", "T2"]);
  });

  it("takes each driver's slowest point of the turn, not of the braking", () => {
    expect([rows[0]!.slowA, rows[0]!.slowB]).toEqual([100, 110]);
    expect([rows[1]!.slowA, rows[1]!.slowB]).toEqual([200, 250]);
    expect(rows[0]!.apex_m).toBe(270);
  });

  it("says where each began braking, else lift or flat", () => {
    expect(rows[0]!.entryA).toEqual({ brake_m: 220 });
    expect(rows[0]!.entryB).toEqual({ brake_m: 240 });
    expect(rows[1]!.entryA).toBe("lift");
    expect(rows[1]!.entryB).toBe("flat");
  });

  it("splits the lap's gap between the turns, adding up to the whole", () => {
    expect(rows[0]!.time_s).toBeCloseTo(0.05, 6);
    expect(rows[1]!.time_s).toBeCloseTo(0, 6);
    expect(rows.reduce((sum, r) => sum + r.time_s, 0)).toBeCloseTo(delta.final_s, 6);
  });

  it("lays a longer reference lap along the subject's distance", () => {
    const longer = lap((m) => (Math.abs(m - 330) <= 44 ? 120 : 300), () => 100, [264], 1100);
    const [t1] = cornerRows({ subject, reference: longer, delta });
    expect(t1!.slowB).toBe(120);
    expect(t1!.entryB).toEqual({ brake_m: 240 });
  });
});
