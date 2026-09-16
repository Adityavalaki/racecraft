import { describe, expect, it } from "vitest";
import { formatClock, formatLapTime } from "./api";

describe("formatLapTime", () => {
  it("writes lap times the way timing screens do", () => {
    expect(formatLapTime(92.608)).toBe("1:32.608");
    expect(formatLapTime(59.999)).toBe("59.999");
    expect(formatLapTime(60)).toBe("1:00.000");   // not 1:0.000
  });

  it("shows a dash when there is no time", () => {
    expect(formatLapTime(null)).toBe("—");
    expect(formatLapTime(undefined)).toBe("—");
    expect(formatLapTime(NaN)).toBe("—");
  });
});

describe("formatClock", () => {
  it("counts session time as hours, minutes and seconds", () => {
    expect(formatClock(0)).toBe("0:00:00");
    expect(formatClock(3661)).toBe("1:01:01");
    expect(formatClock(-5)).toBe("-0:00:05");     // before lights out
  });
});
