"""
Everything the race simulator needs, taken only from races that had finished.

The simulator used to assemble its inputs from the whole lake, and for a race
that has already happened that meant reading the answer. `race Baku --season
2025` fitted tyre wear on every 2025 race including Baku 2025 itself, took the
pace ladder from the season's last five races — for a mid-season race, races
that came *after* it — and measured pit loss, safety-car risk and overtaking at
Baku from every Baku race including the one being simulated.

Here there is one cutoff, and everything respects it. If the circuit has a race
in the season being run, that race is the one being analysed and only races
that started before it are used, for every quantity. If it has not been run yet
— the forecasting case, such as Baku 2026 before 26 September — nothing needs
holding out and everything finished is used.

That rule costs something: the first race at a circuit has no earlier race to
measure its pit lane from, and an early-season race has few same-season races
to fit tyres on. Those fail loudly instead of quietly borrowing from the future.
`include_race` restores the old behaviour for anyone who wants it, and says so.

The terminal command and the interface both build their inputs here, so the two
cannot quietly disagree about what the simulator was told.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from racecraft.model import circuit as circuit_model
from racecraft.model import pace as pace_model
from racecraft.model import race as race_model
from racecraft.model import traffic
from racecraft.model.simulate import Neutralisation

log = logging.getLogger(__name__)

DEFAULT_SCALE = 1.5          # calibrated against 76 dry races; see scripts/calibrate_scale.py
DEFAULT_CARS = 20
LADDER_RACES = 5             # the most recent races a pace ladder is averaged over
MIN_LAPS_TO_FIT = 200
FALLBACK_PERIODS = 1.27      # league-wide neutralisations per race, when a circuit has no history


class NotEnoughData(ValueError):
    """What the rule allows is too little to simulate from. The message says what."""


# One race's fit never changes once the race is in the lake, but every race
# after it asks for it again: studying race k refits races 1..k-1, so a season's
# backtest is quadratic without this. Keyed by lake as well as session, because
# the same key in a different lake is different data.
_race_cache: dict[tuple[str, str], tuple] = {}


def _race_fit(session_key: str, race_laps: pd.DataFrame):
    """(lap-effects model or None, wake residuals or None) for one race, cached."""
    from racecraft import config

    key = (str(config.LAKE_DIR.resolve()), session_key)
    if key not in _race_cache:
        model = None
        clean = pace_model.clean_race_laps(race_laps)
        if len(clean) >= MIN_LAPS_TO_FIT:
            try:
                model = pace_model.fit_lap_effects(clean)
            except (pace_model.Confounded, ValueError):
                model = None
        _race_cache[key] = (model, traffic.race_residuals(race_laps))
    return _race_cache[key]


@dataclass
class RaceInputs:
    """What a simulation of one race was told, and where each number came from."""
    circuit: str
    season: int
    event_name: str
    total_laps: int
    held_out: bool                  # the race itself, and anything later, was excluded
    target_session: str | None      # the race being analysed, if it has happened
    cutoff: pd.Timestamp | None
    fitted_on: list[str]
    degradation: dict[str, float]           # scaled, as the simulator uses it
    degradation_measured: dict[str, float]  # unscaled
    scale: float
    compound_offset_s: dict[str, float]
    pit_loss_s: float
    pit_stops: int
    periods_per_race: float
    neutralisation: Neutralisation
    passes_per_race: float
    passes_per_lap: float
    ladder: list[float]
    quickest_lap_s: float
    following: traffic.FollowingTable
    cars: int = DEFAULT_CARS
    notes: list[str] = field(default_factory=list)

    @property
    def following_table(self):
        """The table the simulator reads, or None to take its 2026 fallback."""
        return self.following.penalties if self.following.measured else None

    def as_dict(self) -> dict:
        return {
            "circuit": self.circuit,
            "season": self.season,
            "event_name": self.event_name,
            "total_laps": self.total_laps,
            "held_out": self.held_out,
            "target_session": self.target_session,
            "cutoff": None if self.cutoff is None else str(self.cutoff),
            "fitted_on": self.fitted_on,
            "fitted_on_count": len(self.fitted_on),
            "degradation_used": {c: round(v, 4) for c, v in self.degradation.items()},
            "degradation_measured": {c: round(v, 4) for c, v in self.degradation_measured.items()},
            "scale": self.scale,
            "pit_loss_s": round(self.pit_loss_s, 2),
            "pit_stops": self.pit_stops,
            "periods_per_race": round(self.periods_per_race, 2),
            "passes_per_race": round(self.passes_per_race, 1),
            "following": self.following.as_dict(),
            "notes": self.notes,
        }


def build(con, circuit: str, season: int, *, scale: float = DEFAULT_SCALE,
          cars: int = DEFAULT_CARS, include_race: bool = False,
          session_key: str | None = None, total_laps: int | None = None) -> RaceInputs:
    """
    Assemble the simulator's inputs for the race at `circuit` in `season`.

    `session_key` names the race directly, which the interface does; otherwise
    it is found from the circuit and the season. Raises `NotEnoughData` when the
    races before the cutoff cannot support a simulation.
    """
    name = str(circuit_model.canonical_circuit(circuit))
    sessions = con.sql("""select session_key, year, round, location, event_name, date_utc,
                                 total_laps from sessions where "session" = 'R'""").df()
    if sessions.empty:
        raise NotEnoughData("no races in the lake")
    sessions["circuit"] = circuit_model.canonical_circuit(sessions["location"])
    sessions["date_utc"] = pd.to_datetime(sessions["date_utc"], utc=True)

    if not session_key and not (sessions["circuit"] == name).any():
        raise NotEnoughData(f"no races at '{circuit}' in the lake")

    if session_key:
        target = sessions[sessions["session_key"] == session_key]
    else:
        # The latest race at this circuit in the season. A circuit visited twice
        # in one year is the later visit being asked about, and the earlier one is
        # then fair training data rather than the answer.
        target = sessions[(sessions["circuit"] == name) & (sessions["year"] == season)]
        target = target.sort_values("date_utc")
    target_row = target.iloc[-1] if not target.empty else None

    held_out = target_row is not None and not include_race
    cutoff = target_row["date_utc"] if held_out else None
    notes: list[str] = []
    if target_row is not None and include_race:
        notes.append("the race itself is included in its own inputs: in-sample, not a forecast")

    if cutoff is None:
        prior = sessions
    else:
        # Before the race means an earlier date, or the same date and an earlier
        # round — the round breaks a tie that real calendars never produce but
        # that would otherwise count a same-day race as neither before nor after.
        earlier = sessions["date_utc"] < cutoff
        same_day_earlier = ((sessions["date_utc"] == cutoff)
                            & (sessions["year"] == target_row["year"])
                            & (sessions["round"] < target_row["round"]))
        prior = sessions[earlier | same_day_earlier]
    prior_keys = set(prior["session_key"])

    laps = con.sql("""select l.*, s.location, s.year from laps l join sessions s using (session_key)
                      where s."session" = 'R'""").df()
    laps = laps[laps["session_key"].isin(prior_keys)]
    here = laps[circuit_model.canonical_circuit(laps["location"]) == name]

    # ---- the circuit: pit lane, safety cars, overtaking, pace, distance
    loss = next((p for p in circuit_model.pit_loss(laps) if p.circuit == name), None)
    if loss is None:
        raise NotEnoughData(
            f"no earlier race at {name} to measure its pit lane from"
            if held_out else f"not enough green-flag stops at {name} to measure its pit lane")

    status = con.sql("select session_key, t, status from track_status").df()
    status = status[status["session_key"].isin(prior_keys)]
    risk = next((r for r in circuit_model.safety_car_risk(
        status, prior[["session_key", "location"]], laps) if r.circuit == name), None)
    periods = risk.periods_per_race if risk else FALLBACK_PERIODS
    if risk is None:
        notes.append(f"no safety-car history at {name} before this race; league average used")

    if total_laps is None:
        if target_row is not None and pd.notna(target_row["total_laps"]):
            total_laps = int(target_row["total_laps"])       # scheduled, so known in advance
        elif not here.empty:
            total_laps = int(here.groupby("session_key")["lap_number"].max().median())
        else:
            raise NotEnoughData(f"race distance at {name} is not known")

    overtaking = circuit_model.passes_per_race(here)
    quickest = float(here["lap_time_s"].min())
    if not np.isfinite(quickest):
        raise NotEnoughData(f"no timed lap at {name} before this race")

    # ---- the season: tyres, compounds, the field's pace, the wake
    season_races = prior[prior["year"] == season].sort_values(["date_utc", "round"])
    residuals, models, fitted_on = [], [], []
    for _, race in season_races.iterrows():
        race_laps = laps[laps["session_key"] == race["session_key"]]
        if race_laps.empty:
            continue
        model, wake = _race_fit(str(race["session_key"]), race_laps)
        residuals.append(wake)
        if model is not None:
            models.append(model)
            fitted_on.append(str(race["event_name"]))
    if not models:
        raise NotEnoughData(
            f"no {season} race before this one to fit tyre wear on"
            if held_out else f"no fittable races in {season}")

    measured = {c: v[0] for c, v in pace_model.combine(models).items()}
    offsets = {
        c: float(np.median([m.compound_offset_s[c] for m in models if c in m.compound_offset_s]))
        for c in pace_model.DRY_COMPOUNDS if any(c in m.compound_offset_s for m in models)
    }

    # The most recent races *before the cutoff*: models are in date order, so
    # the tail is the latest ones that had already happened.
    recent = [sorted(m.driver_baseline_s.values()) for m in models[-LADDER_RACES:]
              if len(m.driver_baseline_s) >= 2]
    if not recent:
        raise NotEnoughData("no fitted driver pace to build a field from")
    width = min(len(r) for r in recent)
    ladder = list(np.mean(np.array([r[:width] for r in recent]), axis=0))

    following = traffic.summarise(residuals)
    if not following.measured:
        notes.append(f"wake penalty not measurable this early in {season} "
                     f"({following.detail}); the 2026 figure is used")

    return RaceInputs(
        circuit=name,
        season=season,
        event_name=str(target_row["event_name"]) if target_row is not None else name,
        total_laps=total_laps,
        held_out=held_out,
        target_session=None if target_row is None else str(target_row["session_key"]),
        cutoff=cutoff,
        fitted_on=fitted_on,
        degradation={c: v * scale for c, v in measured.items()},
        degradation_measured=measured,
        scale=scale,
        compound_offset_s=offsets,
        pit_loss_s=loss.seconds,
        pit_stops=loss.stops,
        periods_per_race=periods,
        neutralisation=Neutralisation.for_circuit(periods, total_laps),
        passes_per_race=overtaking,
        passes_per_lap=race_model.pass_probability(overtaking, total_laps, cars),
        ladder=ladder,
        quickest_lap_s=quickest,
        following=following,
        cars=cars,
        notes=notes,
    )


# ------------------------------------------------------------- the garage

def _safe(value: str) -> str:
    if not value.replace("_", "").isalnum():
        raise ValueError(f"bad session key '{value}'")
    return value


@dataclass
class Stock:
    """What one car had in the garage at the start of a race."""
    driver: str
    driver_number: int
    grid: int | None
    left: dict[str, dict]                  # compound -> {"new": n, "used": [laps, ...]}
    notes: list[str]

    @property
    def sets(self) -> int:
        return sum(held["new"] + len(held["used"]) for held in self.left.values())

    def as_dict(self) -> dict:
        return {
            "driver": self.driver,
            "driver_number": self.driver_number,
            "grid": self.grid,
            "left": {c: {"new": h["new"], "used": list(h["used"])} for c, h in self.left.items()},
            "sets": self.sets,
            "notes": self.notes,
        }


def field_stock(con, session_key: str | None = None, *, year: int | None = None,
                round_number: int | None = None, live_laps=None) -> dict[int, dict]:
    """
    What every car on the grid held at the start, by grid slot.

    One pass over the weekend, rather than one per car: the reconstruction is
    the expensive part and it is the same work for all twenty.
    """
    from racecraft.model import tyre_sets

    if session_key is not None:
        rows = con.sql(f"""select year, round from sessions
                           where session_key = '{_safe(session_key)}'""").df()
        if rows.empty:
            return {}
        year, rnd = int(rows.iloc[0]["year"]), int(rows.iloc[0]["round"])
    elif year is not None and round_number is not None:
        rnd = int(round_number)
    else:
        return {}
    entries = _classification(con, year, rnd)
    if entries.empty:
        entries = _qualifying_order(con, year, rnd)
    if entries.empty:
        return {}
    weekend = tyre_sets.from_lake(con, year, rnd, live_laps=live_laps,
                                  live_session="R" if live_laps is not None else None)
    if "R" not in weekend.sessions:
        return {}
    out: dict[int, dict] = {}
    for row in entries.itertuples(index=False):
        slot, number = row.grid_position, int(row.driver_number)
        if not pd.notna(slot) or not slot or number not in weekend.cars:
            continue
        out[int(slot)] = weekend.holding(number, "R").left()
    return out


def _qualifying_order(con, year: int, round_number: int) -> pd.DataFrame:
    """
    Qualifying's result as a grid: the order cars will start in, penalties aside.

    Used on race day, when the race has no classification yet and so no grid
    column to read.
    """
    import duckdb

    try:
        rows = con.sql(f"""select driver_number, abbreviation, position as grid_position
                           from results
                           where year = {int(year)} and round = {int(round_number)}
                             and "session" = 'Q' and position is not null""").df()
    except duckdb.CatalogException:
        return pd.DataFrame(columns=["driver_number", "abbreviation", "grid_position"])
    return rows


def _classification(con, year: int, round_number: int) -> pd.DataFrame:
    """The race's classification, or nothing when the lake has no results at all."""
    import duckdb

    try:
        return con.sql(f"""select driver_number, abbreviation, grid_position from results
                           where year = {int(year)} and round = {int(round_number)}
                             and "session" = 'R'""").df()
    except duckdb.CatalogException:
        return pd.DataFrame(columns=["driver_number", "abbreviation", "grid_position"])


