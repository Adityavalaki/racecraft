import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Prediction, PredictionDriver } from "../api";
import { PredictionBoard, percent } from "./PredictionBoard";

/**
 * The prediction board shows chances, not a call. What it must get right on
 * screen: the order and the chances as the model gave them, what it was made
 * from and when, and — after the race — the result beside it, scored against
 * simply finishing where you started.
 */
function driver(n: number, code: string, over: Partial<PredictionDriver> = {}): PredictionDriver {
  return {
    driver_number: n, abbreviation: code, team_name: "Team", team_color: "3671C6", grid: n,
    win: 0.1, podium: 0.3, points: 0.8, dnf: 0.12, expected: 5, p10: 2, p50: 4, p90: 9,
    pace_s: -0.2, pace_sd: 0.4, signals: { quali_gap_s: -0.3, long_run_s: null, sprint_s: null, form_s: -0.25, carry_s: null },
    ...over,
  };
}

function answer(over: Partial<Prediction> = {}): Prediction {
  return {
    race_key: "2025_04_R", event_name: "Bahrain Grand Prix", year: 2025, round: 4,
    drivers: [
      driver(81, "PIA", { grid: 1, win: 0.716, podium: 0.82, points: 0.84, expected: 4.1, p10: 1, p90: 2 }),
      driver(16, "LEC", { grid: 2, win: 0.125, podium: 0.65, expected: 5.4, p10: 3, p90: 8 }),
      driver(63, "RUS", { grid: 3, win: 0.002, podium: 0.6, expected: 5.8, p10: 1, p90: 5 }),
      driver(18, "STR", { grid: 99, win: 0, podium: 0, points: 0.05, expected: 17.2, p10: 14, p90: 20 }),
    ],
    basis: {
      sessions: ["FP1", "FP2", "FP3", "Q"], form_races: ["Australian Grand Prix", "Chinese Grand Prix", "Japanese Grand Prix"],
      grid_source: "race", retire_rate: 0.12, runs: 1000, reference_plan: "medium 18 > hard 39",
      calibration: { fitted_on: ["2023", "2024", "2025"] }, notes: ["a note from the model"],
    },
    made_at: "2025-04-12T18:00:00+00:00", before_race: true, in_sample: false, result: null,
    ...over,
  };
}

/** The table row a driver's code sits in: the code also shows in the headline cards. */
function rowButton(codes: HTMLElement[]): HTMLElement {
  return codes.map((el) => el.closest("button.prediction-row")).find((el): el is HTMLElement => el !== null)!;
}

function mock(body: Prediction | { detail: string }, ok = true) {
  const fetchMock = vi.fn(async (_url: string) =>
    ({ ok, statusText: "Unprocessable", json: async () => body }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("PredictionBoard", () => {
  it("says it is working while the first prediction is made", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<PredictionBoard sessionKey="2025_04_Q" selected={[]} onSelect={vi.fn()} />);
    expect(screen.getByText(/predicting the race/i)).toBeDefined();
  });

  it("lists the predicted order with each driver's chances and what it was made from", async () => {
    const fetchMock = mock(answer());
    const { container } = render(<PredictionBoard sessionKey="2025_04_Q" selected={[]} onSelect={vi.fn()} />);
    await screen.findAllByText("PIA");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/sessions/2025_04_Q/prediction");

    const rows = Array.from(container.querySelectorAll("button.prediction-row"));
    expect(rows.map((r) => r.querySelector(".code")?.textContent)).toEqual(["PIA", "LEC", "RUS", "STR"]);
    const first = within(rows[0] as HTMLElement);
    expect(first.getByText("72%")).toBeDefined();               // win
    expect(first.getByText("82%")).toBeDefined();               // podium
    expect(first.getByText("4.1")).toBeDefined();               // expected
    expect(within(rows[2] as HTMLElement).getByText("<1%")).toBeDefined();   // rare, not zero
    expect(within(rows[3] as HTMLElement).getByText("PL")).toBeDefined();    // pit-lane start

    // The headline: the favourite and how often they win, and the podium chances.
    const favourite = within(screen.getByRole("region", { name: "Favourite" }));
    expect(favourite.getByText("PIA")).toBeDefined();
    expect(favourite.getByText(/Wins 72% of 1,000 simulated races/)).toBeDefined();
    expect(screen.getByRole("region", { name: "Podium chances" }).querySelectorAll(".podium-row")).toHaveLength(4);
    expect(screen.getByText(/made before the race/i)).toBeDefined();
    expect(screen.getByText(/FP1, FP2, FP3, qualifying and 3 earlier races/)).toBeDefined();
    expect(screen.getByText(/official starting grid/)).toBeDefined();
    expect(screen.getByText(/at 12% a car/)).toBeDefined();
    expect(screen.getByText("a note from the model")).toBeDefined();
    expect(container.querySelector(".actual")).toBeNull();      // no result yet, no column
  });

  it("puts the result beside the prediction after the race, scored against the grid", async () => {
    mock(answer({
      before_race: false,
      result: {
        finish: { "81": 6, "16": 1, "63": 2, "18": 20 },
        scores: {
          model: { rho: 0.75, winner_hit: true, podium_hits: 2, brier_win: 0.11, brier_podium: 1.26, logloss_win: 0.33 },
          grid: { rho: 0.72, winner_hit: true, podium_hits: 2, brier_win: 0.23, brier_podium: 1.87, logloss_win: 0.55 },
        },
      },
    }));
    const { container } = render(<PredictionBoard sessionKey="2025_04_R" selected={[]} onSelect={vi.fn()} />);
    await screen.findAllByText("PIA");
    expect(screen.getByText(/rebuilt after the race/i)).toBeDefined();
    expect(Array.from(container.querySelectorAll(".actual")).map((c) => c.textContent)).toEqual(["P6", "P1", "P2", "P20"]);
    // Coloured only outside the likely range: LEC won from a P3–P8 range, PIA's P1–P2 ended sixth.
    expect(container.querySelector(".actual.is-better")?.textContent).toBe("P1");
    expect(container.querySelector(".actual.is-worse")?.textContent).toBe("P6");
    expect(container.querySelectorAll(".actual.is-better, .actual.is-worse")).toHaveLength(2);
    const card = within(screen.getByRole("table", { name: /how the prediction did/i }));
    expect(card.getByText("0.75").className).toContain("is-ahead");
    expect(card.getByText("0.72").className).not.toContain("is-ahead");
  });

  it("follows the replay's picks", async () => {
    mock(answer());
    const onSelect = vi.fn();
    render(<PredictionBoard sessionKey="2025_04_R" selected={[16]} onSelect={onSelect} />);
    fireEvent.click(rowButton(await screen.findAllByText("RUS")));
    expect(onSelect).toHaveBeenCalledWith(63);
    expect(rowButton(screen.getAllByText("LEC")).getAttribute("aria-pressed")).toBe("true");
  });

  it("says why when there is no prediction yet", async () => {
    mock({ detail: "the prediction is made once qualifying is in" }, false);
    render(<PredictionBoard sessionKey="2026_17_FP1" selected={[]} onSelect={vi.fn()} />);
    expect(await screen.findByText(/once qualifying is in/)).toBeDefined();
  });

  it("writes chances so that rare is not shown as impossible", () => {
    expect(percent(0)).toBe("—");
    expect(percent(0.003)).toBe("<1%");
    expect(percent(0.716)).toBe("72%");
  });
});
