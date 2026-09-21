"""
Tyre sets: which ones each car has used, and what is left for the race.

Every lap in the feed carries its compound, whether the set was new when
fitted, and how many laps that set has done — counted across sessions, so a
medium run for four laps in qualifying starts the race at age five. That is
enough to follow each physical set through a weekend, and so to say before a
race what every car still has: how many new sets of each compound, and how
worn the used ones are.

The feed does not number sets, so identity is inferred. A stint on a used set
is joined to the earlier set of the same compound whose lap count it
continues. Checked against every weekend from 2023 to 2026, 97% of used-set
stints continue an earlier set exactly. The rest fall into three kinds, each
handled explicitly rather than dropped:

* **Stalled counter.** The next stint starts at the age the last one ended,
  not one lap later: an out-lap the counter did not tick for.
* **Counter slipped back** by one or two laps. Same set, same session; the
  count of laps in the table ran ahead of the feed's own.
* **Laps not seen.** A used set with no earlier set to continue — run in laps
  the feed never timed, or by a stand-in driver whose laps are under another
  number. It is a real set from the allocation and is counted as one.

The rules are Article 30 of the Sporting Regulations, and `RULES` below is that
article as data. A normal weekend allocates 13 dry sets (8 soft, 3 medium, 2
hard) and takes two back after each practice session, leaving seven for
qualifying and the race; a driver who reaches Q3 hands one more soft back after
it. A sprint weekend allocates 12 (6, 4, 2) and takes one back after practice,
the sprint's most-used set after the sprint, and three after qualifying. A
weekend with Pirelli's test tyres in second practice allocates one soft fewer.
The two 2023 trials of the Alternative Tyre Allocation ran 11 (4, 4, 3). Throughout,
one soft cannot be touched before Q3 and one hard and one medium cannot be
handed back before the race.

The regulations say how many sets go back, not which. A set run again later
plainly was not one of them; otherwise the most worn go back, which is what
teams do. When a car has no used set left to give, a new one goes, and the
compound it was is a guess, named as one.

Where a car appears to have run more sets than it was given, the excess is
reported, not hidden: a set has been counted twice.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

DRY_COMPOUNDS = ("SOFT", "MEDIUM", "HARD")



@dataclass(frozen=True)
class Rules:
    """One weekend format's allocation and hand-backs, from Article 30."""
    name: str
    allocation: dict[str, int]
    # (session, sets handed back after it). A second count applies when a
    # stand-in drove the car in first practice.
    returns: tuple[tuple[str, int, int], ...]
    q3_returns_soft: bool                  # a Q3 driver hands one soft back after qualifying
    sprint_returns_most_used: bool = False  # the sprint's most-used set goes back after it
    hand_backs_known: bool = True


RULES = {
    # 30.2 d) ii), 30.5 i)
    "standard": Rules("standard weekend", {"SOFT": 8, "MEDIUM": 3, "HARD": 2},
                      (("FP1", 2, 2), ("FP2", 2, 2), ("FP3", 2, 2)), q3_returns_soft=True),
    # 30.2 d) iii), 30.5 j): Pirelli's evaluation tyres in second practice
    "test": Rules("weekend with Pirelli test tyres", {"SOFT": 7, "MEDIUM": 3, "HARD": 2},
                  (("FP1", 1, 2), ("FP2", 2, 1), ("FP3", 2, 2)), q3_returns_soft=True),
    # 30.2 d) i), 30.5 h)
    "sprint": Rules("sprint weekend", {"SOFT": 6, "MEDIUM": 4, "HARD": 2},
                    (("FP1", 1, 1), ("S", 1, 1), ("Q", 3, 3)), q3_returns_soft=False,
                    sprint_returns_most_used=True),
    # The 2023 trial at Hungary and Monza. Its hand-back schedule is not
    # modelled, so the sets held are an upper bound there.
    "alternative": Rules("alternative allocation trial", {"SOFT": 4, "MEDIUM": 4, "HARD": 3},
                         (), q3_returns_soft=False, hand_backs_known=False),
}
ALTERNATIVE_WEEKENDS = frozenset({(2023, 11), (2023, 14)})

# One set of each that cannot be handed back before the race (30.5 i) ii)),
# and the Q3 soft that cannot be used or handed back before Q3 (30.5 i) i)).
RACE_SPECIFICATIONS = ("HARD", "MEDIUM")

