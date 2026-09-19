import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TyreSets, carAt } from "./TyreSets";
import type { CarSets, DriverTiming, Insight, TyreSets as TyreSetsAnswer } from "../api";

/**
 * The sets panel follows the replay clock. What it has to get right is time:
 * a new set turns used the moment it leaves the pit lane, not when the session
 * does, and the lap count on it climbs a lap at a time.
 */
function car(overrides: Partial<CarSets> = {}): CarSets {
  return {
    driver_number: 1, driver: "VER", team: "Red Bull Racing", stand_ins: [],
    at_start: {
      SOFT: { new: 0, used: [{ set: 8, laps: 2 }] },
      MEDIUM: { new: 0, used: [{ set: 10, laps: 4 }, { set: 9, laps: 6 }] },
      HARD: { new: 2, used: [] },
    },
    returned: [{ set: 1, compound: "SOFT", after: "FP1", laps: 9 }],
    new_returned: {},
    this_session: [
      // A new hard from lap one, then the four-lap medium from qualifying.
      { set: 14, compound: "HARD", new_at_start: true, laps_at_start: 0, thought_returned: false,
        runs: [{ start_t: 100, lap_end_t: [200, 290, 380] }] },
      { set: 10, compound: "MEDIUM", new_at_start: false, laps_at_start: 4, thought_returned: false,
        runs: [{ start_t: 400, lap_end_t: [500, 590] }] },
    ],
    notes: [],
    ...overrides,
  };
}

function answer(cars: CarSets[], session = "R"): TyreSetsAnswer {
  return {
    session_key: "2025_17_R", session, event_name: "Azerbaijan Grand Prix", year: 2025,
    sessions: ["FP1", "FP2", "FP3", "Q", "R"],
    rules: {
      name: "standard weekend", allocation: { SOFT: 8, MEDIUM: 3, HARD: 2 },
      returns: [{ after: "FP1", sets: 2 }, { after: "FP2", sets: 2 }, { after: "FP3", sets: 2 }],
      q3_returns_soft: true, extra: {}, hand_backs_known: true,
    },
    returns_so_far: [], cars, notes: [],
  };
}

function timing(number: number, position: number): DriverTiming {
  return {
    driver_number: number, abbreviation: null, team_name: null, team_color: "3671c6", position,
    status: "racing", laps_completed: 0, gap_to_leader_s: null, gap_text: "", interval_s: null,
    interval_text: "", laps_down: 0, last_lap_s: null, best_lap_s: null, is_session_best: false,
    is_personal_best: false, compound: null, tyre_life: null, laps_in_stint: null, stops: 0, sectors: [],
  };
}

afterEach(() => vi.unstubAllGlobals());

describe("carAt", () => {
  it("shows what the car held before anything is fitted", () => {
    const view = carAt(car(), 50);
    expect(view.HARD).toEqual({ fresh: 2, used: [] });
    expect(view.MEDIUM!.used.map((s) => s.laps)).toEqual([4, 6]);
  });

  it("turns a new set into a used one when it leaves the pit lane, and counts its laps", () => {
    const view = carAt(car(), 300);
    expect(view.HARD!.fresh).toBe(1);
    expect(view.HARD!.used).toEqual([{ set: 14, laps: 2, fitted: true, doubtful: false }]);
  });

  it("carries a used set on from the laps it already had", () => {
    const view = carAt(car(), 600);
    expect(view.MEDIUM!.used.find((s) => s.set === 10)).toEqual({ set: 10, laps: 6, fitted: true, doubtful: false });
    expect(view.HARD!.used[0]!.fitted).toBe(false);
  });

  it("stops calling a set fitted once the car has been in for a while", () => {
    const view = carAt(car(), 590 + 600);
    expect(view.MEDIUM!.used.some((s) => s.fitted)).toBe(false);
  });

  it("marks a set the tracker thought went back but that was run anyway", () => {
    const doubtful = car({
      this_session: [{ set: 3, compound: "SOFT", new_at_start: false, laps_at_start: 7, thought_returned: true,
                       runs: [{ start_t: 10, lap_end_t: [100] }] }],
    });
    const view = carAt(doubtful, 150);
    expect(view.SOFT!.used.find((s) => s.set === 3)).toMatchObject({ laps: 8, doubtful: true });
  });
});

describe("TyreSets", () => {
  function mock(body: TyreSetsAnswer) {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => body }) as Response));
  }

  it("lists cars in running order with the weekend's rules", async () => {
    mock(answer([car(), car({ driver_number: 4, driver: "NOR" })]));
    const { container } = render(
      <TyreSets sessionKey="2025_17_R" t={0} drivers={[timing(1, 2), timing(4, 1)]}
                selected={[]} onSelect={() => undefined} insight={null} />,
    );
    await waitFor(() => expect(container.querySelectorAll(".sets-row").length).toBe(2));
    const names = [...container.querySelectorAll(".sets-driver")].map((n) => n.textContent);
    expect(names).toEqual(["NOR", "VER"]);
    expect(screen.getByText(/13 dry sets each/)).toBeDefined();
  });

  it("selects a car when its row is clicked", async () => {
    mock(answer([car()]));
    const onSelect = vi.fn();
    const { container } = render(
      <TyreSets sessionKey="2025_17_R" t={0} drivers={[]} selected={[]} onSelect={onSelect} insight={null} />,
    );
    await waitFor(() => expect(container.querySelector(".sets-row")).not.toBeNull());
    fireEvent.click(container.querySelector(".sets-row")!);
    expect(onSelect).toHaveBeenCalledWith(1);
  });

  it("says which plans the selected car cannot run and what used sets cost it", async () => {
    mock(answer([car()]));
    const insight = {
      tyre_sets: {
        unavailable: null,
        cars: {
          "1": {
            driver: "VER", left: {},
            plans: [
              { plan: "medium 22 > hard 29", feasible: true, reason: null, extra_s: 6.1,
                stints: [{ compound: "MEDIUM", laps: 22, set_laps: 4 }, { compound: "HARD", laps: 29, set_laps: 0 }] },
              { plan: "soft 15 > soft 15 > hard 21", feasible: false, reason: "needs 2 soft sets, has 1",
                extra_s: 0, stints: [] },
            ],
          },
        },
      },
    } as unknown as Insight;
    render(
      <TyreSets sessionKey="2025_17_R" t={0} drivers={[]} selected={[1]} onSelect={() => undefined}
                insight={insight} />,
    );
    await waitFor(() => expect(screen.getByText(/Can VER run/)).toBeDefined());
    expect(screen.getByText("+6.1s · medium with 4 laps")).toBeDefined();
    expect(screen.getByText("can't: needs 2 soft sets, has 1")).toBeDefined();
    expect(screen.getByText(/upper bound/)).toBeDefined();
  });

  it("does not check plans outside a race", async () => {
    mock(answer([car()], "FP2"));
    render(
      <TyreSets sessionKey="2025_17_FP2" t={0} drivers={[]} selected={[1]} onSelect={() => undefined}
                insight={null} />,
    );
    await waitFor(() => expect(screen.getByText(/Open the race to see them/)).toBeDefined());
  });
});
