"""
Pit windows and undercut odds, at a moment in a race, for the Strategy screen.

Built from the same held-out fit the strategy model uses (`insight`): tyre
wear and compound pace from this season's earlier races, the pit lane from
earlier races at this circuit. What each car is on, how old it is and the
gaps come from the timing at the clock's time, so nothing after it is used.

For each running car: the stop lap that loses least over the rest of the race,
and every lap within two seconds of it. For each car within three seconds of
the one ahead: the chance that stopping first gets it the place.
"""

from __future__ import annotations

import pandas as pd

from racecraft.api import insight
from racecraft.api import session as session_store
from racecraft.model import strategy

UNDERCUT_RANGE_S = 3.0
DRY = {"SOFT", "MEDIUM", "HARD"}

NOTES = [
    "Windows are the stop laps within two seconds of the cheapest, from the strategy model's held-out tyre wear.",
    "Undercut odds count one lap on fresh tyres against the rival's old set, and the scatter of two pit stops. "
    "The out-lap on cold tyres and traffic on rejoining are not modelled, so they flatter the undercut a little.",
]


class NoStrategy(RuntimeError):
    """Not a race, or the model has nothing to work from. The message says why."""


def for_session(session_key: str, t: float) -> dict:
    model = insight.for_session(session_key)
    if not model.get("is_race"):
        raise NoStrategy("pit windows are for races")
    degradation = model.get("degradation_used") or {}
    offsets = model.get("compound_offset_s") or {}
    pit = model.get("pit_loss") or {}
    if not degradation or not pit:
        raise NoStrategy("no tyre wear or pit lane measured for this race yet")
    pit_loss, pit_spread = float(pit["seconds"]), float(pit.get("spread_s") or 0.0)

    data = session_store.load(session_key)
    state = data.state(t)
    total = int(model.get("total_laps") or data.meta.get("total_laps") or 0)
    used = _compounds_run(data.laps, t)

    cars, windows = [], {}
    for row in state["drivers"]:
        number = int(row["driver_number"])
        compound, age, done = row.get("compound"), row.get("tyre_life"), int(row.get("laps_completed") or 0)
        entry = {"driver_number": number, "abbreviation": row.get("abbreviation"), "team_color": row.get("team_color"),
                 "position": row.get("position"), "status": row.get("status"), "compound": compound, "age": age,
                 "laps_completed": done, "stops": row.get("stops"), "used": sorted(used.get(number, set())),
                 "window": None}
        if row.get("status") == "racing" and compound in DRY and age is not None and done > 0:
            window = strategy.stop_window(total, done, compound, int(age), degradation, pit_loss, offsets,
                                          used.get(number, set()))
            if window is not None:
                entry["window"] = window.as_dict()
                windows[number] = window
        cars.append(entry)

    undercuts = []
    order = [r for r in state["drivers"] if r.get("status") == "racing"]
    for ahead, behind in zip(order, order[1:]):
        gap = behind.get("interval_s")
        chaser = windows.get(int(behind["driver_number"]))
        if gap is None or gap > UNDERCUT_RANGE_S or chaser is None or chaser.no_stop:
            continue
        if ahead.get("compound") not in DRY or ahead.get("tyre_life") is None:
            continue
        gain = strategy.undercut_gain(ahead["compound"], int(ahead["tyre_life"]), chaser.next_compound,
                                      degradation, offsets)
        undercuts.append({
            "chaser": int(behind["driver_number"]), "target": int(ahead["driver_number"]),
            "gap_s": round(float(gap), 3), "gain_s": round(gain, 3),
            "chance": round(strategy.undercut_chance(float(gap), gain, pit_spread), 3),
            "fresh_compound": chaser.next_compound,
        })
    undercuts.sort(key=lambda u: -u["chance"])

    return {
        "session_key": session_key,
        "t": t,
        "lap": state["leader_lap"],
        "total_laps": total,
        "model": {"degradation": degradation, "compound_offset_s": offsets, "pit_loss_s": pit_loss,
                  "pit_spread_s": pit_spread, "fitted_on_count": model.get("fitted_on_count"),
                  "held_out": model.get("held_out")},
        "cars": cars,
        "undercuts": undercuts,
        "notes": NOTES,
    }


def _compounds_run(laps: pd.DataFrame, t: float) -> dict[int, set[str]]:
    """Each car's dry compounds on laps it had finished by `t`: the two-compound rule, so far."""
    if laps.empty:
        return {}
    done = laps[laps["lap_end_t"].notna() & (laps["lap_end_t"] <= t) & laps["compound"].isin(DRY)]
    return {int(n): set(group["compound"]) for n, group in done.groupby("driver_number")}
