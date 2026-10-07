import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { FeatureWindow } from "./FeatureWindow";
import { featureById, type FeatureId } from "./features";
import { SILENCE_MS, type ClockState, type SyncMessage } from "./sync";
import { FakeChannel } from "./testing/fakeChannel";

const KEY = "2024_01_R";

const info = (location = "Sakhir", tEnd = 1600) => ({
  session: { event_name: `${location} GP`, session_name: "Race", location },
  t_start: 1000, t_end: tEnd, total_laps: 57,
  drivers: [{ driver_number: 1, abbreviation: "VER", full_name: "Max Verstappen", team_name: "Red Bull",
              team_color: "3671C6", grid_position: 1, position: 1, classified_position: "1", status: "Finished" }],
  outline: [], bounds: {}, has_position_data: false, track_status: [],
});

const driverRow = (n: number, code: string, position: number) => ({
  driver_number: n, abbreviation: code, team_name: "T", team_color: "3671C6", position, status: "racing",
  laps_completed: 12, gap_to_leader_s: position === 1 ? null : 6.2, gap_text: position === 1 ? "" : "+6.200",
  interval_s: null, interval_text: "", laps_down: 0, last_lap_s: 93.1, best_lap_s: 92.6,
  is_session_best: position === 1, is_personal_best: false, compound: "HARD", tyre_life: 9, laps_in_stint: 5,
  stops: 1, sectors: [], penalties: null,
});

const messages = [{ t: 1100, lap: 12, kind: "time_penalty", seconds: 5, reason: "TRACK LIMITS", cars: [11],
                    incident: null, stewards: true, topic: "stewards",
                    message: "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 11 (PER) - TRACK LIMITS" }];

/** The server: every request recorded, answered from small fixtures. */
function server() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    calls.push(url);
    const body = url.includes("/insight") ? { pit_loss: { circuit: "Sakhir", seconds: 22.4, spread_s: 1, stops: 9, seasons: 3 },
                                               safety_car: null, caveats: [], degradation_curve: [], plans: [],
                                               plans_with_risk: [], plans_unavailable: "none here", stints: [],
                                               fitted_on: [], held_out: true, is_race: true }
      : url.includes("/messages") ? messages
      : url.includes("/state") ? { t: 1200, leader_lap: 12, ideal_lap_s: 92.608,
                                   best_sectors: [{ sector: 1, seconds: 29.741, driver_number: 1, driver: "VER" },
                                                  { sector: 2, seconds: 39.916, driver_number: 11, driver: "PER" },
                                                  { sector: 3, seconds: 22.951, driver_number: 1, driver: "VER" }],
                                   drivers: [driverRow(1, "VER", 1), driverRow(11, "PER", 2)], cars: {},
                                   track_status: null, weather: null }
      : url.includes("/laps") ? { drivers: [], leader_crossings: { laps: [1, 2], t: [1090, 1182] } }
      : url.includes("2024_02_R") ? info("Jeddah")
      : info();
    return { ok: true, status: 200, json: async () => body } as Response;
  }));
  return calls;
}

/** A stand-in replay window: answers hello with its clock, and records what it is asked. */
function replay(start: ClockState) {
  const channel = new FakeChannel("racecraft");
  let clock = start;
  const asked: SyncMessage[] = [];
  channel.onmessage = (event) => {
    const message = event.data as SyncMessage;
    if (message.type === "hello") channel.postMessage({ type: "clock", state: clock });
    else asked.push(message);
  };
  return {
    asked,
    move(next: Partial<ClockState>) {
      clock = { ...clock, ...next };
      channel.postMessage({ type: "clock", state: clock });
    },
    close: () => channel.close(),
  };
}

const clock = (over: Partial<ClockState> = {}): ClockState => ({
  session: KEY, t: 1200, playing: false, speed: 1, following: false, selected: [], ...over,
});

