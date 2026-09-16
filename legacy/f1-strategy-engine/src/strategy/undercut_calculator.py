"""
Real-time undercut/overcut probability — the piece that turns this from a
model into a strategy TOOL usable during a live session.

Core logic (standard race-engineering math, made explicit and testable):

An undercut works if:
    fresh_tyre_pace_advantage * laps_before_rival_pits > gap_to_target

In plain terms: you pit first, your rival pits a lap or two later. Both of
you pay the same pit loss, so it cancels. What decides it is the time you
gain on fresh tyres during the laps your rival is still circulating on old
ones. If that gain is bigger than the gap, you come out ahead.

Bug this fixes: the previous formula was `gap - pit_loss + pace_gain`,
which counted the pit stop as time GAINED. With a typical 22 s pit loss
dominating every other term, a 15 s gap with 0.1 s/lap of tyre advantage
reported "succeeds, confidence 0.95". Pit loss only enters the maths when
the rival does not stop at all, which is a different strategy (an offset),
not an undercut.
"""

import os
import sys
from dataclasses import dataclass

sys.path.append(os.path.join(os.path.dirname(__file__), "..", ".."))
from src.features.pit_loss import get_pit_loss_for
from src.features.tyre_degradation import predict_lap_time


@dataclass
class UndercutInput:
    gap_to_target_s: float          # current gap to the car you're undercutting
    pit_loss_s: float                # estimated pit loss for this track/team
    target_tyre_age: int             # rival's current tyre age (laps)
    fresh_tyre_pace_advantage_s: float  # per-lap pace gain of new vs old tyres
    laps_of_advantage: int = 2       # how many laps the fresh-tyre advantage holds


def undercut_probability(inp: UndercutInput) -> dict:
    """
    Returns the projected time delta after the undercut window and a
    simple probability estimate. This is intentionally a transparent
    formula, not a black-box model — race engineers need to see the
    reasoning, not just a score.
    """
    total_pace_gain = inp.fresh_tyre_pace_advantage_s * inp.laps_of_advantage
    # Both cars stop, so pit_loss_s cancels out of the head-to-head. It is kept
    # on the input because it still decides where you rejoin relative to traffic.
    net_position_after = inp.gap_to_target_s - total_pace_gain

    # net_position_after < 0 means you come out ahead
    succeeds = net_position_after < 0
    margin_s = -net_position_after  # positive = you gain track position by this margin

    # crude confidence heuristic: bigger margin = more confident.
    # This is NOT a calibrated probability — say so if you present it as one.
    confidence = min(0.95, max(0.05, 0.5 + margin_s / 10))

    return {
        "succeeds": succeeds,
        "margin_seconds": round(margin_s, 2),
        "confidence_estimate": round(confidence, 2),
        "note": "confidence_estimate is a heuristic, not a calibrated probability "
                "— calibrate it properly against backtested real undercuts before "
                "presenting it as a real probability in your write-up.",
    }


@dataclass
class OvercutInput:
    gap_to_target_s: float              # current gap to the rival who just pitted (+ = they're ahead)
    pit_loss_s: float                    # pit loss the rival incurred
    own_pace_deficit_s: float            # your extra time/lap on old tyres vs their fresh tyres
    laps_staying_out: int = 2            # how many laps longer you stay out before pitting


