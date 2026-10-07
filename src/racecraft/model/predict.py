"""
Sunday, predicted on Saturday night.

Two steps, each checked against races that have already been run.

**Each driver's race pace.** The weekend gives up to four signals per driver
(see `weekend`): qualifying gap, practice long runs, sprint pace, recent form.
Each is treated as a noisy reading of the driver's true race pace:

    signal = scale x pace + noise

and the scale and the noise of every signal are measured from past races,
against the pace each driver actually showed in that race. A driver's pace is
then the usual combination of the readings they have with what is believed
before any of them, the field's spread: a signal that is missing simply adds
nothing, readings that agree narrow the answer, and how wide the answer stays
is measured too, so the simulation is as unsure as the data says it should be.

**Sunday itself.** Those paces go into the race simulator (`race.py`) with the
grid, the circuit's pit lane, safety-car rate and overtaking, the season's tyre
wear, and retirements at the season's rate, and the race is run many times.
What comes out is a chance for each driver to win, finish on the podium and
score, and where they are expected to finish.

`backtest` replays every race since 2023 this way, each from what was known
before it, and scores the predictions against what happened beside two
baselines: the grid, which is hard to beat, and form.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from racecraft.model import race as race_model
from racecraft.model import race_inputs, strategy, weekend
from racecraft.model.places import _draw_field

log = logging.getLogger(__name__)

SIGNALS = weekend.SIGNALS
CALIBRATION_FILE = Path(__file__).with_name("prediction_weights.json")
DEFAULT_RUNS = 1000
# Field draws: stop laps are spread around the reference plan and redrawn this
# many times, so no prediction leans on one arbitrary set of stop laps.
FIELD_DRAWS = 5
# Bounds on a car's chance of not finishing, from the season so far.
RETIRE_FLOOR, RETIRE_CAP = 0.04, 0.25
# Below this, a measured spread is a fluke of few readings, not real certainty.
MIN_PACE_SD = 0.10
# Seconds a lap either side of the field's median. Beyond it a reading is a
# wet session, a crash in Q1 or a fit that failed, not pace: it is held at the
# limit, in calibration and prediction alike, so one such reading cannot
# outweigh a season of ordinary ones.
SIGNAL_CLIP_S = 2.5


@dataclass
class Calibration:
    """What each signal is worth, measured against races already run."""
    scale: dict[str, float]          # signal = scale x pace + noise
    noise_sd: dict[str, float]
    prior_sd: float                  # the spread of race pace across a field
    inflate: float                   # widens the answer so its stated uncertainty is honest
    rows: dict[str, int] = field(default_factory=dict)
    fitted_on: list[str] = field(default_factory=list)
    chances: dict = field(default_factory=dict, repr=False)    # the grid baseline's, for a replay only

    def as_dict(self) -> dict:
        return {"scale": {k: round(v, 4) for k, v in self.scale.items()},
                "noise_sd": {k: round(v, 4) for k, v in self.noise_sd.items()},
                "prior_sd": round(self.prior_sd, 4), "inflate": round(self.inflate, 4),
                "rows": self.rows, "fitted_on": self.fitted_on}

    @classmethod
    def from_dict(cls, data: dict) -> Calibration:
        return cls(scale=data["scale"], noise_sd=data["noise_sd"], prior_sd=data["prior_sd"],
                   inflate=data["inflate"], rows=data.get("rows", {}), fitted_on=data.get("fitted_on", []))


def fit_calibration(rows: pd.DataFrame, fitted_on: list[str] | None = None) -> Calibration:
    """
    Measure each signal against the pace drivers actually showed. `rows` has a
    column per signal and `actual_s`, one row per driver per race.
    """
    rows = clipped(rows)
    actual = rows["actual_s"].dropna()
    prior_sd = float(actual.std())
    scale, noise, counts = {}, {}, {}
    for signal in SIGNALS:
        if signal not in rows:
            continue
        pair = rows[[signal, "actual_s"]].dropna()
        if len(pair) < 30:
            continue
        x, y = pair["actual_s"].to_numpy(), pair[signal].to_numpy()
        beta = float((x * y).sum() / (x * x).sum())          # through the origin: both are centred
        resid = y - beta * x
        if beta <= 0.05:
            continue                                          # says nothing about race pace
        scale[signal], noise[signal], counts[signal] = beta, float(resid.std()), int(len(pair))
    cal = Calibration(scale=scale, noise_sd=noise, prior_sd=prior_sd, inflate=1.0, rows=counts,
                      fitted_on=fitted_on or [])
    # How wide the answers really are: on the same rows, the squared error
    # against the stated variance. Readings are not truly independent (a quick
    # car is quick in qualifying and in form), so the plain combination is
    # overconfident; this is the correction, measured rather than assumed.
    est = combine(rows, cal, inflate=False)
    z = ((rows["actual_s"] - est["pace"]) / est["sd"]).dropna()
    cal.inflate = float(max(1.0, (z ** 2).mean())) if len(z) else 1.0
    return cal


def combine(table: pd.DataFrame, cal: Calibration, inflate: bool = True) -> pd.DataFrame:
    """Each driver's race pace (relative to the field median) and how sure it is."""
    table = clipped(table)
    precision = np.full(len(table), 1.0 / cal.prior_sd ** 2)
    weighted = np.zeros(len(table))
    for signal, beta in cal.scale.items():
        if signal not in table:
            continue
        values = table[signal].to_numpy(dtype=float)
        have = np.isfinite(values)
        noise = cal.noise_sd[signal] ** 2
        precision = precision + np.where(have, beta * beta / noise, 0.0)
        weighted = weighted + np.where(have, beta * values / noise, 0.0)
    pace = weighted / precision
    variance = 1.0 / precision * (cal.inflate if inflate else 1.0)
    return pd.DataFrame({"pace": pace, "sd": np.maximum(np.sqrt(variance), MIN_PACE_SD)}, index=table.index)


