"""Telling F1's sign-in wall apart from a session with no data (since October 2026)."""

from __future__ import annotations

import fastf1
import pytest
import requests

from racecraft.ingest import cli, fastf1_source, openf1_source, tracinginsights_source


class _Session:
    """What FastF1 hands back when the archive gave it nothing: laps were never loaded."""
    api_path = "/static/2026/2026-10-25_United_States_Grand_Prix/2026-10-23_Practice_1/"

    def load(self, **kwargs):
        pass

    @property
    def laps(self):
        raise fastf1.exceptions.DataNotLoadedError("The data you are trying to access has not been loaded yet")


@pytest.fixture
def no_laps(monkeypatch):
    monkeypatch.setattr(fastf1, "get_session", lambda *a: _Session())


def _answer(monkeypatch, status=None, error=None):
    asked = []

    def get(url, timeout):
        asked.append(url)
        if error:
            raise error
        return type("Response", (), {"status_code": status})()

    monkeypatch.setattr(fastf1_source.requests, "get", get)
    return asked


def test_a_401_from_the_archive_is_the_sign_in_wall(no_laps, monkeypatch):
    asked = _answer(monkeypatch, status=401)
    with pytest.raises(fastf1_source.ArchiveLocked, match="F1 TV"):
        fastf1_source.load_session(2026, 18, "Practice 1")
    assert asked == [fastf1_source.ARCHIVE + _Session.api_path + "SessionInfo.json"]


@pytest.mark.parametrize("status, error", [(200, None), (404, None), (None, requests.ConnectionError("offline"))])
def test_no_laps_without_the_wall_is_left_as_before(no_laps, monkeypatch, status, error):
    _answer(monkeypatch, status=status, error=error)
    assert isinstance(fastf1_source.load_session(2026, 18, "Practice 1"), _Session)


def test_a_session_no_source_has_is_reported_not_raised(no_laps, monkeypatch):
    def missing(*a, **k):
        raise openf1_source.NotAvailable("OpenF1 has no drivers for 2026_18_FP1 yet")

    _answer(monkeypatch, status=401)
    monkeypatch.setattr(openf1_source, "extract", missing)
    monkeypatch.setattr(tracinginsights_source, "extract", lambda *a: None)     # not published yet either
    assert cli._ingest_locked(2026, 18, "FP1", "Practice 1", "2026_18_FP1",
                              telemetry=False, force=False, prune=False) == "locked"
