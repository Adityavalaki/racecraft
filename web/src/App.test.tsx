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
    const body = url.includes("/api/sync") ? { state: "idle", weekends: [], items: [], counts: {}, to_fetch: 0, current: null,
                                  started_at: null, finished_at: null, error: null }
      : url.includes("/insight") ? insight
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

/**
 * The same API, but live: a "live" row in the list and a session that grows.
 * Until `ready`, live answers 409 the way a server does before its recording
 * has anything in it. `calls` is every request, in order, as "METHOD url".
 */
function mockLiveApi() {
  const state = { edge: 1200, ready: true, calls: [] as string[] };
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
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    state.calls.push(`${init?.method ?? "GET"} ${url}`);
    const liveData = url.includes("/api/sessions/live");
    if (liveData && !state.ready) {
      return { ok: false, status: 409, statusText: "Conflict",
               json: async () => ({ detail: "the recording has nothing in it yet" }) } as Response;
    }
    const body = url.includes("/api/sync") ? { state: "idle", weekends: [], items: [], counts: {}, to_fetch: 0, current: null,
                                  started_at: null, finished_at: null, error: null }
      : url.includes("/api/live/attach") ? { attached: true, recording: "baku.txt" }
      : url.includes("/insight") ? { detail: "not ready" }
      : url.includes("/state") ? { t: state.edge, leader_lap: 12, best_sectors: [], ideal_lap_s: null,
                                   drivers: [], cars: {}, track_status: null, weather: null }
      : url.includes("/laps") ? { drivers: [], leader_crossings: { laps: [], t: [] } }
      : url.match(/sessions\/[^/?]+$/) ? info()
      : sessions;
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  vi.stubGlobal("fetch", fetchMock);
  return state;
}

/** Lets pending promises settle inside act, for tests on fake timers. */
async function flush() {
  await act(async () => {
    for (let i = 0; i < 20; i += 1) await Promise.resolve();
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("App", () => {
  it("loads a session and fills the leaderboard, the clock and the flag", async () => {
    mockApi();
    const { container } = render(<App />);

    await waitFor(() => expect(container.querySelector(".leaderboard-rows")).not.toBeNull());
    const board = within(container.querySelector(".leaderboard-rows") as HTMLElement);
    await waitFor(() => expect(board.getByText("VER")).toBeDefined());
    expect(board.getByText("LEADER")).toBeDefined();
    expect(board.getByText("+6.213")).toBeDefined();        // the gap; intervals are the tower's
    // The flag shows in the clock bar; lap, clock and weather in the strip under the map.
    expect(within(container.querySelector(".clockbar") as HTMLElement).getByText("TRACK CLEAR")).toBeDefined();
    const strip = container.querySelector(".session-strip") as HTMLElement;
    await waitFor(() => expect(strip.textContent).toContain("12 / 57"));
    expect(within(strip).getByText("32°C")).toBeDefined();
    expect(within(strip).getByText("Bahrain Grand Prix")).toBeDefined();
    expect(screen.getByRole("slider", { name: /session time/i })).toBeDefined();
  });

  it("lays out the sketch: launcher left, map with the session strip and race control in the middle, leaderboard right", async () => {
    mockApi();
    const { container } = render(<App />);
    await waitFor(() => expect(container.querySelector(".workspace")).not.toBeNull());
    const columns = Array.from(container.querySelectorAll(".workspace > .col")).map((col) => col.className);
    expect(columns).toEqual(["col col-left", "col col-map", "col col-right"]);

    const left = container.querySelector(".col-left") as HTMLElement;
    const order = Array.from(left.querySelectorAll(".left-sync, .feature-launcher, .driver-cards, .keys, h2"))
      .map((el) => el.className || el.textContent);
    expect(order[0]).toBe("left-sync");                       // sync first, then the features, then the drivers
    expect(order.indexOf("feature-launcher")).toBeLessThan(order.indexOf("Drivers"));

    const middle = container.querySelector(".col-map") as HTMLElement;
    expect(middle.querySelector(".map-area canvas.track-map")).not.toBeNull();
    expect(middle.querySelector(".map-area .session-strip")).not.toBeNull();
    const below = Array.from(middle.querySelectorAll(".below-map > section")).map((s) => s.getAttribute("aria-label"));
    expect(below).toEqual(["Stewards", "Track log"]);
    expect(middle.querySelector('[role="separator"][aria-orientation="horizontal"]')).not.toBeNull();

    expect(container.querySelector(".col-right .leaderboard")).not.toBeNull();
    expect(within(container.querySelector(".topbar") as HTMLElement).queryByRole("button", { name: /refresh/i })).toBeNull();
  });

  it("selecting a driver in the leaderboard marks that row", async () => {
    mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("PER").length).toBeGreaterThan(0));

    const rows = screen.getAllByRole("button", { pressed: false });
    const perRow = rows.find((row) => row.textContent?.includes("PER"))!;
    perRow.click();
    await waitFor(() => expect(perRow.getAttribute("aria-pressed")).toBe("true"));
  });


  it("never fits a season itself: the model features have their own windows", async () => {
    const fetchMock = mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));
    // The fit costs seconds on the server; the replay window shows nothing that needs it.
    await act(async () => {
      for (let i = 0; i < 20; i += 1) await Promise.resolve();
    });
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/insight"))).toBe(false);
  });

  it("opens each feature in a window of its own for the session on screen", async () => {
    const fetchMock = mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));
    const launcher = screen.getByRole("navigation", { name: /open a feature/i });
    // Stewards and the track log are on this window, under the map; the launcher has the rest.
    expect(within(launcher).getAllByRole("button").map((b) => b.textContent?.replace("↗", "").trim())).toEqual(
      ["Timing tower", "Race trace", "Tyre model", "Strategy", "Tyre sets", "Race prediction"]);

    fireEvent.click(within(launcher).getByRole("button", { name: /strategy/i }));
    fireEvent.click(screen.getByRole("button", { name: /full timing tower/i }));
    fireEvent.click(screen.getByRole("button", { name: /open the stewards in a window/i }));
    await waitFor(() => {
      const calls = fetchMock.mock.calls as unknown as [string, RequestInit | undefined][];
      const opened = calls.filter(([url]) => url.startsWith("/api/app/window"));
      expect(opened.map(([url, init]) => [url, init?.method])).toEqual([
        ["/api/app/window?feature=strategy&session=2024_01_R", "POST"],
        ["/api/app/window?feature=tower&session=2024_01_R", "POST"],
        ["/api/app/window?feature=stewards&session=2024_01_R", "POST"],
      ]);
    });
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

});