def clipped(table: pd.DataFrame) -> pd.DataFrame:
    """Every signal, and the actual pace, held within `SIGNAL_CLIP_S` of the median."""
    out = table.copy()
    for column in (*SIGNALS, "actual_s"):
        if column in out:
            out[column] = out[column].clip(-SIGNAL_CLIP_S, SIGNAL_CLIP_S)
    return out


def load_calibration(path: Path = CALIBRATION_FILE) -> Calibration:
    return Calibration.from_dict(json.loads(path.read_text(encoding="utf-8")))


def retire_rate(con, year: int, rnd: int) -> float:
    """The share of starters who did not finish, in the season's earlier races (or last season's)."""
    for season, before in ((year, rnd), (year - 1, 99)):
        df = con.execute("""select r.classified_position from results r join sessions s using (session_key)
                            where s."session" = 'R' and s.year = ? and s.round < ?""", [season, before]).df()
        if len(df) >= 40:
            out = ~df["classified_position"].astype(str).str.strip().str.isdigit()
            return float(np.clip(out.mean(), RETIRE_FLOOR, RETIRE_CAP))
    return 0.10


@dataclass
class Prediction:
    race_key: str
    event_name: str
    year: int
    round: int
    drivers: list[dict]
    basis: dict
    made_at: str

    def as_dict(self) -> dict:
        return {"race_key": self.race_key, "event_name": self.event_name, "year": self.year,
                "round": self.round, "drivers": self.drivers, "basis": self.basis, "made_at": self.made_at}


