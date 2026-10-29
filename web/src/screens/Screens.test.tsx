import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DriverTiming, Insight, LapSeries, LapTrace, PitWindows, RaceControlEvent, SessionInfo } from "../api";
import { sentence, tone } from "../panels/RaceControl";
import { DEFAULT_SETTINGS, speedIn } from "../settings";
import { ScreenView, type ScreenContext } from "./ScreenView";
import { SettingsScreen } from "./SettingsScreen";
import { titleChance } from "./StandingsScreen";
import { explain } from "./StewardsScreen";
import { leftText } from "./QualifyingScreen";
import { stopText } from "./RaceReviewScreen";
import { places, startText } from "./StartsScreen";
import { chartReach, gapText, niceCeiling } from "./TeammatesScreen";
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

describe("StandingsScreen", () => {
  const table = (moment: "before" | "after") => ({
    year: 2026, moment, races: moment === "before" ? 14 : 15, sprints: 5,
    last: { round: 15, event_name: "Azerbaijan Grand Prix", session: moment === "before" ? "sprint" : "Grand Prix" },
    drivers: [
      { position: 1, driver_number: 63, abbreviation: "RUS", full_name: "George Russell", team_name: "Mercedes",
        team_color: "00D7B6", points: 238, gap: 0, wins: 3, podiums: 8, sprint_wins: 1, change: 1,
        form: [{ round: 14, event_name: "Italian Grand Prix", position: 1, status: null },
               { round: 15, event_name: "Azerbaijan Grand Prix", position: null, status: "R" }] },
      { position: 2, driver_number: 3, abbreviation: "VER", full_name: "Max Verstappen", team_name: "Red Bull Racing",
        team_color: "4781D7", points: 213, gap: 25, wins: 2, podiums: 9, sprint_wins: 0, change: -1, form: [] },
    ],
    constructors: [
      { position: 1, team: "Mercedes", team_color: "00D7B6", points: 573, gap: 0, wins: 11, podiums: 22,
        drivers: [{ abbreviation: "ANT", points: 335 }, { abbreviation: "RUS", points: 238 }] },
      { position: 2, team: "Red Bull Racing", team_color: "4781D7", points: 324, gap: 249, wins: 2, podiums: 10,
        drivers: [{ abbreviation: "VER", points: 213 }, { abbreviation: "LAW", points: 14 }] },
    ],
    notes: ["Singapore Grand Prix sprint: the feed sent no points, so they are worked out from the classified positions"],
  });

  const odds = {
    year: 2026, moment: "before", runs: 10000, notes: [],
    remaining: [{ round: 16, event_name: "Bahrain Grand Prix", session: "Grand Prix" },
                { round: 17, event_name: "Singapore Grand Prix", session: "sprint" }],
    drivers: [{ abbreviation: "RUS", driver_number: 63, points: 238, title: 0.82, expected_points: 270, p10: 250, p90: 290, max_points: 271, alive: true },
              { abbreviation: "VER", driver_number: 3, points: 213, title: 0, expected_points: 230, p10: 215, p90: 245, max_points: 246, alive: true }],
    constructors: [{ team: "Mercedes", points: 573, title: 0.999, expected_points: 610, max_points: 631, alive: true },
                   { team: "Red Bull Racing", points: 324, title: 0, expected_points: 350, max_points: 382, alive: false }],
    second_opinion: { RUS: 0.74, VER: 0.03 },
  };

  it("shows both championships as they stood going into the session, and after it on request", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      ({ ok: true, json: async () => (url.includes("/title") ? { ...odds, moment: url.endsWith("moment=after") ? "after" : "before" } : table(url.endsWith("moment=after") ? "after" : "before")) }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    const onSelect = vi.fn();
    render(<ScreenView id="standings" ctx={context({ onSelect })} />);

    const drivers = within(await screen.findByRole("table", { name: "Drivers' standings" }));
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/sessions/2026_15_R/standings?moment=before");
    expect(drivers.getByText("RUS")).toBeDefined();
    expect(drivers.getByText("238")).toBeDefined();
    expect(await drivers.findByText("82%")).toBeDefined();                // RUS's title chance
    expect(drivers.getByText("74%")).toBeDefined();                       // ...and the results-only second opinion
    expect(drivers.getByRole("columnheader", { name: "Results only" })).toBeDefined();
    expect(within(screen.getByRole("table", { name: "Constructors' standings" })).getByText("out")).toBeDefined();
    expect(screen.getByText(/the 1 Grand Prix and 1 sprint still to run simulated 10,000 times from these standings, up to 33 points/)).toBeDefined();
    expect(drivers.getByText("−25")).toBeDefined();                       // VER's gap to the leader
    expect(drivers.getByLabelText("up 1 since the last weekend")).toBeDefined();
    expect(drivers.getByLabelText("Latest finishes: P1, retired")).toBeDefined();
    const teams = within(screen.getByRole("table", { name: "Constructors' standings" }));
    expect(teams.getByText("573")).toBeDefined();
    expect(teams.getByText("VER 213 · LAW 14")).toBeDefined();            // who scored them
    expect(screen.getByText(/after 14 Grands Prix and 5 sprints, the latest the Azerbaijan Grand Prix sprint/)).toBeDefined();
    expect(screen.getByText(/the feed sent no points/)).toBeDefined();

    fireEvent.click(drivers.getByText("VER"));
    expect(onSelect).toHaveBeenCalledWith(3);

    fireEvent.click(screen.getByRole("radio", { name: "After it" }));
    expect(await screen.findByText(/after 15 Grands Prix/)).toBeDefined();
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/sessions/2026_15_R/standings?moment=after");
    expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/sessions/2026_15_R/title?moment=after");
  });
});