# How far behind the laps table the feed's own lap count can run on a set that
# is still the same set. One and two laps account for 126 of the 311 stints that
# do not continue a set exactly; beyond that it is more likely another set.
COUNTER_SLIP = 2


@dataclass
class Run:
    """One stint on one set: where it was, and when each lap ended."""
    session: str
    stint: int
    age_at_start: int                # the feed's lap count on the set at its first lap here
    laps: int
    start_t: float | None
    lap_end_t: list[float]


@dataclass
class TyreSet:
    number: int                      # per car, in order of first use
    compound: str
    runs: list[Run] = field(default_factory=list)
    seen_new: bool = True            # False when first seen already used, laps unseen
    link: str = "new"                # how its most doubtful run was joined to it
    last_used: int = 0               # order of its latest run among the car's stints

    @property
    def laps(self) -> int:
        """Laps on the set after its last run, as the feed counts them."""
        last = self.runs[-1]
        return last.age_at_start - 1 + last.laps

    def laps_before(self, session: str, order: list[str]) -> int | None:
        """
        Laps on the set when `session` started, or None if it was still new and unfitted.

        A set first seen in `session` already worn was run before it, in laps
        the feed did not show; it had those laps at the start.
        """
        rank = order.index(session)
        earlier = [run for run in self.runs if order.index(run.session) < rank]
        here = [run for run in self.runs if run.session == session]
        # The feed's count when the set is first fitted here beats what we saw
        # of it: laps it ran that were never timed are still on it.
        counted = here[0].age_at_start - 1 if here else None
        if earlier:
            last = earlier[-1]
            seen = last.age_at_start - 1 + last.laps
            return max(seen, counted) if counted is not None else seen
        if not self.seen_new and counted is not None:
            return counted
        return None

    def first_session(self) -> str:
        return self.runs[0].session


@dataclass
class Car:
    driver_number: int
    driver: str
    team: str
    sets: list[TyreSet] = field(default_factory=list)
    stand_ins: list[str] = field(default_factory=list)

    def sets_before(self, session: str, order: list[str]) -> list[TyreSet]:
        """Sets no longer new when `session` started."""
        return [s for s in self.sets if s.laps_before(session, order) is not None]



@dataclass
class Returned:
    set: TyreSet
    after: str                        # the session it went back after
    laps: int


@dataclass
class Holding:
    """What one car had at the start of a session."""
    new: dict[str, int]               # unfitted sets of each compound
    used: list[tuple[TyreSet, int]]   # kept sets and the laps on each, least worn first
    returned: list[Returned]
    notes: list[str]
    new_returned: dict[str, int] = field(default_factory=dict)   # new sets assumed handed back

    def left(self) -> dict[str, dict]:
        """Per compound: new sets, and the laps on each used one."""
        return {c: {"new": max(self.new[c], 0),
                    "used": [laps for s, laps in self.used if s.compound == c]}
                for c in DRY_COMPOUNDS}

    @property
    def total(self) -> int:
        return sum(max(n, 0) for n in self.new.values()) + len(self.used)


