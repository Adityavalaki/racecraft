"""
What race control has said about each car, as of one instant.

The feed carries 9,947 race and sprint messages in this lake and the interface
read none of them. They are the only place it says *why* something happened: a
five-second penalty a car still has to serve, an incident the stewards are
looking at, a lap time taken away.

Everything here is a pure function of the race control table and a time, the
same way `timing.classify` is a pure function of the lap table and a time. That
is not tidiness — it is what makes scrubbing correct. A running accumulator
would be wrong the moment the clock went backwards, and the interface lets it:
the scrubber, the -30s button and live "following" all move the clock freely.
Folding the messages up to `t` on every call costs microseconds on a few
thousand rows and cannot drift out of step with the tower beside it.

## Reading a message

The FIA's text is machine-generated and its grammar is rigid, so this is parsed
rather than judged. Three measurements over every race and sprint in the lake
decided the shape of it, and each one corrected an assumption.

*A car is named by number and abbreviation together, and the abbreviation is
what makes extraction safe.* A message is full of other numbers - a lap time
`1:40.956`, `TURN 9`, `LAP 10`, a stamp `14:23:43` - and none of them is
followed by a three-letter code. But anchoring on the word CAR is wrong:
`CARS 31 (OCO), 77 (BOT) AND 20 (MAG)` writes the word once for three cars, and
requiring it found only the first on **1,514 messages**. So the code is the
anchor and the number in front of it is the car.

*Two things then match that look like cars and are not, and one of them is
dangerous.* A lap deletion ending `... 16:12:10 (PIT)` offers `10 (PIT)`, and 10
is a real driver — so a message about car 23 would charge its deleted lap to car
10. Timestamps are therefore removed before scanning. `CAR 26 (BED)` is the other
kind: a real car in another championship whose messages share the feed. 337
phantom matches are rejected across the lake, 200 of them carrying a number that
belongs to an actual driver. Both kinds go the same way: timestamps first, then a
number not in this session's driver list is not one of this session's cars.

*The verdicts are a closed set.* The rules in `_classify` leave nothing
unclassified across all 3,256 car-concerning messages. The only drift found was
one spelling: `STOP/GO` also appears as `STOP-AND-GO`.

## An incident, not just a count

A single incident is reported several times as it moves - noted, then under
investigation, then a penalty or no further action - so counting the messages
would count one incident four times. They are tied together instead, and the
feed offers two ways to do it. 15.8% of them carry a trailing `(15:03:08)`
which is the incident's own identity and stays fixed through its whole life.
The rest are matched on the offence plus an overlapping car, which links
**88.1% of noted incidents** to a later verdict. The 75 that link to nothing
are genuinely unresolved: the stewards never came back to them before the flag.

An incident whose cars narrow between messages - `CARS 27 (HUL) AND 55 (SAI)
NOTED - CAUSING A COLLISION` resolving as a penalty for HUL alone - is matched
by the subset rule in `_match_incident`: the penalty closes it for HUL, and it
stays open for SAI, which is what the feed literally said.

## What this does not need a model for

Everything here is a known rule applied to a machine-written feed, which is
where code beats a model on every axis: exact, free, instant, the same answer
twice. That includes which pit stop a penalty was served at (`penalised_stops`),
which is decided by timing and never contradicted by the feed's own `PENALTY
SERVED`. The places a semantic judgment could still earn a place are listed in
the README under *TypeSafe*, each with the reason it is not built yet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import duckdb
import numpy as np
import pandas as pd

# A car is `44 (HAM)`: the number, then its code. The code is the anchor
# because the word CAR is written once for a list of cars. See the module note.
CAR = re.compile(r"(\d{1,2})\s*\(([A-Z]{3})\)")

# Removed before scanning for cars, or `... LAP 34 18:58:59 (PIT)` offers
# `59 (PIT)` as a car. Both `14:23:43` and a bare `18:58` appear.
CLOCK = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")

# A lap time, which is also `1:19.870` and must not read as a clock or a car.
LAP_TIME = re.compile(r"\b\d:\d{2}\.\d{3}\b")

# What a lap deletion trails after its offence: `LAP 73 17:20:22 (PIT)`. The lap
# and the time are columns of their own, so they are cut from the offence text.
DELETION_TAIL = re.compile(r"\s+LAP\s+\d+\s+\d{1,2}:\d{2}(?::\d{2})?(?:\s*\(PIT\))?\s*$")

# The incident's own identity, when the feed supplies it: a trailing stamp that
# stays fixed from the first mention to the last.
INCIDENT_STAMP = re.compile(r"\((\d{1,2}:\d{2}:\d{2})\)\s*$")

# `5 SECOND TIME PENALTY`, `10 SECOND STOP/GO PENALTY`. Anchored on the number
# and SECOND, because PENALTY also turns up inside a reason - "FAILING TO SERVE
# TIME PENALTY CORRECTLY" - where it carries no amount.
SECONDS = re.compile(r"(\d+)\s+SECOND")

STOP_GO = re.compile(r"STOP\s*(?:/|-AND-|-)\s*GO")

# Race control's own churn: a blue flag is shown to one lapped car as it is
# passed, and a sector flag repeats for every sector every time the state
# changes. Together they are 4,771 of the feed's 8,028 non-steward race and
# sprint messages - 59% - and they say nothing a panel can act on. The flag
# words are matched rather than the phrase "IN TRACK SECTOR" on its own, because
# `TRACK SURFACE SLIPPERY IN TRACK SECTOR 11` is a condition worth reading and
# 176 of those were swept up by the looser rule.
NOISE = re.compile(
    r"^\s*(?:WAVED\s+)?BLUE FLAG"
    r"|^\s*(?:DOUBLE\s+)?(?:YELLOW|GREEN|CLEAR)[^-]*IN TRACK SECTOR"
    r"|^\s*SECTOR\s+\d",
    re.IGNORECASE)

# What a message is about, and which of the two lists it belongs in.
TOPIC_STEWARDS = "stewards"
TOPIC_TRACK = "track"
TOPIC_NOISE = "noise"
TOPICS = (TOPIC_STEWARDS, TOPIC_TRACK, TOPIC_NOISE)

SERVED_MARK = "PENALTY SERVED"
STEWARDS_PREFIX = "FIA STEWARDS:"
CORRECTION_PREFIX = "CORRECTION:"

# What a message did.
AWARDED_TIME = "time_penalty"
AWARDED_STOP_GO = "stop_go"
AWARDED_DRIVE_THROUGH = "drive_through"
SERVED_PENALTY = "served"
DELETED = "lap_deleted"
INVESTIGATING = "under_investigation"
AFTER_RACE = "investigate_after_race"
NOTED = "noted"
CLEARED = "no_further_action"
BLACK_AND_WHITE = "black_and_white"
# A black flag is a disqualification, not a warning: one in the whole lake
# (2026, car 27) and the most severe thing the stewards can do mid-race.
DISQUALIFIED = "disqualified"
REPRIMAND = "reprimand"
WARNING = "warning"
OTHER = "other"

# Verdicts that award something the car must answer for.
AWARDS = (AWARDED_TIME, AWARDED_STOP_GO, AWARDED_DRIVE_THROUGH)
# Verdicts that move an incident along rather than starting or ending it.
OPENS = (NOTED,)
PROGRESSES = (INVESTIGATING, AFTER_RACE)
CLOSES = (CLEARED,) + AWARDS

# Stages an incident passes through, in order.
STAGE_NOTED = "noted"
STAGE_INVESTIGATING = "investigating"
STAGE_CLEARED = "cleared"
STAGE_PENALISED = "penalised"

# Phrases removed when building an incident's key, so that the same incident
# keys the same however it was reported. Longest first: "REVIEWED NO FURTHER
# INVESTIGATION" must go before "UNDER INVESTIGATION" can match inside it.
VERDICT_PHRASES = tuple(re.compile(p) for p in (
    r"REVIEWED\s+NO\s+FURTHER\s+INVESTIGATION",
    r"WILL\s+BE\s+INVESTIGATED\s+AFTER\s+THE\s+(?:RACE|SESSION)",
    r"NO\s+FURTHER\s+INVESTIGATION",
    r"UNDER\s+INVESTIGATION",
    r"PENALTY\s+SERVED",
    r"\d+\s+SECOND\s+(?:TIME\s+)?PENALTY",
    r"STOP\s*(?:/|-AND-|-)\s*GO\s+PENALTY",
    r"DRIVE[\s-]THROUGH\s+PENALTY",
    r"\bNOTED\b",
    r"\bINCIDENT\b",
    r"\bINVOLVING\b",
    r"\bFOR\b",
))


@dataclass
class Event:
    """One race control message, read."""
    t: float
    lap: int | None
    kind: str
    seconds: float | None            # the amount, for a time or stop/go penalty
    reason: str | None
    cars: tuple[int, ...]            # every car named, filtered to this session
    incident: str | None             # which incident this belongs to
    message: str

    @property
    def stewards(self) -> bool:
        """
        Whether this came from the stewards rather than from race control.

        Any message carrying a verdict did. The `FIA STEWARDS:` prefix looks like
        the obvious test and is not: it is on 971 of the 3,257 steward messages in
        the lake, so filtering on it would drop **70%** of them - every lap
        deletion and most incident notices carry no prefix at all. Nothing with
        the prefix lacks a verdict, so the verdict is the stronger test and this
        is the same question as "did `_classify` recognise it".
        """
        return self.kind != OTHER

    @property
    def topic(self) -> str:
        """
        Which of the feed's three kinds of message this is.

        `stewards` carries a verdict. `track` is something that happened to the
        race - a safety car, a flag, the pit exit, DRS, a slippery patch, a
        recovery vehicle - of which a race sees 17 or so. `noise` is the rest:
        blue flags and sector flags, 4,771 messages that repeat a state nobody
        reads a log for. Splitting three ways rather than two is what lets a
        track list be short enough to be worth showing.
        """
        if self.stewards:
            return TOPIC_STEWARDS
        return TOPIC_NOISE if NOISE.search(self.message) else TOPIC_TRACK

    def as_dict(self) -> dict:
        return {"t": round(self.t, 2), "lap": self.lap, "kind": self.kind,
                "seconds": self.seconds, "reason": self.reason,
                "cars": list(self.cars), "incident": self.incident,
                "stewards": self.stewards, "topic": self.topic,
                "message": self.message}


@dataclass
class Incident:
    """One thing the stewards are dealing with, and how far along it is."""
    key: str
    stage: str
    reason: str | None
    cars: tuple[int, ...]
    opened_t: float
    updated_t: float

    def as_dict(self) -> dict:
        return {"stage": self.stage, "reason": self.reason, "cars": list(self.cars),
                "opened_t": round(self.opened_t, 2), "updated_t": round(self.updated_t, 2)}


@dataclass
class DriverPenalties:
    """Everything outstanding and everything settled against one car, at `t`."""
    driver_number: int
    pending_s: float = 0.0           # awarded time penalties not yet seen served
    served_s: float = 0.0
    awarded_s: float = 0.0           # pending + served
    stop_go: int = 0                 # awarded and not yet seen served
    drive_through: int = 0
    penalties: int = 0               # penalties awarded, of any kind, ever
    laps_deleted: int = 0
    black_and_white: int = 0
    reprimands: int = 0
    warnings: int = 0
    disqualified: bool = False
    incidents: dict[str, Incident] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)

    @property
    def open_incidents(self) -> list[Incident]:
        """Noted or being investigated, and not yet closed."""
        return [i for i in self.incidents.values()
                if i.stage in (STAGE_NOTED, STAGE_INVESTIGATING)]

    @property
    def under_investigation(self) -> int:
        return sum(1 for i in self.incidents.values() if i.stage == STAGE_INVESTIGATING)

    @property
    def noted(self) -> int:
        return sum(1 for i in self.incidents.values() if i.stage == STAGE_NOTED)

    @property
    def cleared(self) -> int:
        return sum(1 for i in self.incidents.values() if i.stage == STAGE_CLEARED)

    @property
    def outstanding(self) -> bool:
        """Something the car still has to serve, as far as the feed says."""
        return self.pending_s > 0 or self.stop_go > 0 or self.drive_through > 0

    def as_dict(self) -> dict:
        return {
            "driver_number": self.driver_number,
            "pending_s": round(self.pending_s, 1),
            "served_s": round(self.served_s, 1),
            "awarded_s": round(self.awarded_s, 1),
            "stop_go": self.stop_go,
            "drive_through": self.drive_through,
            "penalties": self.penalties,
            "laps_deleted": self.laps_deleted,
            "black_and_white": self.black_and_white,
            "reprimands": self.reprimands,
            "warnings": self.warnings,
            "disqualified": self.disqualified,
            "under_investigation": self.under_investigation,
            "noted": self.noted,
            "cleared": self.cleared,
            "outstanding": self.outstanding,
            "incidents": [i.as_dict() for i in self.incidents.values()],
            "events": [e.as_dict() for e in self.events],
        }


# ------------------------------------------------------------------ reading

def _strip(message: str) -> tuple[str, str | None]:
    """The verdict without its speaker, and the incident stamp it carried."""
    text = str(message or "").strip()
    for prefix in (STEWARDS_PREFIX, CORRECTION_PREFIX):
        if text.upper().startswith(prefix):
            text = text[len(prefix):].strip()
    stamp = INCIDENT_STAMP.search(text)
    if stamp:
        text = text[: stamp.start()].strip()
    return text, (stamp.group(1) if stamp else None)


def _classify(upper: str) -> str:
    """
    Which verdict this message carries.

    Order is the whole correctness of this function. A served penalty contains
    the wording of the award it discharges, and a reason can contain the word
    PENALTY without being one, so the specific cases are tested first.
    """
    if "DELETED" in upper:
        return DELETED
    if SERVED_MARK in upper:
        return SERVED_PENALTY
    if STOP_GO.search(upper):
        return AWARDED_STOP_GO
    if "DRIVE THROUGH" in upper or "DRIVE-THROUGH" in upper:
        return AWARDED_DRIVE_THROUGH
    if SECONDS.search(upper) and "PENALTY" in upper:
        return AWARDED_TIME
    if "REPRIMAND" in upper:
        return REPRIMAND
    if "BLACK AND WHITE" in upper:
        return BLACK_AND_WHITE
    if "BLACK FLAG" in upper:
        return DISQUALIFIED
    if "WARNING" in upper:
        return WARNING
    if "NO FURTHER" in upper:
        return CLEARED
    if "WILL BE INVESTIGATED AFTER" in upper:
        return AFTER_RACE
    if "UNDER INVESTIGATION" in upper:
        return INVESTIGATING
    if "NOTED" in upper:
        return NOTED
    return OTHER


def _reason(text: str, kind: str) -> str | None:
    """
    The offence, which the feed puts after the last dash.

    Not every message carries one: `5 SECOND TIME PENALTY FOR CAR 55 (SAI)`
    arrives with nothing but a stamp. A lap deletion's dash introduces the
    offence too (`DELETED - TRACK LIMITS AT TURN 10`), so one rule reads both.

    A deletion then trails bookkeeping the offence does not need — `TRACK LIMITS
    AT TURN 10 LAP 73 17:20:22 (PIT)` — and the lap and the time are already
    columns of their own, so that is cut off rather than shown twice.
    """
    if " - " not in text:
        return None
    tail = DELETION_TAIL.sub("", text.rsplit(" - ", 1)[1].strip()).strip()
    # `PENALTY SERVED - DRIVE THROUGH PENALTY FOR CAR 11 (PER)` with no offence
    # would otherwise read the award itself as the reason.
    if kind == SERVED_PENALTY and "PENALTY" in tail.upper() and CAR.search(tail):
        return None
    return tail or None


def _cars(text: str, known: frozenset[int], teams: dict[str, tuple[int, ...]]) -> tuple[int, ...]:
    """
    Every car of this session that the message names, in the order written.

    Clock stamps and lap times go first, or `... 18:58:59 (PIT)` reads as car
    59. Then a number is only a car if it is one of this session's: that is what
    rejects `CAR 26 (BED)`, a real car in another championship sharing the feed.

    A few messages name a team instead - `INCIDENT INVOLVING MCLAREN NOTED` -
    and mean that team's cars. That is only looked for when no car was spelled
    out, since a message naming both means the car.
    """
    scrubbed = CLOCK.sub(" ", LAP_TIME.sub(" ", text))
    found = [int(number) for number, _ in CAR.findall(scrubbed)]
    cars = tuple(dict.fromkeys(n for n in found if not known or n in known))
    if cars:
        return cars
    upper = text.upper()
    for name, numbers in teams.items():
        if name and name in upper:
            return numbers
    return ()


def _incident_key(text: str, cars: tuple[int, ...], stamp: str | None) -> str:
    """
    A key that is the same for every message about one incident.

    The feed's own stamp when there is one; otherwise the message with its
    verdict, its car spellings and its punctuation taken out, which leaves the
    place and the offence - the parts that do not change as an incident moves.
    """
    if stamp:
        return f"@{stamp}"
    body = CAR.sub(" ", CLOCK.sub(" ", LAP_TIME.sub(" ", text.upper())))
    for phrase in VERDICT_PHRASES:
        body = phrase.sub(" ", body)
    body = re.sub(r"[^A-Z0-9 ]+", " ", body)
    body = re.sub(r"\s+", " ", body).strip()
    return f"{sorted(cars)}|{body}"


def read(message: str, t: float, lap: int | None,
         known: frozenset[int] = frozenset(),
         teams: dict[str, tuple[int, ...]] | None = None) -> Event:
    """One message, as an `Event`. Exposed so it can be tested on the real feed."""
    text, stamp = _strip(message)
    upper = text.upper()
    kind = _classify(upper)
    amount = SECONDS.search(upper)
    cars = _cars(text, known, teams or {})
    return Event(
        t=float(t),
        lap=lap,
        kind=kind,
        seconds=(float(amount.group(1)) if amount and kind in
                 (AWARDED_TIME, AWARDED_STOP_GO, SERVED_PENALTY) else None),
        reason=_reason(text, kind),
        cars=cars,
        incident=(_incident_key(text, cars, stamp)
                  if kind in OPENS + PROGRESSES + CLOSES + (SERVED_PENALTY,) else None),
        message=str(message or ""),
    )


# ------------------------------------------------------------------ folding

def _match_incident(state: DriverPenalties, event: Event) -> Incident | None:
    """
    The open incident this verdict is about.

    The key matches outright when the feed stamped it or when the place and
    offence were written the same way, which covers every message that reports
    an incident with the same cars.

    A verdict that *closes* one may name fewer cars than the notice did - a
    two-car collision penalising one of them - so those are also allowed to
    attach to an open incident whose cars theirs are a subset of, with the same
    offence. Both halves of that test are needed. Matching on the offence alone
    put two separate collisions together in 2026 Spain, where SAI was in a
    TURN 8 incident with COL and another with HUL twenty seconds apart: the
    second notice merged into the first and was cleared by the first's verdict.
    A notice never falls back, because a combination of cars not seen before is
    a new incident by definition.
    """
    existing = state.incidents.get(event.incident or "")
    if existing is not None:
        return existing
    if event.kind not in CLOSES or not event.reason:
        return None
    reason = event.reason.upper()
    cars = set(event.cars)
    for incident in reversed(state.open_incidents):
        if (incident.reason and incident.reason.upper() == reason
                and cars and cars.issubset(set(incident.cars))):
            return incident
    return None


def _apply(state: DriverPenalties, event: Event) -> None:
    """Fold one event into one car's running state."""
    kind = event.kind
    if kind == OTHER:
        # Blue flags, DRS notices and the like name a car without saying
        # anything about it. They belong in the ticker, not against the driver.
        return
    state.events.append(event)

    if kind == DELETED:
        state.laps_deleted += 1
        return
    if kind == BLACK_AND_WHITE:
        state.black_and_white += 1
        return
    if kind == REPRIMAND:
        state.reprimands += 1
        return
    if kind == WARNING:
        state.warnings += 1
        return
    if kind == DISQUALIFIED:
        state.disqualified = True
        return

    if kind == SERVED_PENALTY:
        seconds = event.seconds or 0.0
        # A served stop/go carries its ten seconds too, so what to clear is
        # decided by what the car actually has outstanding, not by the wording.
        if seconds and state.pending_s > 0:
            moved = min(seconds, state.pending_s)
            state.pending_s -= moved
            state.served_s += moved
        elif state.stop_go > 0:
            state.stop_go -= 1
            state.served_s += seconds
        elif state.drive_through > 0:
            state.drive_through -= 1
        else:
            # Served without the award having been seen: carried in from
            # qualifying, or a message the feed dropped. Counted, not lost.
            state.served_s += seconds
        return

    incident = _match_incident(state, event)
    if incident is None and event.incident:
        incident = Incident(key=event.incident, stage=STAGE_NOTED, reason=event.reason,
                            cars=event.cars, opened_t=event.t, updated_t=event.t)
        state.incidents[event.incident] = incident

    if kind in AWARDS:
        if kind == AWARDED_TIME:
            seconds = event.seconds or 0.0
            state.pending_s += seconds
            state.awarded_s += seconds
        elif kind == AWARDED_STOP_GO:
            state.stop_go += 1
        else:
            state.drive_through += 1
        state.penalties += 1
        if incident is not None:
            incident.stage, incident.updated_t = STAGE_PENALISED, event.t
        return

    if incident is None:
        return
    if kind == NOTED and incident.stage == STAGE_NOTED:
        incident.updated_t = event.t
    elif kind in PROGRESSES:
        incident.stage, incident.updated_t = STAGE_INVESTIGATING, event.t
    elif kind == CLEARED:
        incident.stage, incident.updated_t = STAGE_CLEARED, event.t


