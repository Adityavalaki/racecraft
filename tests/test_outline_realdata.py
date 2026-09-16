"""
Track outline checks against the real lake.

These are skipped when the lake is missing, so the suite still runs anywhere.
They exist because the outline is geometry: the only way to know it is right
is to measure it against the published length of the circuit it claims to be.
"""

import numpy as np
import pytest

from racecraft.api import session
from racecraft.store import lake

# Official circuit lengths in km.
CIRCUITS = [
    ("2024_01_R", "Bahrain", 5.412),
    ("2025_08_R", "Monaco", 3.337),
    ("2024_12_R", "Silverstone", 5.891),
    ("2025_16_R", "Monza", 5.793),
]

pytestmark = pytest.mark.realdata


def _load(key: str):
    year, rnd, code = key.split("_")
    if not lake.is_ingested(int(year), int(rnd), code):
        pytest.skip(f"{key} is not in the lake")
    return session.load(key)


@pytest.mark.parametrize("key,name,official_km", CIRCUITS)
def test_outline_matches_the_real_circuit_length(key, name, official_km):
    data = _load(key)
    points = np.array(data.outline)
    assert len(points) > 100, f"{name}: outline too sparse"

    steps = np.hypot(np.diff(points[:, 0]), np.diff(points[:, 1]))
    measured_km = steps.sum() / 10 / 1000        # coordinates are tenths of a metre

    # The racing line cuts inside the centreline, so the trace is slightly
    # shorter than the published length. Much shorter means a dropout has been
    # bridged by a straight chord; longer means the line is wandering.
    error = (measured_km - official_km) / official_km
    assert -0.04 < error < 0.01, f"{name}: outline {measured_km:.3f} km vs official {official_km:.3f} km ({error:+.1%})"


@pytest.mark.parametrize("key,name,official_km", CIRCUITS)
def test_outline_is_closed_and_evenly_spaced(key, name, official_km):
    data = _load(key)
    points = np.array(data.outline)
    steps = np.hypot(np.diff(points[:, 0]), np.diff(points[:, 1]))

    assert np.hypot(*(points[0] - points[-1])) < 1.0, f"{name}: outline does not close"
    # Resampling by distance should leave no step far larger than the rest;
    # a big one would be a chord cutting across a corner.
    assert steps.max() < 8 * np.median(steps), f"{name}: step of {steps.max():.0f} against median {np.median(steps):.0f}"


def test_a_session_without_position_data_has_no_outline():
    # 2026 Monaco lost its position feed before the race; the map must be
    # empty rather than a shape invented from a handful of samples.
    data = _load("2026_06_R")
    assert data.outline == []
    assert data.state(data.t_start + 1000)["cars"], "timing should still work without positions"
