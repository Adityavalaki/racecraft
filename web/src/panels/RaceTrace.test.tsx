import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { RaceTrace } from "./RaceTrace";
import type { LapSeries } from "../api";

/**
 * A canvas cannot be asserted on directly, so these record the draw calls and
 * check what the chart asked the context to do. What matters is that it never
 * draws a lap the clock has not reached — the panel is meant to grow with the
 * race, and a chart that quietly shows the whole result while the clock sits on
 * lap 3 gives the ending away.
 */
function driver(code: string, positions: number[]): LapSeries {
  return {
    driver_number: code.charCodeAt(0),
    abbreviation: code,
    team_color: "3671C6",
    laps: positions.map((_, index) => index + 1),
    gap_to_leader_s: positions.map(() => 0),
    position: positions,
    lap_time_s: positions.map(() => 90),
    compound: positions.map(() => "SOFT"),
    pit_in: positions.map(() => false),
  };
}

function record() {
  const calls: { text: string[]; lineTo: number[]; labels: Record<string, number> } =
    { text: [], lineTo: [], labels: {} };
  const context = {
    setTransform: vi.fn(), clearRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(),
    stroke: vi.fn(), fill: vi.fn(), arc: vi.fn(), setLineDash: vi.fn(),
    lineTo: vi.fn((x: number) => calls.lineTo.push(x)),
    fillText: vi.fn((t: string, _x: number, y: number) => {
      calls.text.push(t);
      calls.labels[t] = y;          // last write wins: the right-hand gutter
    }),
    font: "", textAlign: "", textBaseline: "", fillStyle: "", strokeStyle: "",
    lineWidth: 1, globalAlpha: 1,
  };
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(context as never);
  Object.defineProperty(HTMLCanvasElement.prototype, "clientWidth", { value: 600, configurable: true });
  Object.defineProperty(HTMLCanvasElement.prototype, "clientHeight", { value: 300, configurable: true });
  return calls;
}

const FIELD = [driver("VER", [1, 1, 2, 2, 3, 3, 1, 1, 1, 1]), driver("NOR", [2, 2, 1, 1, 1, 1, 2, 2, 2, 2])];

describe("RaceTrace", () => {
  it("draws only as far as the clock has reached", () => {
    const calls = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={4} onSelectLap={vi.fn()} />);
    expect(calls.text).toContain("LAP 4");
    expect(calls.text).not.toContain("LAP 10");
  });

  it("stops the lines at the current lap rather than running them to the flag", () => {
    // Counted, not measured: the gridlines end at the same x as a line that has
    // run the full distance, so the furthest point drawn cannot tell the two
    // apart. The number of segments can — each lap drawn is two more of them.
    const early = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={3} onSelectLap={vi.fn()} />);
    const earlySegments = early.lineTo.length;
    vi.restoreAllMocks();

    const late = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={10} onSelectLap={vi.fn()} />);

    expect(earlySegments).toBeLessThan(late.lineTo.length);
  });

  it("labels each line with its driver, so the order reads off the leading edge", () => {
    const calls = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={10} onSelectLap={vi.fn()} />);
    expect(calls.text).toContain("VER");
    expect(calls.text).toContain("NOR");
  });


  it("orders the right-hand codes by where cars stand now, not where they finish", () => {
    // VER runs 1st, drops to 3rd, and wins; NOR does the reverse. The gutter is
    // a legend and a live leaderboard at once, so at lap 3 it has to show NOR
    // above VER even though VER ends up on top.
    const early = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={3} onSelectLap={vi.fn()} />);
    expect(early.labels["NOR"]).toBeLessThan(early.labels["VER"]!);
    vi.restoreAllMocks();

    const late = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={10} onSelectLap={vi.fn()} />);
    expect(late.labels["VER"]).toBeLessThan(late.labels["NOR"]!);
  });

  it("draws something at a standing start instead of an empty panel", () => {
    const calls = record();
    render(<RaceTrace series={FIELD} selected={[]} currentLap={0} onSelectLap={vi.fn()} />);
    expect(calls.text).toContain("LAP 1");
    expect(calls.text).toContain("VER");
  });
});