@dataclass
class Weekend:
    year: int
    round: int
    event_name: str
    sessions: list[str]              # session codes in the order they ran
    sprint: bool
    cars: dict[int, Car]
    notes: list[str] = field(default_factory=list)
    q3_cars: set[int] = field(default_factory=set)
    test_tyres: bool = False          # Pirelli's evaluation tyres ran in practice
    extra: dict[str, int] = field(default_factory=dict)   # sets beyond Article 30 the field ran

    @property
    def rules(self) -> Rules:
        if (self.year, self.round) in ALTERNATIVE_WEEKENDS:
            return RULES["alternative"]
        if self.sprint:
            return RULES["sprint"]
        # Before 2024 the evaluation tyres came on top of the normal thirteen:
        # most of the field ran eight softs at all three 2023 test weekends.
        return RULES["test" if self.test_tyres and self.year >= 2024 else "standard"]

    @property
    def allocation(self) -> dict[str, int]:
        limits = dict(self.rules.allocation)
        for compound, n in self.extra.items():
            limits[compound] += n
        return limits

    @property
    def allocation_name(self) -> str:
        return self.rules.name

    def over_allocation(self) -> dict[int, dict[str, int]]:
        """Cars with more sets of a compound than exist: a set counted twice."""
        limits = self.allocation
        out: dict[int, dict[str, int]] = {}
        for number, car in self.cars.items():
            excess = {}
            for compound in DRY_COMPOUNDS:
                seen = sum(1 for s in car.sets if s.compound == compound)
                if seen > limits[compound]:
                    excess[compound] = seen - limits[compound]
            if excess:
                out[number] = excess
        return out

    def holding(self, number: int, session: str) -> Holding:
        """
        What a car had at the start of `session`, after the sets handed back.

        Everything up to the start of `session` is used, including which sets
        were run again: a set run in qualifying was not handed back after
        practice. Nothing from `session` itself or later is.
        """
        car, order, rules = self.cars[number], self.sessions, self.rules
        rank = order.index(session)
        before = order[:rank]
        fitted = car.sets_before(session, order)
        new = {c: rules.allocation[c] - sum(1 for s in fitted if s.compound == c) for c in DRY_COMPOUNDS}
        stood_in_fp1 = any(entry.endswith("(FP1)") for entry in car.stand_ins)
        notes: list[str] = []
        if not rules.hand_backs_known:
            notes.append(f"hand-backs at the {rules.name} are not modelled: the sets shown "
                         "include some that went back to Pirelli")

        due = [(code, stand_in if stood_in_fp1 else normal, None)
               for code, normal, stand_in in rules.returns if code in before]
        if rules.q3_returns_soft and number in self.q3_cars and "Q" in before:
            due.append(("Q", 1, "SOFT"))

        returned: list[Returned] = []
        new_returned = {c: 0 for c in DRY_COMPOUNDS}
        gone: set[int] = set()
        for code, count, only in due:
            at = order.index(code)
            following = order[at + 1]
            pool = [s for s in fitted
                    if s.number not in gone and order.index(s.first_session()) <= at
                    and (only is None or s.compound == only)
                    and not any(at < order.index(run.session) < rank for run in s.runs)]
            if rules.sprint_returns_most_used and code == "S":
                # 30.5 h) ii): the set with the most laps in the sprint, if one was run.
                in_sprint = [s for s in pool if any(run.session == "S" for run in s.runs)]
                if in_sprint:
                    pool = [max(in_sprint, key=lambda s: sum(r.laps for r in s.runs if r.session == "S"))]
            pool.sort(key=lambda s: -(s.laps_before(following, order) or 0))
            for tyre in pool:
                if count == 0:
                    break
                if not self._may_return(tyre.compound, new, fitted, gone, before):
                    continue
                gone.add(tyre.number)
                returned.append(Returned(tyre, code, tyre.laps_before(following, order) or 0))
                count -= 1
            while count > 0:
                compound = only or self._spare_new(new, before)
                if compound is None:
                    notes.append(f"a set due back after {code} could not be found")
                    break
                new[compound] -= 1
                new_returned[compound] += 1
                count -= 1
            if not only and new_returned and any(new_returned.values()) and \
                    not any(n.startswith("new sets handed back") for n in notes):
                notes.append("new sets handed back where no used one was left; which compound "
                             "they were is a guess")

        used = sorted(((s, s.laps_before(session, order)) for s in fitted if s.number not in gone),
                      key=lambda pair: (pair[1], pair[0].number))
        for compound, n in new.items():
            if n < 0:
                plural = "s" if n < -1 else ""
                notes.append(f"{-n} more {compound.lower()} set{plural} run than the allocation: "
                             "a set is probably counted twice")
        return Holding(new=new, used=used, returned=returned, notes=notes,
                       new_returned={c: n for c, n in new_returned.items() if n})

    @staticmethod
    def _may_return(compound: str, new: dict[str, int], fitted: list[TyreSet],
                    gone: set[int], before: list[str]) -> bool:
        """
        Whether handing back a used set of `compound` leaves what must be kept.

        One set of each race specification must survive to the race.
        """
        if compound not in RACE_SPECIFICATIONS or "R" in before:
            return True
        kept = max(new[compound], 0) + sum(1 for s in fitted
                                           if s.compound == compound and s.number not in gone)
        return kept > 1

    @staticmethod
    def _spare_new(new: dict[str, int], before: list[str]) -> str | None:
        """
        The compound of a new set a team would hand back: the one it has most to
        spare, after the soft saved for Q3 and one of each race specification.
        """
        reserved = {"SOFT": 0 if "Q" in before else 1, "MEDIUM": 1, "HARD": 1}
        spare = {c: new[c] - reserved[c] for c in DRY_COMPOUNDS}
        compound = max(DRY_COMPOUNDS, key=lambda c: (spare[c], c == "SOFT"))
        return compound if spare[compound] > 0 else None


