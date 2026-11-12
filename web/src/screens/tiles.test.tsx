import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { CrewStanding, DriverStarts, DriverTiming, PitCrews, QualiDriver, RaceControlEvent, RaceReview, Standings } from "../api";
import { KpiRow, type Kpi } from "../shell/KpiRow";
import { boxOf, crewTiles } from "./CrewsScreen";
import { qualiTiles } from "./QualifyingScreen";
import { reviewTiles } from "./RaceReviewScreen";
import { standingsTiles } from "./StandingsScreen";
import { startsTiles } from "./StartsScreen";
import { stewardsTiles } from "./StewardsScreen";
import { ringCars, spread, towerTiles } from "./TowerScreen";

const shown = (tiles: (Kpi | null | false | undefined)[]) => tiles.filter((t): t is Kpi => Boolean(t && t.value));

describe("headline tiles", () => {
  it("leaves out a tile with nothing to say", () => {
    render(<KpiRow tiles={[{ label: "A", value: "1" }, null, { label: "B", value: "" }]} />);
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(["A1"]);
  });

  it("timing: fastest lap, ideal lap, leader to last, cars within a second", () => {
    const d = (n: number, best: number | null, gap: number | null, interval: number | null) =>
      ({ driver_number: n, abbreviation: `D${n}`, status: "racing", laps_down: 0, best_lap_s: best, gap_to_leader_s: gap, interval_s: interval }) as DriverTiming;
    const tiles = shown(towerTiles([d(1, 95.2, 0, null), d(2, 94.8, 0.6, 0.6), d(3, null, 12.4, 11.8)], 94.5));
    expect(tiles.map((t) => [t.label, t.value])).toEqual([
      ["Fastest lap", "1:34.800"], ["Ideal lap", "1:34.500"], ["Within 1 s", "1 car"], ["Leader to last", "+12.4 s"]]);
  });

  it("field spread: the leader at 0, lapped cars left out", () => {
    const d = (n: number, pos: number, gap: number | null, down = 0) =>
      ({ driver_number: n, position: pos, status: "racing", laps_down: down, gap_to_leader_s: gap }) as DriverTiming;
    expect(spread([d(1, 1, null), d(2, 2, 3.5), d(3, 3, null, 1)]).map((c) => [c.driver.driver_number, c.gap])).toEqual([[1, 0], [2, 3.5]]);
    // Past the chequered flag the cars are "finished", and still count.
    const done = (n: number, pos: number, gap: number | null) => ({ ...d(n, pos, gap), status: "finished" }) as DriverTiming;
    expect(spread([done(1, 1, null), done(2, 2, 13.2)]).length).toBe(2);
    expect(shown(towerTiles([done(1, 1, null), done(2, 2, 13.2)], null)).find((t) => t.label === "Leader to last")?.note).toBe("2 cars on the lead lap");
  });

  it("race review: ties named together, safety-car stops counted", () => {
    const stop = (kind: "green" | "VSC") => ({ lap: 20, kind, places: 1 });
    const data = { green_stop_places: 3, drivers: [
      { abbreviation: "RUS", passes_made: 6, passes_lost: 0, stops: [stop("VSC")] },
      { abbreviation: "HAD", passes_made: 6, passes_lost: 1, stops: [stop("green")] },
      { abbreviation: "HAM", passes_made: 0, passes_lost: 4, stops: [] },
    ] } as unknown as RaceReview;
    expect(shown(reviewTiles(data)).map((t) => t.value)).toEqual(["3 places", "RUS, HAD · 6", "HAM · 4", "1"]);
  });

  it("stewards: an investigation stays open until a verdict on the same incident", () => {
    const e = (t: number, kind: string, incident: string | null, cars: number[] = [1]) =>
      ({ t, kind, incident, cars }) as RaceControlEvent;
    const tiles = shown(stewardsTiles([e(1, "under_investigation", "a"), e(2, "under_investigation", "b"),
                                       e(3, "time_penalty", "a"), e(4, "lap_deleted", null), e(5, "lap_deleted", null)]));
    expect(tiles.map((t) => [t.label, t.value])).toEqual([
      ["Under investigation", "1"], ["Penalties", "1"], ["No further action", "0"], ["Lap times deleted", "2"]]);
  });

  it("standings: leaders by margin, most wins, points still on offer", () => {
    const table = { drivers: [{ abbreviation: "ANT", points: 292, wins: 8 }, { abbreviation: "RUS", points: 211, wins: 2 }],
                    constructors: [{ team: "Mercedes", points: 503 }, { team: "Ferrari", points: 358 }] } as unknown as Standings;
    const odds = { remaining: [{ session: "race" }, { session: "race" }, { session: "sprint" }] } as never;
    expect(shown(standingsTiles(table, odds)).map((t) => [t.value, t.note])).toEqual([
      ["ANT · 292", "81 ahead of RUS"], ["Mercedes · 503", "145 ahead of Ferrari"], ["ANT · 8", "Grands Prix"],
      ["58", "2 Grands Prix, 1 sprint to run"]]);
  });

  it("pit crews: against the race's typical stop, thin samples left out", () => {
    const team = (name: string, typical: number, spread: number, slow: number, thin = false) =>
      ({ team: name, typical_s: typical, spread_s: spread, slow_share: slow, thin }) as CrewStanding;
    const crews = { stops: 120, races: 6, teams: [team("Ferrari", -0.42, 0.3, 0.1), team("McLaren", -0.2, 0.15, 0.3), team("Audi", -0.9, 0.1, 0, true)] } as unknown as PitCrews;
    expect(shown(crewTiles(crews)).map((t) => t.value)).toEqual(["Ferrari · −0.42 s", "McLaren · ±0.15 s", "McLaren · 30%", "120"]);
  });

  it("starts and qualifying name the best and the worst", () => {
    const s = (code: string, vs: number | null, gained: number | null, out = 0) =>
      ({ abbreviation: code, vs_normal: vs, gained, out_lap1: out }) as DriverStarts;
    const race = { session_key: "k", round: 2, code: "R", event_name: "Chinese Grand Prix", cars: [
      { abbreviation: "VER", team_color: null, grid: 1, lap1: 3 }, { abbreviation: "LAW", team_color: null, grid: 4, lap1: 1 },
      { abbreviation: "HUL", team_color: null, grid: 3, lap1: 2 }, { abbreviation: "EEE", team_color: null, grid: 2, lap1: null }] };
    const tiles = shown(startsTiles([s("EEE", null, null, 2), s("LAW", 1.32, 2.1), s("HUL", -0.9, -0.4, 1)], race));
    expect(tiles.map((t) => t.value)).toEqual(["LAW +3", "VER −2", "LAW +1.32", "3 cars"]);
    expect(tiles.map((t) => t.label)[0]).toBe("Best launch at Chinese");
    expect(tiles[3]!.note).toBe("at Chinese, 1 out on lap 1");
    expect(shown(startsTiles([], null))).toEqual([]);
    const q = (code: string, pos: number, left: number | null, season: number | null) =>
      ({ abbreviation: code, position: pos, best_s: 94.035, left_s: left, season_left_s: season, season_sessions: 18 }) as QualiDriver;
    expect(shown(qualiTiles([q("ANT", 1, 0.13, 0.049), q("HAD", 3, 0, 0.074), q("BOR", 13, 0.214, 0.062)])).map((t) => t.value))
      .toEqual(["ANT · 1:34.035", "BOR · +0.214", "1", "ANT · +0.049"]);
  });
});

