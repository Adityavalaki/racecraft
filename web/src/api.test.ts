import { afterEach, describe, expect, it, vi } from "vitest";
import { HttpError, api, formatClock, formatLapTime } from "./api";

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

describe("errors from the server", () => {
  afterEach(() => vi.unstubAllGlobals());

  const answer = (status: number, detail: string) =>
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status, statusText: "Conflict", json: async () => ({ detail }),
    } as Response)));

  it("carry the status, so live can tell 'not ready' from 'broken'", async () => {
    answer(409, "live is not attached to a recording");
    const error = await api.info("live").catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect(error).toBeInstanceOf(Error);
    expect((error as HttpError).status).toBe(409);
    expect((error as HttpError).message).toBe("live is not attached to a recording");
  });

  it("do the same for a POST", async () => {
    answer(409, "no recording");
    const error = await api.liveAttach().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(HttpError);
    expect((error as HttpError).status).toBe(409);
  });
});
