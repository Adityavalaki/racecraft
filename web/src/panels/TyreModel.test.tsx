import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TyreModel } from "./TyreModel";
import type { DegradationCurve, Insight } from "../api";

function curve(compound: string, slope: number, ages: number): DegradationCurve {
  return {
    compound,
    observed_to_age: ages,
    points: Array.from({ length: ages }, (_, index) => {
      const age = index + 1;
      return {
        age,
        model_s: Number((slope * 1.5 * age).toFixed(3)),
        model_unscaled_s: Number((slope * age).toFixed(3)),
        observed_s: age % 2 === 0 ? Number((slope * age).toFixed(3)) : null,
        laps: 12,
      };
    }),
  };
}

function curveWithoutObservations(compound: string, slope: number, ages: number): DegradationCurve {
  const full = curve(compound, slope, ages);
  return { ...full, observed_to_age: 0, points: full.points.map((p) => ({ ...p, observed_s: null, laps: 0 })) };
}

function insight(overrides: Partial<Insight> = {}): Insight {
  return {
    session_key: "2026_14_R",
    circuit: "Madrid",
    event_name: "Spanish Grand Prix",
    year: 2026,
    is_race: true,
    total_laps: 57,
    pit_loss: null,
    safety_car: null,
    scale: 1.5,
    degradation_measured: { SOFT: 0.033, HARD: 0.048 },
    degradation_used: { SOFT: 0.0495, HARD: 0.072 },
    compound_offset_s: {},
    fuel_s_per_lap: 0.05,
    fitted_on: ["Bahrain Grand Prix", "Monaco Grand Prix", "Monza Grand Prix"],
    fitted_on_count: 3,
    held_out: true,
    caveats: [],
    degradation_curve: [curve("SOFT", 0.033, 12), curve("HARD", 0.048, 30)],
    plans: [],
    plans_with_risk: [],
    stints: [],
    ...overrides,
  };
}

describe("TyreModel", () => {
  it("lists each compound with the degradation actually used to cost plans", () => {
    render(<TyreModel insight={insight()} loading={false} error={null} />);
    expect(screen.getByText("soft")).toBeDefined();
    expect(screen.getByText("0.050")).toBeDefined();      // 0.0495 rounded, the scaled figure
    expect(screen.getByText("0.072")).toBeDefined();
  });

  it("states that the line was fitted on other races, which is what makes it a prediction", () => {
    render(<TyreModel insight={insight()} loading={false} error={null} />);
    const note = screen.getByText(/fitted on/i);
    expect(note.textContent).toContain("3 other 2026 races");
    expect(note.textContent).toContain("never this one");
  });

  it("says the line is scaled, so an adjusted number is never shown as a raw measurement", () => {
    render(<TyreModel insight={insight()} loading={false} error={null} />);
    expect(screen.getByText(/raw measurement/i)).toBeDefined();
    expect(screen.getByText(/×1.5/)).toBeDefined();
  });


  it("explains the missing dots on a non-race session rather than drawing a bare line", () => {
    // Practice mixes fuel runs, qualifying simulations and out-laps, so its
    // observed wear is not comparable with anything. The line still holds — it
    // is fitted on races — but the panel has to say why the dots are absent.
    render(
      <TyreModel
        insight={insight({
          is_race: false,
          observed_unavailable: "this is not a race: practice and qualifying laps mix fuel loads",
          degradation_curve: [curveWithoutObservations("SOFT", 0.033, 12)],
        })}
        loading={false}
        error={null}
      />,
    );
    expect(screen.getByText(/this is not a race/i)).toBeDefined();
    const note = screen.getByText(/fitted on/i);
    expect(note.textContent).not.toContain("never this one");
    expect(note.textContent).not.toContain("what this race did");
  });

  it("says so plainly when a session has no dry laps to measure", () => {
    render(<TyreModel insight={insight({ degradation_curve: [] })} loading={false} error={null} />);
    expect(screen.getByText(/no dry-tyre laps/i)).toBeDefined();
  });

  it("shows that it is working rather than an empty panel while the season is fitted", () => {
    render(<TyreModel insight={null} loading={true} error={null} />);
    expect(screen.getByText(/fitting the season/i)).toBeDefined();
  });

  it("reports an error instead of a blank chart", () => {
    render(<TyreModel insight={null} loading={false} error="lake unreachable" />);
    expect(screen.getByText("lake unreachable")).toBeDefined();
  });
});
