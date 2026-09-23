import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { PenaltyChip, describe as describePenalties } from "./PenaltyChip";
import type { DriverPenalties } from "../api";

function against(overrides: Partial<DriverPenalties>): DriverPenalties {
  return {
    driver_number: 44, pending_s: 0, served_s: 0, awarded_s: 0, stop_go: 0, drive_through: 0,
    penalties: 0, laps_deleted: 0, black_and_white: 0, reprimands: 0, warnings: 0,
    disqualified: false, under_investigation: 0, noted: 0, cleared: 0, outstanding: false,
    incidents: [], events: [],
    ...overrides,
  };
}

/**
 * The column answers one question — does this car still owe something? — so
 * there are four marks and no vocabulary to learn. Everything settled belongs
 * in the tooltip, and these tests hold that line.
 */
describe("PenaltyChip", () => {
  it("shows a dash when race control has said nothing", () => {
    render(<PenaltyChip against={null} />);
    expect(screen.getByText("–")).toBeTruthy();
  });

  it("shows seconds still to serve", () => {
    render(<PenaltyChip against={against({ pending_s: 5, awarded_s: 5, penalties: 1 })} />);
    expect(screen.getByText("+5s")).toBeTruthy();
  });

  it("adds two penalties into one figure", () => {
    render(<PenaltyChip against={against({ pending_s: 15, awarded_s: 15, penalties: 2 })} />);
    expect(screen.getByText("+15s")).toBeTruthy();
  });

  it("says STOP for a penalty served in the pit lane", () => {
    render(<PenaltyChip against={against({ stop_go: 1 })} />);
    expect(screen.getByText("STOP")).toBeTruthy();
  });

  it("says STOP for a drive-through too, since both cost a trip down the lane", () => {
    render(<PenaltyChip against={against({ drive_through: 1 })} />);
    expect(screen.getByText("STOP")).toBeTruthy();
  });

  it("puts a disqualification above everything else", () => {
    render(<PenaltyChip against={against({ disqualified: true, pending_s: 5, stop_go: 1 })} />);
    expect(screen.getByText("DSQ")).toBeTruthy();
  });

  it("marks a car the stewards are looking at", () => {
    render(<PenaltyChip against={against({ under_investigation: 1 })} />);
    expect(screen.getByText("•")).toBeTruthy();
  });

  it("shows nothing for a penalty already served — it changes no decision", () => {
    render(<PenaltyChip against={against({ served_s: 5, awarded_s: 5, penalties: 1 })} />);
    expect(screen.getByText("–")).toBeTruthy();
  });

  it("shows nothing for deleted laps, a noted incident or a warning flag", () => {
    for (const settled of [
      { laps_deleted: 3 },
      { noted: 2 },
      { black_and_white: 1 },
      { cleared: 1 },
      { reprimands: 1 },
    ]) {
      const { unmount } = render(<PenaltyChip against={against(settled)} />);
      expect(screen.getByText("–")).toBeTruthy();
      unmount();
    }
  });

  it("prefers the live thing when a car has both", () => {
    render(<PenaltyChip against={against({ pending_s: 5, laps_deleted: 4, served_s: 10 })} />);
    expect(screen.getByText("+5s")).toBeTruthy();
  });
});

describe("the tooltip", () => {
  it("carries everything the column leaves out", () => {
    const text = describePenalties(against({
      pending_s: 10, penalties: 1, under_investigation: 1, served_s: 5, laps_deleted: 3,
      black_and_white: 1,
      incidents: [{ stage: "investigating", reason: "CAUSING A COLLISION", cars: [44, 16], opened_t: 1, updated_t: 2 }],
    }));
    expect(text).toContain("10s still to serve");
    expect(text).toContain("5s already served");
    expect(text).toContain("3 lap times deleted");
    expect(text).toContain("black-and-white flag");
    expect(text).toContain("CAUSING A COLLISION");
  });

  it("names the offence, not only the count", () => {
    const text = describePenalties(against({
      noted: 1,
      incidents: [{ stage: "noted", reason: "IMPEDING", cars: [44], opened_t: 1, updated_t: 1 }],
    }));
    expect(text).toContain("IMPEDING");
  });

  it("leaves a closed incident out of the offence list", () => {
    const text = describePenalties(against({
      cleared: 1,
      incidents: [{ stage: "cleared", reason: "TRACK LIMITS", cars: [44], opened_t: 1, updated_t: 2 }],
    }));
    expect(text).toContain("cleared, no further action");
    expect(text).not.toContain("  cleared: TRACK LIMITS");
  });

  it("says so plainly when there is nothing to report", () => {
    expect(describePenalties(against({}))).toBe("Nothing from race control");
  });
});
