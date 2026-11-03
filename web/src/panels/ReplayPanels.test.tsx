import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DriverTiming } from "../api";
import { ClockBar, statusBands } from "./ClockBar";
import { assignSlots, DriverCards, drsLabel, MAX_FOLLOWED, overtakeLabel } from "./DriverCards";
import { channelPath, cursorIndex, TelemetryStrip } from "./TelemetryStrip";
import { Leaderboard } from "./Leaderboard";

function driver(n: number, code: string, position: number, over: Partial<DriverTiming> = {}): DriverTiming {
  return {
    driver_number: n, abbreviation: code, team_name: "Team", team_color: "3671C6", position, status: "racing",
    laps_completed: 30, gap_to_leader_s: position === 1 ? null : position * 2, gap_text: position === 1 ? "" : `+${position * 2}.000`,
    interval_s: position === 1 ? null : 2, interval_text: position === 1 ? "" : `+${position}.500`, laps_down: 0,
    last_lap_s: 92, best_lap_s: 91, is_session_best: false, is_personal_best: false, compound: "MEDIUM",
    tyre_life: 12, laps_in_stint: 10, stops: 1, sectors: [], penalties: null, ...over,
  };
}

const field = [driver(1, "VER", 1), driver(4, "NOR", 2), driver(16, "LEC", 3), driver(44, "HAM", 4)];

describe("Leaderboard", () => {
  it("shows the running order: position, driver, gap and tyre", () => {
    const { container } = render(<Leaderboard drivers={field} selected={[]} onSelect={vi.fn()} />);
    const rows = Array.from(container.querySelectorAll(".leaderboard-row")).map((row) => row.textContent);
    expect(rows[0]).toContain("VER");
    expect(rows[0]).toContain("LEADER");
    expect(rows[1]).toContain("+4.000");
    expect(within(container.querySelector(".leaderboard-rows") as HTMLElement).getAllByTitle(/MEDIUM, 12 laps old/))
      .toHaveLength(4);
  });

  it("picks a driver on click, and marks the picked ones", () => {
    const onSelect = vi.fn();
    render(<Leaderboard drivers={field} selected={[16]} onSelect={onSelect} />);
    fireEvent.click(screen.getByText("HAM").closest("button")!);
    expect(onSelect).toHaveBeenCalledWith(44);
    expect(screen.getByText("LEC").closest("button")!.getAttribute("aria-pressed")).toBe("true");
  });

  it("opens the full timing tower when asked", () => {
    const onOpenTower = vi.fn();
    render(<Leaderboard drivers={field} selected={[]} onSelect={vi.fn()} onOpenTower={onOpenTower} />);
    fireEvent.click(screen.getByRole("button", { name: /full timing tower/i }));
    expect(onOpenTower).toHaveBeenCalledTimes(1);
  });
});

