import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";

/** Enough of the API to drive the whole app, so the wiring is exercised end to end. */
function mockApi() {
  const sessions = [
    { session_key: "2024_01_R", year: 2024, round: 1, session: "R", event_name: "Bahrain Grand Prix",
      location: "Sakhir", session_name: "Race", date_utc: "2024-03-02 15:00:00+00:00", total_laps: 57 },
  ];
  const info = {
    session: { event_name: "Bahrain Grand Prix", session_name: "Race", location: "Sakhir", circuit_rotation_deg: 0 },
    t_start: 1000, t_end: 1600, total_laps: 57,
    drivers: [
      { driver_number: 1, abbreviation: "VER", full_name: "Max Verstappen", team_name: "Red Bull",
        team_color: "3671C6", grid_position: 1, position: 1, classified_position: "1", status: "Finished" },
      { driver_number: 11, abbreviation: "PER", full_name: "Sergio Perez", team_name: "Red Bull",
        team_color: "3671C6", grid_position: 5, position: 2, classified_position: "2", status: "Finished" },
    ],
    outline: [[0, 0], [100, 0], [100, 100], [0, 100]],
    bounds: { min_x: 0, max_x: 100, min_y: 0, max_y: 100 },
    has_position_data: true,
  };
  const sectors = (a: number, b: number, c: number) => [
    { sector: 1, seconds: a, state: "normal" as const },
    { sector: 2, seconds: b, state: "normal" as const },
    { sector: 3, seconds: c, state: "normal" as const },
  ];
  const state = {
    t: 1000, leader_lap: 12,
    best_sectors: [
      { sector: 1, seconds: 29.741, driver_number: 1, driver: "VER" },
      { sector: 2, seconds: 39.916, driver_number: 11, driver: "PER" },
      { sector: 3, seconds: 22.951, driver_number: 1, driver: "VER" },
    ],
    ideal_lap_s: 92.608,
    drivers: [
      { driver_number: 1, abbreviation: "VER", team_name: "Red Bull", team_color: "3671C6", position: 1,
        status: "racing", laps_completed: 12, gap_to_leader_s: null, gap_text: "", interval_s: null,
        interval_text: "", laps_down: 0, last_lap_s: 92.608, best_lap_s: 92.608, is_session_best: true,
        is_personal_best: true, compound: "HARD", tyre_life: 9, laps_in_stint: 5, stops: 1,
        sectors: sectors(29.741, 39.916, 22.951) },
      { driver_number: 11, abbreviation: "PER", team_name: "Red Bull", team_color: "3671C6", position: 2,
        status: "racing", laps_completed: 12, gap_to_leader_s: 6.213, gap_text: "+6.213", interval_s: 6.213,
        interval_text: "+6.213", laps_down: 0, last_lap_s: 93.104, best_lap_s: 93.0, is_session_best: false,
        is_personal_best: false, compound: "SOFT", tyre_life: 3, laps_in_stint: 3, stops: 1,
        sectors: sectors(30.1, 40.2, 23.0) },
    ],
    cars: { "1": { x: 10, y: 10, speed: 280 }, "11": { x: 20, y: 20, speed: 275 } },
    track_status: { status: "1", message: "AllClear" },
    weather: { air_temp: 25, track_temp: 31.5, rainfall: false },
  };
  const laps = {
    drivers: [
      { driver_number: 1, abbreviation: "VER", team_color: "3671C6", laps: [1, 2], gap_to_leader_s: [0, 0], position: [1, 1],
        lap_time_s: [93.0, 92.608], compound: ["SOFT", "SOFT"], pit_in: [false, false] },
      { driver_number: 11, abbreviation: "PER", team_color: "3671C6", laps: [1, 2], gap_to_leader_s: [2.1, 6.2], position: [2, 2],
        lap_time_s: [94.0, 93.104], compound: ["SOFT", "SOFT"], pit_in: [false, true] },
    ],
    leader_crossings: { laps: [1, 2], t: [1090, 1182] },
  };
  const frames = {
    t: [1000, 1001], drivers: { "1": { x: [10, 12], y: [10, 12] }, "11": { x: [20, 22], y: [20, 22] } },
  };

  const insight = {
    session_key: "2024_01_R", circuit: "Sakhir", event_name: "Bahrain Grand Prix", year: 2024,
    is_race: true, total_laps: 57,
    pit_loss: { circuit: "Sakhir", seconds: 22.4, spread_s: 0.8, stops: 60, seasons: 3 },
    safety_car: null, scale: 1.5,
    degradation_measured: { SOFT: 0.04 }, degradation_used: { SOFT: 0.06 },
    compound_offset_s: {}, fuel_s_per_lap: 0.05,
    fitted_on: ["Jeddah Grand Prix"], fitted_on_count: 1, held_out: true,
    caveats: ["traffic: a car released into a queue loses time this does not count"],
    degradation_curve: [], plans: [], plans_with_risk: [], plans_unavailable: "no plans in this fixture", stints: [],
  };

  const messages = [
    { t: 1100, lap: 12, kind: "time_penalty", seconds: 5, reason: "TRACK LIMITS",
      cars: [11], incident: null, stewards: true, topic: "stewards",
      message: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 11 (PER) - TRACK LIMITS" },
  ];

  const fetchMock = vi.fn(async (url: string) => {
    const body = url.includes("/insight") ? insight
      : url.includes("/messages") ? messages
      : url.includes("/state") ? state
      : url.includes("/frames") ? frames
      : url.includes("/laps") ? laps
      : url.match(/sessions\/[^/?]+$/) ? info
      : sessions;
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** The same API, but live: a "live" row in the list and a session that grows. */
function mockLiveApi() {
  const state = { edge: 1200 };
  const sessions = [
    { session_key: "live", year: 2026, round: 17, session: "LIVE", event_name: "Live timing",
      location: "", country: "", session_name: "Race", date_utc: "", total_laps: null },
    { session_key: "2024_01_R", year: 2024, round: 1, session: "R", event_name: "Bahrain Grand Prix",
      location: "Sakhir", session_name: "Race", date_utc: "2024-03-02 15:00:00+00:00", total_laps: 57 },
  ];
  const info = () => ({
    session: { event_name: "Azerbaijan Grand Prix", session_name: "Race", location: "Baku" },
    t_start: 1000, t_end: state.edge, total_laps: 51,
    drivers: [{ driver_number: 1, abbreviation: "VER", full_name: "Max Verstappen",
                team_name: "Red Bull", team_color: "3671C6", grid_position: 1, position: 1,
                classified_position: "1", status: "Finished" }],
    outline: [], bounds: {}, has_position_data: false,
  });
  const fetchMock = vi.fn(async (url: string) => {
    const body = url.includes("/insight") ? { detail: "not ready" }
      : url.includes("/state") ? { t: state.edge, leader_lap: 12, best_sectors: [], ideal_lap_s: null,
                                   drivers: [], cars: {}, track_status: null, weather: null }
      : url.includes("/laps") ? { drivers: [], leader_crossings: { laps: [], t: [] } }
      : url.match(/sessions\/[^/?]+$/) ? info()
      : sessions;
    return { ok: true, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return state;
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("loads a session and fills the tower, the clock and the flag bar", async () => {
    mockApi();
    const { container } = render(<App />);

    // Scoped to the tower: driver codes and sector times also appear in the
    // best-sectors strip beneath it.
    await waitFor(() => expect(container.querySelector(".tower-rows")).not.toBeNull());
    const tower = within(container.querySelector(".tower-rows") as HTMLElement);
    await waitFor(() => expect(tower.getByText("VER")).toBeDefined());
    expect(screen.getByText("LEADER")).toBeDefined();
    // Both the gap and the interval columns: PER is second and 6.213 s behind.
    expect(tower.getAllByText("+6.213")).toHaveLength(2);
    expect(screen.getByText("TRACK CLEAR")).toBeDefined();
    expect(screen.getByText("LAP 12 / 57")).toBeDefined();
    expect(screen.getByText("TRACK 32°C")).toBeDefined();
    expect(screen.getByRole("slider", { name: /session time/i })).toBeDefined();
  });

  it("selecting a driver in the tower marks that row", async () => {
    mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("PER").length).toBeGreaterThan(0));

    const rows = screen.getAllByRole("button", { pressed: false });
    const perRow = rows.find((row) => row.textContent?.includes("PER"))!;
    perRow.click();
    await waitFor(() => expect(perRow.getAttribute("aria-pressed")).toBe("true"));
  });


  it("does not fit a season until a tab that needs it is opened", async () => {
    const fetchMock = mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));

    // The fit costs seconds on the server, so opening a replay must not trigger it.
    const asked = () => fetchMock.mock.calls.filter(([url]) => String(url).includes("/insight"));
    expect(asked()).toHaveLength(0);

    screen.getByRole("tab", { name: "Strategy" }).click();
    await waitFor(() => expect(asked().length).toBeGreaterThan(0));
    await waitFor(() => expect(screen.getByText("22.4s")).toBeDefined());

    // Switching between the two model tabs reuses the one fit.
    const once = asked().length;
    screen.getByRole("tab", { name: "Tyre model" }).click();
    await waitFor(() => expect(screen.getByText(/no dry-tyre laps/i)).toBeDefined());
    expect(asked()).toHaveLength(once);
  });

  it("keeps the race trace as the tab that opens first", async () => {
    mockApi();
    const { container } = render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));
    expect(screen.getByRole("tab", { name: "Race trace" }).getAttribute("aria-selected")).toBe("true");
    expect(container.querySelector(".tab-body canvas")).not.toBeNull();
  });


  it("opens a live session following the newest lap", async () => {
    mockLiveApi();
    render(<App />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeDefined());

    // Following means the clock sits at the leading edge, not at the start.
    const slider = screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
    await waitFor(() => expect(Number(slider.value)).toBe(1200));
  });

  it("follows the session forward as laps are completed", async () => {
    // The re-read runs on a ten-second timer. Fake timers have to be installed
    // before the render that schedules it — switching afterwards leaves the
    // real interval in place and nothing ever fires. Real timers would make
    // this test take longer than the rest of the suite put together.
    const flush = async () => {
      await act(async () => {
        for (let i = 0; i < 20; i += 1) await Promise.resolve();
      });
    };

    vi.useFakeTimers();
    try {
      const state = mockLiveApi();
      render(<App />);
      await flush();

      const slider = () => screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
      expect(Number(slider().value)).toBe(1200);

      state.edge = 1300;                     // a lap goes by
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await flush();

      expect(Number(slider().value)).toBe(1300);
    } finally {
      vi.useRealTimers();
    }
  });

  it("stops following when the clock is scrubbed, and says so", async () => {
    mockLiveApi();
    render(<App />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeDefined());

    const slider = screen.getByRole("slider", { name: /session time/i });
    fireEvent.change(slider, { target: { value: "1100" } });

    // Someone looking at an earlier lap must not be yanked forward a second later.
    await waitFor(() => expect(screen.getByText("PAUSED")).toBeDefined());
    expect(screen.getByRole("button", { name: /go live/i })).toBeDefined();
  });

  it("goes back to following when asked", async () => {
    mockLiveApi();
    render(<App />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeDefined());

    fireEvent.change(screen.getByRole("slider", { name: /session time/i }), { target: { value: "1100" } });
    await waitFor(() => expect(screen.getByText("PAUSED")).toBeDefined());

    screen.getByRole("button", { name: /go live/i }).click();
    await waitFor(() => expect(screen.getByText("LIVE")).toBeDefined());
    const slider = screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
    await waitFor(() => expect(Number(slider.value)).toBe(1200));
  });

  it("shows no live badge on a session from the lake", async () => {
    mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));
    expect(screen.queryByText("LIVE")).toBeNull();
  });

  it("shows the error when the API is unreachable, rather than an empty screen", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, statusText: "Service Unavailable", json: async () => ({ detail: "lake not found" }),
    } as Response)));
    render(<App />);
    await waitFor(() => expect(screen.getByText("lake not found")).toBeDefined());
  });

  it("shows who holds each sector and what an ideal lap would be", async () => {
    mockApi();
    const { container } = render(<App />);
    await waitFor(() => expect(container.querySelector(".best-sectors")).not.toBeNull());
    const strip = within(container.querySelector(".best-sectors") as HTMLElement);
    expect(strip.getByText("29.741")).toBeDefined();     // fastest S1, held by VER
    expect(strip.getByText("IDEAL")).toBeDefined();
    expect(strip.getByText("1:32.608")).toBeDefined();   // the three best sectors added up
  });
});