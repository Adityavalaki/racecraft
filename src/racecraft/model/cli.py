"""
Run the models over the lake: `racecraft-analyse`.

    racecraft-analyse pace                 # degradation and fuel, per season
    racecraft-analyse pace --season 2026   # one season, with each race listed
    racecraft-analyse circuits             # pit loss and neutralisation risk
    racecraft-analyse circuit Baku         # everything known about one circuit
    racecraft-analyse following            # time lost in another car's wake, per season
    racecraft-analyse race Baku --grid 8   # plans for one car, ranked in places

Every number the README quotes comes from these commands, so anyone can
reproduce them rather than taking them on trust.
"""

from __future__ import annotations

import argparse
import sys

import numpy as np
import pandas as pd

from racecraft import config
from racecraft.model import circuit as circuit_model
from racecraft.model.circuit import passes_per_race
from racecraft.model import pace as pace_model
from racecraft.store.db import connect


def _race_laps(con, where: str = "") -> pd.DataFrame:
    return con.sql(f"""select l.*, s.location, s.year from laps l join sessions s using (session_key)
                       where s.session = 'R' {where}""").df()


def _clean_by_session(con, year: int) -> tuple[dict, dict]:
    sessions = con.sql(f"select session_key, total_laps, event_name from sessions "
                       f"where year = {year} and session = 'R' order by round").df()
    clean, totals, names = {}, {}, {}
    for _, row in sessions.iterrows():
        laps = con.sql(f"select * from laps where session_key = '{row.session_key}'").df()
        cleaned = pace_model.clean_race_laps(laps)
        if len(cleaned) > 50:
            clean[row.session_key] = cleaned
            names[row.session_key] = row.event_name
            if pd.notna(row.total_laps):
                totals[row.session_key] = int(row.total_laps)
    return (clean, totals), names


def cmd_pace(args) -> int:
    con = connect()
    if args.method == "lap-effects":
        return _pace_by_lap_effects(args, con)
    seasons = [args.season] if args.season else sorted(
        r[0] for r in con.sql("select distinct year from sessions where session='R'").fetchall())

    print(f"{'season':>6} {'races':>6} {'laps':>7} {'fuel':>8}   " +
          "  ".join(f"{c:>16}" for c in pace_model.DRY_COMPOUNDS))
    for year in sorted(seasons, reverse=True):
        (clean, totals), names = _clean_by_session(con, year)
        if not clean:
            print(f"{year:>6}   no races with enough clean laps")
            continue
        model = pace_model.fit_pooled(clean, totals)
        cells = []
        for compound in pace_model.DRY_COMPOUNDS:
            value = model.degradation_s_per_lap.get(compound)
            error = model.standard_errors.get(f"deg_{compound}")
            cells.append(f"{value:.4f} ± {error:.4f}" if value is not None else "—")
        print(f"{year:>6} {len(clean):>6} {model.n_laps:>7} {model.fuel_s_per_lap:>8.4f}   " +
              "  ".join(f"{c:>16}" for c in cells))

        if args.season:
            print(f"\n  per race (single races are noisy; the pooled figure above is the one to use):")
            print(f"  {'race':<28} {'laps':>5} {'fuel':>7}   " +
                  "  ".join(f"{c:>8}" for c in pace_model.DRY_COMPOUNDS))
            for key, laps in clean.items():
                try:
                    single = pace_model.fit(laps, totals.get(key))
                except pace_model.Confounded:
                    print(f"  {names[key]:<28} {len(laps):>5}   every driver stopped alike: not separable")
                    continue
                except ValueError as error:
                    print(f"  {names[key]:<28} {len(laps):>5}   {error}")
                    continue
                values = "  ".join(
                    f"{single.degradation_s_per_lap.get(c, float('nan')):>8.3f}" for c in pace_model.DRY_COMPOUNDS)
                print(f"  {names[key]:<28} {single.n_laps:>5} {single.fuel_s_per_lap:>7.3f}   {values}")
    return 0