def _team_index(drivers: pd.DataFrame | None) -> dict[str, tuple[int, ...]]:
    """Upper-cased team name -> its car numbers, for team-level messages."""
    if drivers is None or drivers.empty or "team_name" not in drivers:
        return {}
    out: dict[str, list[int]] = {}
    for row in drivers.itertuples(index=False):
        name = str(getattr(row, "team_name", "") or "").strip().upper()
        if name:
            out.setdefault(name, []).append(int(row.driver_number))
    # Longest first, so a short team name cannot match inside a longer one.
    return {name: tuple(sorted(numbers))
            for name, numbers in sorted(out.items(), key=lambda kv: -len(kv[0]))}


def _known(drivers: pd.DataFrame | None) -> frozenset[int]:
    if drivers is None or drivers.empty or "driver_number" not in drivers:
        return frozenset()
    numbers = pd.to_numeric(drivers["driver_number"], errors="coerce").dropna()
    return frozenset(int(n) for n in numbers)


def _events(race_control: pd.DataFrame, drivers: pd.DataFrame | None,
            t: float) -> list[Event]:
    """Every message up to `t`, read, in the order it arrived."""
    teams, known = _team_index(drivers), _known(drivers)
    past = race_control[race_control["t"].notna() & (race_control["t"] <= t)]
    out = []
    for row in past.sort_values("t").itertuples(index=False):
        lap = getattr(row, "lap", None)
        out.append(read(row.message, row.t,
                        None if lap is None or pd.isna(lap) else int(lap),
                        known, teams))
    return out


