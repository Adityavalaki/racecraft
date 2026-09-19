"""
Which of Pirelli's compounds each label was, race by race.

The feed says SOFT, MEDIUM or HARD. Pirelli brings three of its six compounds
to each race, C1 the hardest, and the labels follow: at Silverstone the medium
is a C2, at Baku it can be a C5. `pirelli_compounds.csv`, beside this module, has every race in
the lake, each row with the Pirelli release it was read from.

It is shown, not fitted on. Predicting a race's tyre wear from the compound
does worse than from the label (scripts/compare_compounds.py): Pirelli chooses
each weekend's compounds so that the labels behave alike, and they do.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

TABLE = Path(__file__).resolve().parent / "pirelli_compounds.csv"
LABELS = ("HARD", "MEDIUM", "SOFT")


@lru_cache(maxsize=1)
def _table() -> pd.DataFrame:
    if not TABLE.exists():
        return pd.DataFrame(columns=["year", "round", "race", "hard", "medium", "soft", "source"])
    return pd.read_csv(TABLE)


def for_race(year: int, round_number: int | None = None, race: str | None = None) -> dict | None:
    """
    {"HARD": "C3", "MEDIUM": "C4", "SOFT": "C5", "source": url} for one race, or None.

    By round when the race is in the lake; by name for one that is not yet,
    whose round the table may not know.
    """
    table = _table()
    rows = table[table["year"] == year]
    if round_number is not None:
        match = rows[rows["round"] == round_number]
    elif race is not None:
        match = rows[rows["race"].str.lower() == race.lower()]
    else:
        return None
    if len(match) != 1:
        return None
    row = match.iloc[0]
    return {"HARD": row["hard"], "MEDIUM": row["medium"], "SOFT": row["soft"], "source": row["source"]}