def _pace_by_lap_effects(args, con) -> int:
    """Degradation from comparing drivers at the same lap, fuel absorbed rather than modelled."""
    seasons = [args.season] if args.season else sorted(
        r[0] for r in con.sql("select distinct year from sessions where session='R'").fetchall())
    header = "  ".join(f"{c:>18}" for c in pace_model.DRY_COMPOUNDS)
    print(f"{'season':>6} {'races':>6}   {header}")
    for year in sorted(seasons, reverse=True):
        (clean, _), _ = _clean_by_session(con, year)
        models = []
        for laps in clean.values():
            if len(laps) < 200:
                continue
            try:
                models.append(pace_model.fit_lap_effects(laps, curved=args.curved))
            except (pace_model.Confounded, ValueError):
                continue
        if not models:
            print(f"{year:>6}   nothing fittable")
            continue
        pooled = pace_model.combine(models)
        cells = [f"{pooled[c][0]:.4f} ± {pooled[c][1]:.4f}" if c in pooled else "—"
                 for c in pace_model.DRY_COMPOUNDS]
        print(f"{year:>6} {len(models):>6}   " + "  ".join(f"{c:>18}" for c in cells))
    print()
    print("Fuel is absorbed into the per-lap effects here, so it is not reported.")
    return 0


def cmd_strategy(args) -> int:
    """Cheapest plans for one circuit, from measured degradation and pit loss."""
    import numpy as np
    from racecraft.model import strategy as strategy_model

    con = connect()
    name = circuit_model.canonical_circuit(args.circuit)
    laps_all = _race_laps(con)
    loss = next((p for p in circuit_model.pit_loss(laps_all) if p.circuit == name), None)
    if loss is None:
        print(f"no pit loss known for '{args.circuit}': not enough green-flag stops in the lake")
        return 1

    (clean, _), _ = _clean_by_session(con, args.season)
    models = []
    for laps in clean.values():
        if len(laps) < 200:
            continue
        try:
            models.append(pace_model.fit_lap_effects(laps))
        except (pace_model.Confounded, ValueError):
            continue
    if not models:
        print(f"no fittable races in {args.season}")
        return 1
    degradation = {c: v[0] * args.scale for c, v in pace_model.combine(models).items()}
    offsets = {c: float(np.median([m.compound_offset_s[c] for m in models if c in m.compound_offset_s]))
               for c in pace_model.DRY_COMPOUNDS
               if any(c in m.compound_offset_s for m in models)}

    total = args.laps or int(laps_all[circuit_model.canonical_circuit(laps_all["location"]) == name]
                             .groupby("session_key")["lap_number"].max().median())
    print(f"{name}, {total} laps — {args.season} tyre behaviour, pit loss {loss.seconds:.1f}s"
          + (f", degradation scaled x{args.scale}" if args.scale != 1.0 else ""))
    print(f"  degradation s/lap: " + ", ".join(f"{c.lower()} {v:.4f}" for c, v in degradation.items()))
    print(f"  pace at equal age: " + ", ".join(f"{c.lower()} {v:+.2f}s" for c, v in offsets.items()))
    print()

    if args.safety_car:
        from racecraft.model import simulate as simulate_model

        sessions = con.sql("select session_key, location from sessions where session='R'").df()
        track_status = con.sql("select session_key, t, status from track_status").df()
        risk = next((r for r in circuit_model.safety_car_risk(track_status, sessions, laps_all)
                     if r.circuit == name), None)
        periods = risk.periods_per_race if risk else 1.27
        neutralisation = simulate_model.Neutralisation.for_circuit(periods, total)
        print(f"  safety cars:       {periods:.2f} per race here, "
              f"{neutralisation.per_lap:.3f} chance per lap, a stop under one costs "
              f"{neutralisation.stop_discount:.0%}")
        print()
        plans = strategy_model.enumerate_plans(total, tuple(degradation), max_stops=2,
                                               min_stint=10, step=max(2, args.step))
        ranked = simulate_model.best_plans_with_risk(plans, degradation, loss.seconds, neutralisation,
                                                     compound_offset_s=offsets, runs=args.runs, top=args.top)
        print(f"  {'plan':<28} {'expected':>9} {'if green':>9} {'lucky':>7} {'unlucky':>8} {'cheap stop':>11}")
        for costed in ranked:
            d = costed.as_dict()
            print(f"  {d['plan']:<28} {d['expected_s']:>9.1f} {d['green_s']:>9.1f} "
                  f"{d['best_case_s']:>7.1f} {d['worst_case_s']:>8.1f} {d['cheap_stop_share']:>10.0%}")
    else:
        for costed in strategy_model.best_plans(total, degradation, loss.seconds,
                                                compound_offset_s=offsets, top=args.top, step=args.step):
            d = costed.as_dict()
            print(f"  {d['plan']:<30} {d['stops']} stop   {d['seconds_lost']:6.1f}s lost   "
                  f"(tyres {d['tyre_seconds']:5.1f}, compound {d['compound_seconds']:+5.1f}, pits {d['pit_seconds']:4.0f})")

    print()
    print("  This counts seconds, not places. It leaves out:")
    for omission in strategy_model.KNOWN_OMISSIONS:
        if args.safety_car and omission.startswith("safety cars"):
            continue          # simulated here, so no longer a limitation
        print(f"    - {omission}")
    return 0


