import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DriverTiming, Insight, LapSeries, LapTrace, PitWindows, RaceControlEvent, SessionInfo } from "../api";
import { sentence, tone } from "../panels/RaceControl";
import { DEFAULT_SETTINGS, speedIn } from "../settings";
import { ScreenView, type ScreenContext } from "./ScreenView";
import { SettingsScreen } from "./SettingsScreen";
import { explain } from "./StewardsScreen";
import { seriesFor } from "./TraceScreen";
import { ageAtLost, lostAt } from "./TyresScreen";

/**
 * The screens, each given a session at a moment as the main window would.
 * What they must get right is what the data says, and never more: timing
 * colours as a timing screen uses them, nothing from after the clock, and
 * every estimate saying it is one.
 */

function driver(n: number, code: string, position: number, over: Partial<DriverTiming> = {}): DriverTiming {
  return {
    driver_number: n, abbreviation: code, team_name: "Team", team_color: "3671C6", position, status: "racing",
    laps_completed: 16, gap_to_leader_s: position === 1 ? null : position * 2, gap_text: position === 1 ? "" : `+${position * 2}.000`,
    interval_s: position === 1 ? null : 2, interval_text: position === 1 ? "" : "+2.000", laps_down: 0,
    last_lap_s: 92 + position / 10, best_lap_s: 91 + position / 10, is_session_best: false, is_personal_best: false,
    compound: "MEDIUM", tyre_life: 10 + position, laps_in_stint: 10, stops: 0, sectors: [], penalties: null, ...over,
  };
}

const info = {
  session: { event_name: "Azerbaijan Grand Prix", session_name: "Race", location: "Baku", circuit_rotation_deg: 0, round: 15 },
  t_start: 1000, t_end: 7000, total_laps: 51,
  drivers: [{ driver_number: 63, abbreviation: "RUS", full_name: "George Russell", team_name: "Mercedes", team_color: "00D7B6",
              grid_position: 2, position: 1, classified_position: "1", status: "Finished" },
            { driver_number: 3, abbreviation: "VER", full_name: "Max Verstappen", team_name: "Red Bull", team_color: "4781D7",
              grid_position: 1, position: 2, classified_position: "2", status: "Finished" }],
  outline: [], bounds: {}, has_position_data: false,
  track_status: [{ t: 1000, status: "1" }, { t: 2000, status: "4" }, { t: 2300, status: "1" }, { t: 6000, status: "4" }, { t: 6200, status: "1" }],
} as unknown as SessionInfo;

const series = (n: number, code: string, gaps: number[], compounds: string[]): LapSeries => ({
  driver_number: n, abbreviation: code, team_color: "777777", laps: gaps.map((_, i) => i + 1),
  gap_to_leader_s: gaps, position: gaps.map(() => (n === 63 ? 1 : 2)), lap_time_s: gaps.map(() => 92),
  compound: compounds, pit_in: gaps.map(() => false),
});

function context(over: Partial<ScreenContext> = {}): ScreenContext {
  const drivers = [
    driver(63, "RUS", 1, { is_personal_best: true, sectors: [{ sector: 1, seconds: 30.1, state: "session_best" },
                                                              { sector: 2, seconds: 40.2, state: "personal_best" },
                                                              { sector: 3, seconds: 22.3, state: "normal" }] }),
    driver(3, "VER", 2, { overtake: "eligible", best_lap_s: 90.5 }),
  ];
  return {
    session: "2026_15_R", t: 3000, info,
    state: { t: 3000, leader_lap: 16, drivers, cars: {}, best_sectors: [], ideal_lap_s: null, track_status: null, weather: null } as never,
    laps: [series(63, "RUS", [0, 0, 0, 0], ["MEDIUM", "MEDIUM", "HARD", "HARD"]), series(3, "VER", [1, 1.5, 2, 2.4], ["SOFT", "SOFT", "SOFT", "SOFT"])],
    crossings: { laps: [1, 2, 3, 4], t: [1500, 2200, 2900, 3600] },
    selected: [], onSelect: vi.fn(), onSelectLap: vi.fn(), insight: null, insightError: null,
    actualStops: null, sessionBest: null, stewards: [], trackLog: [], driverCodes: { 63: "RUS", 3: "VER" },
    ...over,
  };
}

