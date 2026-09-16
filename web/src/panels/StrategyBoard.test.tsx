import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StrategyBoard } from "./StrategyBoard";
import type { Insight, Plan } from "../api";

function plan(overrides: Partial<Plan> = {}): Plan {
  return {
    plan: "soft 25 > medium 26",
    stops: 1,
    seconds_lost: 52.6,
    tyre_seconds: 34.7,
    compound_seconds: -3.1,
    pit_seconds: 21.0,
    behind_best_s: 0,
    stint_laps: [25, 26],
    stop_laps: [25],
    orders: ["medium 26 > soft 25", "soft 25 > medium 26"],
    ...overrides,
  };
}

function insight(overrides: Partial<Insight> = {}): Insight {
  return {
    session_key: "2025_17_R",
    circuit: "Baku",
    event_name: "Azerbaijan Grand Prix",
    year: 2025,
    is_race: true,
    total_laps: 51,
    pit_loss: { circuit: "Baku", seconds: 21.0, spread_s: 1.0, stops: 42, seasons: 3 },
    safety_car: {
      circuit: "Baku", races: 3, share_of_races: 1, probability: 0.83,
      periods_per_race: 1, per_lap: 0.02, median_laps_lost: 4.1,
    },
    scale: 1.5,
    degradation_measured: { SOFT: 0.0327, MEDIUM: 0.0356, HARD: 0.0432 },
    degradation_used: { SOFT: 0.0491, MEDIUM: 0.0534, HARD: 0.0649 },
    compound_offset_s: { SOFT: 0, MEDIUM: -0.12, HARD: 0.18 },
    fuel_s_per_lap: 0.05,
    fitted_on: ["Bahrain Grand Prix", "Monaco Grand Prix"],
    fitted_on_count: 2,
    held_out: true,
    caveats: [
      "traffic: a car released into a queue loses time this does not count",
      "track position: this counts seconds, not places, and races are scored in places",
      "the cliff: degradation past the point teams actually pit is unmeasured",
    ],
    degradation_curve: [],
    plans: [plan(), plan({ plan: "soft 22 > medium 29", seconds_lost: 53.1, behind_best_s: 0.5, stop_laps: [22], orders: ["soft 22 > medium 29"] })],
    stints: [],
    ...overrides,
  };
}

describe("StrategyBoard", () => {
  it("shows the measured circuit constants rather than round numbers", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} />);
    expect(screen.getByText("21.0s")).toBeDefined();
    expect(screen.getByText("±1.0 · 42 stops")).toBeDefined();
    expect(screen.getByText("0.83")).toBeDefined();
    expect(screen.getByText("51")).toBeDefined();
  });

  it("ranks plans with the best marked and the rest measured against it", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} />);
    expect(screen.getByText("best")).toBeDefined();
    expect(screen.getByText("+0.5s")).toBeDefined();
  });

  it("says when a row stands for both running orders, because the model cannot tell them apart", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} />);
    const badges = screen.getAllByText("either order");
    expect(badges).toHaveLength(1);                       // only the plan with two orders
    expect(badges[0]?.getAttribute("title")).toContain("medium 26 > soft 25");
  });

  it("always shows what the model leaves out", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} />);
    const omissions = screen.getByRole("list");
    expect(within(omissions).getByText("traffic")).toBeDefined();
    expect(within(omissions).getByText("track position")).toBeDefined();
    expect(within(omissions).getByText("the cliff")).toBeDefined();
  });

  it("puts the model's stop count beside what the race actually ran", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={1.1} />);
    expect(screen.getByText("1 stop")).toBeDefined();
    expect(screen.getByText("race ran 1.10 avg")).toBeDefined();
  });

  it("explains itself when there are no plans instead of rendering an empty table", () => {
    render(
      <StrategyBoard
        insight={insight({ plans: [], plans_unavailable: "not enough green-flag stops at this circuit" })}
        loading={false}
        error={null}
        actualStops={null}
      />,
    );
    expect(screen.getByText("not enough green-flag stops at this circuit")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says a circuit with one season has no safety car figure, rather than showing zero", () => {
    render(
      <StrategyBoard insight={insight({ safety_car: null })} loading={false} error={null} actualStops={null} />,
    );
    expect(screen.getByText("one season only")).toBeDefined();
  });

  it("reports an error instead of pretending it has a model", () => {
    render(<StrategyBoard insight={null} loading={false} error="lake unreachable" actualStops={null} />);
    expect(screen.getByText("lake unreachable")).toBeDefined();
  });
});