def _driver_number(con, session_key: str, abbreviation: str) -> int | None:
    """The number behind a three-letter code, in the race being studied."""
    rows = con.sql(f"""select driver_number from results
                       where session_key = '{session_key}'
                         and upper(abbreviation) = '{abbreviation.upper()}'""").df()
    return None if rows.empty else int(rows.iloc[0]["driver_number"])


def _held(compound: str, held: dict) -> str:
    """'2 new hard' / 'medium with 4, 7 laps'."""
    parts = []
    if held["new"]:
        parts.append(f"{held['new']} new {compound.lower()}")
    if held["used"]:
        laps = ", ".join(str(n) for n in held["used"])
        plural = "s" if len(held["used"]) > 1 or held["used"][0] != 1 else ""
        parts.append(f"{compound.lower()} with {laps} lap{plural}")
    return " and ".join(parts)


def cmd_race(args) -> int:
    """
    Rank plans for one car by where they finish, racing the whole field.

    Every input comes from `race_inputs`, which uses only races that finished
    before the one being studied: a race that has happened is never fitted on
    itself or on anything after it. See that module for why.

    That includes the tyres. For a race in the lake, the car on the chosen grid
    slot races the sets it actually had left — reconstructed from the weekend's
    earlier sessions, so still known before the start — unless `--new-tyres`
    asks for the ideal case instead.
    """
    from racecraft.model import places as places_model
    from racecraft.model import race_inputs

    con = connect()
    try:
        inputs = race_inputs.build(con, args.circuit, args.season, scale=args.scale,
                                   cars=args.cars, include_race=args.include_race,
                                   total_laps=args.laps)
    except race_inputs.NotEnoughData as error:
        print(f"cannot simulate: {error}")
        return 1

    if inputs.held_out:
        print(f"{inputs.event_name} {inputs.season} — held out: fitted only on races before "
              f"{inputs.cutoff:%d %b %Y}, none of it on this race or any after it")
    else:
        print(f"{inputs.circuit} — not run yet in {inputs.season}, so every finished race is used")
    print(f"  {inputs.total_laps} laps | pit lane {inputs.pit_loss_s:.1f}s ({inputs.pit_stops} stops) | "
          f"{inputs.passes_per_race:.0f} passes per race | "
          f"{inputs.periods_per_race:.2f} safety cars per race")
    print(f"  tyres from {len(inputs.fitted_on)} {inputs.season} races, "
          + ", ".join(f"{c.lower()} {v:.4f}" for c, v in inputs.degradation.items())
          + f" s/lap (x{inputs.scale})")
    wake = inputs.following
    if wake.measured:
        print(f"  wake measured from {wake.races} races: "
              + ", ".join(f"<{edge}s {value:+.2f}" for edge, value in wake.penalties[:3]) + " s/lap")
    for note in inputs.notes:
        print(f"  note: {note}")
    print()

    stock, grid = None, args.grid
    if inputs.target_session and (args.driver or not args.new_tyres):
        number = _driver_number(con, inputs.target_session, args.driver) if args.driver else None
        if args.driver and number is None:
            print(f"no driver {args.driver!r} in this race")
            return 1
        stock = race_inputs.tyre_stock(con, inputs.target_session,
                                       grid=None if number else grid, driver_number=number)
        if stock and stock.grid:
            grid = stock.grid            # a named driver is advised from where they started
        if args.new_tyres:
            stock = None
    result = places_model.study(inputs, grid, plans=args.plans, runs=args.runs,
                                stock=stock.left if stock else None)
    if not result.ranking:
        print("no plans to race")
        if result.dropped:
            for entry in result.dropped:
                print(f"  {entry['plan']}: {entry['reason']}")
        return 1

    if stock:
        print(f"  On {stock.driver}'s own tyres, as they were at the start: "
              + ", ".join(_held(compound, held) for compound, held in stock.left.items()
                          if held["new"] or held["used"]))
        for entry in result.dropped:
            print(f"    cannot run {entry['plan']}: {entry['reason']}")
        for note in stock.notes:
            print(f"    note: {note}")
    elif inputs.target_session:
        print("  On new sets for every stint, which is the ideal case rather than the real one.")
    print()

    low, high = places_model.field_stop_window(inputs.total_laps, result.field_plan)
    print(f"  A car starting P{grid}. The rest of the field stops between laps {low} and "
          f"{high}, redrawn {places_model.DEFAULT_FIELD_DRAWS} times so that no one guess about")
    print("  them decides this. Plans are shortlisted allowing for safety cars.")
    print()

    expected = {str(c.plan): c.expected_s for c in result.shortlist}
    header = f"  {'plan':<30} {'expected':>9} {'finish':>8} {'±':>6} {'behind':>7} {'points':>8}"
    print(header + ("   starts on" if stock else ""))
    for entry in result.ranking:
        name = str(entry.plan)
        tie = " tied" if entry.within_noise else ""
        sets = ""
        if stock:
            sets = "   " + ", ".join(
                "new" if age == 0 else f"{age} lap" + ("" if age == 1 else "s")
                for age in entry.start_ages)
        print(f"  {name:<30} {expected[name]:>8.1f}s {entry.mean_finish:>8.2f} "
              f"{entry.std_error:>6.2f} {entry.behind_best:>7.2f} {entry.points_share:>7.0%}{tie}{sets}")

    said = places_model.verdict(result)
    print()
    print(f"  cheapest in seconds : {said['cheapest_in_seconds']}  "
          f"({expected[said['cheapest_in_seconds']]:.1f}s expected)")
    print(f"  best in places      : {said['best_in_places']}  (P{result.ranking[0].mean_finish:.2f})")
    if len(said["tied"]) > 1:
        print(f"  cannot be separated : {', '.join(said['tied'])}")
    print()
    if said["price"] is None:
        if said["cheapest_in_seconds"] == said["best_in_places"]:
            print("  The two models agree on the best plan here.")
        else:
            print(f"  A different plan tops the places ranking, but {said['cheapest_in_seconds']} is")
            print("  inside its error bar. On this evidence the two models agree.")
    else:
        price = said["price"]
        print(f"  {price['plan']} is as good as the best in places and costs {price['extra_seconds']:.1f}s")
        print(f"  more than {price['instead_of']}, for {price['places_gained']:.2f} places. "
              "That is the price of track position here.")
    if said["bad_plan"]:
        bad = said["bad_plan"]
        print()
        print("  Where the two models really differ is how bad a bad plan is:")
        print(f"  {bad['plan']} costs {bad['extra_seconds']:.1f}s more in seconds and "
              f"{bad['places_lost']:.2f} places more here.")

    print()
    print("  Comparing plans for one car is what this is for. It does not predict")
    print("  finishing order: with pace from earlier races only it is level with")
    print("  guessing the grid (see scripts/validate_race.py).")
    return 0