function serve(routes: Record<string, unknown>) {
  const fetchMock = vi.fn(async (url: string) => {
    const hit = Object.keys(routes).find((prefix) => url.includes(prefix));
    return { ok: hit !== undefined, status: hit ? 200 : 404, statusText: "x",
             json: async () => (hit ? routes[hit] : { detail: "not here" }) } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the timing tower", () => {
  it("colours times as a timing screen does, and marks the overtake window", () => {
    const { container } = render(<ScreenView id="tower" ctx={context()} />);
    const rus = container.querySelectorAll(".tower-table tbody tr")[0] as HTMLElement;
    const cells = Array.from(rus.querySelectorAll("td.num")).map((td) => td.className);
    expect(cells.some((c) => c.includes("is-purple"))).toBe(true);      // S1, fastest of everyone
    expect(cells.some((c) => c.includes("is-yellow"))).toBe(true);      // S3, slower than their best
    expect(rus.querySelector(".strong")?.className).toContain("is-green");   // last lap, a personal best
    expect(within(container.querySelectorAll(".tower-table tbody tr")[1] as HTMLElement).getByText("Eligible")).toBeDefined();
  });

  it("reorders by best lap, and follows a driver on a click", () => {
    const ctx = context();
    const { container } = render(<ScreenView id="tower" ctx={ctx} />);
    fireEvent.click(screen.getByRole("radio", { name: "Best laps" }));
    const codes = () => Array.from(container.querySelectorAll(".row-pick")).map((b) => b.textContent);
    expect(codes()).toEqual(["VER", "RUS"]);                             // 1:30.5 before 1:31.1
    fireEvent.click(screen.getByRole("button", { name: "RUS" }));
    expect(ctx.onSelect).toHaveBeenCalledWith(63);
  });
});

describe("the race trace", () => {
  it("measures intervals against whoever was a place ahead on that lap", () => {
    const values = seriesFor(context().laps, "interval");
    expect(values.get(3)!.get(4)).toBeCloseTo(2.4);
    expect(values.get(63)).toBeUndefined();                              // the leader has no one ahead
  });

  it("shades only the safety cars that have happened by the clock", () => {
    const { container } = render(<ScreenView id="trace" ctx={context({ t: 3000 })} />);
    const rects = Array.from(container.querySelectorAll(".trace-canvas rect"))
      .filter((r) => (r.getAttribute("fill") ?? "").includes("255, 162, 58"));
    expect(rects).toHaveLength(1);                                       // the lap-2 one; not the one at t=6000
  });

  it("jumps the clock to a lap clicked on the chart", () => {
    const ctx = context();
    const { container } = render(<ScreenView id="trace" ctx={ctx} />);
    const svg = container.querySelector(".trace-canvas svg") as SVGSVGElement;
    vi.spyOn(svg, "getBoundingClientRect").mockReturnValue({ left: 0, width: 500, top: 0, height: 440 } as DOMRect);
    fireEvent.click(svg, { clientX: 250 });
    expect(ctx.onSelectLap).toHaveBeenCalledWith(26);                    // halfway through 51 laps
  });
});

describe("the stewards", () => {
  const penalty: RaceControlEvent = { t: 2500, lap: 9, kind: "time_penalty", seconds: 5, reason: "TRACK LIMITS", cars: [3],
    incident: null, stewards: true, topic: "stewards", message: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 3 (VER) - TRACK LIMITS" };
  const sc: RaceControlEvent = { t: 2000, lap: 8, kind: "other", seconds: null, reason: null, cars: [], incident: null,
    stewards: false, topic: "track", message: "SAFETY CAR DEPLOYED" };

  it("explains a verdict in plain words, from what kind it is", () => {
    const what = explain(penalty, "VER");
    expect(what.title).toBe("VER, track limits");
    expect(what.body).toMatch(/5-second penalty/);
    expect(what.effect).toBe("5 s added");
    expect(explain(sc, "").effect).toMatch(/stop is cheaper/);
  });

  it("filters to incidents or the track, and explains the newest by default", () => {
    render(<ScreenView id="stewards" ctx={context({ stewards: [penalty], trackLog: [sc] })} />);
    expect(screen.getByText(/served at the next stop/)).toBeDefined();
    fireEvent.click(screen.getByRole("radio", { name: "Track" }));
    const list = within(screen.getByRole("region", { name: "Race control messages" }));
    expect(list.getByText("Safety car deployed")).toBeDefined();
    expect(list.queryByText(/track limits/i)).toBeNull();
  });
});

describe("race control's words", () => {
  it("reads capitals as a sentence, keeping acronyms and driver codes", () => {
    expect(sentence("DRS ENABLED")).toBe("DRS enabled");
    expect(sentence("INCIDENT INVOLVING CAR 55 (SAI) NOTED")).toBe("Incident involving car 55 (SAI) noted");
  });

  it("colours a message by what kind of news it is", () => {
    const track = (message: string) => ({ t: 0, lap: 1, kind: "other", seconds: null, reason: null, cars: [], incident: null,
                                          stewards: false, topic: "track" as const, message });
    expect(tone(track("RED FLAG"))).toBe("red");
    expect(tone(track("VIRTUAL SAFETY CAR DEPLOYED"))).toBe("amber");
    expect(tone(track("GREEN LIGHT - PIT EXIT OPEN"))).toBe("green");
  });
});

describe("the tyres", () => {
  const curve = { compound: "MEDIUM", observed_to_age: 20,
                  points: [0, 10, 20, 30].map((age) => ({ age, model_s: age * 0.05, model_unscaled_s: age * 0.04,
                                                          observed_s: age <= 20 ? age * 0.06 : null, laps: 5 })) };

  it("reads time lost, and the age at a second lost, off the model's curve", () => {
    expect(lostAt(curve, 15)).toBeCloseTo(0.75);
    expect(ageAtLost(curve)).toBe(20);
    expect(lostAt(undefined, 10)).toBeNull();
  });

  it("puts every car on the curve, and shows what the race did only when asked", () => {
    const insight = { degradation_curve: [curve], compound_offset_s: { MEDIUM: 0.3 }, fitted_on_count: 14,
                      compounds: null, observed_unavailable: undefined, scale: 1.5 } as unknown as Insight;
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    const { container } = render(<ScreenView id="tyres" ctx={context({ insight })} />);
    const rows = Array.from(container.querySelectorAll(".tyre-table tbody tr"));
    expect(rows).toHaveLength(2);
    expect(rows[0]!.textContent).toContain("0.55 s");                   // RUS, 11 laps on mediums
    const dashed = () => container.querySelectorAll('.wear-plot path[stroke-dasharray="2 5"]').length;
    expect(dashed()).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: "What this race did" }));
    expect(dashed()).toBe(1);
  });
});

