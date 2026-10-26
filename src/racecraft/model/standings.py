"""
The championships: drivers' and constructors' points, as they stood at a moment.

Points are the feed's own, from every Grand Prix and sprint result in the lake,
so penalties, disqualifications and (in 2023 and 2024) the fastest-lap point
are as F1 awarded them. Summed that way, 2023 to 2025 come out at the published
final tables: Verstappen 575 and Red Bull 860; Verstappen 437 and McLaren 666;
Norris 423 and McLaren 833.

A result the feed sent without points (the 2026 Singapore sprint, ingested soon
after it ran) is scored from its classified positions with the season's
scale, and the answer says so: no fastest-lap point is guessed at.

`as_of` decides what counts. By default only results from before the session
being viewed, so opening a race does not give away who won it.

Ties are broken as the FIA breaks them: the most Grand Prix wins, then the most
second places, and so on. Sprint finishes do not count back.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Points by finishing place: a Grand Prix pays the top ten, a sprint the top eight.
RACE_POINTS = (25, 18, 15, 12, 10, 8, 6, 4, 2, 1)
SPRINT_POINTS = (8, 7, 6, 5, 4, 3, 2, 1)
# How many of each driver's latest Grand Prix finishes the table shows.
FORM_RACES = 5
COUNTBACK_PLACES = 22


@dataclass
class Standings:
    year: int
    drivers: list[dict]
    constructors: list[dict]
    races: int                                   # Grand Prix counted
    sprints: int                                 # sprints counted
    last: dict | None                            # the latest result counted
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"year": self.year, "drivers": self.drivers, "constructors": self.constructors,
                "races": self.races, "sprints": self.sprints, "last": self.last, "notes": self.notes}


def results(con, year: int) -> pd.DataFrame:
    """Every Grand Prix and sprint result of the season, one row per driver per session, in running order."""
    df = con.execute("""
        select s.session_key, s.year, cast(s.round as integer) as round, s."session" as code, s.event_name,
               s.date_utc, r.driver_number, r.abbreviation, r.full_name, r.team_name, r.team_id, r.team_color,
               r.position, r.classified_position, r.points
        from results r join sessions s using (session_key)
        where s.year = ? and s."session" in ('R', 'S')
        order by s.date_utc, r.position""", [int(year)]).df()
    if df.empty:
        return df
    df["classified"] = pd.to_numeric(df["classified_position"], errors="coerce")
    return _resolve_teams(df)


_BLANK = {"", "nan", "none", "null"}


def _known(series: pd.Series) -> pd.Series:
    """The values that say something: empty, "nan" and None are all missing."""
    text = series.astype("string").str.strip()
    return text.where(series.notna() & ~text.str.lower().isin(_BLANK))


def _resolve_teams(df: pd.DataFrame) -> pd.DataFrame:
    """
    One key per team for the whole season, and its latest name and colour.

    The feed is not consistent about it: in 2026 some sessions carry a team id
    and a name, some the id as the text "nan", some an id and no name, and the
    Singapore sprint neither. Names and ids are matched to each other across
    the season, and a row with neither takes the team its driver had in that
    session's weekend or, failing that, the driver's latest known team.
    """
    df = df.copy()
    team_id, team_name, color = _known(df["team_id"]), _known(df["team_name"]), _known(df["team_color"])
    both = pd.DataFrame({"id": team_id, "name": team_name}).dropna()
    id_of_name = both.drop_duplicates("name", keep="last").set_index("name")["id"].to_dict()
    key = team_id.fillna(team_name.map(id_of_name)).fillna(team_name)
    # A row with no team at all: the driver's team from their nearest result in the season.
    if key.isna().any():
        known = pd.DataFrame({"abbreviation": df["abbreviation"], "date": df["date_utc"], "key": key}).dropna()
        for i in key[key.isna()].index:
            mine = known[known["abbreviation"] == df.at[i, "abbreviation"]]
            if not mine.empty:
                nearest = (pd.to_datetime(mine["date"], utc=True) - pd.to_datetime(df.at[i, "date_utc"], utc=True)).abs()
                key.at[i] = mine.loc[nearest.idxmin(), "key"]
    df["team_key"] = key.fillna("unknown team").astype(str)
    names = pd.DataFrame({"key": df["team_key"], "name": team_name}).dropna().drop_duplicates("key", keep="last")
    colors = pd.DataFrame({"key": df["team_key"], "color": color}).dropna().drop_duplicates("key", keep="last")
    df["team_name"] = df["team_key"].map(names.set_index("key")["name"]).fillna(df["team_key"])
    df["team_color"] = df["team_key"].map(colors.set_index("key")["color"])
    return df


def standings(con, year: int, as_of: pd.Timestamp | None = None) -> Standings:
    """The championships of `year`, counting results from sessions that started before `as_of` (all, if None)."""
    df = results(con, year)
    notes: list[str] = []
    if not df.empty and as_of is not None:
        df = df[pd.to_datetime(df["date_utc"], utc=True) < pd.Timestamp(as_of).tz_convert("UTC")]
    if df.empty:
        return Standings(year=int(year), drivers=[], constructors=[], races=0, sprints=0, last=None,
                         notes=["no Grand Prix or sprint has been run yet this season"])

    df = df.copy()
    missing = df.groupby("session_key")["points"].transform(lambda p: p.isna().all())
    if missing.any():
        df.loc[missing, "points"] = [_scale_points(code, place)
                                     for code, place in zip(df.loc[missing, "code"], df.loc[missing, "classified"])]
        for event, code in df.loc[missing, ["event_name", "code"]].drop_duplicates().itertuples(index=False):
            notes.append(f"{event} {'sprint' if code == 'S' else 'Grand Prix'}: the feed sent no points, "
                         "so they are worked out from the classified positions")
    df["points"] = df["points"].fillna(0.0)

    sessions = df.drop_duplicates("session_key").sort_values("date_utc")
    last = sessions.iloc[-1]
    latest_round = int(last["round"])
    earlier = df[df["round"] < latest_round]

    drivers = _drivers(df, earlier)
    constructors = _constructors(df)
    return Standings(
        year=int(year), drivers=drivers, constructors=constructors,
        races=int((sessions["code"] == "R").sum()), sprints=int((sessions["code"] == "S").sum()),
        last={"round": latest_round, "event_name": str(last["event_name"]),
              "session": "sprint" if last["code"] == "S" else "Grand Prix"},
        notes=notes,
    )


def _scale_points(code: str, place: float) -> float:
    scale = SPRINT_POINTS if code == "S" else RACE_POINTS
    if pd.isna(place) or not 1 <= int(place) <= len(scale):
        return 0.0
    return float(scale[int(place) - 1])


def _countback(rows: pd.DataFrame) -> tuple:
    """Grand Prix finishes by place, most wins first: the FIA's tie-break."""
    places = rows.loc[rows["code"] == "R", "classified"].dropna().astype(int)
    return tuple(-int((places == p).sum()) for p in range(1, COUNTBACK_PLACES + 1))