def tyre_stock(con, session_key: str | None = None, *, grid: int | None = None,
               driver_number: int | None = None, year: int | None = None,
               round_number: int | None = None, live_laps=None) -> Stock | None:
    """
    The tyres one car held at the start of a race, by grid slot or by number.

    Known before the race starts — every set it names was run in practice or
    qualifying — so a held-out study may use it.

    Before the race is classified there is no grid to read, so the order comes
    from qualifying instead, which is the grid apart from penalties, and the
    stock says so. `live_laps` is the race in progress, whose laps are not in
    the lake; without it a race that has not been ingested has no sets at all.
    Returns None when neither is available, or when nobody started from that
    slot.
    """
    from racecraft.model import tyre_sets

    if session_key is not None:
        rows = con.sql(f"""select year, round from sessions
                           where session_key = '{_safe(session_key)}'""").df()
        if rows.empty:
            return None
        year, rnd = int(rows.iloc[0]["year"]), int(rows.iloc[0]["round"])
    elif year is not None and round_number is not None:
        rnd = int(round_number)
    else:
        return None

    notes: list[str] = []
    entries = _classification(con, year, rnd)
    if entries.empty:
        # No classification yet: qualifying is the grid, penalties aside.
        entries = _qualifying_order(con, year, rnd)
        if not entries.empty:
            notes.append("the grid is taken from qualifying: penalties are not applied")
    if entries.empty:
        return None
    if driver_number is None:
        if grid is None:
            return None
        match = entries[entries["grid_position"] == grid]
        if match.empty:
            return None
        driver_number = int(match.iloc[0]["driver_number"])
    row = entries[entries["driver_number"] == driver_number]
    if row.empty:
        return None

    weekend = tyre_sets.from_lake(con, year, rnd, live_laps=live_laps,
                                  live_session="R" if live_laps is not None else None)
    if driver_number not in weekend.cars or "R" not in weekend.sessions:
        return None
    held = weekend.holding(driver_number, "R")
    slot = row.iloc[0]["grid_position"]
    return Stock(
        driver=str(row.iloc[0]["abbreviation"] or weekend.cars[driver_number].driver),
        driver_number=driver_number,
        grid=int(slot) if pd.notna(slot) and slot else None,
        left=held.left(),
        notes=held.notes + notes,
    )