describe("the strategy", () => {
  const windows: PitWindows = {
    session_key: "2026_15_R", t: 3000, lap: 16, total_laps: 51,
    model: { degradation: {}, compound_offset_s: {}, pit_loss_s: 21, pit_spread_s: 1, fitted_on_count: 14, held_out: true },
    cars: [
      { driver_number: 63, abbreviation: "RUS", team_color: "00D7B6", position: 1, status: "racing", compound: "MEDIUM", age: 18,
        laps_completed: 16, stops: 0, used: ["MEDIUM"],
        window: { laps_until: 10, window: [20, 31], most_likely_lap: 26, next_compound: "HARD", no_stop: false } },
      { driver_number: 3, abbreviation: "VER", team_color: "4781D7", position: 2, status: "racing", compound: "SOFT", age: 16,
        laps_completed: 16, stops: 0, used: ["SOFT"], window: null },
    ],
    undercuts: [{ chaser: 3, target: 63, gap_s: 0.893, gain_s: 0.885, chance: 0.498, fresh_compound: "MEDIUM" }],
    notes: ["windows", "undercut: the out-lap is not modelled"],
  };

  it("shows when each followed car stops, who can undercut whom, and the stints so far", async () => {
    const fetchMock = serve({ "/pit-windows": windows });
    const { container } = render(<ScreenView id="strategy" ctx={context({ selected: [63] })} />);
    const card = within(await screen.findByRole("region", { name: "RUS pit stop estimate" }));
    expect(card.getByText("10")).toBeDefined();
    expect(card.getByText("L20–31")).toBeDefined();
    expect(card.getByText("hard")).toBeDefined();
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2026_15_R/pit-windows?t=3000.00");
    expect(within(screen.getByRole("region", { name: "Undercut watch" })).getByText("50%")).toBeDefined();
    // RUS changed from mediums to hards at lap 3: two stints so far.
    const rus = Array.from(container.querySelectorAll(".stint-row")).find((r) => r.textContent?.includes("RUS"))!;
    expect(rus.querySelectorAll(".stint")).toHaveLength(2);
    expect(screen.getByText(/out-lap is not modelled/)).toBeDefined();
  });
});