def race(con, session_key: str, *, runs: int = DEFAULT_RUNS, calibration: Calibration | None = None,
         seed: int = 7) -> Prediction:
    """
    Predict the race of the weekend `session_key` belongs to, from what was
    known before it started. The race need not have been run.
    """
    cal = calibration or load_calibration()
    ev = weekend.evidence(con, session_key)
    race_key = ev.race_key
    if ev.table["grid"].lt(weekend.BACK_OF_GRID).sum() < 2:
        raise race_inputs.NotEnoughData("no grid yet: a prediction is made once qualifying is in")
    paces = combine(ev.table, cal)
    inputs = race_inputs.build(con, ev.location, ev.year, session_key=race_key if ev.race_in_lake else None,
                               lenient=True, weekend=(ev.year, ev.round))
    rate = retire_rate(con, ev.year, ev.round)

    plans = strategy.best_plans(inputs.total_laps, inputs.degradation, inputs.pit_loss_s,
                                compound_offset_s=inputs.compound_offset_s, min_stops=inputs.min_stops)
    reference = plans[0].plan
    table = ev.table.join(paces)
    order = table.sort_values("grid").index.tolist()
    quickest = float(table["pace"].min())
    rng = np.random.default_rng(seed)
    positions: dict[int, list[int]] = {int(d): [] for d in order}
    retired: dict[int, list[bool]] = {int(d): [] for d in order}
    per_draw = max(1, runs // FIELD_DRAWS)
    for _ in range(FIELD_DRAWS):
        field_plans = _draw_field(reference, len(order), inputs.total_laps, rng)
        cars = [race_model.Car(driver_number=int(d), abbreviation=str(table.at[d, "abbreviation"]),
                               pace_s=inputs.quickest_lap_s + float(table.at[d, "pace"]) - quickest,
                               grid=slot, plan=field_plans[slot - 1])
                for slot, d in enumerate(order, start=1)]
        result = race_model.simulate(cars, inputs.total_laps, inputs.degradation, inputs.pit_loss_s,
                                     inputs.neutralisation, inputs.passes_per_lap,
                                     compound_offset_s=inputs.compound_offset_s, runs=per_draw, rng=rng,
                                     following=inputs.following_table,
                                     pace_sd={int(d): float(table.at[d, "sd"]) for d in order},
                                     retire_rate=rate)
        for driver, finishes in result.positions.items():
            positions[driver].extend(int(p) for p in finishes)
            retired[driver].extend(bool(r) for r in result.retired[driver])

    drivers = []
    for d in order:
        finishes = np.array(positions[int(d)])
        out = np.array(retired[int(d)])
        classified = finishes[~out] if (~out).any() else finishes
        drivers.append({
            "driver_number": int(d),
            "abbreviation": str(table.at[d, "abbreviation"]),
            "team_name": None if pd.isna(table.at[d, "team_name"]) else str(table.at[d, "team_name"]),
            "team_color": None if pd.isna(table.at[d, "team_color"]) else str(table.at[d, "team_color"]),
            "grid": int(table.at[d, "grid"]),
            "win": round(float((finishes == 1).mean()), 4),
            "podium": round(float((finishes <= 3).mean()), 4),
            "points": round(float((finishes <= 10).mean()), 4),
            "expected": round(float(finishes.mean()), 2),
            "dnf": round(float(out.mean()), 4),
            # The likely range if the car finishes; retiring is the separate chance above.
            "p10": int(np.percentile(classified, 10)),
            "p50": int(np.median(classified)),
            "p90": int(np.percentile(classified, 90)),
            "pace_s": round(float(table.at[d, "pace"]), 3),
            "pace_sd": round(float(table.at[d, "sd"]), 3),
            "signals": {s: (None if pd.isna(table.at[d, s]) else round(float(table.at[d, s]), 3)) for s in SIGNALS},
        })
    drivers.sort(key=lambda row: row["expected"])
    basis = {
        "sessions": ev.sessions_used,
        "form_races": ev.form_races,
        "grid_source": ev.grid_source,
        "retire_rate": round(rate, 3),
        "runs": per_draw * FIELD_DRAWS,
        "reference_plan": str(reference),
        "calibration": cal.as_dict(),
        "notes": ev.notes + inputs.notes,
    }
    return Prediction(race_key=race_key, event_name=ev.event_name, year=ev.year, round=ev.round,
                      drivers=drivers, basis=basis, made_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))


# ------------------------------------------------------------------ scoring

def actual_finish(con, race_key: str) -> pd.Series:
    """
    Where each driver was classified, retirements included. A driver with no
    position at all (disqualified, or excluded) goes behind everyone who has one.
    """
    df = con.execute("select driver_number, position from results where session_key = ?", [race_key]).df()
    df = df.dropna(subset=["driver_number"])
    if df.empty:
        return pd.Series(dtype=int)
    back = df["position"].max() if df["position"].notna().any() else 0
    df["position"] = df["position"].fillna(back + 1).rank(method="first")
    return pd.Series(df["position"].astype(int).values, index=df["driver_number"].astype(int).values)