def _ranked(totals: dict, rows_of) -> list:
    """Keys ordered by points, then countback, then name: the championship order."""
    return sorted(totals, key=lambda key: (-totals[key], _countback(rows_of(key)), str(key)))


def _drivers(df: pd.DataFrame, earlier: pd.DataFrame) -> list[dict]:
    by = df.groupby("abbreviation")
    totals = by["points"].sum().to_dict()
    order = _ranked(totals, lambda code: df[df["abbreviation"] == code])
    before: dict[str, int] = {}
    if not earlier.empty:
        prior = earlier.groupby("abbreviation")["points"].sum().to_dict()
        before = {code: i for i, code in enumerate(_ranked(prior, lambda c: earlier[earlier["abbreviation"] == c]), 1)}
    leader = totals[order[0]]
    out = []
    for place, code in enumerate(order, start=1):
        rows = df[df["abbreviation"] == code]
        latest = rows.iloc[-1]
        races = rows[rows["code"] == "R"]
        out.append({
            "position": place,
            "driver_number": int(latest["driver_number"]),
            "abbreviation": str(code),
            "full_name": None if pd.isna(latest["full_name"]) else str(latest["full_name"]),
            "team_name": None if pd.isna(latest["team_name"]) else str(latest["team_name"]),
            "team_color": None if pd.isna(latest["team_color"]) else str(latest["team_color"]),
            "points": _number(totals[code]),
            "gap": _number(leader - totals[code]),
            "wins": int((races["classified"] == 1).sum()),
            "podiums": int((races["classified"] <= 3).sum()),
            "sprint_wins": int((rows.loc[rows["code"] == "S", "classified"] == 1).sum()),
            # Places gained (+) or lost since before the latest weekend; None for a first appearance.
            "change": (before[code] - place) if code in before else None,
            "form": [_finish(r) for r in races.tail(FORM_RACES).itertuples()],
        })
    return out


def _constructors(df: pd.DataFrame) -> list[dict]:
    totals = df.groupby("team_key")["points"].sum().to_dict()
    order = _ranked(totals, lambda key: df[df["team_key"] == key])
    leader = totals[order[0]]
    out = []
    for place, key in enumerate(order, start=1):
        rows = df[df["team_key"] == key]
        latest = rows.iloc[-1]
        races = rows[rows["code"] == "R"]
        split = rows.groupby("abbreviation")["points"].sum().sort_values(ascending=False)
        out.append({
            "position": place,
            "team": str(latest["team_name"]),
            "team_color": None if pd.isna(latest["team_color"]) else str(latest["team_color"]),
            "points": _number(totals[key]),
            "gap": _number(leader - totals[key]),
            "wins": int((races["classified"] == 1).sum()),
            "podiums": int((races["classified"] <= 3).sum()),
            # Who scored them: a driver who moved team mid-season counts for each team they drove for.
            "drivers": [{"abbreviation": str(code), "points": _number(points)} for code, points in split.items()],
        })
    return out


def _finish(row) -> dict:
    """One Grand Prix finish for the form strip: the place, or why there was none."""
    place = None if pd.isna(row.classified) else int(row.classified)
    return {"round": int(row.round), "event_name": str(row.event_name), "position": place,
            "status": None if place is not None else str(row.classified_position or "")}


def _number(value: float) -> float | int:
    """Whole points as whole numbers; a half point (a shortened race) kept."""
    value = float(value)
    return int(value) if value.is_integer() else round(value, 1)