it("calls a title certain only once nobody else can reach the leader", () => {
  expect(titleChance(0.999, false)).toBe(">99%");
  expect(titleChance(1, false)).toBe(">99%");
  expect(titleChance(1, true)).toBe("100%");
  expect(titleChance(0.42, false)).toBe("42%");
});

describe("CrewsScreen", () => {
  const crews = {
    year: 2026, moment: "before", stops: 312, races: 20, notes: [],
    excluded: { "safety car": 321, "red flag": 57, penalty: 29 },
    teams: [
      { position: 1, team: "Mercedes", team_color: "00D7B6", stops: 30, typical_s: -0.61, spread_s: 1.1, q1_s: -1.0, q3_s: 0.1, slow_share: 0.11, thin: false },
      { position: 2, team: "Cadillac", team_color: "909090", stops: 31, typical_s: 1.14, spread_s: 2.7, q1_s: 0.2, q3_s: 2.9, slow_share: 0.38, thin: false },
    ],
    session_stops: [
      { t: 2000, lap: 18, driver_number: 63, abbreviation: "RUS", team: "Mercedes", team_color: "00D7B6", lane_s: 23.6, vs_typical_s: -0.4, excluded: null },
      { t: 2500, lap: 22, driver_number: 11, abbreviation: "PER", team: "Cadillac", team_color: "909090", lane_s: 21.0, vs_typical_s: -3.0, excluded: "safety car" },
      { t: 9000, lap: 40, driver_number: 3, abbreviation: "VER", team: "Red Bull Racing", team_color: "4781D7", lane_s: 24.0, vs_typical_s: 0.0, excluded: null },
    ],
  };

  it("ranks the crews and lists this session's stops up to the clock", async () => {
    const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => crews }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    render(<ScreenView id="crews" ctx={context({ t: 3000 })} />);

    const ranking = within(await screen.findByRole("table", { name: "Pit crew ranking" }));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2026_15_R/pit-crews?moment=before");
    expect(ranking.getByText("−0.61 s")).toBeDefined();
    expect(ranking.getByText("+1.14 s")).toBeDefined();
    expect(screen.getByText(/312 green-flag stops in 20 races and sprints; left out: 321 under a safety car or VSC, 57 in red flags, 29 serving penalties/)).toBeDefined();

    const stops = within(screen.getByRole("table", { name: "Stops in this session" }));
    expect(screen.getByText(/This session's stops so far: 2 of 3/)).toBeDefined();   // VER's, at t=9000, not yet
    expect(stops.queryByText("VER")).toBeNull();
    expect(stops.getByText(/not counted: under a safety car or VSC/)).toBeDefined();
  });
});

describe("Teammates", () => {
  afterEach(() => vi.unstubAllGlobals());

  const finishes = { ahead: [0, 0], races: 0, retired: [0, 0] };
  const pair = {
    team: "Mercedes", team_color: "00D7B6", rounds_together: 2,
    drivers: [{ abbreviation: "ANT", driver_number: 12, full_name: "Kimi Antonelli" },
              { abbreviation: "RUS", driver_number: 63, full_name: "George Russell" }],
    qualifying: { ahead: [1, 1], sessions: 2, gap_s: -0.231, pct: -0.248 },
    race_pace: { faster: [2, 0], sessions: 2, gap_s: -0.304 },
    practice: { faster: [3, 2], sessions: 5, gap_s: 0.11 },
    results: { ahead: [1, 0], races: 2, retired: [0, 1], points: [43, 0] },
    sprint: { ...finishes, qualifying: { ahead: [0, 0], sessions: 0, gap_s: null, pct: null }, pace: { faster: [0, 0], sessions: 0, gap_s: null } },
    rounds: [
      { round: 1, event_name: "Australian Grand Prix", quali_gap_s: -0.4, quali_pct: -0.5, race_gap_s: -0.2, sprint_gap_s: null, practice_gap_s: null },
      { round: 2, event_name: "Chinese Grand Prix", quali_gap_s: 0.1, quali_pct: 0.11, race_gap_s: null, sprint_gap_s: null, practice_gap_s: 0.11 },
    ],
  };

  it("shows each pair head to head and charts the gap the reader picks", async () => {
    const fetchMock = vi.fn(async (url: string) =>
      ({ ok: true, json: async () => ({ year: 2026, moment: url.endsWith("after") ? "after" : "before", rounds: 2, notes: ["a note"], pairs: [pair] }) }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    render(<ScreenView id="teammates" ctx={context()} />);

    const table = within(await screen.findByRole("table", { name: "Mercedes: ANT against RUS, head to head" }));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2026_15_R/teammates?moment=before");
    expect(table.getByText("ANT 0.231 s quicker (0.25%)")).toBeDefined();
    expect(table.getByText("ANT 0.304 s a lap quicker · 2 sessions")).toBeDefined();
    expect(table.getByText("RUS 0.110 s quicker · 5 sessions")).toBeDefined();
    expect(table.getByText("retirements: ANT 0, RUS 1")).toBeDefined();
    expect(table.getByText("Qualified ahead")).toBeDefined();
    expect(table.queryByText("Sprints ahead")).toBeNull();                 // no sprint run yet
    expect(screen.getByText("a note")).toBeDefined();

    // Qualifying first: one round each way.
    expect(screen.getByRole("img", { name: "Qualifying gap by round: ANT quicker in 1, RUS in 1" })).toBeDefined();
    fireEvent.click(screen.getByRole("radio", { name: "Race pace" }));
    expect(screen.getByRole("img", { name: "Race pace gap by round: ANT quicker in 1, RUS in 0" })).toBeDefined();
    expect(screen.getByText("Round 2, Chinese Grand Prix: nothing to compare")).toBeDefined();

    fireEvent.click(screen.getByRole("radio", { name: "After it" }));
    await waitFor(() => expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/sessions/2026_15_R/teammates?moment=after"));
  });

  it("words a gap by who was quicker, and rounds the chart's reach up", () => {
    expect(gapText(-0.2314, "ANT", "RUS")).toBe("ANT 0.231 s quicker");
    expect(gapText(0.0004, "ANT", "RUS")).toBe("level");
    expect(gapText(0.5, "ANT", "RUS", "a lap")).toBe("RUS 0.500 s a lap quicker");
    expect([0.03, 0.31, 0.5, 1.2, 7].map(niceCeiling)).toEqual([0.05, 0.5, 0.5, 2, 10]);
    // One 1.6 s round among 0.1-0.3 s ones: the scale stops at three times the median (0.2), not 2 s.
    expect(chartReach([-0.1, 0.2, -0.3, 0.2, -1.6])).toBe(1);
    expect(chartReach([-0.2, 0.3])).toBe(0.5);                           // nothing to clip
  });
});

describe("Starts", () => {
  it("signs places gained and keeps a level start plain", () => {
    expect(places(1.294)).toBe("+1.29");
    expect(places(-0.4)).toBe("−0.40");
    expect(places(0.001)).toBe("0.00");
    expect(places(null)).toBe("—");
  });

  it("names a start by its grid slot, lap-1 place and event", () => {
    expect(startText({ event_name: "Chinese Grand Prix", grid: 14, lap1: 7, gain: 7 })).toBe("P14 → P7, Chinese");
    expect(startText({ event_name: "Miami Grand Prix sprint", grid: 3, lap1: 5, gain: -2 })).toBe("P3 → P5, Miami sprint");
    expect(startText(null)).toBe("—");
  });
});

describe("Qualifying laps", () => {
  afterEach(() => vi.unstubAllGlobals());

  const driver = (abbreviation: string, position: number, left: number, split: number[]) => ({
    abbreviation, full_name: null, team: "Mercedes", team_color: "00D7B6", position, best_s: 94.035,
    ideal_s: 94.035 - left, left_s: left, sectors_left: split, season_left_s: 0.049, season_sessions: 18 });

  it("shows each driver's best lap against their perfect lap, and asks for sprint qualifying", async () => {
    const fetchMock = vi.fn(async (_url: string) =>
      ({ ok: true, json: async () => ({ year: 2026, moment: "before", session_key: "2026_18_Q", event_name: "United States Grand Prix",
                                         sessions: 18, notes: [], drivers: [driver("ANT", 1, 0.13, [0.018, 0.112, 0]), driver("HAD", 3, 0, [0, 0, 0])] }) }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    render(<ScreenView id="qualifying" ctx={context()} />);

    const table = within(await screen.findByRole("table", { name: "Time left on the table" }));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2026_15_R/qualifying?moment=before&kind=Q");
    expect(table.getByText("+0.130")).toBeDefined();
    expect(table.getByText("perfect")).toBeDefined();
    expect(table.getByText("0.112").tagName).toBe("B");                  // the sector that cost most
    expect(table.getAllByText("1:34.035")).toHaveLength(3);          // ANT best, HAD best and perfect
    expect(screen.getByText("United States Grand Prix, qualifying")).toBeDefined();

    fireEvent.click(screen.getByRole("radio", { name: "Sprint qualifying" }));
    await waitFor(() => expect(fetchMock.mock.calls.map((c) => c[0])).toContain("/api/sessions/2026_15_R/qualifying?moment=before&kind=SQ"));
  });

  it("words the time left", () => {
    expect(leftText(0.1304)).toBe("+0.130");
    expect(leftText(0.0002)).toBe("perfect");
    expect(leftText(null)).toBe("—");
  });
});

describe("Race review", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows overtakes and what each stop cost, marking the cheap ones", async () => {
    const drivers = [
      { abbreviation: "BOR", full_name: null, team: "Audi", team_color: "ff0000", position: "13", status: null, passes_made: 4, passes_lost: 0,
        stops: [{ lap: 26, kind: "green", places: 5 }, { lap: 50, kind: "VSC", places: 2 }], pit_places: 7 },
      { abbreviation: "BOT", full_name: null, team: "Cadillac", team_color: null, position: null, status: "R", passes_made: 0, passes_lost: 4,
        stops: [], pit_places: 0 },
    ];
    const fetchMock = vi.fn(async (_url: string) =>
      ({ ok: true, json: async () => ({ year: 2026, moment: "before", session_key: "2026_18_R", event_name: "United States Grand Prix",
                                         green_stop_places: 4, notes: [], drivers }) }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    render(<ScreenView id="review" ctx={context()} />);

    const table = within(await screen.findByRole("table", { name: "Overtakes and pit stops" }));
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2026_15_R/race-review?moment=before");
    expect(table.getByText("L50 VSC −2").className).toBe("is-quick");
    expect(table.getByText("DNF")).toBeDefined();
    expect(screen.getByText(/a normal pit stop here cost about 4 places/)).toBeDefined();
  });

  it("words a stop", () => {
    expect(stopText({ lap: 24, kind: "green", places: 2 })).toBe("L24 −2");
    expect(stopText({ lap: 31, kind: "safety car", places: 0 })).toBe("L31 SC ±0");
  });
});
