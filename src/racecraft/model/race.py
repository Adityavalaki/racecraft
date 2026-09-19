"""
A whole race, so strategy can be judged in places rather than seconds.

Everything before this counts time: how many seconds a plan loses to tyres and
pit stops. Races are not scored in seconds. A plan that is two seconds quicker
but rejoins behind a car it cannot pass has lost, and a lap-time model cannot
see that because it never looks at anyone else.

So this puts the whole field on track together and runs the race lap by lap.
Each car has its own pace, tyres that wear, and a plan. Cars that catch
another lose time in its wake and only get past when the circuit allows, which
is measured per circuit and is why Monaco behaves differently from Monza.
Safety cars arrive on the circuit's own schedule, bunch the field up and hand
a cheap stop to whoever still owes one.

Every input is measured from the lake rather than assumed; the modules in
`racecraft.model` each supply one. What comes out is a distribution of
finishing positions per driver, which is the shape a strategy decision
actually has.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

# Time lost per lap in another car's wake, by gap in seconds: the 2026 figure,
# measured by `racecraft-analyse following --season 2026` on laps where the
# follower was slower than the car ahead and so could not be being held up.
# Being held up is modelled separately, by blocking, so it must not be in here.
#
# This is a fallback. The simulator is normally handed the table measured for
# the season it is running, and uses this only when a season has too few laps
# close behind another car to measure one. It used to read 0.55 s inside half a
# second, with a comment claiming a measurement nothing in the repository made;
# that was the wake and the holding-up together, and counted the second twice.
FOLLOWING_PENALTY_S = ((0.5, 0.283), (1.0, 0.072), (1.5, 0.034), (2.5, 0.002), (4.0, 0.0))

# How close a car sits behind one it cannot pass.
MIN_FOLLOWING_GAP_S = 0.4
# Under a safety car the field closes up to roughly this spacing.
SAFETY_CAR_GAP_S = 1.5
SAFETY_CAR_LAP_MULTIPLIER = 1.4
# Lap-to-lap variation in a driver's pace, from the residual scatter of the
# pace model on clean laps.
LAP_NOISE_S = 0.35


@dataclass
class Car:
    driver_number: int
    abbreviation: str
    pace_s: float                 # seconds a lap slower than the quickest car
    grid: int
    plan: Plan
    team_color: str | None = None


@dataclass
class RaceResult:
    """Where each car finished, over many simulated races."""
    positions: dict[int, np.ndarray] = field(default_factory=dict)      # driver -> finishing positions
    order: list[int] = field(default_factory=list)                      # by mean finish

    def summary(self, cars: dict[int, Car]) -> list[dict]:
        out = []
        for driver in self.order:
            finishes = self.positions[driver]
            out.append({
                "driver_number": driver,
                "abbreviation": cars[driver].abbreviation,
                "grid": cars[driver].grid,
                "mean_finish": round(float(finishes.mean()), 2),
                "median_finish": int(np.median(finishes)),
                "best": int(finishes.min()),
                "worst": int(finishes.max()),
                "win_share": round(float((finishes == 1).mean()), 3),
                "podium_share": round(float((finishes <= 3).mean()), 3),
                "points_share": round(float((finishes <= 10).mean()), 3),
                "plan": str(cars[driver].plan),
            })
        return out


def following_penalty(gap_s: float, table=None) -> float:
    """Time lost this lap to the wake of the car ahead."""
    for limit, penalty in (table or FOLLOWING_PENALTY_S):
        if gap_s < limit:
            return penalty
    return 0.0


def simulate(cars: list[Car], total_laps: int, degradation: dict[str, float], pit_loss_s: float,
             neutralisation: Neutralisation, passes_per_lap: float,
             compound_offset_s: dict[str, float] | None = None,
             curvature: dict[str, float] | None = None,
             runs: int = 200, rng: np.random.Generator | None = None,
             following=None) -> RaceResult:
    """
    Run the race `runs` times and collect where everyone finished.

    `following` is the wake penalty by gap, as measured for the season being
    run; see `traffic.measure`. It falls back to the 2026 figure.
    """
    rng = rng or np.random.default_rng(0)
    by_number = {car.driver_number: car for car in cars}
    finishes: dict[int, list[int]] = {car.driver_number: [] for car in cars}

    for _ in range(runs):
        order = _one_race(cars, total_laps, degradation, pit_loss_s, neutralisation,
                          passes_per_lap, compound_offset_s or {}, curvature, rng, following)
        for position, driver in enumerate(order, start=1):
            finishes[driver].append(position)

    positions = {driver: np.array(values) for driver, values in finishes.items()}
    ranked = sorted(positions, key=lambda d: positions[d].mean())
    result = RaceResult(positions=positions, order=ranked)
    result.summary(by_number)      # validates every car is present
    return result


def _one_race(cars: list[Car], total_laps: int, degradation: dict[str, float], pit_loss_s: float,
              neutralisation: Neutralisation, passes_per_lap: float,
              compound_offset_s: dict[str, float], curvature: dict[str, float] | None,
              rng: np.random.Generator, following=None) -> list[int]:
    n = len(cars)
    numbers = [car.driver_number for car in cars]
    elapsed = np.array([0.6 * (car.grid - 1) for car in cars], dtype=float)   # the grid is staggered
    tyre_age = np.ones(n)
    stint = np.zeros(n, dtype=int)
    stops_left = [[sum(length for _, length in car.plan.stints[:i + 1]) for i in range(car.plan.stops)]
                  for car in cars]
    neutral_laps = _draw_neutral_laps(total_laps, neutralisation, rng)
    # Everyone runs to the same delta-time behind the safety car, so the lap is
    # the field's own pace slowed down rather than a fixed number.
    safety_car_lap = float(np.median([car.pace_s for car in cars])) * SAFETY_CAR_LAP_MULTIPLIER

    for lap in range(1, total_laps + 1):
        neutral = lap in neutral_laps
        order = np.argsort(elapsed)                 # current running order
        gaps = _gaps_to_car_ahead(elapsed, order)

        lap_times = np.empty(n)
        for index, car in enumerate(cars):
            compound = car.plan.stints[min(stint[index], len(car.plan.stints) - 1)][0]
            age = tyre_age[index]
            wear = degradation.get(compound, 0.0) * age + (curvature or {}).get(compound, 0.0) * age * age
            base = car.pace_s + compound_offset_s.get(compound, 0.0) + wear
            if neutral:
                lap_times[index] = safety_car_lap
            else:
                lap_times[index] = (base + following_penalty(gaps[index], following)
                                    + rng.normal(0, LAP_NOISE_S))

        elapsed = elapsed + lap_times
        tyre_age += 1

        for index, car in enumerate(cars):
            if not stops_left[index]:
                continue
            due = lap >= stops_left[index][0]
            opportunity = neutral and tyre_age[index] >= 8 and total_laps - lap >= 8
            if due or opportunity:
                elapsed[index] += pit_loss_s * (neutralisation.stop_discount if neutral else 1.0)
                stops_left[index].pop(0)
                stint[index] += 1
                tyre_age[index] = 1

        if neutral:
            elapsed = _bunch_up(elapsed)
        else:
            # Judged against the order at the start of the lap: a car that has
            # caught the one ahead has to get past it, and whether it does is
            # what the circuit decides.
            elapsed = _apply_blocking(elapsed, order, passes_per_lap, rng)

    return [numbers[i] for i in np.argsort(elapsed)]


def _gaps_to_car_ahead(elapsed: np.ndarray, order: np.ndarray) -> np.ndarray:
    gaps = np.full(len(elapsed), np.inf)
    for place, index in enumerate(order):
        if place > 0:
            gaps[index] = elapsed[index] - elapsed[order[place - 1]]
    return gaps


def _apply_blocking(elapsed: np.ndarray, order_at_lap_start: np.ndarray,
                    passes_per_lap: float, rng: np.random.Generator) -> np.ndarray:
    """
    Hold a car up behind one it has caught but cannot pass.

    The order matters: this works down the field as it was at the start of the
    lap, so a car that has closed onto the one ahead must actually get past it
    rather than being counted through because its race time is now lower.
    Whether it gets by is a coin weighted by how often this circuit allows a
    pass. Working front to back lets a queue form behind one slow car, which
    is what a hard-to-pass circuit really does to a race.
    """
    for place in range(1, len(order_at_lap_start)):
        behind, ahead = order_at_lap_start[place], order_at_lap_start[place - 1]
        if elapsed[behind] >= elapsed[ahead] + MIN_FOLLOWING_GAP_S:
            continue                                  # never caught it
        if rng.random() < passes_per_lap:
            continue                                  # through, and keeps its own time
        elapsed[behind] = elapsed[ahead] + MIN_FOLLOWING_GAP_S
    return elapsed


def _bunch_up(elapsed: np.ndarray) -> np.ndarray:
    """A safety car closes the field to a queue, which is most of what makes it decisive."""
    order = np.argsort(elapsed)
    bunched = elapsed.copy()
    leader = elapsed[order[0]]
    for place, index in enumerate(order):
        bunched[index] = leader + place * SAFETY_CAR_GAP_S
    return bunched


def _draw_neutral_laps(total_laps: int, neutralisation: Neutralisation, rng: np.random.Generator) -> set[int]:
    neutral: set[int] = set()
    for lap in np.flatnonzero(rng.random(total_laps) < neutralisation.per_lap) + 1:
        length = max(1, int(round(rng.exponential(neutralisation.laps))))
        neutral.update(range(int(lap), min(total_laps, int(lap) + length) + 1))
    return neutral


def pass_probability(passes_per_race: float, total_laps: int, cars: int = 20) -> float:
    """
    Turn measured passes per race into the chance one held-up car gets by on a
    given lap. Roughly: passes are spread over laps and over the cars that are
    actually in a fight, which is a fraction of the field at any moment.
    """
    fights_per_lap = max(1.0, cars * 0.25)
    return float(np.clip(passes_per_race / (total_laps * fights_per_lap), 0.005, 0.9))