def cmd_following(args) -> int:
    """The time lost in another car's wake, by gap, per season. See model/traffic.py."""
    from racecraft.model import traffic

    con = connect()
    seasons = [args.season] if args.season else sorted(
        r[0] for r in con.sql("select distinct year from sessions where session='R'").fetchall())
    labels = [f"<{edge}s" for edge in traffic.EDGES]

    for year in seasons:
        keys = [r[0] for r in con.sql(
            f"select session_key from sessions where year = {year} and session = 'R' order by round"
        ).fetchall()]
        races = [con.sql(f"select * from laps where session_key = '{k}'").df() for k in keys]
        table = traffic.measure([r for r in races if not r.empty])
        print()
        print(f"{year}   {table.detail}")
        if not table.measured:
            print("  not measurable")
            continue
        print(f"  {'gap':>7} {'wake':>14} {'laps':>7} {'all laps':>10}")
        for label, (_, value), error, n, raw in zip(labels, table.penalties, table.errors,
                                                   table.laps, table.all_laps):
            print(f"  {label:>7} {value:>+7.3f} ± {error:.3f} {n:>7} {raw:>+10.3f}")

    print()
    print("  wake: laps where the follower was slower than the car ahead, so it cannot")
    print("  have been held up. That is what the race simulator uses, because it models")
    print("  being held up separately. 'all laps' includes the holding-up, and is the")
    print("  larger figure a following penalty would be if measured naively.")
    return 0