def score(prediction: dict | Prediction, finish: pd.Series) -> dict:
    """How a prediction did against the race: order, winner, podium, and how honest its chances were."""
    rows = (prediction.as_dict() if isinstance(prediction, Prediction) else prediction)["drivers"]
    table = pd.DataFrame(rows).set_index("driver_number")
    table = table[table.index.isin(finish.index)]
    actual = finish.loc[table.index]
    predicted_order = table["expected"].rank(method="first")
    winner = int(actual.idxmin())
    top3 = set(actual.nsmallest(3).index)
    won = (table.index == winner).astype(float)
    on_podium = table.index.isin(top3).astype(float)
    return {
        "rho": float(spearmanr(predicted_order, actual).statistic),
        "winner_hit": bool(int(table["expected"].idxmin()) == winner),
        "podium_hits": len(set(table["expected"].nsmallest(3).index) & top3),
        "brier_win": float(((table["win"] - won) ** 2).sum()),
        "brier_podium": float(((table["podium"] - on_podium) ** 2).sum()),
        "logloss_win": float(-np.log(max(float(table.at[winner, "win"]) if winner in table.index else 0.0, 1e-3))),
    }


def grid_score(grid: pd.Series, finish: pd.Series, chances: dict[int, tuple[float, float]]) -> dict:
    """The same scores for "finish where you start", with each slot's historical chances."""
    common = grid.index.intersection(finish.index)
    grid, actual = grid.loc[common], finish.loc[common]
    winner = int(actual.idxmin())
    top3 = set(actual.nsmallest(3).index)
    win_p = grid.map(lambda slot: chances.get(int(slot), (0.0, 0.0))[0])
    podium_p = grid.map(lambda slot: chances.get(int(slot), (0.0, 0.0))[1])
    return {
        "rho": float(spearmanr(grid, actual).statistic),
        "winner_hit": bool(int(grid.idxmin()) == winner),
        "podium_hits": len(set(grid.nsmallest(3).index) & top3),
        "brier_win": float(((win_p - (grid.index == winner)) ** 2).sum()),
        "brier_podium": float(((podium_p - grid.index.isin(top3)) ** 2).sum()),
        "logloss_win": float(-np.log(max(float(win_p.get(winner, 0.0)), 1e-3))),
    }


def slot_chances(con, years: list[int]) -> dict[int, tuple[float, float]]:
    """How often each grid slot won and reached the podium, in the given seasons (smoothed)."""
    df = con.execute(f"""select r.grid_position g, r.position p from results r join sessions s using (session_key)
                         where s."session" = 'R' and s.year in ({",".join(str(int(y)) for y in years)})
                         and r.grid_position > 0""").df()
    out = {}
    for slot in range(1, 23):
        here = df[df["g"] == slot]
        n = len(here)
        out[slot] = (((here["p"] == 1).sum() + 0.05) / (n + 1), ((here["p"] <= 3).sum() + 0.15) / (n + 1))
    return out


# ------------------------------------------------------------------ replay

def race_keys(con, years: list[int] | None = None) -> list[str]:
    """Every race in the lake that has a result, in calendar order."""
    df = con.execute("""select distinct s.session_key, s.year, s.round from sessions s join results r using (session_key)
                        where s."session" = 'R' order by s.year, s.round""").df()
    if years:
        df = df[df["year"].isin(years)]
    return df["session_key"].tolist()


def training_rows(con, keys: list[str]) -> pd.DataFrame:
    """One row per driver per race: the weekend's signals, and the pace they actually showed."""
    frames = []
    for key in keys:
        try:
            ev = weekend.evidence(con, key)
        except Exception as exc:                 # a weekend the lake cannot read is skipped, not fatal
            log.warning("no evidence for %s: %s", key, exc)
            continue
        actual = weekend.actual_pace(con, key)
        table = ev.table[list(SIGNALS)].copy()
        table["actual_s"] = actual.reindex(table.index)
        table["race_key"], table["year"] = key, ev.year
        frames.append(table)
    return pd.concat(frames) if frames else pd.DataFrame(columns=[*SIGNALS, "actual_s", "race_key", "year"])