# ------------------------------------------------------------- reconstruction

def stints_from_laps(laps: pd.DataFrame, session: str) -> pd.DataFrame:
    """
    One row per stint on a dry compound, in the order they started.

    The feed's stint number goes up at every pit visit, including ones that
    refit the same set, so a stint is a run, not a set.
    """
    columns = ["session", "driver_number", "driver", "team", "stint", "compound",
               "fresh", "age_at_start", "laps", "start_t", "lap_end_t"]
    if laps is None or laps.empty:
        return pd.DataFrame(columns=columns)
    dry = laps[laps["compound"].isin(DRY_COMPOUNDS) & laps["tyre_life"].notna()]
    if dry.empty:
        return pd.DataFrame(columns=columns)
    dry = dry.sort_values(["driver_number", "lap_number"])
    rows = []
    for (number, stint), run in dry.groupby(["driver_number", "stint"], sort=False):
        start = run["lap_start_t"].dropna()
        rows.append({
            "session": session,
            "driver_number": int(number),
            "driver": str(run["driver"].iloc[0]),
            "team": run["team"].iloc[0] if pd.notna(run["team"].iloc[0]) else None,
            "stint": int(stint),
            "compound": str(run["compound"].iloc[0]),
            "fresh": bool(run["fresh_tyre"].fillna(False).any()),
            "age_at_start": int(run["tyre_life"].min()),
            "laps": len(run),
            "start_t": float(start.iloc[0]) if not start.empty else None,
            "lap_end_t": [float(t) for t in run["lap_end_t"].dropna()],
        })
    return pd.DataFrame(rows, columns=columns)


def _continuation(sets: list[TyreSet], compound: str, age: int) -> tuple[TyreSet | None, str]:
    """
    The set a stint starting at feed age `age` continues, and how sure the join is.

    `gap` is how many laps the set did that we did not see: 0 is the normal case.
    Two sets can fit equally well — a six-lap soft from practice and another
    from qualifying — and then the one run most recently wins: the sets a car
    races on are the ones it kept, and the ones it kept are the ones it was
    still using. Choosing the older one sends to the race a set that went back
    to Pirelli days earlier.
    """
    best, best_rank, kind = None, None, "unseen"
    for candidate in sets:
        if candidate.compound != compound:
            continue
        gap = age - 1 - candidate.laps
        if gap == 0:
            rank, label = (0, 0), "exact"
        elif gap == -1:
            rank, label = (1, 0), "stalled"
        elif gap > 0:
            rank, label = (2, gap), "laps not seen"
        elif gap >= -1 - COUNTER_SLIP:
            rank, label = (3, -gap), "counter slipped"
        else:
            continue
        rank = (*rank, -candidate.last_used)
        if best_rank is None or rank < best_rank:
            best, best_rank, kind = candidate, rank, label
    return best, kind


_LINK_DOUBT = {"new": 0, "exact": 0, "stalled": 1, "counter slipped": 2, "laps not seen": 3, "unseen": 4}


def reconstruct(stints: pd.DataFrame, order: list[str]) -> dict[int, list[TyreSet]]:
    """Every car's sets, from its stints across the weekend."""
    if stints.empty:
        return {}
    rank = {code: i for i, code in enumerate(order)}
    stints = stints.assign(_order=stints["session"].map(rank),
                           _start=stints["start_t"].fillna(float("inf")))
    stints = stints.sort_values(["driver_number", "_order", "_start", "stint"])
    out: dict[int, list[TyreSet]] = {}
    for number, rows in stints.groupby("driver_number", sort=False):
        sets: list[TyreSet] = []
        for sequence, row in enumerate(rows.itertuples(index=False), start=1):
            run = Run(session=row.session, stint=row.stint, age_at_start=row.age_at_start,
                      laps=row.laps, start_t=row.start_t, lap_end_t=list(row.lap_end_t))
            brand_new = row.age_at_start == 1 and row.fresh
            found, kind = (None, "new") if brand_new else _continuation(sets, row.compound, row.age_at_start)
            if found is not None:
                found.runs.append(run)
                found.last_used = sequence
                if _LINK_DOUBT[kind] > _LINK_DOUBT[found.link]:
                    found.link = kind
                continue
            # A new set: brand new, or already used in laps we never saw. Age 1
            # with the "new" flag off is a set with no laps on it, whatever the
            # flag says, so it is new too.
            seen_new = row.age_at_start == 1
            sets.append(TyreSet(number=len(sets) + 1, compound=row.compound, runs=[run],
                                seen_new=seen_new, link="new" if seen_new else "unseen",
                                last_used=sequence))
        out[int(number)] = sets
    return out


