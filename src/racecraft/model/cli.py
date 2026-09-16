"""
Run the models over the lake: `racecraft-analyse`.

    racecraft-analyse pace                 # degradation and fuel, per season
    racecraft-analyse pace --season 2026   # one season, with each race listed
    racecraft-analyse circuits             # pit loss and neutralisation risk
    racecraft-analyse circuit Baku         # everything known about one circuit

Every number the README quotes comes from these commands, so anyone can
reproduce them rather than taking them on trust.
"""

from __future__ import annotations

import argparse
import sys

import pandas as pd

from racecraft import config
from racecraft.model import circuit as circuit_model
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

    circuits_parser = commands.add_parser("circuits", help="pit loss and neutralisation risk, every circuit")
    circuits_parser.set_defaults(handler=cmd_circuits)

    circuit_parser = commands.add_parser("circuit", help="everything known about one circuit")
    circuit_parser.add_argument("name")
    circuit_parser.set_defaults(handler=cmd_circuit)

    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