describe("DriverCards", () => {
  const cars = { "16": { x: 0, y: 0, speed: 287.4, gear: 7, throttle: 64, brake: 0, drs: 12 } };

  it("asks for a pick when nobody is followed", () => {
    render(<DriverCards selected={[]} drivers={field} cars={{}} hasDrs onUnpick={vi.fn()} />);
    expect(screen.getByText(/click a driver in the timing tower/i)).toBeDefined();
  });

  it("shows what the car is doing now and the gaps either side", () => {
    const { container } = render(<DriverCards selected={[16]} drivers={field} cars={cars} hasDrs onUnpick={vi.fn()} />);
    const card = within(screen.getByRole("article", { name: /LEC telemetry/ }));
    expect(card.getByText("P3")).toBeDefined();
    expect(container.querySelector(".card-speed")?.textContent).toBe("287 km/h");   // whole km/h
    expect(container.querySelector(".card-gear b")?.textContent).toBe("7");
    expect(card.getByText("Open")).toBeDefined();                                    // DRS 12, under a DRS label
    // Ahead is NOR, by LEC's own interval; behind is HAM, by HAM's interval.
    expect(card.getByText("NOR +3.500")).toBeDefined();
    expect(card.getByText("HAM +4.500")).toBeDefined();
  });

  it("shows speed in the chosen units", () => {
    const { container } = render(<DriverCards selected={[16]} drivers={field} cars={cars} hasDrs onUnpick={vi.fn()} units="imperial" />);
    expect(container.querySelector(".card-speed")?.textContent).toBe("179 mph");
  });

  it("shows a dashboard for up to four followed, and unfollows from the card", () => {
    const onUnpick = vi.fn();
    render(<DriverCards selected={[1, 4, 16, 44]} drivers={field} cars={{}} hasDrs onUnpick={onUnpick} />);
    expect(screen.getAllByRole("article").map((a) => a.getAttribute("aria-label")))
      .toEqual(["VER telemetry", "NOR telemetry", "LEC telemetry", "HAM telemetry"]);
    fireEvent.click(screen.getByRole("button", { name: "Stop following HAM" }));
    expect(onUnpick).toHaveBeenCalledWith(44);
  });

  it("says the pedals are unknown rather than guessing, while speed still reads (BUG-007)", () => {
    const blind = { "16": { x: 0, y: 0, speed: 296, gear: 8, throttle: null, brake: null, drs: 0 } };
    const { container } = render(<DriverCards selected={[16]} drivers={field} cars={blind as never} hasDrs onUnpick={vi.fn()} />);
    const values = Array.from(container.querySelectorAll(".meter-value")).map((v) => v.textContent);
    expect(values.slice(1)).toEqual(["—", "—"]);
    expect(container.querySelector(".meter-value.is-on")).toBeNull();
    expect(container.querySelector(".card-speed")?.textContent).toBe("296 km/h");
  });

  it("reads the DRS codes as the feed means them, and shows none for 2026", () => {
    expect(drsLabel(12, true).text).toBe("DRS open");
    expect(drsLabel(10, true).text).toBe("DRS open");
    expect(drsLabel(8, true).text).toBe("DRS eligible");
    expect(drsLabel(1, true).text).toBe("DRS off");
    expect(drsLabel(null, true).text).toBe("—");
    expect(drsLabel(12, false).text).toBe("—");             // no DRS this session
  });

  it("reads the car's telemetry at the clock's time", async () => {
    const trace = { driver_number: 16, seconds: 30, t: [-30, -20, -10, 0], speed: [300, 120, 200, 310],
                    throttle: [100, 0, 60, 100], brake: [false, true, false, false], gear: [8, 3, 5, 8] };
    const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => trace }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    try {
      const { container } = render(<DriverCards selected={[16]} drivers={field} cars={cars} hasDrs onUnpick={vi.fn()}
                                                sessionKey="2025_17_R" t={4000} />);
      // Fetched in one go: the half-minute behind the clock and fifteen seconds ahead of it.
      await waitFor(() => expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2025_17_R/recent?driver=16&t=4015.00&seconds=47"));
      // Read at the clock's own time: answered from 4015, so 4000 is halfway from 120 at 3995 to 200 at 4005.
      await waitFor(() => expect(container.querySelector(".card-speed")?.textContent).toBe("160 km/h"), { timeout: 2000 });
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("four dashboards", () => {
  it("keeps each driver in their slot: new picks fill gaps, and a fifth takes the oldest's place", () => {
    expect(MAX_FOLLOWED).toBe(4);
    const empty = [null, null, null, null];
    expect(assignSlots(empty, [1, 4])).toEqual([1, 4, null, null]);          // the first two go under the map
    const full = assignSlots(assignSlots(empty, [1, 4]), [1, 4, 16, 44]);
    expect(full).toEqual([1, 4, 16, 44]);
    expect(assignSlots(full, [4, 16, 44, 63])).toEqual([63, 4, 16, 44]);     // a fifth pick: 1 dropped, nobody else moves
    expect(assignSlots(full, [1, 16, 44])).toEqual([1, null, 16, 44]);       // unfollowing leaves the others where they are
    expect(assignSlots([1, null, 16, 44], [1, 16, 44, 63])).toEqual([1, 63, 16, 44]);
  });

  it("draws the dashboard for its slot, and asks for a driver in an empty one", () => {
    const { rerender } = render(<DriverCards slot={2} slots={[1, 4, 16, null]} selected={[1, 4, 16]} drivers={field} cars={{}} hasDrs onUnpick={vi.fn()} />);
    expect(screen.getByRole("article", { name: /LEC telemetry/ })).toBeDefined();
    rerender(<DriverCards slot={3} slots={[1, 4, 16, null]} selected={[1, 4, 16]} drivers={field} cars={{}} hasDrs onUnpick={vi.fn()} />);
    expect(screen.getByText("A fourth driver shows here.")).toBeDefined();
  });
});

describe("the telemetry strip's driver chips", () => {
  const lap = (n: number) => ({ driver_number: n, abbreviation: "X", lap: 29, lap_time_s: 90, compound: "SOFT", tyre_life: 3, start_t: 0, length_m: 1000, step_m: 500,
    distance: [0, 500, 1000], t: [0, 45, 90], speed: [100, 300, 200], throttle: [0, 100, 50], brake: [true, false, false], gear: [2, 8, 5],
    x: [0, 1, 2], y: [0, 1, 2], brake_zones: [], corners: [], summary: {} });

  it("offers every followed driver, draws the two under the map first, and turns any on or off", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const n = Number(/driver=(\d+)/.exec(url)?.[1] ?? /laps?\/(\d+)/.exec(url)?.[1]);
      return { ok: true, json: async () => lap(n) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
    try {
      // VER and NOR under the map, LEC and HAM beside it.
      const { container } = render(<TelemetryStrip sessionKey="2025_17_R" followed={[1, 4, 16, 44]} drivers={field} cars={{}} />);
      const chip = (code: string) => screen.getByRole("button", { name: new RegExp(`^${code}`) });
      await waitFor(() => expect(chip("VER").textContent).toContain("L29"));
      expect(["VER", "NOR", "LEC", "HAM"].map((c) => chip(c).getAttribute("aria-pressed"))).toEqual(["true", "true", "false", "false"]);
      const speedLines = () => container.querySelectorAll(".tel-speed path").length;
      await waitFor(() => expect(speedLines()).toBe(2));

      fireEvent.click(chip("HAM"));
      await waitFor(() => expect(speedLines()).toBe(3));
      fireEvent.click(chip("VER"));
      await waitFor(() => expect(speedLines()).toBe(2));
      expect(chip("VER").getAttribute("aria-pressed")).toBe("false");

      // All off is a choice the screen explains.
      fireEvent.click(chip("NOR"));
      fireEvent.click(chip("HAM"));
      expect(await screen.findByText(/pick a driver above/i)).toBeDefined();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("dashes the later team-mate, since they share a colour", async () => {
    const pair = [driver(63, "RUS", 1, { team_color: "00D7B6" }), driver(12, "ANT", 2, { team_color: "00D7B6" })];
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => lap(1) }) as Response));
    try {
      const { container } = render(<TelemetryStrip sessionKey="2025_17_R" followed={[63, 12, null, null]} drivers={pair} cars={{}} />);
      await waitFor(() => expect(container.querySelectorAll(".tel-speed path")).toHaveLength(2));
      const dashes = Array.from(container.querySelectorAll(".tel-speed path")).map((path) => path.getAttribute("stroke-dasharray"));
      expect(dashes).toEqual([null, "5 3"]);
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("the card's telemetry, as the clock runs", () => {
  it("moves the bars and states with every frame while the figures hold", async () => {
    // Samples at 3968, 3990, 3995, 4005 and 4015, as below.
    const trace = { driver_number: 16, seconds: 47, t: [-47, -25, -20, -10, 0], speed: [300, 250, 100, 200, 310],
                    throttle: [100, 100, 0, 60, 100], brake: [false, false, true, false, false], gear: [8, 7, 3, 5, 8],
                    rpm: [11000, 11000, 6000, 8000, 12000] };
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => trace }) as unknown as Response));
    try {
      const props = { selected: [16], drivers: field, cars: {}, hasDrs: true, onUnpick: vi.fn(), sessionKey: "2025_17_R" };
      const { container, rerender } = render(<DriverCards {...props} t={4000} />);
      const speedAt = () => container.querySelector(".card-speed")?.textContent;
      await waitFor(() => expect(speedAt()).toBe("150 km/h"));
      const bars = () => Array.from(container.querySelectorAll<HTMLElement>(".meter i")).map((b) => b.style.transform);
      const values = () => Array.from(container.querySelectorAll(".meter-value")).map((v) => v.textContent);
      // Halfway from 3995 to 4005: revs 7000 of 15000, throttle 30%, and on the brake.
      expect(bars()).toEqual([`scaleX(${7000 / 15000})`, "scaleX(0.3)", "scaleX(1)"]);
      expect(values()).toEqual(["7,000", "30%", "ON"]);

      rerender(<DriverCards {...props} t={4006} />);
      // Off the brake and up a gear at once, and the bars have moved...
      expect(container.querySelector(".card-gear b")?.textContent).toBe("5");
      expect(values()[2]).toBe("OFF");
      expect(bars()[2]).toBe("scaleX(0)");
      expect(bars()[1]).toBe("scaleX(0.64)");
      // ...while the figures wait for the second to turn.
      expect(speedAt()).toBe("150 km/h");
      expect(values().slice(0, 2)).toEqual(["7,000", "30%"]);
      await waitFor(() => expect(values().slice(0, 2)).toEqual(["8,400", "64%"]), { timeout: 2000 });
      expect(speedAt()).toBe("211 km/h");
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("slides with the clock without asking again, and reads speed between samples", async () => {
    // Samples at 3968, 3990, 3995, 4005 and 4015: the server answers relative to the end it was asked for.
    const trace = { driver_number: 16, seconds: 47, t: [-47, -25, -20, -10, 0], speed: [300, 250, 100, 200, 310],
                    throttle: [100, 100, 0, 60, 100], brake: [false, false, true, false, false], gear: [8, 7, 3, 5, 8] };
    const fetchMock = vi.fn(async (_url: string) => ({ ok: true, json: async () => trace }) as Response);
    vi.stubGlobal("fetch", fetchMock);
    try {
      const props = { selected: [16], drivers: field, cars: {}, hasDrs: true, onUnpick: vi.fn(), sessionKey: "2025_17_R" };
      const { container, rerender } = render(<DriverCards {...props} t={4000} />);
      const speedAt = () => container.querySelector(".card-speed")?.textContent;
      await waitFor(() => expect(speedAt()).toBe("150 km/h"));   // halfway from 100 at 3995 to 200 at 4005
      rerender(<DriverCards {...props} t={4002} />);
      expect(speedAt()).toBe("150 km/h");                     // the figure holds, so it can be read
      await waitFor(() => expect(speedAt()).toBe("170 km/h"), { timeout: 1000 });   // and ticks within half a second
      expect(fetchMock).toHaveBeenCalledTimes(1);             // still inside what was fetched
    } finally {
      vi.unstubAllGlobals();
    }
  });
});

describe("the timeline", () => {
  const statuses = [
    { t: 1000, status: "1" }, { t: 1100, status: "2" }, { t: 1150, status: "1" },
    { t: 1300, status: "4" }, { t: 1500, status: "1" }, { t: 1800, status: "5" },
  ];

  it("colours every span under yellow, safety car, VSC or red flag", () => {
    expect(statusBands(statuses, 1000, 2000)).toEqual([
      { from: 0.1, to: 0.15, status: "2" },
      { from: 0.3, to: 0.5, status: "4" },
      { from: 0.8, to: 1, status: "5" },                    // red to the end of the session
    ]);
  });

  it("keeps bands inside the timeline and survives an empty session", () => {
    expect(statusBands([{ t: 900, status: "4" }, { t: 1050, status: "1" }], 1000, 2000))
      .toEqual([{ from: 0, to: 0.05, status: "4" }]);
    expect(statusBands(statuses, 1000, 1000)).toEqual([]);
  });

  it("draws the bands and marks every tenth lap", () => {
    const clock = { t: 1200, playing: false, speed: 1, toggle: vi.fn(), play: vi.fn(), pause: vi.fn(),
                    seek: vi.fn(), nudge: vi.fn(), setSpeed: vi.fn() };
    const crossings = { laps: Array.from({ length: 20 }, (_, i) => i + 1), t: Array.from({ length: 20 }, (_, i) => 1000 + (i + 1) * 45) };
    const { container } = render(
      <ClockBar clock={clock} start={1000} end={2000}
                loading={false} statuses={statuses} crossings={crossings} />,
    );
    expect(Array.from(container.querySelectorAll(".band")).map((b) => b.className))
      .toEqual(["band is-yellow", "band is-sc", "band is-red"]);
    expect(container.querySelectorAll(".lap-mark")).toHaveLength(20);
    expect(Array.from(container.querySelectorAll(".lap-mark.is-major")).map((m) => m.textContent)).toEqual(["L10", "L20"]);
    expect((container.querySelector(".timeline-played") as HTMLElement).style.width).toBe("20%");
  });
});

describe("overtake mode (2026)", () => {
  const cars = { "16": { x: 0, y: 0, speed: 287.4, gear: 7, throttle: 64, brake: 0, drs: 0 } };

  it("shows overtake mode in place of DRS when the session has it", () => {
    const field2026 = [driver(1, "VER", 1, { overtake: "not_eligible" }), driver(16, "LEC", 2, { overtake: "eligible" })];
    render(<DriverCards selected={[16]} drivers={field2026} cars={cars} hasDrs={false} hasOvertake onUnpick={vi.fn()} />);
    const card = within(screen.getByRole("article", { name: /LEC telemetry/ }));
    expect(card.getByText("Yes").className).toContain("is-eligible");
    expect(card.queryByText(/DRS/)).toBeNull();
  });

  it("reads race control's switch and the one-second window", () => {
    expect(overtakeLabel("eligible").text).toBe("Overtake eligible");
    expect(overtakeLabel("disabled").text).toBe("Overtake off");
    expect(overtakeLabel("not_eligible").text).toBe("Not eligible");
    expect(overtakeLabel(null).text).toBe("—");
  });

  it("keeps DRS for a session that has it", () => {
    render(<DriverCards selected={[16]} drivers={field} cars={cars} hasDrs onUnpick={vi.fn()} />);
    expect(within(screen.getByRole("article", { name: /LEC telemetry/ })).getByText("Off")).toBeDefined();   // code 0
  });
});

describe("the telemetry strip", () => {
  const trace = {
    driver_number: 16, abbreviation: "LEC", lap: 12, lap_time_s: 90, compound: "MEDIUM", tyre_life: 5, start_t: 0, length_m: 1000, step_m: 500,
    distance: [0, 500, 1000], t: [0, 45, 90], speed: [100, 300, 200], throttle: [0, 100, 50], brake: [true, false, false],
    gear: [1, 8, 4], x: [0, 100, 200], y: [0, 0, 0], brake_zones: [], corners: [],
    summary: { top_speed: 300, min_speed: 100, full_throttle_share: 0.3, braking_share: 0.1, brake_zones: 1 },
  };

  it("puts each car's cursor at the nearest point of its lap", () => {
    expect(cursorIndex(trace, { x: 90, y: 5 })).toBe(1);
    expect(cursorIndex(trace, { x: 190, y: 0 })).toBe(2);
    expect(cursorIndex(trace, undefined)).toBeNull();
  });

  it("draws a channel across the full width, scaled to its range", () => {
    // Speed 300 of a 300 top reaches the top padding; the lap ends at x = 1000.
    expect(channelPath(trace, "speed", 100, 300)).toBe("M0.0 64.0L500.0 8.0L1000.0 36.0");
    expect(channelPath(trace, "brake", 30, 300).startsWith("M0.0 2.4")).toBe(true);    // on: at the top
  });
});