def assign_stand_ins(stints: pd.DataFrame, regulars: set[int]) -> tuple[pd.DataFrame, dict[int, list[str]], list[str]]:
    """
    Put laps driven by a stand-in under the car they drove.

    A rookie in first practice drives a race driver's car on that car's
    allocation, under their own number. A stand-in is anyone not among the
    weekend's regular entrants; their car is the one of the same team whose
    regular driver has no laps in that session. When that is not exactly one
    car the laps are left out and the reason noted.
    """
    notes: list[str] = []
    stood_in: dict[int, list[str]] = {}
    if stints.empty:
        return stints, stood_in, notes
    stints = stints.copy()
    stints["driven_by"] = stints["driver_number"]
    if "teams" not in stints:
        stints["teams"] = [[t] if isinstance(t, str) else [] for t in stints["team"]]
    keep = pd.Series(True, index=stints.index)
    teams = stints[stints["driver_number"].isin(regulars)].dropna(subset=["team"])         .groupby("driver_number")["team"].last()
    left_out: dict[str, list[str]] = {}
    claimed: set[tuple[str, int]] = set()
    groups = list(stints[~stints["driver_number"].isin(regulars)].groupby(
        ["session", "driver_number"], sort=False))
    # Stand-ins whose team is certain claim their cars first.
    groups.sort(key=lambda item: len(item[1]["teams"].iloc[0]))
    for (session, number), rows in groups:
        present = set(stints.loc[stints["session"] == session, "driven_by"])
        free = [n for n, t in teams.items()
                if t in rows["teams"].iloc[0] and n not in present and (session, n) not in claimed]
        hosts = free
        driver = str(rows["driver"].iloc[0])
        if len(hosts) == 1:
            claimed.add((session, hosts[0]))
            stints.loc[rows.index, "driver_number"] = hosts[0]
            stints.loc[rows.index, "team"] = teams[hosts[0]]
            stood_in.setdefault(hosts[0], []).append(f"{driver} ({session})")
        else:
            keep[rows.index] = False
            reason = ("both of the team's cars were driven by stand-ins" if len(hosts) > 1
                      else "no car of theirs in the race was free")
            left_out.setdefault(f"{driver}: {reason}", []).append(session)
    for reason, sessions in left_out.items():
        driver, why = reason.split(": ", 1)
        notes.append(f"{driver} ({', '.join(sessions)}) left out — {why}")
    return stints[keep], stood_in, notes


def build(stints: pd.DataFrame, order: list[str], regulars: set[int], *, year: int, round_number: int,
          event_name: str, sprint: bool, q3_cars: set[int] | None = None,
          test_tyres: bool = False) -> Weekend:
    """A weekend from its stints. `regulars` are the cars entered for the race."""
    stints, stood_in, notes = assign_stand_ins(stints, regulars)
    sets = reconstruct(stints, order)
    cars = {}
    for number, car_sets in sets.items():
        if number not in regulars:
            continue
        # The regular driver's own name and team, not a stand-in's.
        own = stints[stints["driven_by"] == number]
        cars[number] = Car(driver_number=number, driver=str(own["driver"].iloc[-1]),
                           team=str(own["team"].iloc[-1]), sets=car_sets,
                           stand_ins=stood_in.get(number, []))
    weekend = Weekend(year=year, round=round_number, event_name=event_name, sessions=order,
                      sprint=sprint, cars=cars, notes=notes, q3_cars=set(q3_cars or ()),
                      test_tyres=test_tyres)
    weekend.extra = _field_wide_extra(weekend)
    for compound, n in weekend.extra.items():
        weekend.notes.append(
            f"most of the field ran {n} more {compound.lower()} set{'s' if n > 1 else ''} than "
            f"Article 30 gives a {weekend.rules.name}; counted as allocated")
    for number, excess in weekend.over_allocation().items():
        described = ", ".join(f"{n} {c.lower()}" for c, n in excess.items())
        weekend.notes.append(f"{cars[number].driver}: {described} more than the allocation — "
                             "a set is probably counted twice")
    return weekend


