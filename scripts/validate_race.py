"""
Does the race simulator reproduce real races?

Run it two ways and compare:

    python scripts/validate_race.py prior       # only what was known before each race
    python scripts/validate_race.py hindsight   # the race's own pace, and itself in every fit

The difference between those two numbers is the whole lesson. With hindsight the
simulator looks good; without it, it is level with simply predicting the
starting grid. Finishing order is dominated by car pace, and forecasting car pace
is the hard part — not something a strategy model solves.

The baseline to beat is the grid, because a model that cannot beat "everyone
finishes where they started" is not adding anything.

**What "prior" means changed, and the old number was not what it claimed.** The
first version held out only driver pace. Tyre wear was fitted on the whole
season — the race being predicted and every race after it — and pit loss,
safety-car risk and overtaking were measured from every race in the lake,
including the one being predicted. Now every input comes from
`racecraft.model.race_inputs`, which uses only races that started before the one
being simulated. Driver pace is still the mean of the previous five races.

Two things are deliberately still given to the simulator: each car's actual
strategy, and its actual grid slot. This tests whether the race dynamics carry a
grid through a race given the plans the teams chose; it does not test choosing
the plans.
"""

import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from racecraft.model import pace, race as race_model, race_inputs      # noqa: E402
from racecraft.model.strategy import Plan                               # noqa: E402
from racecraft.store.db import connect                                  # noqa: E402

MODE = sys.argv[1] if len(sys.argv) > 1 else "prior"
if MODE not in ("prior", "hindsight"):
    sys.exit("mode is prior or hindsight")
SEASONS = (2026, 2025)
EARLIER_RACES = 5
RUNS = 120

con = connect()
rows, skipped = [], []

for year in SEASONS:
    keys = con.sql(f"""select session_key, location, total_laps, event_name from sessions
                       where year = {year} and session = 'R' order by round""").df()
    driver_pace: dict[str, dict[int, float]] = {}

    for _, k in keys.iterrows():
        key = k.session_key
        laps = con.sql(f"select * from laps where session_key = '{key}'").df()
        clean = pace.clean_race_laps(laps)
        model = None
        if len(clean) >= 200:
            try:
                model = pace.fit_lap_effects(clean)
            except (pace.Confounded, ValueError):
                model = None

        if pd.isna(k.total_laps):
            skipped.append((key, "no scheduled distance"))
        else:
            try:
                inputs = race_inputs.build(con, str(k.location), year, session_key=key,
                                           include_race=(MODE == "hindsight"),
                                           total_laps=int(k.total_laps))
            except race_inputs.NotEnoughData as error:
                inputs = None
                skipped.append((key, str(error)))

            if inputs is not None:
                if MODE == "hindsight":
                    pace_by_driver = model.driver_baseline_s if model else {}
                else:
                    # Driver pace from the previous races only: the mean of each
                    # driver's effect over the last few that had happened.
                    earlier = list(driver_pace.values())[-EARLIER_RACES:]
                    collected: dict[int, list[float]] = {}
                    for race in earlier:
                        for drv, value in race.items():
                            collected.setdefault(drv, []).append(value)
                    pace_by_driver = {drv: float(np.mean(v)) for drv, v in collected.items()}

                if len(driver_pace) < 3 and MODE == "prior":
                    skipped.append((key, "fewer than three earlier races for driver pace"))
                else:
                    results = con.sql(f"""select driver_number, abbreviation, grid_position, position
                                          from results where session_key = '{key}'""").df()
                    results = results[results.grid_position.notna() & results.position.notna()]

                    cars = []
                    for _, r in results.iterrows():
                        drv = int(r.driver_number)
                        if drv not in pace_by_driver:
                            continue
                        stints = (laps[laps.driver_number == drv].groupby("stint")
                                  .agg(compound=("compound", "first"), length=("lap_number", "size")))
                        stints = stints[stints.compound.isin(pace.DRY_COMPOUNDS)]
                        if stints.empty:
                            continue
                        plan = Plan(tuple((c, int(n)) for c, n in zip(stints.compound, stints.length)))
                        cars.append(race_model.Car(
                            driver_number=drv, abbreviation=r.abbreviation,
                            pace_s=inputs.quickest_lap_s + pace_by_driver[drv],
                            grid=int(r.grid_position) or 20, plan=plan))

                    if len(cars) < 10:
                        skipped.append((key, f"only {len(cars)} cars with a known pace and plan"))
                    else:
                        passes = race_model.pass_probability(inputs.passes_per_race,
                                                             inputs.total_laps, len(cars))
                        simulated = race_model.simulate(
                            cars, inputs.total_laps, inputs.degradation, inputs.pit_loss_s,
                            inputs.neutralisation, passes, compound_offset_s=inputs.compound_offset_s,
                            runs=RUNS, rng=np.random.default_rng(11),
                            following=inputs.following_table)
                        predicted = {d: simulated.positions[d].mean() for d in simulated.positions}
                        ranked = {d: i + 1 for i, d in enumerate(sorted(predicted, key=predicted.get))}
                        actual = {int(r.driver_number): int(r.position) for _, r in results.iterrows()}
                        grid = {int(r.driver_number): int(r.grid_position) for _, r in results.iterrows()}
                        shared = [d for d in ranked if d in actual]
                        if len(shared) >= 10:
                            rows.append(dict(
                                year=year, race=k.event_name, cars=len(shared),
                                sim_error=np.mean([abs(ranked[d] - actual[d]) for d in shared]),
                                grid_error=np.mean([abs(grid[d] - actual[d]) for d in shared]),
                                sim_top3=len({d for d in shared if ranked[d] <= 3}
                                             & {d for d in shared if actual[d] <= 3}),
                                grid_top3=len({d for d in shared if grid[d] <= 3}
                                              & {d for d in shared if actual[d] <= 3}),
                            ))

        # This race joins the pool of earlier races only after it has been
        # predicted, so it can never inform its own prediction.
        if model is not None:
            driver_pace[key] = model.driver_baseline_s

df = pd.DataFrame(rows)
print()
print(f"{len(df)} races simulated, {RUNS} runs each, mode: {MODE}")
if MODE == "prior":
    print("every input from races that started before the one being simulated")
print()
print(f"mean position error   simulator {df.sim_error.mean():.2f}   grid order {df.grid_error.mean():.2f}")
print(f"podium hits (of 3)    simulator {df.sim_top3.mean():.2f}   grid order {df.grid_top3.mean():.2f}")
print(f"races where the simulator beats the grid: {(df.sim_error < df.grid_error).sum()} of {len(df)}")
print("\nby season:")
print(df.groupby("year")[["sim_error", "grid_error", "sim_top3", "grid_top3"]].mean().round(2).to_string())
print("\nworst races for the simulator:")
print(df.nlargest(5, "sim_error")[["year", "race", "sim_error", "grid_error"]].round(2).to_string(index=False))
if skipped:
    print(f"\n{len(skipped)} races not simulated:")
    reasons: dict[str, int] = {}
    for _, reason in skipped:
        reasons[reason.split(":")[0]] = reasons.get(reason.split(":")[0], 0) + 1
    for reason, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>3}  {reason}")