describe("pedals and speed", () => {
  const lap = (n: number, code: string, braking: [number, number]): LapTrace => {
    const distance = Array.from({ length: 200 }, (_, i) => i * 5);
    const brake = distance.map((d) => d >= braking[0] && d < braking[1]);
    return {
      driver_number: n, abbreviation: code, lap: 16, lap_time_s: 60, compound: "MEDIUM", tyre_life: 10, start_t: 0,
      length_m: 1000, step_m: 5, distance, t: distance.map((d) => d / 16.6),
      speed: brake.map((b) => (b ? 120 : 280)), throttle: brake.map((b) => (b ? 0 : 100)), brake,
      gear: brake.map((b) => (b ? 3 : 8)), x: distance.map((d) => d), y: distance.map(() => 0),
      brake_zones: [{ start_m: braking[0], end_m: braking[1], duration_s: 2, entry_speed: 280, min_speed: 120 }],
      corners: [{ number: 1, letter: null, distance: 520 }],
      summary: { top_speed: 280, min_speed: 120, full_throttle_share: 0.9, braking_share: 0.1, brake_zones: 1 },
    };
  };

  it("lays two laps over each other, and lists each brake zone against the reference", async () => {
    serve({ "/compare": { subject: lap(63, "RUS", [500, 600]), reference: lap(3, "VER", [480, 600]),
                          delta: { distance: lap(63, "RUS", [0, 0]).distance, delta_s: Array(200).fill(-0.1), final_s: -0.1 } } });
    render(<ScreenView id="pedals" ctx={context()} />);
    const zones = within(await screen.findByRole("region", { name: "Brake zones" }));
    const row = zones.getAllByRole("row")[1]!;
    expect(row.textContent).toContain("T1");
    expect(row.textContent).toContain("500 m");
    expect(row.textContent).toContain("480 m");                          // VER braked 20 m earlier
    expect(row.querySelector("td")?.className).toContain("is-better");   // so RUS's later point is the better
    expect(screen.getByText(/RUS quicker by 0.100 s/)).toBeDefined();
  });

  it("moves the cursor through every trace, and swaps subject and reference", async () => {
    const fetchMock = serve({ "/compare": { subject: lap(63, "RUS", [500, 600]), reference: lap(3, "VER", [480, 600]),
                                            delta: { distance: [0], delta_s: [0], final_s: 0 } } });
    render(<ScreenView id="pedals" ctx={context()} />);
    const slider = await screen.findByRole("slider", { name: /cursor position/i });
    fireEvent.change(slider, { target: { value: "550" } });
    const at = within(screen.getByRole("region", { name: "At the cursor" }));
    expect(at.getAllByText("On")).toHaveLength(2);                       // both on the brake at 550 m
    fireEvent.click(screen.getByRole("button", { name: /swap subject and reference/i }));
    await waitFor(() => expect(fetchMock.mock.calls.some(([url]) => String(url).includes("driver=3&ref=63"))).toBe(true));
  });
});

describe("settings", () => {
  it("changes units, density and the map, and shows them in the preview", () => {
    const update = vi.fn();
    render(<SettingsScreen settings={DEFAULT_SETTINGS} update={update} onSynced={vi.fn()} />);
    fireEvent.click(screen.getByRole("radio", { name: "Imperial" }));
    expect(update).toHaveBeenCalledWith({ units: "imperial" });
    fireEvent.click(screen.getByRole("switch", { name: "Driver codes on cars" }));
    expect(update).toHaveBeenCalledWith({ names: true });
    expect(screen.getByText("312 km/h")).toBeDefined();
  });

  it("converts speed for imperial", () => {
    expect(speedIn(320, "imperial")).toEqual({ value: "199", unit: "mph" });
    expect(speedIn(null, "metric").value).toBe("—");
  });
});