def cmd_circuits(args) -> int:
    con = connect()
    laps = _race_laps(con)
    sessions = con.sql("select session_key, location from sessions where session='R'").df()
    track_status = con.sql("select session_key, t, status from track_status").df()

    losses = {p.circuit: p for p in circuit_model.pit_loss(laps)}
    risks = {r.circuit: r for r in circuit_model.safety_car_risk(track_status, sessions, laps)}

    print(f"{'circuit':<20} {'pit loss':>9} {'stops':>6}   {'races':>6} {'SC/VSC':>7} {'shrunk':>7} {'laps lost':>10}")
    for name in sorted(set(losses) | set(risks), key=lambda n: -(risks[n].probability if n in risks else 0)):
        loss, risk = losses.get(name), risks.get(name)
        print(f"{name:<20} "
              f"{f'{loss.seconds:.1f}s' if loss else '—':>9} {loss.stops if loss else 0:>6}   "
              f"{risk.races if risk else 0:>6} "
              f"{f'{risk.share_of_races:.0%}' if risk else '—':>7} "
              f"{f'{risk.probability:.2f}' if risk else '—':>7} "
              f"{f'{risk.median_laps_lost:.1f}' if risk else '—':>10}")
    print("\nSC/VSC is the raw share of races neutralised; shrunk pulls it toward the league")
    print("average by four races, so three-from-three does not read as certainty.")
    return 0