def state_at(race_control: pd.DataFrame, drivers: pd.DataFrame | None,
             t: float) -> dict[int, DriverPenalties]:
    """
    Every car's penalty state as of session time `t`.

    Messages after `t` do not exist yet, which is the point: at lap 12 the tower
    shows what was known at lap 12, whether the clock arrived there by playing
    forward or by being dragged back.
    """
    out: dict[int, DriverPenalties] = {}
    if race_control is None or race_control.empty:
        return out
    for event in _events(race_control, drivers, t):
        for number in event.cars:
            out.setdefault(number, DriverPenalties(driver_number=number))
            _apply(out[number], event)
    return {number: state for number, state in out.items() if state.events}


def feed(race_control: pd.DataFrame, drivers: pd.DataFrame | None, t: float,
         limit: int = 40, topic: str | None = None) -> list[dict]:
    """
    The messages themselves up to `t`, newest first, read rather than raw.

    `topic` selects one of `stewards`, `track` or `noise`; None returns all
    three. The filter is applied before `limit`, so asking for the stewards' last
    twenty gets twenty of theirs rather than twenty of everything, of which six
    happen to be theirs.

    The original string is kept on every entry, so nothing is lost to the parse.
    """
    if race_control is None or race_control.empty:
        return []
    teams, known = _team_index(drivers), _known(drivers)
    past = race_control[race_control["t"].notna() & (race_control["t"] <= t)]
    out = []
    for row in past.sort_values("t").itertuples(index=False):
        lap = getattr(row, "lap", None)
        event = read(row.message, row.t,
                     None if lap is None or pd.isna(lap) else int(lap), known, teams)
        if topic is not None and event.topic != topic:
            continue
        entry = event.as_dict()
        entry["category"] = _text_or_none(getattr(row, "category", None))
        entry["flag"] = _text_or_none(getattr(row, "flag", None))
        entry["scope"] = _text_or_none(getattr(row, "scope", None))
        out.append(entry)
    return list(reversed(out[-limit:]))


