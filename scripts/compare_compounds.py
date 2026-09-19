"""
Does knowing the real compound (C1-C6) predict tyre wear better than the label?

The strategy model learns one wear rate per label per season: a "medium" is a
medium wherever it runs. But Pirelli brings different rubber to different
tracks — the medium is a C2 at Silverstone and a C5 at Baku — so a label mixes
compounds. The obvious fix is to learn wear per C-number instead.

It is not obviously right. Pirelli chooses each weekend's three compounds so
that hard, medium and soft behave alike wherever they run: a hard C1 at a
severe track and a hard C4 at a gentle one are meant to wear the same. If that
works, the label already carries the information and the C-number does worse,
because it pools a C3 from Suzuka, where it was the soft, with a C3 from Baku,
where it was the hard.

So both are tried, out of sample. For every race, each label's wear is
predicted from that season's earlier races only, five ways, and scored against
what the race itself measured:

* label     pool earlier races' wear for the same label (what the model does now)
* compound  pool earlier races' wear for the same C-number, whatever its label
* both      the label's pool, shifted by how much softer or harder this race's
            compound is than the label usually is, at a rate fitted on the
            earlier races
* circuit   the label's pool, pulled toward what the same label did at the
            same circuit the season before, when there was a visit
* heat      the label's pool, shifted by how much hotter or cooler the track
            ran than at the earlier races, at a rate fitted on them. Track
            temperature is known before a race starts, so this is fair.

    python scripts/compare_compounds.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from racecraft.api import insight
from racecraft.model import pace
from racecraft.store.db import connect

from racecraft.model.compounds import TABLE
# A race whose own wear figure is this uncertain is not a fair thing to score against.
MAX_TRUTH_ERROR = 0.03
MIN_PRIOR = 3
# How far a single earlier visit pulls the season's figure toward itself.
CIRCUIT_WEIGHT = 0.5


def compounds() -> dict[tuple[int, int], dict[str, int]]:
    table = pd.read_csv(TABLE).dropna(subset=["round"])
    return {(int(r.year), int(r.round)): {"HARD": int(r.hard[1:]), "MEDIUM": int(r.medium[1:]),
                                          "SOFT": int(r.soft[1:])}
            for r in table.itertuples()}


def _pool(pairs: list[tuple[float, float]]) -> float | None:
    """Precision-weighted mean of (value, standard error) pairs."""
    pairs = [(v, e) for v, e in pairs if e and np.isfinite(e) and e > 0]
    if not pairs:
        return None
    w = np.array([1 / e**2 for _, e in pairs])
    return float(np.dot(w, [v for v, _ in pairs]) / w.sum())


def main() -> int:
    con = connect()
    nominated = compounds()
    rows = []
    location = dict(con.sql("""select session_key, location from sessions where "session" = 'R'""").fetchall())
    heat = dict(con.sql("""select w.session_key, median(w.track_temp) from weather w
                           join sessions s using (session_key) where s."session" = 'R'
                           group by w.session_key""").fetchall())
    from racecraft.model import circuit as circuit_model
    for year in (2023, 2024, 2025, 2026):
        fits = insight._season_fits(year)
        rounds = dict(con.sql(f"""select session_key, round from sessions
                                  where year = {year} and "session" = 'R'""").fetchall())
        last_year = insight._season_fits(year - 1) if year > 2023 else None
        visits = {}
        if last_year is not None:
            for k, m in last_year.by_session.items():
                visits[str(circuit_model.canonical_circuit(location[k]))] = m
        ordered = sorted(fits.by_session, key=lambda k: rounds[k])
        for i, key in enumerate(ordered):
            target = fits.by_session[key]
            here = nominated[(year, rounds[key])]
            prior = [(fits.by_session[k], nominated[(year, rounds[k])]) for k in ordered[:i]]
            if len(prior) < MIN_PRIOR:
                continue
            label_pool = {c: v for c, (v, _) in pace.combine([m for m, _ in prior]).items()}

            # How wear moves with softness within a label, from the earlier races:
            # slope of wear on (C-number minus that label's usual C-number).
            usual = {c: np.mean([n[c] for _, n in prior]) for c in pace.DRY_COMPOUNDS}
            xs, ys, ws = [], [], []
            for model, n in prior:
                for c in pace.DRY_COMPOUNDS:
                    v, e = model.degradation_s_per_lap.get(c), model.standard_errors.get(f"deg_{c}")
                    if v is None or not e or not np.isfinite(e) or c not in label_pool:
                        continue
                    xs.append(n[c] - usual[c]); ys.append(v - label_pool[c]); ws.append(1 / e**2)
            xs, ys, ws = map(np.array, (xs, ys, ws))
            slope = float(np.sum(ws * xs * ys) / np.sum(ws * xs * xs)) if np.sum(ws * xs * xs) > 0 else 0.0

            # The same for track temperature: wear against heat, from the earlier races.
            temps = [heat.get(k) for k in ordered[:i]]
            known_temps = [t for t in temps if t is not None]
            usual_heat = float(np.mean(known_temps)) if known_temps else None
            hx, hy, hw = [], [], []
            for (model, _), t in zip(prior, temps):
                if t is None or usual_heat is None:
                    continue
                for c in pace.DRY_COMPOUNDS:
                    v, e = model.degradation_s_per_lap.get(c), model.standard_errors.get(f"deg_{c}")
                    if v is None or not e or not np.isfinite(e) or c not in label_pool:
                        continue
                    hx.append(t - usual_heat)
                    hy.append(v - label_pool[c])
                    hw.append(1 / e**2)
            hx, hy, hw = map(np.array, (hx, hy, hw))
            spread = np.sum(hw * hx * hx) if len(hx) else 0.0
            per_degree = float(np.sum(hw * hx * hy) / spread) if spread > 0 else 0.0
            race_heat = heat.get(key)

            for c in pace.DRY_COMPOUNDS:
                truth = target.degradation_s_per_lap.get(c)
                error = target.standard_errors.get(f"deg_{c}")
                if truth is None or not error or not np.isfinite(error) or error > MAX_TRUTH_ERROR:
                    continue
                if c not in label_pool:
                    continue
                same_c = [(m.degradation_s_per_lap[l], m.standard_errors.get(f"deg_{l}"))
                          for m, n in prior for l in pace.DRY_COMPOUNDS
                          if n[l] == here[c] and l in m.degradation_s_per_lap]
                by_c = _pool(same_c)
                visit = visits.get(str(circuit_model.canonical_circuit(location[key])))
                was = visit.degradation_s_per_lap.get(c) if visit is not None else None
                rows.append({
                    "circuit_pred": (label_pool[c] if was is None
                                     else (1 - CIRCUIT_WEIGHT) * label_pool[c] + CIRCUIT_WEIGHT * was),
                    "circuit_known": was is not None,
                    "year": year, "race": fits.names[key], "label": c, "compound": f"C{here[c]}",
                    "truth": truth, "truth_error": error,
                    "label_pred": label_pool[c],
                    "compound_pred": by_c if by_c is not None else label_pool[c],
                    "compound_fell_back": by_c is None,
                    "both_pred": label_pool[c] + slope * (here[c] - usual[c]),
                    "heat_pred": (label_pool[c] if race_heat is None or usual_heat is None
                                  else label_pool[c] + per_degree * (race_heat - usual_heat)),
                    "per_degree": per_degree, "track_temp": race_heat,
                    "slope": slope,
                })

    df = pd.DataFrame(rows)
    print(f"{len(df)} label-races scored, {len(df.groupby(['year', 'race']))} races, "
          f"each predicted from its own season's earlier races only\n")
    print("mean absolute error in wear, s/lap per lap of tyre age:")
    for name in ("label", "compound", "both", "circuit", "heat"):
        err = (df[f"{name}_pred"] - df.truth).abs()
        print(f"  {name:<9} {err.mean():.4f}   median {err.median():.4f}")
    print(f"  noise     {df.truth_error.mean():.4f}   (the races' own standard error: no method can beat this much)")
    print(f"\ncompound pool had no earlier race with the same C-number {df.compound_fell_back.sum()} times "
          "(label used instead)")
    print(f"softness slope, last fitted: {df.slope.iloc[-1]:+.4f} s/lap per step softer")
    print(f"heat slope, last fitted: {df.per_degree.iloc[-1] * 10:+.4f} s/lap per 10 degC of track temperature")
    hot = df[df.track_temp.notna()]
    missed = hot.truth - hot.label_pred
    print(f"correlation of what the label missed with track temperature: "
          f"{np.corrcoef(missed, hot.track_temp)[0, 1]:+.2f}")
    print()

    print("by season:")
    by = df.assign(label_err=(df.label_pred - df.truth).abs(), compound_err=(df.compound_pred - df.truth).abs(),
                   both_err=(df.both_pred - df.truth).abs(), circuit_err=(df.circuit_pred - df.truth).abs(),
                   heat_err=(df.heat_pred - df.truth).abs())
    print(by.groupby("year")[["label_err", "compound_err", "both_err", "circuit_err", "heat_err"]]
          .mean().round(4).to_string())
    known = by[by.circuit_known]
    print()
    print(f"where last season's visit exists ({len(known)} label-races): "
          f"label {known.label_err.mean():.4f}, circuit {known.circuit_err.mean():.4f}")
    print("\nwhere the compound and the label disagree most (the label's usual C-number is far off):")
    wins = (by.label_err - by.both_err)
    print(f"  'both' beats 'label' on {int((wins > 0).sum())} of {len(by)} label-races")
    return 0


if __name__ == "__main__":
    sys.exit(main())
