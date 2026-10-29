import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Driver, SessionSummary } from "../api";
import { CommandPalette, matches } from "./CommandPalette";

const sessions = [
  { session_key: "2026_15_R", year: 2026, round: 15, event_name: "Azerbaijan Grand Prix", session_name: "Race" },
  { session_key: "2026_15_Q", year: 2026, round: 15, event_name: "Azerbaijan Grand Prix", session_name: "Qualifying" },
] as SessionSummary[];
const drivers = [{ driver_number: 1, abbreviation: "VER", full_name: "Max Verstappen", team_name: "Red Bull Racing" }] as Driver[];

function open() {
  const props = { onScreen: vi.fn(), onSession: vi.fn(), onFollow: vi.fn(), onClose: vi.fn() };
  render(<CommandPalette sessions={sessions} drivers={drivers} {...props} />);
  return { ...props, input: screen.getByRole("combobox") };
}

describe("the Ctrl K search", () => {
  it("matches every word typed, in any order", () => {
    expect(matches("2026 · R15 Azerbaijan Grand Prix · Race", "race azer")).toBe(true);
    expect(matches("2026 · R15 Azerbaijan Grand Prix · Race", "race monaco")).toBe(false);
  });

  it("opens a session, follows a driver or goes to a screen, then closes", () => {
    const p = open();
    expect(document.activeElement).toBe(p.input);
    fireEvent.change(p.input, { target: { value: "azerbaijan qualifying" } });
    fireEvent.keyDown(p.input, { key: "Enter" });
    expect(p.onSession).toHaveBeenCalledWith("2026_15_Q");
    expect(p.onClose).toHaveBeenCalled();
  });

  it("moves with the arrows and closes on Escape", () => {
    const p = open();
    fireEvent.change(p.input, { target: { value: "verstappen" } });
    expect(screen.getAllByRole("option").map((o) => o.textContent)).toEqual(["VER · Max VerstappenRed Bull Racing · follow on the map"]);
    fireEvent.keyDown(p.input, { key: "Enter" });
    expect(p.onFollow).toHaveBeenCalledWith(1);

    fireEvent.change(p.input, { target: { value: "standings" } });
    fireEvent.keyDown(p.input, { key: "ArrowDown" });
    fireEvent.keyDown(p.input, { key: "ArrowUp" });
    fireEvent.click(screen.getByRole("option", { name: /^Standings/ }));
    expect(p.onScreen).toHaveBeenCalledWith("standings");

    fireEvent.keyDown(p.input, { key: "Escape" });
    expect(p.onClose).toHaveBeenCalled();
  });

  it("says so when nothing matches", () => {
    const p = open();
    fireEvent.change(p.input, { target: { value: "monaco 1999" } });
    expect(screen.getByText(/nothing matches/i)).toBeDefined();
  });
});
