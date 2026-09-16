import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StintChart } from "./StintChart";
import type { DriverStints } from "../api";

function driver(name: string, stints: [string, number][]): DriverStints {
  let lap = 1;
  return {
    driver: name,
    driver_number: name.charCodeAt(0),
    stops: stints.length - 1,
    stints: stints.map(([compound, laps]) => {
      const stint = { compound, laps, first_lap: lap, last_lap: lap + laps - 1 };
      lap += laps;
      return stint;
    }),
  };
}

const FIELD = [
  driver("HAM", [["MEDIUM", 18], ["HARD", 15], ["SOFT", 18]]),   // two stops
  driver("VER", [["SOFT", 25], ["MEDIUM", 26]]),                 // one stop
  driver("NOR", [["MEDIUM", 24], ["SOFT", 27]]),                 // one stop
];

describe("StintChart", () => {
  it("orders the field by stop count, so the split reads without counting", () => {
    const { container } = render(
      <StintChart stints={FIELD} totalLaps={51} modelStints={null} modelLabel="" />,
    );
    const codes = [...container.querySelectorAll(".stint-row .stint-driver")].map((n) => n.textContent);
    expect(codes).toEqual(["NOR", "VER", "HAM"]);      // one-stoppers first, then alphabetical
  });

  it("draws each stint to the same lap scale as the race", () => {
    const { container } = render(
      <StintChart stints={[driver("VER", [["SOFT", 25], ["MEDIUM", 25]])]} totalLaps={50} modelStints={null} modelLabel="" />,
    );
    const bars = [...container.querySelectorAll(".stint-bar")] as HTMLElement[];
    expect(bars).toHaveLength(2);
    expect(bars[0]?.style.width).toBe("50%");
    expect(bars[1]?.style.width).toBe("50%");
  });

  it("names the compound and lap range of a stint, since a colour alone is not a number", () => {
    render(<StintChart stints={FIELD} totalLaps={51} modelStints={null} modelLabel="" />);
    expect(screen.getByTitle("soft · laps 1–25 (25)")).toBeDefined();
  });

  it("draws the model's own plan on the same scale, marked apart from the cars", () => {
    const { container } = render(
      <StintChart
        stints={FIELD}
        totalLaps={51}
        modelStints={[
          { compound: "SOFT", laps: 26, first_lap: 1, last_lap: 26 },
          { compound: "MEDIUM", laps: 25, first_lap: 27, last_lap: 51 },
        ]}
        modelLabel="soft 26 > medium 25"
      />,
    );
    const model = container.querySelector(".stint-row.is-model") as HTMLElement;
    expect(model).not.toBeNull();
    expect(within(model).getByText("MODEL")).toBeDefined();
    expect(model.querySelectorAll(".stint-bar")).toHaveLength(2);
  });

  it("falls back to the last lap run when the race distance is unknown", () => {
    const { container } = render(
      <StintChart stints={[driver("VER", [["SOFT", 20], ["HARD", 20]])]} totalLaps={null} modelStints={null} modelLabel="" />,
    );
    const bars = [...container.querySelectorAll(".stint-bar")] as HTMLElement[];
    expect(bars[0]?.style.width).toBe("50%");
  });

  it("renders nothing at all rather than an empty frame when no stints are known", () => {
    const { container } = render(
      <StintChart stints={[]} totalLaps={51} modelStints={null} modelLabel="" />,
    );
    expect(container.querySelector(".stint-chart")).toBeNull();
  });
});