def cmd_circuit(args) -> int:
    con = connect()
    name = circuit_model.canonical_circuit(args.name)
    laps = _race_laps(con)
    here = laps[circuit_model.canonical_circuit(laps["location"]) == name]
    if here.empty:
        print(f"no races at '{args.name}' in the lake at {config.LAKE_DIR}")
        return 1

    sessions = con.sql("select session_key, location from sessions where session='R'").df()
    track_status = con.sql("select session_key, t, status from track_status").df()
    loss = next((p for p in circuit_model.pit_loss(laps) if p.circuit == name), None)
    risk = next((r for r in circuit_model.safety_car_risk(track_status, sessions, laps) if r.circuit == name), None)

    print(f"{name}\n")
    if loss:
        print(f"  pit lane costs      {loss.seconds:.1f}s  (± {loss.spread_s:.1f}s, {loss.stops} green-flag stops, "
              f"{loss.seasons} seasons)")
    if risk:
        print(f"  neutralised         {risk.share_of_races:.0%} of {risk.races} races, "
              f"{risk.probability:.2f} allowing for the short history")
        print(f"  when it happens     {risk.median_laps_lost:.1f} laps under SC or VSC")

    print("\n  races in the lake:")
    for year, group in here.groupby("year"):
        stops = group.groupby("driver_number")["is_pit_in_lap"].sum()
        compounds = group[group["compound"].notna()].groupby("compound").size().sort_values(ascending=False)
        share = ", ".join(f"{c.lower()} {100 * n / compounds.sum():.0f}%" for c, n in compounds.items())
        print(f"    {year}  {int(group['lap_number'].max())} laps, "
              f"{stops.mean():.2f} stops per driver, {share}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    pace_parser = commands.add_parser("pace", help="fuel and tyre degradation per season")
    pace_parser.add_argument("--season", type=int, help="one season, listing each race")
    pace_parser.add_argument("--method", choices=["fuel", "lap-effects"], default="fuel",
                             help="fuel: models fuel explicitly. lap-effects: compares drivers at the "
                                  "same lap, absorbing fuel and track evolution whatever their shape")
    pace_parser.add_argument("--curved", action="store_true",
                             help="let degradation bend rather than run straight (lap-effects only)")
    pace_parser.set_defaults(handler=cmd_pace)

    following_parser = commands.add_parser("following", help="time lost in another car's wake, per season")
    following_parser.add_argument("--season", type=int)
    following_parser.set_defaults(handler=cmd_following)

    circuits_parser = commands.add_parser("circuits", help="pit loss and neutralisation risk, every circuit")
    circuits_parser.set_defaults(handler=cmd_circuits)

    strategy_parser = commands.add_parser("strategy", help="cheapest plans for one circuit")
    strategy_parser.add_argument("circuit")
    strategy_parser.add_argument("--season", type=int, default=2026, help="whose tyre behaviour to use")
    strategy_parser.add_argument("--laps", type=int, help="race distance; defaults to this circuit's usual")
    strategy_parser.add_argument("--scale", type=float, default=1.0,
                                 help="multiply measured degradation; 1.5 best reproduces real stop counts")
    strategy_parser.add_argument("--top", type=int, default=6)
    strategy_parser.add_argument("--step", type=int, default=1)
    strategy_parser.add_argument("--safety-car", action="store_true",
                                 help="simulate races with safety cars instead of assuming green throughout")
    strategy_parser.add_argument("--runs", type=int, default=600, help="simulated races per plan")
    strategy_parser.set_defaults(handler=cmd_strategy)

    race_parser = commands.add_parser("race", help="simulate the field and compare plans for one car")
    race_parser.add_argument("circuit")
    race_parser.add_argument("--season", type=int, default=2026)
    race_parser.add_argument("--laps", type=int, help="race distance; defaults to this circuit's usual")
    race_parser.add_argument("--grid", type=int, default=8, help="grid slot of the car being advised")
    race_parser.add_argument("--cars", type=int, default=20)
    race_parser.add_argument("--runs", type=int, default=300, help="simulated races per plan")
    race_parser.add_argument("--plans", type=int, default=10,
                             help="how many of the cheapest plans to race, one per shape")
    race_parser.add_argument("--include-race", action="store_true",
                             help="fit on the race itself and races after it too: in-sample, "
                                  "for comparison only")
    race_parser.add_argument("--scale", type=float, default=1.5,
                             help="multiply measured degradation; 1.5 matches real stop counts")
    race_parser.add_argument("--driver", help="advise this driver, from the slot they started")
    race_parser.add_argument("--new-tyres", action="store_true",
                             help="give the car new sets for every stint instead of the ones it "
                                  "actually had left")
    race_parser.set_defaults(handler=cmd_race)

    circuit_parser = commands.add_parser("circuit", help="everything known about one circuit")
    circuit_parser.add_argument("name")
    circuit_parser.set_defaults(handler=cmd_circuit)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
