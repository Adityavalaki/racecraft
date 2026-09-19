"""
Pirelli's compound nominations, and the rule that keeps the table honest.

Every race in the lake has a row, and every row names the release it was read
from. A lower C-number is always the harder compound, so a row whose labels run
the other way is a typing error, not a nomination.
"""

import pandas as pd
import pytest

from racecraft.model import compounds


def test_every_row_is_ordered_hardest_first_and_sourced():
    table = pd.read_csv(compounds.TABLE)
    for row in table.itertuples():
        hard, medium, soft = (int(c[1:]) for c in (row.hard, row.medium, row.soft))
        assert hard < medium < soft, (row.year, row.race)
        assert 0 <= hard and soft <= 6, (row.year, row.race)
        assert str(row.source).startswith("https://"), (row.year, row.race)
    assert not table.dropna(subset=["round"]).duplicated(["year", "round"]).any()


def test_a_race_is_found_by_round_or_by_name():
    baku = compounds.for_race(2025, 17)
    assert baku["HARD"] == "C4" and baku["SOFT"] == "C6"
    # Baku 2026 is not in the lake yet, so its round is not known here.
    assert compounds.for_race(2026, race="Azerbaijan")["MEDIUM"] == "C4"


def test_a_non_consecutive_nomination_is_kept_as_announced():
    """Belgium 2025 skipped the C2: hard C1, medium C3."""
    spa = compounds.for_race(2025, 13)
    assert (spa["HARD"], spa["MEDIUM"], spa["SOFT"]) == ("C1", "C3", "C4")


@pytest.mark.parametrize("year, round_number", [(1999, 1), (2025, 99)])
def test_an_unknown_race_is_none(year, round_number):
    assert compounds.for_race(year, round_number) is None
