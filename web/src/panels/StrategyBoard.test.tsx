import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { StrategyBoard } from "./StrategyBoard";
import type { Insight, Plan, RiskyPlan } from "../api";

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

function riskyPlan(overrides: Partial<RiskyPlan> = {}): RiskyPlan {
  return {
    plan: "medium 30 > soft 21",
    stops: 1,
    expected_s: 51.7,
    green_s: 53.6,
    best_case_s: 44.4,
    worst_case_s: 54.4,
    cheap_stop_share: 0.4,
    stop_laps: [30],
    behind_best_s: 0,
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
    plans_with_risk: [riskyPlan(), riskyPlan({ plan: "medium 26 > soft 25", expected_s: 51.9, green_s: 52.6, behind_best_s: 0.2, cheap_stop_share: 0.35, stop_laps: [26] })],
    stints: [],
    ...overrides,
  };
}

describe("StrategyBoard", () => {
  it("shows the measured circuit constants rather than round numbers", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    expect(screen.getByText("21.0s")).toBeDefined();
    expect(screen.getByText("±1.0 · 42 stops")).toBeDefined();
    expect(screen.getByText("0.83")).toBeDefined();
    expect(screen.getByText("51")).toBeDefined();
  });

  it("ranks plans with the best marked and the rest measured against it", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    expect(screen.getByText("best")).toBeDefined();
    expect(screen.getByText("+0.5s")).toBeDefined();
  });

  it("says when a row stands for both running orders, because the model cannot tell them apart", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    const badges = screen.getAllByText("either order");
    expect(badges).toHaveLength(1);                       // only the plan with two orders
    expect(badges[0]?.getAttribute("title")).toContain("medium 26 > soft 25");
  });

  it("always shows what the model leaves out", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    const omissions = screen.getByRole("list");
    expect(within(omissions).getByText("traffic")).toBeDefined();
    expect(within(omissions).getByText("track position")).toBeDefined();
    expect(within(omissions).getByText("the cliff")).toBeDefined();
  });

  it("puts the model's stop count beside what the race actually ran", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={1.1} sessionKey={null} />);
    expect(screen.getByText("1 stop")).toBeDefined();
    expect(screen.getByText("race ran 1.10 avg")).toBeDefined();
  });

  it("explains itself when there are no plans instead of rendering an empty table", () => {
    render(
      <StrategyBoard
        insight={insight({ plans: [], plans_unavailable: "not enough green-flag stops at this circuit" })}
        loading={false}
        error={null}
        actualStops={null} sessionKey={null}
      />,
    );
    expect(screen.getByText("not enough green-flag stops at this circuit")).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("says a circuit with one season has no safety car figure, rather than showing zero", () => {
    render(
      <StrategyBoard insight={insight({ safety_car: null })} loading={false} error={null} actualStops={null} sessionKey={null} />,
    );
    expect(screen.getByText("one season only")).toBeDefined();
  });


  it("opens on the green ranking, because that one is arithmetic rather than simulation", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    expect(screen.getByRole("radio", { name: "If green" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByText("where it goes")).toBeDefined();
  });

  it("switches to the safety-car ranking, which answers a different question", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null} sessionKey={null} />);
    fireEvent.click(screen.getByRole("radio", { name: /safety cars/i }));

    expect(screen.getByText("cheap stop")).toBeDefined();
    // Each stint is its own span so it can carry a compound colour, so the
    // plan is matched by its parts rather than as one string.
    expect(screen.getByText("medium 30")).toBeDefined();
    expect(screen.getByText("soft 21")).toBeDefined();
    expect(screen.getByText("40%")).toBeDefined();
    // The green ranking's own columns are gone, not merely hidden behind it.
    expect(screen.queryByText("where it goes")).toBeNull();
  });

  it("stops listing safety cars as an omission once they are modelled", () => {
    const withSafetyCarCaveat = insight({
      caveats: [
        "safety cars: a stop under one costs roughly half, which can flip the answer",
        "traffic: a car released into a queue loses time this does not count",
      ],
    });
    render(<StrategyBoard insight={withSafetyCarCaveat} loading={false} error={null} actualStops={null} sessionKey={null} />);
    expect(within(screen.getByRole("list")).getByText("safety cars")).toBeDefined();

    fireEvent.click(screen.getByRole("radio", { name: /safety cars/i }));
    expect(within(screen.getByRole("list")).queryByText("safety cars")).toBeNull();
    expect(within(screen.getByRole("list")).getByText("traffic")).toBeDefined();
  });

  it("disables the safety-car ranking when the circuit has no risk figure to simulate", () => {
    render(
      <StrategyBoard
        insight={insight({ plans_with_risk: [] })}
        loading={false}
        error={null}
        actualStops={null} sessionKey={null}
      />,
    );
    expect(screen.getByRole("radio", { name: /safety cars/i }).hasAttribute("disabled")).toBe(true);
  });


  it("does not report a stop average for a session that is not a race", () => {
    // Practice stops are cars trundling through the pit lane. Quoting a field
    // average of four stops beside a modelled one would be nonsense presented
    // with a decimal point.
    render(
      <StrategyBoard
        insight={insight({ is_race: false, stints: [] })}
        loading={false}
        error={null}
        actualStops={4.18} sessionKey={null}
      />,
    );
    expect(screen.queryByText(/race ran/i)).toBeNull();
    expect(screen.getByText("cheapest plan")).toBeDefined();
  });

  it("says plainly that a non-race session measured none of what it shows", () => {
    render(
      <StrategyBoard
        insight={insight({ is_race: false, stints: [] })}
        loading={false}
        error={null}
        actualStops={null} sessionKey={null}
      />,
    );
    expect(screen.getByText(/nothing here is measured from this session/i)).toBeDefined();
  });

  it("keeps the race comparison when it is a race", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={1.1} sessionKey={null} />);
    expect(screen.getByText("race ran 1.10 avg")).toBeDefined();
    expect(screen.queryByText(/nothing here is measured/i)).toBeNull();
  });


  it("offers a third view that ranks plans by where they finish", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null}
                          sessionKey="2025_17_R" />);
    fireEvent.click(screen.getByRole("radio", { name: "In places" }));
    expect(screen.getByRole("radio", { name: "In places" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByLabelText(/starting from/i)).toBeDefined();
    // The seconds views' caveats name traffic and track position as missing,
    // which this view models, so they are not shown here.
    expect(screen.queryByText("This counts seconds, not places. It leaves out:")).toBeNull();
    vi.unstubAllGlobals();
  });

  it("cannot open the places view without a session to ask about", () => {
    render(<StrategyBoard insight={insight()} loading={false} error={null} actualStops={null}
                          sessionKey={null} />);
    expect(screen.getByRole("radio", { name: "In places" }).hasAttribute("disabled")).toBe(true);
  });

  it("reports an error instead of pretending it has a model", () => {
    render(<StrategyBoard insight={null} loading={false} error="lake unreachable" actualStops={null} sessionKey={null} />);
    expect(screen.getByText("lake unreachable")).toBeDefined();
  });
});