def overcut_probability(inp: OvercutInput) -> dict:
    """
    Symmetric case to undercut_probability(): here YOU stay out while the
    rival pits first, then you pit. Both stops cost the same, so pit loss
    cancels (the previous formula credited you with the rival's stop and
    never charged you for your own). You lose `own_pace_deficit_s` per lap
    while staying out on old tyres.

    Consequence worth knowing: with a positive deficit this can never pass a
    car ahead. That's correct for this simple model. Real overcuts work when
    fresh tyres are slow to warm up (a NEGATIVE deficit on the rival's out
    lap) or the rival rejoins in traffic, neither of which is modelled here.
    """
    total_pace_loss = inp.own_pace_deficit_s * inp.laps_staying_out
    net_position_after = inp.gap_to_target_s + total_pace_loss

    succeeds = net_position_after < 0
    margin_s = -net_position_after
    confidence = min(0.95, max(0.05, 0.5 + margin_s / 10))

    return {
        "succeeds": succeeds,
        "margin_seconds": round(margin_s, 2),
        "confidence_estimate": round(confidence, 2),
        "note": "confidence_estimate is a heuristic, not a calibrated probability "
                "— same caveat as undercut_probability().",
    }


def auto_fill_from_data(session_key, own_driver_number: int, target_driver_number: int,
                         current_lap: int, team: str, gp: str, pit_loss_df,
                         fresh_tyre_pace_advantage_s: float = 1.0,
                         laps_of_advantage: int = 2) -> "UndercutInput":
    """
    Builds an UndercutInput automatically from live OpenF1 data instead of
    requiring every field typed in by hand during a live session.

    fresh_tyre_pace_advantage_s currently defaults to a generic 1.0s/lap —
    this is a placeholder, not a real per-compound/per-track number. Replace
    it by passing in a value derived from predict_lap_time() on a fitted
    degradation model for the current compound/track once you have one
    available at inference time. Using the generic default without
    overriding it will make the tool's recommendations track-agnostic in a
    way real strategists would immediately notice as wrong.

    Requires network access to OpenF1 at call time — not usable in this
    sandbox, only when run against a live/recent session.
    """
    from src.data import openf1_client

    intervals = openf1_client.get_live_intervals(session_key)
    own_row = intervals[intervals["driver_number"] == own_driver_number]
    target_row = intervals[intervals["driver_number"] == target_driver_number]
    if own_row.empty or target_row.empty:
        raise ValueError("Could not find interval data for one or both drivers.")

    # gap_to_leader is a float for normal gaps but a STRING like "+1 LAP"
    # for lapped cars (confirmed against OpenF1's docs) — a bare float()
    # would crash the whole calculator the first time it's used on a
    # lapped car, which during a real race is common, not an edge case.
    def _parse_gap(val):
        if isinstance(val, (int, float)):
            return float(val)
        raise ValueError(
            f"gap_to_leader is '{val}', not a plain number (likely a lapped "
            f"car showing '+1 LAP' or similar). The undercut/overcut math "
            f"here assumes both cars are on the lead lap — decide explicitly "
            f"how you want to handle a lapped-car scenario before using "
            f"this calculator on one; don't silently coerce it to a number."
        )

    gap_to_target = abs(
        _parse_gap(own_row["gap_to_leader"].iloc[-1])
        - _parse_gap(target_row["gap_to_leader"].iloc[-1])
    )

    stints = openf1_client.get_stints(session_key)
    target_stints = stints[stints["driver_number"] == target_driver_number].sort_values("lap_start")
    if target_stints.empty:
        raise ValueError(f"No stint data for driver {target_driver_number}.")
    latest_stint = target_stints.iloc[-1]
    target_tyre_age = int(latest_stint["tyre_age_at_start"]) + (
        current_lap - int(latest_stint["lap_start"])
    )

    pit_loss_s = get_pit_loss_for(team, gp, pit_loss_df)

    return UndercutInput(
        gap_to_target_s=gap_to_target,
        pit_loss_s=pit_loss_s,
        target_tyre_age=target_tyre_age,
        fresh_tyre_pace_advantage_s=fresh_tyre_pace_advantage_s,
        laps_of_advantage=laps_of_advantage,
    )


if __name__ == "__main__":
    example = UndercutInput(
        gap_to_target_s=1.8,
        pit_loss_s=22.0,
        target_tyre_age=18,
        fresh_tyre_pace_advantage_s=1.1,
        laps_of_advantage=3,
    )
    print(undercut_probability(example))