describe("App on a new install", () => {
  /** An empty lake, whose first sync writes one race. */
  function mockEmptyLake() {
    const race = {
      session_key: "2024_01_R", year: 2024, round: 1, session: "R", event_name: "Bahrain Grand Prix",
      location: "Sakhir", session_name: "Race", date_utc: "2024-03-02 15:00:00+00:00", total_laps: 57,
    };
    const lake = { sessions: [] as (typeof race)[], calls: [] as string[] };
    const idle = { state: "idle", weekends: [], items: [], counts: {}, to_fetch: 0, current: null,
                   started_at: null, finished_at: null, error: null };
    const synced = { ...idle, state: "done", weekends: ["Bahrain"], counts: { written: 1 },
                     started_at: "2026-09-30T10:00:00Z", finished_at: "2026-09-30T10:01:00Z" };
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      lake.calls.push(`${method} ${url}`);
      let body: unknown;
      if (url.includes("/api/sync")) {
        if (method === "POST") lake.sessions = [race];    // the sync writes it
        body = method === "POST" ? synced : idle;
      } else if (url.includes("/laps")) {
        body = { drivers: [], leader_crossings: { laps: [], t: [] } };
      } else if (url.includes("/state")) {
        body = { t: 1000, leader_lap: 0, best_sectors: [], ideal_lap_s: null, drivers: [], cars: {},
                 track_status: null, weather: null };
      } else if (/sessions\/[^/?]+$/.test(url)) {
        body = { session: { event_name: "Bahrain Grand Prix", session_name: "Race", location: "Sakhir" },
                 t_start: 1000, t_end: 1600, total_laps: 57, drivers: [], outline: [], bounds: {},
                 has_position_data: false };
      } else if (url.includes("/api/sessions?") || url.endsWith("/api/sessions")) {
        body = lake.sessions;
      } else {
        body = [];
      }
      return { ok: true, status: 200, json: async () => body } as Response;
    }));
    return lake;
  }

  it("says there are no sessions yet and how to get some", async () => {
    mockEmptyLake();
    render(<App />);
    await waitFor(() => expect(screen.getByText("No sessions yet.")).toBeDefined());
    expect(screen.getByText(/Refresh downloads the latest race weekends/)).toBeDefined();
    expect(screen.queryByText(/Loading/)).toBeNull();
    const sync = screen.getByRole("button", { name: /^refresh$/i }) as HTMLButtonElement;
    expect(sync.disabled).toBe(false);
  });

  it("opens the first session a sync brings in", async () => {
    const lake = mockEmptyLake();
    render(<App />);
    await waitFor(() => expect(screen.getByText("No sessions yet.")).toBeDefined());

    screen.getByRole("button", { name: /^refresh$/i }).click();

    await waitFor(() => expect(lake.calls).toContain("GET /api/sessions/2024_01_R"));
    expect(lake.calls).toContain("GET /api/sessions/2024_01_R/laps");
    await waitFor(() => expect(screen.getByText(/Sakhir · 0 cars/)).toBeDefined());
    expect(screen.queryByText("No sessions yet.")).toBeNull();
    const picker = screen.getByRole("combobox") as HTMLSelectElement;
    expect(picker.value).toBe("2024_01_R");
  });

  it("shows why the list could not be read instead of loading forever", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false, status: 500, statusText: "Internal Server Error", json: async () => ({ detail: "disk unreadable" }),
    } as Response)));
    render(<App />);
    await waitFor(() => expect(screen.getByText("disk unreadable")).toBeDefined());
    expect(screen.getByText("Could not read the session list.")).toBeDefined();
    expect(screen.queryByText(/Loading/)).toBeNull();
  });
});

