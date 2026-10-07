"""
Feature windows, without opening any.

Each feature opens in a window of its own that follows the replay. What is
pinned here: only known features open, one window per feature (asking again
brings it forward), the URL carries where the window starts, and every feature
window closes with the replay.
"""

from urllib.parse import parse_qs, urlparse

import pytest

from racecraft.app.windows import FEATURES, FeatureWindows


class FakeEvent(list):
    def __iadd__(self, handler):
        self.append(handler)
        return self

    def fire(self):
        for handler in list(self):
            handler()


class FakeWindow:
    def __init__(self, title, url, **options):
        self.title, self.url, self.options = title, url, options
        self.destroyed = False
        self.events = type("Events", (), {"closed": FakeEvent()})()

    def destroy(self):
        self.destroyed = True
        self.events.closed.fire()


@pytest.fixture
def made():
    return []


@pytest.fixture
def windows(made):
    def create(title, url, **options):
        window = FakeWindow(title, url, **options)
        made.append(window)
        return window

    forward = []
    manager = FeatureWindows("http://127.0.0.1:5555/", create, bring_forward=forward.append)
    manager.forwarded = forward
    return manager


def test_a_feature_opens_a_window_at_its_own_url(windows, made):
    assert windows.open("strategy", "2024_01_R") == {"feature": "strategy", "opened": True}
    assert len(made) == 1
    url = urlparse(made[0].url)
    assert (url.scheme, url.netloc, url.path) == ("http", "127.0.0.1:5555", "/")
    assert parse_qs(url.query) == {"feature": ["strategy"], "session": ["2024_01_R"]}
    assert made[0].title == "Racecraft · Strategy"


def test_asking_again_brings_the_open_window_forward_instead_of_another(windows, made):
    windows.open("tower", "2024_01_R")
    assert windows.open("tower", "2024_01_R") == {"feature": "tower", "opened": False}
    assert len(made) == 1
    assert windows.forwarded == [made[0]]


def test_a_closed_window_can_be_opened_again(windows, made):
    windows.open("trace", "live")
    made[0].events.closed.fire()                     # the user closed it
    assert windows.open_features == []
    windows.open("trace", "live")
    assert len(made) == 2


@pytest.mark.parametrize("feature", ["", "map", "../tower", "tower?x=1"])
def test_only_known_features_open(windows, made, feature):
    with pytest.raises(ValueError):
        windows.open(feature, "2024_01_R")
    assert made == []


@pytest.mark.parametrize("session", ["", "2024_01_R&x=1", "a b", "../x", "x" * 41])
def test_a_strange_session_code_never_reaches_a_url(windows, made, session):
    with pytest.raises(ValueError):
        windows.open("tower", session)
    assert made == []


def test_every_feature_window_closes_with_the_replay(windows, made):
    for feature in ("tower", "strategy", "stewards"):
        windows.open(feature, "2024_01_R")
    windows.close_all()
    assert all(window.destroyed for window in made)
    assert windows.open_features == []


def test_the_page_and_the_app_agree_on_the_features():
    """web/src/features.ts lists the same ids; a feature missing from either opens nothing."""
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "web" / "src" / "features.ts").read_text(encoding="utf-8")
    for feature in FEATURES:
        assert f'id: "{feature}"' in source, f"{feature} is not in features.ts"
