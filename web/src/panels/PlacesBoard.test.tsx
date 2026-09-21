import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PlacesBoard } from "./PlacesBoard";
import type { PlacesAnswer, PlaceRow } from "../api";

/**
 * The places view races plans against a whole field. What it has to get right
 * on screen is not the numbers — the model tests check those — but saying no
 * more than they support: ties shown as ties, the price of track position rather
 * than a winner, and whether the race itself was held out.
 */
function row(overrides: Partial<PlaceRow>): PlaceRow {
  return {
    plan: "medium 22 > hard 29", stops: 1, stop_laps: [22], mean_finish: 8.44, std_error: 0.16,
    median_finish: 8, best: 2, worst: 17, podium_share: 0.1, points_share: 0.86,
    gained: -0.44, behind_best: 0, within_noise: true, expected_s: 60.0, green_s: 61.0,
    start_ages: [4, 0], on_used_sets: true,
    ...overrides,
  };
}

function answer(overrides: Partial<PlacesAnswer> = {}): PlacesAnswer {
  return {
    session_key: "2025_17_R", grid: 8, runs: 300, tyres: "car",
    stock: {
      driver: "HAD", driver_number: 6, grid: 8, sets: 6,
      left: { SOFT: { new: 0, used: [2, 3, 5] }, MEDIUM: { new: 0, used: [4, 7] },
              HARD: { new: 0, used: [1] } },
      notes: [],
    },
    inputs: {
      circuit: "Baku", season: 2025, event_name: "Azerbaijan Grand Prix", total_laps: 51,
      held_out: true, target_session: "2025_17_R", cutoff: "2025-09-21 11:00:00+00:00",
      fitted_on_count: 14, pit_loss_s: 21.3, pit_stops: 27, periods_per_race: 1,
      passes_per_race: 28.5,
      following: { measured: true, penalties: [{ under_s: 0.5, seconds: 0.276 }], races: 14, detail: "" },
      notes: [],
    },
    study: {
      grid: 8,
      plans: [
        row({ plan: "hard 31 > medium 20", stop_laps: [31], mean_finish: 8.41, behind_best: 0, expected_s: 63.1 }),
        row({ plan: "medium 22 > hard 29", mean_finish: 8.44, behind_best: 0.03 }),
        row({ plan: "medium 25 > hard 26", stop_laps: [25], mean_finish: 8.84, behind_best: 0.43,
              within_noise: false, expected_s: 59.9 }),
        row({ plan: "medium 16 > hard 35", stop_laps: [16], mean_finish: 10.33, behind_best: 1.91,
              within_noise: false, expected_s: 62.6 }),
      ],
      cheapest_in_seconds: "medium 25 > hard 26", best_in_places: "hard 31 > medium 20",
      field_plan: "medium 25 > hard 26", field_stop_window: [20, 31], field_draws: 15,
      stock: { SOFT: { new: 0, used: [2, 3, 5] }, MEDIUM: { new: 0, used: [4, 7] },
               HARD: { new: 0, used: [1] } },
      dropped: [{ plan: "hard 25 > hard 26", reason: "needs 2 hard sets, has 1" }],
    },
    verdict: {
      cheapest_in_seconds: "medium 25 > hard 26", best_in_places: "hard 31 > medium 20", agree: false,
      tied: ["hard 31 > medium 20", "medium 22 > hard 29"],
      price: { plan: "medium 22 > hard 29", instead_of: "medium 25 > hard 26",
               extra_seconds: 0.1, places_gained: 0.4 },
      bad_plan: { plan: "medium 16 > hard 35", extra_seconds: 2.7, places_lost: 1.91 },
    },
    omissions: ["rivals: the rest of the field runs a fixed plan and never covers a stop"],
    ...overrides,
  };
}