@dataclass
class RaceScore:
    race_key: str
    year: int
    model: dict
    grid: dict
    form: dict | None
    skipped: str | None = None


def form_score(evidence_table: pd.DataFrame, finish: pd.Series) -> dict | None:
    """Order by recent form alone (drivers without any go to the back, in grid order)."""
    table = evidence_table[evidence_table.index.isin(finish.index)]
    if table["form_s"].notna().sum() < 5:
        return None
    key = table["form_s"].fillna(table["form_s"].max() + 1) + table["grid"] * 1e-3
    order = key.rank(method="first")
    actual = finish.loc[table.index]
    winner, top3 = int(actual.idxmin()), set(actual.nsmallest(3).index)
    return {"rho": float(spearmanr(order, actual).statistic),
            "winner_hit": bool(int(order.idxmin()) == winner),
            "podium_hits": len(set(order.nsmallest(3).index) & top3)}


def backtest(con, *, runs: int = 500, holdout: int = 2026, progress=None,
             seasons: list[int] | None = None) -> list[RaceScore]:
    """
    Predict every race from what was known before it, and score it.

    Each season before `holdout` is predicted with the signals' worth measured
    on the other seasons before `holdout`; `holdout` itself with all of them.
    `seasons` predicts only those, with the same calibrations.
    """
    keys = race_keys(con)
    rows = training_rows(con, keys)
    in_lake = sorted(int(y) for y in rows["year"].unique())
    train_years = [y for y in in_lake if y < holdout]
    calibrations = {}
    for year in in_lake:
        fit_years = [y for y in train_years if y != year] if year in train_years else train_years
        calibrations[year] = fit_calibration(rows[rows["year"].isin(fit_years)], [str(y) for y in fit_years])
        chances = slot_chances(con, fit_years)
        calibrations[year].chances = chances    # the grid baseline sees the same seasons
    scores = []
    if seasons:
        keys = [k for k in keys if int(k[:4]) in seasons]
    for i, key in enumerate(keys):
        year = int(key[:4])
        finish = actual_finish(con, key)
        try:
            prediction = race(con, key, runs=runs, calibration=calibrations[year])
            ev = weekend.evidence(con, key)
        except (race_inputs.NotEnoughData, ValueError, KeyError) as exc:
            scores.append(RaceScore(key, year, {}, {}, None, skipped=str(exc)))
            continue
        grid = ev.table["grid"]
        scores.append(RaceScore(key, year, score(prediction, finish),
                                grid_score(grid[grid < weekend.BACK_OF_GRID], finish, calibrations[year].chances),
                                form_score(ev.table, finish)))
        if progress:
            progress(i + 1, len(keys), key)
    return scores


def summarise(scores: list[RaceScore], holdout: int = 2026) -> pd.DataFrame:
    """Season by season, model against grid and form."""
    out = []
    done = [s for s in scores if not s.skipped]
    for label, group in [(str(y), [s for s in done if s.year == y]) for y in sorted({s.year for s in done})] + \
            [(f"all before {holdout}", [s for s in done if s.year < holdout])]:
        if not group:
            continue
        row = {"season": label, "races": len(group)}
        for name in ("model", "grid"):
            part = pd.DataFrame([getattr(s, name) for s in group])
            row[f"{name}_rho"] = part["rho"].mean()
            row[f"{name}_winner"] = part["winner_hit"].mean()
            row[f"{name}_podium"] = part["podium_hits"].mean()
            row[f"{name}_brier_win"] = part["brier_win"].mean()
            row[f"{name}_brier_podium"] = part["brier_podium"].mean()
            row[f"{name}_logloss_win"] = part["logloss_win"].mean()
        forms = pd.DataFrame([s.form for s in group if s.form])
        if not forms.empty:
            row["form_rho"], row["form_winner"], row["form_podium"] = (
                forms["rho"].mean(), forms["winner_hit"].mean(), forms["podium_hits"].mean())
        out.append(row)
    return pd.DataFrame(out)