describe("App attaching live", () => {
  const indexOf = (calls: string[], call: string) => calls.findIndex((c) => c === call);

  it("attaches live before asking for its info and laps", async () => {
    const live = mockLiveApi();
    render(<App />);
    await waitFor(() => expect(screen.getByText("LIVE")).toBeDefined());
    await waitFor(() => expect(indexOf(live.calls, "GET /api/sessions/live/laps")).toBeGreaterThan(-1));

    const attach = indexOf(live.calls, "POST /api/live/attach");
    expect(attach).toBeGreaterThan(-1);
    expect(attach).toBeLessThan(indexOf(live.calls, "GET /api/sessions/live"));
    expect(attach).toBeLessThan(indexOf(live.calls, "GET /api/sessions/live/laps"));
  });

  it("waits while live has nothing yet, and recovers on the next poll", async () => {
    vi.useFakeTimers();
    try {
      const live = mockLiveApi();
      live.ready = false;
      render(<App />);
      await flush();

      expect(screen.getByText("Waiting for live data…")).toBeDefined();
      expect(screen.queryByText("the recording has nothing in it yet")).toBeNull();
      const attaches = () => live.calls.filter((c) => c === "POST /api/live/attach").length;
      expect(attaches()).toBe(1);

      live.ready = true;
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await flush();

      expect(attaches()).toBe(2);                // attached again while waiting
      expect(screen.queryByText("Waiting for live data…")).toBeNull();
      const slider = screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
      expect(Number(slider.value)).toBe(1200);

      // Once it has data it is not attached again on every poll.
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await flush();
      expect(attaches()).toBe(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("never attaches for a session from the lake", async () => {
    const fetchMock = mockApi();
    render(<App />);
    await waitFor(() => expect(screen.getAllByText("VER").length).toBeGreaterThan(0));
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/api/live/attach"))).toBe(false);
  });
});

describe("App nudging a live clock", () => {
  it("−30s stops following, and a later lap does not pull the clock forward", async () => {
    vi.useFakeTimers();
    try {
      const live = mockLiveApi();
      render(<App />);
      await flush();

      const slider = () => screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
      expect(Number(slider().value)).toBe(1200);
      expect(screen.getByText("LIVE")).toBeDefined();

      fireEvent.click(screen.getByRole("button", { name: "Back 30 seconds" }));
      await flush();

      expect(Number(slider().value)).toBe(1170);
      expect(screen.getByText("PAUSED")).toBeDefined();
      expect(screen.getByRole("button", { name: /go live/i })).toBeDefined();

      live.edge = 1300;                          // a lap goes by
      await act(async () => {
        vi.advanceTimersByTime(10_000);
      });
      await flush();

      expect(Number(slider().value)).toBe(1170);
    } finally {
      vi.useRealTimers();
    }
  });
});

// ------------------------------------------------------------- answers that arrive late

/** Returned by a route to hold a request until the test answers it. */
const HOLD = Symbol("hold");

interface Held {
  url: string;
  aborted: boolean;
  /** Answer now; ignored once aborted, as a real fetch would be. */
  answer: (body: unknown, status?: number) => void;
}

function respond(body: unknown, status = 200): Response {
  return { ok: status < 400, status, statusText: status < 400 ? "OK" : "Error", json: async () => body } as Response;
}

/**
 * A server the test answers by hand. `route` returns the body to answer at
 * once, or HOLD to keep the request open. Held requests honour their abort
 * signal like the stub in positions.test.ts: aborting rejects with AbortError
 * and a later answer is dropped.
 */
function deferredFetch(route: (url: string, method: string) => unknown) {
  const held: Held[] = [];
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    calls.push(`${method} ${url}`);
    const body = route(url, method);
    if (body !== HOLD) return Promise.resolve(respond(body));
    return new Promise<Response>((resolve, reject) => {
      const entry: Held = {
        url,
        aborted: false,
        answer: (answer, status = 200) => {
          if (!entry.aborted) resolve(respond(answer, status));
        },
      };
      init?.signal?.addEventListener("abort", () => {
        entry.aborted = true;
        const error = new Error("aborted");
        error.name = "AbortError";
        reject(error);
      });
      held.push(entry);
    });
  }));
  /** The oldest request still held for exactly this URL. */
  const take = (url: string) => {
    const index = held.findIndex((h) => h.url === url);
    if (index === -1) throw new Error(`nothing held for ${url}; held: ${held.map((h) => h.url).join(", ")}`);
    return held.splice(index, 1)[0]!;
  };
  const waitsFor = (url: string) => held.some((h) => h.url === url);
  return { calls, take, waitsFor };
}

const IDLE_SYNC = { state: "idle", weekends: [], items: [], counts: {}, to_fetch: 0, current: null,
                    started_at: null, finished_at: null, error: null };

function summary(key: string, round: number, session: string, event: string) {
  return { session_key: key, year: 2024, round, session, event_name: event, location: "",
           session_name: session === "R" ? "Race" : "Qualifying", date_utc: "", total_laps: 57 };
}

const BAHRAIN = summary("2024_01_R", 1, "R", "Bahrain Grand Prix");
const BAHRAIN_Q = summary("2024_01_Q", 1, "Q", "Bahrain Grand Prix");
const JEDDAH = summary("2024_02_R", 2, "R", "Saudi Arabian Grand Prix");

function infoAt(location: string, tEnd = 1600) {
  return { session: { event_name: location, session_name: "Race", location }, t_start: 1000, t_end: tEnd,
           total_laps: 57, drivers: [], outline: [], bounds: {}, has_position_data: false };
}

function insightWith(pitLoss: number) {
  return {
    session_key: "x", circuit: "x", event_name: "x", year: 2024, is_race: true, total_laps: 57,
    pit_loss: { circuit: "x", seconds: pitLoss, spread_s: 0.8, stops: 60, seasons: 3 },
    safety_car: null, scale: 1, degradation_measured: {}, degradation_used: {}, compound_offset_s: {},
    fuel_s_per_lap: 0.05, fitted_on: [], fitted_on_count: 0, held_out: true, caveats: [],
    degradation_curve: [], plans: [], plans_with_risk: [], plans_unavailable: "none here", stints: [],
  };
}

/** Everything a session page asks for, answered at once, unless `hold` or `overrides` say otherwise. */
function answers(sessions: unknown[], hold: (url: string, method: string) => boolean = () => false,
                 overrides: (url: string, method: string) => unknown = () => undefined) {
  return (url: string, method: string) => {
    if (hold(url, method)) return HOLD;
    const special = overrides(url, method);
    if (special !== undefined) return special;
    if (url.includes("/api/sync")) return IDLE_SYNC;
    if (url.includes("/api/live/attach")) return { attached: true, recording: "baku.txt" };
    if (url.includes("/insight")) return insightWith(22.4);
    if (url.includes("/messages")) return [];
    if (url.includes("/state")) {
      return { t: 1000, leader_lap: 0, best_sectors: [], ideal_lap_s: null, drivers: [], cars: {},
               track_status: null, weather: null };
    }
    if (url.includes("/laps")) return { drivers: [], leader_crossings: { laps: [], t: [] } };
    if (url.includes("2024_02_R")) return infoAt("Jeddah");
    if (url.includes("2024_01_Q")) return infoAt("Sakhir Q");
    if (/sessions\/[^/?]+$/.test(url)) return infoAt("Sakhir");
    return sessions;
  };
}

describe("App with answers that arrive late", () => {
  const picker = () => screen.getByRole("combobox") as HTMLSelectElement;

  it("a slow first session list does not undo what a sync brought, or the pick made since", async () => {
    const before = [BAHRAIN];
    const after = [JEDDAH, BAHRAIN, BAHRAIN_Q];
    const server = deferredFetch(answers(before, (url) => url === "/api/sessions",
      (url, method) => (url === "/api/sync" && method === "POST"
        ? { ...IDLE_SYNC, state: "done", counts: { written: 2 }, finished_at: "2026-09-30T10:00:00Z" }
        : undefined)));
    render(<App />);
    await waitFor(() => expect(server.waitsFor("/api/sessions")).toBe(true));
    const first = server.take("/api/sessions");

    screen.getByRole("button", { name: /^refresh$/i }).click();
    await waitFor(() => expect(server.waitsFor("/api/sessions")).toBe(true));
    await act(async () => server.take("/api/sessions").answer(after));
    await waitFor(() => expect(picker().value).toBe("2024_02_R"));

    fireEvent.change(picker(), { target: { value: "2024_01_Q" } });
    await waitFor(() => expect(screen.getByText(/Sakhir Q · 0 cars/)).toBeDefined());

    await act(async () => first.answer(before));        // the list from before the sync, late
    await flush();
    expect(picker().value).toBe("2024_01_Q");
    expect(Array.from(picker().options).map((o) => o.value)).toContain("2024_02_R");
  });

  it("a late answer for the previous session does not replace the one now open", async () => {
    const server = deferredFetch(answers([BAHRAIN, JEDDAH],
      (url) => url === "/api/sessions/2024_01_R" || url === "/api/sessions/2024_01_R/laps"));
    render(<App />);
    await waitFor(() => expect(server.waitsFor("/api/sessions/2024_01_R")).toBe(true));
    const oldInfo = server.take("/api/sessions/2024_01_R");
    const oldLaps = server.take("/api/sessions/2024_01_R/laps");

    fireEvent.change(picker(), { target: { value: "2024_02_R" } });
    await waitFor(() => expect(screen.getByText(/Jeddah · 0 cars/)).toBeDefined());

    await act(async () => {
      oldInfo.answer(infoAt("Sakhir"));
      oldLaps.answer({ drivers: [], leader_crossings: { laps: [1], t: [1090] } });
    });
    await flush();
    expect(screen.getByText(/Jeddah · 0 cars/)).toBeDefined();
    expect(screen.queryByText(/Sakhir/)).toBeNull();
  });

  it("a late failure for the previous session is not shown on the one now open", async () => {
    const server = deferredFetch(answers([BAHRAIN, JEDDAH], (url) => url === "/api/sessions/2024_01_R"));
    render(<App />);
    await waitFor(() => expect(server.waitsFor("/api/sessions/2024_01_R")).toBe(true));
    const oldInfo = server.take("/api/sessions/2024_01_R");

    fireEvent.change(picker(), { target: { value: "2024_02_R" } });
    await waitFor(() => expect(screen.getByText(/Jeddah · 0 cars/)).toBeDefined());

    await act(async () => oldInfo.answer({ detail: "Bahrain could not be read" }, 500));
    await flush();
    expect(screen.queryByText("Bahrain could not be read")).toBeNull();
  });


  it("an earlier live answer arriving after a later one does not move the live edge back", async () => {
    vi.useFakeTimers();
    try {
      const live = summary("live", 17, "LIVE", "Live timing");
      const server = deferredFetch(answers([live], (url) => url === "/api/sessions/live"));
      render(<App />);
      await flush();
      const first = server.take("/api/sessions/live");     // the opening read, slow

      await act(async () => {
        vi.advanceTimersByTime(10_000);                  // the first live refresh
      });
      await flush();
      await act(async () => server.take("/api/sessions/live").answer(infoAt("Baku", 1300)));
      await flush();
      const slider = () => screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement;
      expect(Number(slider().value)).toBe(1300);

      await act(async () => first.answer(infoAt("Baku", 1200)));   // older, and late
      await flush();
      expect(Number(slider().value)).toBe(1300);
    } finally {
      vi.useRealTimers();
    }
  });
});