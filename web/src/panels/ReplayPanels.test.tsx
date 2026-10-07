import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DriverTiming } from "../api";
import { ClockBar, statusBands } from "./ClockBar";
import { DriverCards, drsLabel } from "./DriverCards";
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

  it("asks for a pick when nobody is picked", () => {
    render(<DriverCards selected={[]} drivers={field} cars={{}} hasDrs onUnpick={vi.fn()} />);
    expect(screen.getByText(/click a driver on the leaderboard/i)).toBeDefined();
  });

  it("shows what the car is doing now and the gaps either side", () => {
    render(<DriverCards selected={[16]} drivers={field} cars={cars} hasDrs onUnpick={vi.fn()} />);
    const card = within(screen.getByRole("article", { name: /LEC telemetry/ }));
    expect(card.getByText("P3")).toBeDefined();
    expect(card.getByText("287")).toBeDefined();            // speed, whole km/h
    expect(card.getByText("7")).toBeDefined();               // gear
    expect(card.getByText("OPEN")).toBeDefined();            // DRS 12
    expect(card.getByRole("meter", { name: "THR" }).getAttribute("aria-valuenow")).toBe("64");
    expect(card.getByRole("meter", { name: "BRK" }).getAttribute("aria-valuenow")).toBe("0");
    // Vertical bars, filling upward from the bottom, as broadcast telemetry draws them.
    const throttle = card.getByRole("meter", { name: "THR" }).querySelector(".pedal-fill") as HTMLElement;
    expect(throttle.style.height).toBe("64%");
    expect(throttle.style.width).toBe("");
    // Ahead is NOR, by LEC's own interval; behind is HAM, by HAM's interval.
    expect(card.getByText("AHEAD NOR")).toBeDefined();
    expect(card.getByText("+3.500")).toBeDefined();
    expect(card.getByText("BEHIND HAM")).toBeDefined();
    expect(card.getByText("+4.500")).toBeDefined();
  });

  it("keeps the newest three picks, and unpicks from the card", () => {
    const onUnpick = vi.fn();
    render(<DriverCards selected={[1, 4, 16, 44]} drivers={field} cars={{}} hasDrs onUnpick={onUnpick} />);
    expect(screen.getAllByRole("article").map((a) => a.getAttribute("aria-label")))
      .toEqual(["NOR telemetry", "LEC telemetry", "HAM telemetry"]);
    fireEvent.click(screen.getByRole("button", { name: "Stop following HAM" }));
    expect(onUnpick).toHaveBeenCalledWith(44);
  });

  it("reads the DRS codes as the feed means them, and shows none for 2026", () => {
    expect(drsLabel(12, true).text).toBe("OPEN");
    expect(drsLabel(10, true).text).toBe("OPEN");
    expect(drsLabel(8, true).text).toBe("ELIGIBLE");
    expect(drsLabel(1, true).text).toBe("OFF");
    expect(drsLabel(null, true).text).toBe("—");
    expect(drsLabel(12, false).text).toBe("—");             // no DRS this session
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
      <ClockBar clock={clock} start={1000} end={2000} leaderLap={5} totalLaps={20} trackStatus={null}
                weather={null} loading={false} statuses={statuses} crossings={crossings} />,
    );
    expect(Array.from(container.querySelectorAll(".band")).map((b) => b.className))
      .toEqual(["band is-yellow", "band is-sc", "band is-red"]);
    expect(container.querySelectorAll(".lap-mark")).toHaveLength(20);
    expect(Array.from(container.querySelectorAll(".lap-mark.is-major")).map((m) => m.textContent)).toEqual(["10", "20"]);
    expect((container.querySelector(".timeline-played") as HTMLElement).style.width).toBe("20%");
  });
});
