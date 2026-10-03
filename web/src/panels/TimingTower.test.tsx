import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TimingTower } from "./TimingTower";
import type { DriverTiming } from "../api";

function driver(overrides: Partial<DriverTiming>): DriverTiming {
  return {
    driver_number: 1, abbreviation: "VER", team_name: "Red Bull", team_color: "3671C6",
    position: 1, status: "racing", laps_completed: 10, gap_to_leader_s: null, gap_text: "",
    interval_s: null, interval_text: "", laps_down: 0, last_lap_s: 92.608, best_lap_s: 92.608,
    is_session_best: true, is_personal_best: true, compound: "HARD", tyre_life: 12,
    laps_in_stint: 8, stops: 1, penalties: null,
    sectors: [
      { sector: 1, seconds: 29.741, state: "session_best" },
      { sector: 2, seconds: 39.916, state: "personal_best" },
      { sector: 3, seconds: 22.951, state: "normal" },
    ],
    ...overrides,
  };
}

describe("TimingTower", () => {
  it("shows the leader with a LEADER label and rivals with their gap", () => {
    render(
      <TimingTower
        drivers={[driver({}), driver({ driver_number: 11, abbreviation: "PER", position: 2, gap_text: "+6.213", last_lap_s: 93.104, is_session_best: false })]}
        selected={[]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByText("LEADER")).toBeDefined();
    expect(screen.getByText("+6.213")).toBeDefined();
    const last = Array.from(document.querySelectorAll(".tower-row .last")).map((cell) => cell.textContent);
    expect(last).toEqual(["1:32.608", "1:33.104"]);
  });

  it("calls only P1 the leader when no gaps exist yet, as on the grid before the start", () => {
    const grid = [1, 2, 3].map((position) =>
      driver({ driver_number: position, abbreviation: `D${position}`, position, status: "not_started",
               gap_text: "", last_lap_s: null }));
    const { container } = render(
      <TimingTower drivers={grid} selected={[]} onSelect={vi.fn()} />,
    );
    const gaps = Array.from(container.querySelectorAll(".tower-row .gap")).map((cell) => cell.textContent);
    expect(gaps).toEqual(["LEADER", "—", "—"]);
  });

  it("shows the fastest lap in purple in BEST, never in LAST, and a personal best in green in LAST", () => {
    const { container } = render(
      <TimingTower
        drivers={[
          // Holds the session's fastest lap, and set it on the lap just completed.
          driver({ last_lap_s: 92.608, best_lap_s: 92.608, is_session_best: true, is_personal_best: true }),
          driver({ driver_number: 11, position: 2, last_lap_s: 93.1, best_lap_s: 93.0,
                   is_session_best: false, is_personal_best: false }),
        ]}
        selected={[]}
        onSelect={vi.fn()}
      />,
    );
    const best = container.querySelectorAll(".tower-row .best");
    expect(Array.from(best).map((cell) => cell.textContent)).toEqual(["1:32.608", "1:33.000"]);
    expect(container.querySelectorAll(".best.is-session-best")).toHaveLength(1);
    expect(best[0]!.classList.contains("is-session-best")).toBe(true);
    // LAST is never purple, even on the lap that set the session's fastest.
    expect(container.querySelectorAll(".last.is-session-best")).toHaveLength(0);
    expect(container.querySelectorAll(".last.is-personal-best")).toHaveLength(1);
  });

  it("puts BEST immediately before LAST", () => {
    const { container } = render(<TimingTower drivers={[driver({})]} selected={[]} onSelect={vi.fn()} />);
    const heads = Array.from(container.querySelectorAll(".tower-head span")).map((s) => s.textContent);
    expect(heads.indexOf("LAST") - heads.indexOf("BEST")).toBe(1);
    const cells = Array.from(container.querySelector(".tower-row")!.children).map((c) => c.className);
    expect(cells.findIndex((c) => c.includes("last")) - cells.findIndex((c) => c.includes("best"))).toBe(1);
    // A heading for every cell, so nothing slides under the wrong title.
    expect(heads).toHaveLength(cells.length);
  });

  it("dims a retired car and shows OUT instead of a gap", () => {
    const { container } = render(
      <TimingTower drivers={[driver({ status: "out", gap_text: "+1 LAP" })]} selected={[]} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("OUT")).toBeDefined();
    expect(container.querySelectorAll(".tower-row.is-out")).toHaveLength(1);
  });

  it("reports which driver was clicked", () => {
    const onSelect = vi.fn();
    render(<TimingTower drivers={[driver({ driver_number: 44 })]} selected={[44]} onSelect={onSelect} />);
    screen.getByRole("button", { pressed: true }).click();
    expect(onSelect).toHaveBeenCalledWith(44);
  });

  it("shows each sector separately, coloured by how it stands", () => {
    const { container } = render(
      <TimingTower drivers={[driver({})]} selected={[]} onSelect={vi.fn()} />,
    );
    expect(screen.getByText("29.741")).toBeDefined();
    expect(screen.getByText("39.916")).toBeDefined();
    expect(screen.getByText("22.951")).toBeDefined();
    expect(container.querySelectorAll(".sector.is-session_best")).toHaveLength(1);
    expect(container.querySelectorAll(".sector.is-personal_best")).toHaveLength(1);
  });

  it("shows a dash for a sector the feed never delivered", () => {
    render(
      <TimingTower
        drivers={[driver({ sectors: [{ sector: 1, seconds: null, state: "none" }] })]}
        selected={[]} onSelect={vi.fn()}
      />,
    );
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(3);
  });
});