def _text_or_none(value) -> str | None:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    return None if pd.isna(value) else str(value)


# ------------------------------------------------------------ pit-lane cost

def penalised_stops(laps: pd.DataFrame, race_control: pd.DataFrame,
                    drivers: pd.DataFrame | None = None) -> frozenset[tuple[str, int, int]]:
    """
    Pit stops that carried a penalty, as (session_key, driver_number, in-lap number).

    A time penalty is served at the car's next stop — the car is held for five or
    ten seconds before anyone touches it — and a stop/go or drive-through is a
    trip down the lane of its own. Either way that stop is not a measurement of
    what the pit lane costs, and `model/circuit.pit_loss` must not average it in.
    Across the lake this marks 107 stops, of which 70 were green-flag stops in
    the pit-loss sample: 1,954 fall to 1,884. The ones first found by the plain
    rule ran 8.4 s dearer than a clean stop on average, and leaving them out
    moves Montréal's pit loss by 0.65 s and no other circuit by more than 0.2 s.

    This is decided from timing, not judged: the rule is in the regulations, and
    tested against the 40 penalties the feed itself marks `PENALTY SERVED` it
    never contradicts them. 34 were served at the very next stop. The rest are
    covered by two refinements, both measured:

    * a stop counts only if its in-lap *started* after the award, because a
      penalty handed down while the car is already on its in-lap moves to the
      following stop (2025 round 9, car 23);
    * the first *green-flag* stop after the award is excluded as well as the
      first stop of any kind, because at 2026 Spain penalties went unserved at
      stops made under the safety car and red flag.

    When the feed does say `PENALTY SERVED`, the stop just before that message
    is excluded too. The rule leans towards excluding on purpose: dropping a
    clean stop costs one sample of dozens, and keeping a penalised one biases
    the median.
    """
    if laps is None or laps.empty or race_control is None or race_control.empty:
        return frozenset()
    needed = {"session_key", "driver_number", "lap_number", "is_pit_in_lap"}
    if not needed.issubset(laps.columns):
        return frozenset()

    known = _known(drivers) if drivers is not None else frozenset(
        int(n) for n in pd.to_numeric(laps["driver_number"], errors="coerce").dropna())
    stops = laps[laps["is_pit_in_lap"].fillna(False).astype(bool)]
    if stops.empty:
        return frozenset()
    starts = stops["lap_start_t"] if "lap_start_t" in stops else pd.Series(np.nan, index=stops.index)
    ends = stops["lap_end_t"] if "lap_end_t" in stops else pd.Series(np.nan, index=stops.index)
    stops = stops.assign(_start=starts.fillna(ends), _end=ends.fillna(starts),
                         _green=(stops["track_status"].astype(str) == "1")
                         if "track_status" in stops else False)

    out: set[tuple[str, int, int]] = set()
    rc = race_control[race_control["session_key"].isin(set(stops["session_key"]))] \
        if "session_key" in race_control else race_control
    for session_key, messages in rc.groupby("session_key"):
        here = stops[stops["session_key"] == session_key]
        if here.empty:
            continue
        for row in messages.sort_values("t").itertuples(index=False):
            if row.t is None or pd.isna(row.t):
                continue
            event = read(row.message, row.t, None, known)
            if event.kind not in AWARDS + (SERVED_PENALTY,):
                continue
            for car in event.cars:
                mine = here[here["driver_number"] == car]
                if mine.empty:
                    continue
                if event.kind == SERVED_PENALTY:
                    before = mine[mine["_end"] <= event.t].sort_values("_end")
                    if len(before):
                        out.add((session_key, int(car), int(before["lap_number"].iloc[-1])))
                    continue
                after = mine[mine["_start"] > event.t].sort_values("_start")
                if len(after):
                    out.add((session_key, int(car), int(after["lap_number"].iloc[0])))
                green = after[after["_green"]]
                if len(green):
                    out.add((session_key, int(car), int(green["lap_number"].iloc[0])))
    return frozenset(out)


def penalised_stops_in(con, laps: pd.DataFrame) -> frozenset[tuple[str, int, int]]:
    """`penalised_stops` for laps read from the lake, fetching the race control it needs."""
    if laps is None or laps.empty or "session_key" not in laps:
        return frozenset()
    keys = sorted({str(k) for k in laps["session_key"].dropna()})
    if not keys:
        return frozenset()
    quoted = ", ".join("'" + k.replace("'", "") + "'" for k in keys)
    try:
        rc = con.sql(f"""select session_key, t, message from race_control
                         where session_key in ({quoted}) and message is not null""").df()
    except duckdb.CatalogException:         # a lake ingested before race control was stored
        return frozenset()
    return penalised_stops(laps, rc)
