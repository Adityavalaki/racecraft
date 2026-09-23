import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Stewards, filterLabel, verdictLabel } from "./Stewards";
import type { RaceControlEvent } from "../api";

const CODES = { 44: "HAM", 16: "LEC", 27: "HUL", 55: "SAI" };

function verdict(overrides: Partial<RaceControlEvent> = {}): RaceControlEvent {
  return {
    t: 100, lap: 10, kind: "noted", seconds: null, reason: "TRACK LIMITS",
    cars: [44], incident: null, stewards: true, topic: "stewards",
    message: "INCIDENT INVOLVING CAR 44 (HAM) NOTED - TRACK LIMITS",
    ...overrides,
  };
}

function show(props: Partial<Parameters<typeof Stewards>[0]> = {}) {
  return render(
    <Stewards
      events={[]}
      track={[]}
      start={0}
      codes={CODES}
      selected={[]}
      onSelect={vi.fn()}
      {...props}
    />,
  );
}

function trackEvent(overrides: Partial<RaceControlEvent> = {}): RaceControlEvent {
  return {
    t: 100, lap: 10, kind: "other", seconds: null, reason: null, cars: [],
    incident: null, stewards: false, topic: "track", message: "SAFETY CAR DEPLOYED",
    ...overrides,
  };
}