describe("pit crews' box plot", () => {
  it("whiskers to the furthest stops within 1.5 boxes, anything past them far off", () => {
    // Middle half -0.2 to +0.2 s: whiskers may reach -0.8 to +0.8 s.
    const box = boxOf([-0.5, -0.2, 0, 0.1, 0.2, 0.7, 2.4], -0.2, 0.2);
    expect([box.low, box.high]).toEqual([-0.5, 0.7]);
    expect(box.outliers).toEqual([2.4]);
  });
  it("is just the box with no stops listed", () => {
    expect(boxOf([], -0.1, 0.3)).toEqual({ low: -0.1, high: 0.3, outliers: [] });
  });
});

describe("field ring", () => {
  const d = (n: number, pos: number, gap: number | null, down = 0) =>
    ({ driver_number: n, position: pos, status: "racing", laps_down: down, gap_to_leader_s: gap, last_lap_s: 80 }) as DriverTiming;
  const crossings = { laps: [9, 10], t: [1000, 1080] };     // the leader finished lap 10 at t 1080, an 80 s lap

  it("puts the leader its share of the lap round, and each car its gap behind at that pace", () => {
    const { cars, lapSeconds } = ringCars([d(1, 1, null), d(2, 2, 20), d(3, 3, null, 1)], 1040, crossings, 0);
    expect(lapSeconds).toBe(80);
    expect(cars.map((c) => [c.driver.driver_number, c.angle])).toEqual([[1, 9.5 * 360], [2, 9.5 * 360 - 90]]);   // lapped car 3 not drawn
  });

  it("keeps turning forward past the last crossing, on the leader's last lap time", () => {
    const { cars } = ringCars([d(1, 1, null)], 1120, crossings, 0);
    expect(cars[0]!.angle).toBe(10.5 * 360);
  });
});
