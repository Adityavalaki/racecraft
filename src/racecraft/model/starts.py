"""
Starts: places gained or lost on lap 1, per driver, as of a moment like the standings.

A start is the grid slot minus the position at the end of lap 1, so positive
means places gained. Raw places gained mostly says where a driver qualified
(from pole they can only lose), so each start is also set against the average
for that grid slot: every Grand Prix (or sprint) start in the lake from that
slot, up to the same moment. That difference, "vs normal", is the fair number.

Left out, each with a note: pit-lane starts (grid 0), cars that did not start
(classified W) and sessions with no published grid (grid missing or -1). A car
with no lap-1 position that did start went out on lap 1: counted apart, not
as places lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from racecraft.model import standings
from racecraft.store.db import has_table

KINDS = {"races": ("R",), "sprints": ("S",), "both": ("R", "S")}


@dataclass
class Starts:
    year: int
    drivers: dict[str, list[dict]]           # by KINDS key
    sessions: dict[str, int]                 # starts counted per kind: sessions, not cars
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"year": self.year, "drivers": self.drivers, "sessions": self.sessions, "notes": self.notes}


def season(con, year: int, as_of: pd.Timestamp | None = None) -> Starts:
    """Every driver's starts of `year`, from sessions that started before `as_of` (all, if None)."""
    df = standings.results(con, year)
    cut = None if as_of is None else pd.Timestamp(as_of).tz_convert("UTC")
    if not df.empty and cut is not None:
        df = df[pd.to_datetime(df["date_utc"], utc=True) < cut]
    if df.empty or not has_table(con, "laps"):
        return Starts(year=int(year), drivers={k: [] for k in KINDS}, sessions={k: 0 for k in KINDS},
                      notes=["no race or sprint has been run yet this season"])
    every = _every_start(con, cut)
    df = df.merge(every[["session_key", "driver_number", "grid", "lap1"]], on=["session_key", "driver_number"], how="left")

    notes = []
    no_grid = df.groupby("session_key")["grid"].apply(lambda g: bool((g.isna() | (g < 0)).all()))
    for key in no_grid[no_grid].index:
        notes.append(f"{_label(df[df['session_key'] == key].iloc[0])}: no grid published, so it is left out")
    df = df[~df["session_key"].isin(no_grid[no_grid].index) & (df["classified_position"] != "W")]
    for row in df[df["grid"] == 0].itertuples():
        notes.append(f"{_label(row._asdict())}: {row.abbreviation} started from the pit lane, left out")

    slot = _slot_averages(every)
    df = df.assign(gain=df["grid"] - df["lap1"],
                   normal=[slot.get((c, g)) for c, g in zip(df["code"], df["grid"])])
    df["vs_normal"] = df["gain"] - df["normal"]
    counted = df[df["grid"] > 0]
    return Starts(year=int(year),
                  drivers={kind: _drivers(counted[counted["code"].isin(codes)]) for kind, codes in KINDS.items()},
                  sessions={kind: int(counted.loc[counted["code"].isin(codes), "session_key"].nunique())
                            for kind, codes in KINDS.items()},
                  notes=notes)


def _every_start(con, cut: pd.Timestamp | None) -> pd.DataFrame:
    """Every Grand Prix and sprint start in the lake before `cut`: grid slot and position after lap 1."""
    df = con.execute("""
        select r.session_key, s."session" as code, s.date_utc, r.driver_number, r.grid_position as grid,
               r.classified_position, l.position as lap1
        from results r join sessions s using (session_key)
        left join (select session_key, driver_number, position from laps where lap_number = 1) l
          using (session_key, driver_number)
        where s."session" in ('R', 'S')""").df()
    if cut is not None:
        df = df[pd.to_datetime(df["date_utc"], utc=True) < cut]
    return df.astype({"grid": "Float64", "lap1": "Float64"})


def _slot_averages(every: pd.DataFrame) -> dict[tuple[str, int], float]:
    """{(session code, grid slot): average places gained on lap 1}, over starts that reached the end of lap 1."""
    ok = every[(every["grid"] > 0) & every["lap1"].notna() & (every["classified_position"] != "W")]
    gain = (ok["grid"] - ok["lap1"]).astype(float)
    return {(code, int(grid)): float(v) for (code, grid), v in gain.groupby([ok["code"], ok["grid"]]).mean().items()}


def _drivers(df: pd.DataFrame) -> list[dict]:
    """One row per driver, best start against their slot first; a driver with no counted start goes last."""
    out = []
    for abbreviation, mine in df.groupby("abbreviation"):
        latest = mine.iloc[-1]
        ran = mine[mine["lap1"].notna()]
        gains = ran["gain"].astype(float)
        best = ran.loc[gains.idxmax()] if len(ran) else None
        worst = ran.loc[gains.idxmin()] if len(ran) else None
        out.append({
            "abbreviation": abbreviation, "full_name": latest["full_name"],
            "team": latest["team_name"], "team_color": latest["team_color"],
            "starts": len(ran),
            "gained": _r(gains.mean()) if len(ran) else None,
            "vs_normal": _r(ran["vs_normal"].astype(float).mean()) if len(ran) else None,
            "up": int((gains > 0).sum()), "same": int((gains == 0).sum()), "down": int((gains < 0).sum()),
            "best": _start(best), "worst": _start(worst),
            "out_lap1": int(mine["lap1"].isna().sum()),
        })
    out.sort(key=lambda d: (d["vs_normal"] is None, -(d["vs_normal"] or 0), d["abbreviation"]))
    return out


def _start(row) -> dict | None:
    if row is None:
        return None
    return {"event_name": _label(row), "grid": int(row["grid"]), "lap1": int(row["lap1"]), "gain": int(row["gain"])}


def _label(row) -> str:
    return f"{row['event_name']}{' sprint' if row['code'] == 'S' else ''}"


def _r(value: float) -> float:
    return round(float(value), 2)
