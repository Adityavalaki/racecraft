import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TrackLog } from "./TrackLog";
import type { RaceControlEvent } from "../api";

function event(overrides: Partial<RaceControlEvent> = {}): RaceControlEvent {
  return {
    t: 100, lap: 10, kind: "other", seconds: null, reason: null, cars: [],
    incident: null, stewards: false, topic: "track", message: "SAFETY CAR DEPLOYED",
    ...overrides,
  };
}

describe("TrackLog", () => {
  it("says so when race control has said nothing", () => {
    render(<TrackLog events={[]} start={0} />);
    expect(screen.getByText("Nothing from race control yet.")).toBeTruthy();
  });

  it("shows each event in the feed's own words", () => {
    render(<TrackLog events={[event(), event({ message: "GREEN LIGHT - PIT EXIT OPEN" })]} start={0} />);
    expect(screen.getByText("SAFETY CAR DEPLOYED")).toBeTruthy();
    expect(screen.getByText("GREEN LIGHT - PIT EXIT OPEN")).toBeTruthy();
  });

  it("shows the lap when the feed gave one and the clock when it did not", () => {
    render(<TrackLog events={[event({ lap: 23 }), event({ t: 90, lap: null, message: "RACE START" })]} start={0} />);
    expect(screen.getByText("L23")).toBeTruthy();
    expect(screen.getByText("0:01:30")).toBeTruthy();
  });

  it("survives a response that is not the shape it expects", () => {
    render(<TrackLog events={[null, { t: 1 }] as unknown as RaceControlEvent[]} start={0} />);
    expect(screen.getByText("Nothing from race control yet.")).toBeTruthy();
    render(<TrackLog events={undefined as unknown as RaceControlEvent[]} start={0} />);
  });

  it("has no controls of its own", () => {
    const { container } = render(<TrackLog events={[event()]} start={0} />);
    expect(container.querySelectorAll("button").length).toBe(0);
  });
});