function mock(body: PlacesAnswer | { detail: string }, ok = true) {
  const fetchMock = vi.fn(async (_url: string) =>
    ({ ok, statusText: "Unprocessable", json: async () => body }) as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe("PlacesBoard", () => {
  it("says it is working while the field is raced, rather than showing an empty table", () => {
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => undefined)));
    render(<PlacesBoard sessionKey="2025_17_R" />);
    expect(screen.getByText(/about half a minute/i)).toBeDefined();
  });

  it("leads with the price of track position, not a winner", async () => {
    mock(answer());
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(screen.getByText(/price of track position/i)).toBeDefined());
    const verdict = screen.getByText(/price of track position/i).closest("p")!;
    expect(verdict.textContent).toContain("0.1s");
    expect(verdict.textContent).toContain("0.40 places");
  });

  it("marks plans that cannot be told apart from the best as tied", async () => {
    mock(answer());
    const { container } = render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(container.querySelectorAll(".plan-row-places").length).toBe(4));

    const rows = [...container.querySelectorAll(".plan-row-places")];
    expect(rows[1]!.className).toContain("is-tied");
    expect(within(rows[1] as HTMLElement).getByText("tied")).toBeDefined();
    expect(rows[2]!.className).not.toContain("is-tied");
  });

  it("says when the race itself was held out of its own fit", async () => {
    mock(answer());
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(screen.getByText(/none of this race/i)).toBeDefined());
  });

  it("says when nothing was held out because the race has not been run", async () => {
    mock(answer({ inputs: { ...answer().inputs, held_out: false, cutoff: null, target_session: null } }));
    render(<PlacesBoard sessionKey="live" />);
    await waitFor(() => expect(screen.getByText(/not run yet this season/i)).toBeDefined());
  });

  it("says the two models agree when the seconds pick is inside the error bar", async () => {
    mock(answer({ verdict: { ...answer().verdict, agree: true, price: null } }));
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(screen.getByText(/inside its error bar/i)).toBeDefined());
  });

  it("asks again for a different grid slot", async () => {
    const fetchMock = mock(answer());
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0]![0])).toContain("grid=8");

    fireEvent.change(screen.getByLabelText(/starting from/i), { target: { value: "3" } });
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[1]![0])).toContain("grid=3");
  });

  it("explains a race that cannot be simulated instead of failing silently", async () => {
    mock({ detail: "no earlier race at Madrid to measure its pit lane from" }, false);
    render(<PlacesBoard sessionKey="2026_14_R" />);
    await waitFor(() => expect(screen.getByText(/no earlier race at Madrid/)).toBeDefined());
  });

  it("says whose tyres it raced and what they ruled out", async () => {
    mock(answer());
    const { container } = render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(container.querySelector(".places-garage")).not.toBeNull());
    const line = container.querySelector(".places-garage")!;
    expect(line.textContent).toContain("HAD");
    expect(line.textContent).toContain("6 sets");
    expect(line.textContent).toContain("hard: 1 laps");
    // A plan the car has no sets for is named, not silently missing.
    expect(line.textContent).toContain("hard 25 > hard 26 (needs 2 hard sets, has 1)");
  });

  it("shows the laps on the set each stint starts on", async () => {
    mock(answer());
    const { container } = render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(container.querySelectorAll(".plan-row-places").length).toBe(4));
    expect(container.querySelector(".plan-sets")!.textContent).toBe("4 · new");
  });

  it("asks again for new sets, which is the ideal case rather than the real one", async () => {
    const fetchMock = mock(answer());
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(String(fetchMock.mock.calls[0]![0])).toContain("tyres=car");

    fireEvent.click(screen.getByRole("radio", { name: /new sets/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(String(fetchMock.mock.calls[1]![0])).toContain("tyres=new");
  });

  it("says when it is racing new sets because the car's own are not known", async () => {
    mock(answer({ stock: null, tyres: "car" }));
    render(<PlacesBoard sessionKey="live" />);
    await waitFor(() => expect(screen.getByText(/not in the lake, so they cannot be raced/)).toBeDefined());
  });

  it("lists what this view still cannot see", async () => {
    mock(answer());
    render(<PlacesBoard sessionKey="2025_17_R" />);
    await waitFor(() => expect(screen.getByText("rivals")).toBeDefined());
  });
});