describe("Stewards", () => {
  it("says so when the stewards have said nothing", () => {
    show();
    expect(screen.getByText("The stewards have said nothing yet.")).toBeTruthy();
  });

  it("shows both lists at once, with nothing to click between them", () => {
    show({
      events: [verdict({ kind: "time_penalty", seconds: 5, reason: "UNSAFE RELEASE" })],
      track: [trackEvent({ message: "SAFETY CAR DEPLOYED" })],
    });
    expect(screen.getByText("+5s PENALTY")).toBeTruthy();
    expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Track" })).toBeTruthy();
  });

  it("shows the track list in the feed's own words", () => {
    show({ track: [trackEvent({ message: "GREEN LIGHT - PIT EXIT OPEN" })] });
    expect(screen.getByText("GREEN LIGHT - PIT EXIT OPEN")).toBeTruthy();
  });

  it("never narrows the track list, which is not about cars", () => {
    show({ track: [trackEvent()], selected: [44] });
    expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeTruthy();
  });

  it("survives a track list that is not the shape it expects", () => {
    show({ track: [null, { t: 1 }] as unknown as RaceControlEvent[] });
    expect(screen.getByText("Nothing yet.")).toBeTruthy();
  });

  it("shows the verdict and the offence", () => {
    show({ events: [verdict({ kind: "time_penalty", seconds: 5, reason: "TRACK LIMITS" })] });
    expect(screen.getByText("+5s PENALTY")).toBeTruthy();
    expect(screen.getByText("TRACK LIMITS")).toBeTruthy();
  });

  it("keeps the feed's own wording available without printing it", () => {
    // The panel is narrow, so the full message is the tooltip rather than a column.
    const message = "FIA STEWARDS: 5 SECOND TIME PENALTY FOR CAR 44 (HAM) - TRACK LIMITS";
    show({ events: [verdict({ kind: "time_penalty", seconds: 5, message })] });
    expect(screen.getByTitle(message)).toBeTruthy();
  });

  it("names every car of a multi-car incident as its own chip", () => {
    show({
      events: [verdict({
        cars: [27, 55],
        message: "TURN 8 INCIDENT INVOLVING CARS 27 (HUL) AND 55 (SAI) NOTED - CAUSING A COLLISION",
      })],
    });
    expect(screen.getByRole("button", { name: "Select HUL" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Select SAI" })).toBeTruthy();
  });

  it("narrows to the selected cars", () => {
    show({
      events: [
        verdict({ cars: [44], reason: "TRACK LIMITS" }),
        verdict({ cars: [16], reason: "UNSAFE RELEASE" }),
      ],
      selected: [44],
    });
    expect(screen.getByText("TRACK LIMITS")).toBeTruthy();
    expect(screen.queryByText("UNSAFE RELEASE")).toBeNull();
  });

  it("keeps a multi-car incident when either of its cars is selected", () => {
    show({
      events: [verdict({ cars: [27, 55], reason: "CAUSING A COLLISION" })],
      selected: [55],
    });
    expect(screen.getByText("CAUSING A COLLISION")).toBeTruthy();
  });

  it("says when a selection has nothing against it", () => {
    show({ events: [verdict({ cars: [16] })], selected: [44] });
    expect(screen.getByText("Nothing about these cars yet.")).toBeTruthy();
  });

  it("selects a driver when their chip is clicked", () => {
    const onSelect = vi.fn();
    show({ events: [verdict({ cars: [44] })], onSelect });
    screen.getByRole("button", { name: "Select HAM" }).click();
    expect(onSelect).toHaveBeenCalledWith(44);
  });

  it("marks a verdict that names no car rather than leaving a blank", () => {
    show({ events: [verdict({ cars: [], message: "LAP 1 TURN 1 INCIDENT NOTED" })] });
    expect(screen.getByTitle("no car named")).toBeTruthy();
  });

  it("shows the lap when the feed gave one and the clock when it did not", () => {
    show({ events: [verdict({ lap: 23 }), verdict({ t: 90, lap: null, reason: "IMPEDING" })] });
    expect(screen.getByText("L23")).toBeTruthy();
    expect(screen.getByText("0:01:30")).toBeTruthy();
  });

  it("leaves the second line out when there is no offence to put on it", () => {
    const { container } = show({ events: [verdict({ reason: null })] });
    expect(container.querySelectorAll(".stw-reason").length).toBe(0);
  });

  it("draws a penalty louder than a noted incident", () => {
    const { container } = show({
      events: [
        verdict({ kind: "time_penalty", seconds: 5 }),
        verdict({ kind: "noted" }),
      ],
    });
    expect(container.querySelectorAll(".stw-row.is-loud").length).toBe(1);
    expect(container.querySelectorAll(".stw-row.is-quiet").length).toBe(1);
  });

  it("leaves deleted laps to the tower, which already counts them", () => {
    // 47% of steward messages are deletions; repeating each one here would fill
    // half the panel with the one thing the PEN column already shows.
    show({ events: [verdict({ kind: "lap_deleted", reason: "TRACK LIMITS AT TURN 10" })] });
    expect(screen.getByText("The stewards have said nothing yet.")).toBeTruthy();
  });

  it("still shows a penalty when deletions are mixed in with it", () => {
    show({
      events: [
        verdict({ kind: "lap_deleted", reason: "TRACK LIMITS AT TURN 10" }),
        verdict({ kind: "time_penalty", seconds: 5, reason: "UNSAFE RELEASE" }),
      ],
    });
    expect(screen.getByText("+5s PENALTY")).toBeTruthy();
    expect(screen.queryByText("TRACK LIMITS AT TURN 10")).toBeNull();
  });

  it("survives a response that is not the shape it expects", () => {
    // The panel is on screen all session. A truncated body or an error object
    // must not take the whole app down with it.
    const junk = [{ t: 1, lap: null }, null, { cars: "not an array" }] as unknown as RaceControlEvent[];
    show({ events: junk });
    expect(screen.getByText("The stewards have said nothing yet.")).toBeTruthy();

    show({ events: undefined as unknown as RaceControlEvent[] });
    expect(screen.getAllByText("The stewards have said nothing yet.").length).toBeGreaterThan(0);
  });

  it("shows the readable rows and drops only the unreadable ones", () => {
    const mixed = [verdict({ reason: "TRACK LIMITS" }), null] as unknown as RaceControlEvent[];
    show({ events: mixed });
    expect(screen.getByText("TRACK LIMITS")).toBeTruthy();
  });

  it("offers no controls of its own", () => {
    // The tower's selection is the only filter; anything else is another thing
    // to learn in a panel that is meant to be glanced at.
    const { container } = show({ events: [verdict()], track: [trackEvent()] });
    const buttons = [...container.querySelectorAll("button")];
    expect(buttons.every((b) => b.className.includes("rc-car"))).toBe(true);
  });
});

describe("filterLabel", () => {
  it("is absent when nothing is selected", () => {
    expect(filterLabel([], CODES)).toBeNull();
  });

  it("names the selected cars", () => {
    expect(filterLabel([44], CODES)).toBe("HAM only");
    expect(filterLabel([44, 16], CODES)).toBe("HAM · LEC only");
  });

  it("falls back to the number for a car with no code", () => {
    expect(filterLabel([99], CODES)).toBe("99 only");
  });
});

describe("verdictLabel", () => {
  it("spells a served penalty out rather than showing its amount", () => {
    // A served 5s and an awarded 5s are opposite news; the number alone loses that.
    expect(verdictLabel(verdict({ kind: "served", seconds: 5 }))).toBe("SERVED");
    expect(verdictLabel(verdict({ kind: "time_penalty", seconds: 5 }))).toBe("+5s PENALTY");
  });

  it("covers every kind the reader emits", () => {
    const kinds = [
      "time_penalty", "stop_go", "drive_through", "served", "disqualified",
      "under_investigation", "investigate_after_race", "no_further_action", "noted",
      "lap_deleted", "black_and_white", "reprimand", "warning",
    ];
    for (const kind of kinds) {
      const label = verdictLabel(verdict({ kind, seconds: 10 }));
      // Readable rather than shouty: the seconds suffix in "+10s PENALTY" is
      // deliberately lowercase, so the test is that nothing leaks the raw key.
      expect(label).toBeTruthy();
      expect(label).not.toContain("_");
    }
  });

  it("falls back readably on a kind it has never seen", () => {
    expect(verdictLabel(verdict({ kind: "some_new_verdict" }))).toBe("SOME NEW VERDICT");
  });
});