/** A driver's row in the tower; their code also shows in the best-sectors strip. */
function towerRow(code: string): HTMLElement {
  const row = Array.from(document.querySelectorAll<HTMLElement>(".tower-rows .tower-row"))
    .find((each) => each.querySelector(".code")?.textContent === code);
  if (!row) throw new Error(`no tower row for ${code}`);
  return row;
}

function open(id: FeatureId) {
  return render(<FeatureWindow feature={featureById(id)!} initialSession={KEY} />);
}

const settle = () => act(async () => {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
});

beforeEach(() => {
  FakeChannel.reset();
  vi.stubGlobal("BroadcastChannel", FakeChannel);
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("a feature window", () => {
  it("shows its feature for the replay's session, at the replay's time", async () => {
    const calls = server();
    replay(clock({ t: 1234.5 }));
    open("tower");
    await waitFor(() => expect(screen.getByText("Timing tower")).toBeDefined());
    await waitFor(() => expect(towerRow("PER")).toBeDefined());
    expect(calls).toContain("/api/sessions/2024_01_R/state?t=1234.50");
    expect(screen.getByRole("status").textContent).toBe("following the replay");
  });

  it("the tower window shows who holds each sector and what an ideal lap would be", async () => {
    server();
    replay(clock());
    const { container } = open("tower");
    await waitFor(() => expect(container.querySelector(".best-sectors")).not.toBeNull());
    const strip = container.querySelector(".best-sectors") as HTMLElement;
    await waitFor(() => expect(strip.textContent).toContain("29.741"));   // fastest S1, held by VER
    expect(strip.textContent).toContain("IDEAL");
    expect(strip.textContent).toContain("1:32.608");                       // the three best sectors added up
  });

  it("moves to whatever session the replay window opens", async () => {
    const calls = server();
    const main = replay(clock());
    open("tower");
    await waitFor(() => expect(screen.getByText(/Sakhir GP/)).toBeDefined());
    act(() => main.move({ session: "2024_02_R" }));
    await waitFor(() => expect(screen.getByText(/Jeddah GP/)).toBeDefined());
    expect(calls.some((url) => url.startsWith("/api/sessions/2024_02_R"))).toBe(true);
  });

  it("asks the replay window to seek, play and pick drivers rather than doing it itself", async () => {
    server();
    const main = replay(clock());
    open("tower");
    await waitFor(() => expect(towerRow("PER")).toBeDefined());

    fireEvent.change(screen.getByRole("slider", { name: /session time/i }), { target: { value: "1500" } });
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    fireEvent.click(towerRow("PER"));
    await settle();
    expect(main.asked).toEqual([
      { type: "seek", t: 1500 },
      { type: "toggle" },
      { type: "select", driver: 11 },
    ]);
  });

  it("asks for the model fit only for the features that need it", async () => {
    const calls = server();
    replay(clock());
    const { unmount } = open("trace");
    await waitFor(() => expect(calls.some((url) => url.endsWith("/laps"))).toBe(true));
    await settle();
    expect(calls.some((url) => url.includes("/insight"))).toBe(false);
    unmount();

    open("strategy");
    await waitFor(() => expect(calls.some((url) => url.includes("/insight"))).toBe(true));
    await waitFor(() => expect(screen.getByText("22.4s")).toBeDefined());
  });

  it("reads race control only for the stewards and the track log", async () => {
    const calls = server();
    replay(clock());
    open("stewards");
    await waitFor(() => expect(screen.getByText(/TRACK LIMITS/i)).toBeDefined());
    expect(calls.some((url) => url.includes("/messages") && url.includes("topic=stewards"))).toBe(true);
    expect(calls.some((url) => url.includes("/state?"))).toBe(false);
  });

  it("says when the replay window has closed, and stops offering controls", async () => {
    vi.useFakeTimers();
    server();
    const main = replay(clock());
    open("tower");
    await settle();
    await settle();
    main.close();
    act(() => vi.advanceTimersByTime(SILENCE_MS + 1100));
    expect(screen.getByRole("status").textContent).toBe("replay window closed");
    expect((screen.getByRole("slider", { name: /session time/i }) as HTMLInputElement).disabled).toBe(true);
  });
});
