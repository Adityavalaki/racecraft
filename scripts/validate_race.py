"""
Does the race simulator reproduce real races?

Run it two ways and compare:

    python scripts/validate_race.py prior       # pace from earlier races only
    python scripts/validate_race.py hindsight   # pace from the race being predicted

The difference between those two numbers is the whole lesson. With hindsight
the simulator looks good; without it, it is level with simply predicting the
starting grid. Finishing order is dominated by car pace, and forecasting car
pace is the hard part - not something a strategy model solves.

The baseline to beat is the grid, because a model that cannot beat "everyone
finishes where they started" is not adding anything.
"""
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd
from racecraft.store.db import connect
from racecraft.model import pace, circuit as circuit_model, race as race_model
from racecraft.model.simulate import Neutralisation
from racecraft.model.strategy import Plan

import sys
MODE = sys.argv[1] if len(sys.argv) > 1 else "prior"
con = connect()
laps_all = con.sql("select l.*, s.location from laps l join sessions s using (session_key) where s.session='R'").df()
pit_by_circuit = {p.circuit: p.seconds for p in circuit_model.pit_loss(laps_all)}
sessions_all = con.sql("select session_key, location from sessions where session='R'").df()
ts_all = con.sql("select session_key, t, status from track_status").df()
risk_by_circuit = {r.circuit: r for r in circuit_model.safety_car_risk(ts_all, sessions_all, laps_all)}

# Passes per race, measured pairwise (neither car pitting, green flag).
def passes_per_race(circuit_laps):
    per_race = []
    for key, race_laps in circuit_laps.groupby("session_key"):
        per_lap = {n: g.set_index("driver_number") for n, g in race_laps.groupby("lap_number")}
        passes = 0
        for lap in sorted(per_lap):
            before, after = per_lap.get(lap - 1), per_lap.get(lap)
            if before is None or after is None or str(after.track_status.iloc[0]) != "1":
                continue
            clean = [d for d in after.index if d in before.index
                     and not bool(before.loc[d, "is_pit_in_lap"]) and not bool(after.loc[d, "is_pit_in_lap"])
                     and not bool(after.loc[d, "is_pit_out_lap"]) and not bool(before.loc[d, "is_pit_out_lap"])
                     and pd.notna(before.loc[d, "position"]) and pd.notna(after.loc[d, "position"])]
            for i, a in enumerate(clean):
                for b in clean[i + 1:]:
                    passes += (before.loc[a, "position"] < before.loc[b, "position"]) != \
                              (after.loc[a, "position"] < after.loc[b, "position"])
        per_race.append(passes)
    return float(np.mean(per_race)) if per_race else 30.0

laps_all["circuit"] = circuit_model.canonical_circuit(laps_all["location"])
passes_by_circuit = {c: passes_per_race(g) for c, g in laps_all.groupby("circuit")}

rows = []
for year in (2026, 2025):
    keys = con.sql(f"""select session_key, location, total_laps, event_name from sessions
                       where year={year} and session='R' order by round""").df()
    models, clean_by = {}, {}
    for _, k in keys.iterrows():
        clean = pace.clean_race_laps(con.sql(f"select * from laps where session_key='{k.session_key}'").df())
        clean_by[k.session_key] = clean
        if len(clean) >= 200:
            try:
                models[k.session_key] = pace.fit_lap_effects(clean)
            except Exception:
                pass
    season_deg = {c: v[0] for c, v in pace.combine(list(models.values())).items()}
    season_off = {c: float(np.median([m.compound_offset_s[c] for m in models.values() if c in m.compound_offset_s]))
                  for c in pace.DRY_COMPOUNDS if any(c in m.compound_offset_s for m in models.values())}

    for _, k in keys.iterrows():
        key = k.session_key
        if key not in models or pd.isna(k.total_laps):
            continue
        circuit = circuit_model.canonical_circuit(k.location)
        if circuit not in pit_by_circuit:
            continue
        results = con.sql(f"""select driver_number, abbreviation, grid_position, position, classified_position
                              from results where session_key='{key}'""").df()
        results = results[results.grid_position.notna() & results.position.notna()]
        laps = con.sql(f"select * from laps where session_key='{key}'").df()
        # Pace from EARLIER races only. Using this race's own pace would be
        # hindsight: the simulator would already know how quick each car was
        # on the day it is meant to be predicting.
        if MODE == "hindsight":
            pace_by_driver = models[key].driver_baseline_s
        else:
            order = list(keys.session_key)
            earlier = [models[k2] for k2 in order[:order.index(key)] if k2 in models]
            if len(earlier) < 3:
                continue
            collected: dict[int, list[float]] = {}
            for m in earlier[-5:]:                     # the last five races
                for drv, value in m.driver_baseline_s.items():
                    collected.setdefault(drv, []).append(value)
            pace_by_driver = {drv: float(np.mean(v)) for drv, v in collected.items()}
        quickest = con.sql(f"""select min(lap_time_s) from laps where session_key='{key}'""").fetchone()[0]

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
            cars.append(race_model.Car(driver_number=drv, abbreviation=r.abbreviation,
                                       pace_s=quickest + pace_by_driver[drv],
                                       grid=int(r.grid_position) or 20, plan=plan))
        if len(cars) < 10:
            continue

        total = int(k.total_laps)
        risk = risk_by_circuit.get(circuit)
        neutralisation = Neutralisation.for_circuit(risk.periods_per_race if risk else 1.27, total)
        passes = race_model.pass_probability(passes_by_circuit.get(circuit, 30.0), total, len(cars))
        simulated = race_model.simulate(cars, total, season_deg, pit_by_circuit[circuit], neutralisation,
                                        passes, compound_offset_s=season_off, runs=120,
                                        rng=np.random.default_rng(11))
        predicted = {d: simulated.positions[d].mean() for d in simulated.positions}
        ranked = {d: i + 1 for i, d in enumerate(sorted(predicted, key=predicted.get))}
        actual = {int(r.driver_number): int(r.position) for _, r in results.iterrows()}
        grid = {int(r.driver_number): int(r.grid_position) for _, r in results.iterrows()}
        shared = [d for d in ranked if d in actual]
        if len(shared) < 10:
            continue
        rows.append(dict(
            year=year, race=k.event_name, cars=len(shared),
            sim_error=np.mean([abs(ranked[d] - actual[d]) for d in shared]),
            grid_error=np.mean([abs(grid[d] - actual[d]) for d in shared]),
            sim_top3=len({d for d in shared if ranked[d] <= 3} & {d for d in shared if actual[d] <= 3}),
            grid_top3=len({d for d in shared if grid[d] <= 3} & {d for d in shared if actual[d] <= 3}),
        ))

df = pd.DataFrame(rows)
print()
print(f"{len(df)} races simulated, 120 runs each, pace from: {MODE}")
print()
print(f"mean position error   simulator {df.sim_error.mean():.2f}   grid order {df.grid_error.mean():.2f}")
print(f"podium hits (of 3)    simulator {df.sim_top3.mean():.2f}   grid order {df.grid_top3.mean():.2f}")
print(f"races where the simulator beats the grid: {(df.sim_error < df.grid_error).sum()} of {len(df)}")
print("\nby season:")
print(df.groupby("year")[["sim_error", "grid_error", "sim_top3", "grid_top3"]].mean().round(2).to_string())
print("\nworst races for the simulator:")
print(df.nlargest(5, "sim_error")[["year", "race", "sim_error", "grid_error"]].round(2).to_string(index=False))