# A set beyond the rules that at least this share of the field ran was
# allocated, not miscounted. Qatar 2025 is the clearest: ten cars ran a third
# hard set at the weekend stints were capped at 25 laps.
FIELD_WIDE_SHARE = 0.25


def _field_wide_extra(weekend: Weekend) -> dict[str, int]:
    """Sets the rules do not give but a quarter of the field ran anyway."""
    if not weekend.cars:
        return {}
    limits = weekend.rules.allocation
    extra = {}
    for compound in DRY_COMPOUNDS:
        excess = [sum(1 for s in car.sets if s.compound == compound) - limits[compound]
                  for car in weekend.cars.values()]
        over = sorted(e for e in excess if e > 0)
        if len(over) >= max(3, FIELD_WIDE_SHARE * len(excess)):
            extra[compound] = over[len(over) // 2]
    return extra


# ------------------------------------------------------------- from the lake

SPRINT_SESSIONS = ("SQ", "SS", "S")


def from_lake(con, year: int, round_number: int, *, live_laps: pd.DataFrame | None = None,
              live_session: str | None = None, sprint: bool | None = None) -> Weekend:
    """
    One weekend from the lake, optionally with a session in progress on top.

    `live_laps` is the session being recorded: its laps are not in the lake yet.
    Whether the weekend is a sprint weekend is read from the sessions stored;
    before the sprint itself exists, pass `sprint` from the schedule.
    """
    meta = con.sql(f"""
        select session_key, "session", event_name, date_utc from sessions
        where year = {int(year)} and round = {int(round_number)} order by date_utc""").df()
    if meta.empty and live_laps is None:
        raise KeyError(f"{year} round {round_number}")

    order = [str(code) for code in meta["session"]]
    frames = []
    for row in meta.itertuples(index=False):
        if live_session and row.session == live_session:
            continue                           # the live copy wins
        laps = con.sql(f"""select * from laps where session_key = '{row.session_key}'""").df()
        frames.append(stints_from_laps(laps, str(row.session)))
    if live_laps is not None and live_session:
        if live_session not in order:
            order.append(live_session)
        frames.append(stints_from_laps(live_laps, live_session))
    stints = pd.concat([f for f in frames if not f.empty], ignore_index=True) if frames else \
        stints_from_laps(None, "")

    stints = _fill_teams(con, stints, year)
    entries = _results(con, year, round_number)
    if live_laps is not None and live_session:
        entries = pd.concat([entries, pd.DataFrame({
            "session": live_session, "driver_number": live_laps["driver_number"].dropna().unique()})])
    regulars = _regulars(entries, order)
    event = str(meta["event_name"].iloc[0]) if not meta.empty else ""
    is_sprint = sprint if sprint is not None else any(code in SPRINT_SESSIONS for code in order)
    classification = _results(con, year, round_number, extra=", q3_s")
    q3 = classification[(classification["session"] == "Q") & classification["q3_s"].notna()]         if "q3_s" in classification else classification.iloc[0:0]
    test = con.sql(f"""
        select count(*) from laps
        where year = {int(year)} and round = {int(round_number)} and compound = 'TEST_UNKNOWN'""").fetchone()[0]
    return build(stints, order, regulars, year=year, round_number=round_number,
                 event_name=event, sprint=is_sprint, q3_cars={int(n) for n in q3["driver_number"]},
                 test_tyres=bool(test))


def _results(con, year: int, round_number: int, extra: str = "") -> pd.DataFrame:
    """
    Every session's classification for a weekend, or nothing at all.

    A lake written without results — some tests, and any session ingested
    before the table existed — is a lake where the entry list is unknown, not a
    broken one.
    """
    import duckdb

    try:
        return con.sql(f"""
            select "session", driver_number{extra} from results
            where year = {int(year)} and round = {int(round_number)}""").df()
    except duckdb.CatalogException:
        return pd.DataFrame(columns=["session", "driver_number"])


def _fill_teams(con, stints: pd.DataFrame, year: int) -> pd.DataFrame:
    """
    A team for every stint, where the feed left it out.

    First practice at two 2026 rounds carries no team for anyone, in the laps
    or the classification, and a stand-in cannot be put in a car without one.
    A driver's team is taken from their other sessions that weekend. Failing
    that, every team they drove for that season is a candidate — a rookie can
    run first practice for two teams in a year — and the stand-in step picks the
    one with a car free.
    """
    stints = stints.copy()
    stints["teams"] = [[t] if isinstance(t, str) else [] for t in stints["team"]]
    if stints.empty or stints["team"].notna().all():
        return stints
    known = stints.dropna(subset=["team"]).groupby("driver")["team"].agg(lambda t: t.mode().iloc[0])
    season = con.sql(f"""
        select driver, team, count(*) as laps from laps
        where year = {int(year)} and team is not null group by all order by laps desc""").df()
    candidates = season.groupby("driver", sort=False)["team"].agg(list).to_dict()
    for index in stints.index[stints["team"].isna()]:
        driver = stints.at[index, "driver"]
        if driver in known:
            stints.at[index, "team"] = known[driver]
            stints.at[index, "teams"] = [known[driver]]
        else:
            stints.at[index, "teams"] = candidates.get(driver, [])
    return stints


def _regulars(entries: pd.DataFrame, order: list[str]) -> set[int]:
    """
    The cars entered for the race: the classification of the latest session.

    From the classification, not from dry-tyre laps: a car that crashed on the
    formation lap of a wet race has no dry stint in it and is still entered.
    First practice is where rookies stand in, so it is the one session that
    cannot say who the regulars are. With nothing later, everyone counts.
    """
    if entries.empty:
        return set()
    for code in reversed(order):
        present = {int(n) for n in entries.loc[entries["session"] == code, "driver_number"]}
        if present and code != "FP1":
            return present
    return {int(n) for n in entries["driver_number"]}


# ------------------------------------------------------------- plans

@dataclass
class PlanCheck:
    """Whether a plan can be run on the sets a car has, and what used ones cost."""
    feasible: bool
    reason: str | None
    stints: list[tuple[str, int, int]]      # compound, stint laps, laps already on the set
    extra_s: float                          # wear cost of starting stints on used sets

    def as_dict(self) -> dict:
        return {
            "feasible": self.feasible,
            "reason": self.reason,
            "stints": [{"compound": c, "laps": n, "set_laps": a} for c, n, a in self.stints],
            "extra_s": round(self.extra_s, 1),
        }


def check_plan(stints: list[tuple[str, int]], left: dict[str, dict], degradation: dict[str, float],
               curvature: dict[str, float] | None = None) -> PlanCheck:
    """
    Fit a plan's stints to the sets a car has left.

    Each stint needs its own set. New sets go first; after them, the least worn
    used ones. Within a compound the longest stint gets the freshest set, which
    is the cheapest pairing: a set already `a` laps old costs `slope * a` on
    every lap of the stint it is given to, so the old set belongs on the short
    stint.

    The cost is the wear model's own line, extended from where the set already
    is. It knows nothing of the cliff, so a well-worn set run long is costed
    optimistically, and the answer says how old the set is so that can be judged.
    """
    bend = curvature or {}
    assigned: dict[int, int] = {}
    for compound in {c for c, _ in stints}:
        wanted = sorted((i for i, (c, _) in enumerate(stints) if c == compound),
                        key=lambda i: -stints[i][1])
        have = left.get(compound, {"new": 0, "used": []})
        supply = [0] * max(have["new"], 0) + sorted(have["used"])
        if len(supply) < len(wanted):
            n = len(supply)
            reason = (f"needs {len(wanted)} {compound.lower()} sets, has {n}" if n
                      else f"no {compound.lower()} sets left")
            return PlanCheck(False, reason, [(c, n_laps, 0) for c, n_laps in stints], 0.0)
        for index, age in zip(wanted, supply):
            assigned[index] = age

    extra = 0.0
    out = []
    for index, (compound, laps) in enumerate(stints):
        age = assigned[index]
        slope, curve = degradation.get(compound, 0.0), bend.get(compound, 0.0)
        # sum over n = 1..laps of wear at (age + n), less the same stint on a new set
        extra += sum(slope * age + curve * ((age + n) ** 2 - n ** 2) for n in range(1, laps + 1))
        out.append((compound, laps, age))
    return PlanCheck(True, None, out, extra)
