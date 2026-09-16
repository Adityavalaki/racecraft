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
    laps_in_stint: 8, stops: 1, ...overrides,
  };
}

describe("TimingTower", () => {
  it("shows the leader with a LEADER label and rivals with their gap", () => {
    render(
      <TimingTower
        drivers={[driver({}), driver({ driver_number: 11, abbreviation: "PER", position: 2, gap_text: "+6.213", last_lap_s: 93.104, is_session_best: false })]}
        selected={[]}
        onSelect={vi.fn()}
        sessionBest={92.608}
      />,
    );
    expect(screen.getByText("LEADER")).toBeDefined();
    expect(screen.getByText("+6.213")).toBeDefined();
    expect(screen.getByText("1:32.608")).toBeDefined();
  });

  it("marks the session's fastest lap in purple and a personal best in green", () => {
    const { container } = render(
      <TimingTower
        drivers={[driver({}), driver({ driver_number: 11, position: 2, last_lap_s: 93.1, is_personal_best: true })]}
        selected={[]}
        onSelect={vi.fn()}
        sessionBest={92.608}
      />,
    );
    expect(container.querySelectorAll(".last.is-session-best")).toHaveLength(1);
    expect(container.querySelectorAll(".last.is-personal-best")).toHaveLength(1);
  });

  it("dims a retired car and shows OUT instead of a gap", () => {
    const { container } = render(
      <TimingTower drivers={[driver({ status: "out", gap_text: "+1 LAP" })]} selected={[]} onSelect={vi.fn()} sessionBest={null} />,
    );
    expect(screen.getByText("OUT")).toBeDefined();
    expect(container.querySelectorAll(".tower-row.is-out")).toHaveLength(1);
  });

  it("reports which driver was clicked", () => {
    const onSelect = vi.fn();
    render(<TimingTower drivers={[driver({ driver_number: 44 })]} selected={[44]} onSelect={onSelect} sessionBest={null} />);
    screen.getByRole("button", { pressed: true }).click();
    expect(onSelect).toHaveBeenCalledWith(44);
  });
});
