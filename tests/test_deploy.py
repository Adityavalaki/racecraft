"""
Running somewhere other than a laptop.

Two things have to hold for a deployment to be worth making. A lake without
telemetry has to serve everything except the track map — which is what makes it
23 MB instead of 1.5 GB, and therefore hostable at all. And an ingest started
from the interface has to report what it is doing, because on a deployment
nobody is watching a terminal.

The third thing is the one that bites quietly: on hosting whose filesystem is
rebuilt on restart, an ingest that is not pushed somewhere durable looks like it
worked and is gone an hour later.
"""

import os
import shutil
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from racecraft import config
from racecraft.api import ingest_job
from racecraft.api import session as session_store
from racecraft.api.app import app
from racecraft.deploy import persist

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import export_lake                                              # noqa: E402


def _tiny_lake(root: Path) -> Path:
    """A lake with one session, telemetry included."""
    from racecraft.store import lake

    key = "2024_01_R"
    laps = pd.DataFrame([{
        "session_key": key, "driver_number": 1, "driver": "VER", "team": "T",
        "lap_number": lap, "stint": 1, "compound": "HARD", "tyre_life": lap,
        "laps_in_stint": lap, "fresh_tyre": False, "lap_time_s": 90.0,
        "sector1_s": 30.0, "sector2_s": 30.0, "sector3_s": 30.0,
        "lap_start_t": 1000.0 + (lap - 1) * 90, "lap_end_t": 1000.0 + lap * 90,
        "pit_in_t": None, "pit_out_t": None, "is_pit_in_lap": False, "is_pit_out_lap": False,
        "speed_i1": 250.0, "speed_i2": 260.0, "speed_fl": 280.0, "speed_st": 320.0,
        "position": 1, "track_status": "1", "is_personal_best": False, "deleted": False,
        "deleted_reason": None, "is_accurate": True, "fastf1_generated": False,
    } for lap in (1, 2, 3)])
    telemetry = pd.DataFrame({
        "session_key": key, "driver_number": 1,
        "t": [1000.0, 1000.24], "x": [1.0, 2.0], "y": [1.0, 2.0], "z": [0.0, 0.0],
        "status": ["OnTrack", "OnTrack"]})
    tables = {
        "sessions": pd.DataFrame({
            "session_key": [key], "event_name": ["Bahrain Grand Prix"], "country": ["Bahrain"],
            "location": ["Sakhir"], "session_name": ["Race"],
            "date_utc": [pd.Timestamp("2024-03-02 15:00", tz="UTC")],
            "t0_utc": [pd.Timestamp("2024-03-02 14:00", tz="UTC")], "start_t": [1000.0],
            "total_laps": [3], "circuit_rotation_deg": [0.0], "fastf1_version": ["test"],
            "ingested_at": [pd.Timestamp.now(tz="UTC")]}),
        "laps": laps,
        "results": pd.DataFrame({
            "session_key": key, "driver_number": [1], "abbreviation": ["VER"],
            "full_name": ["Max Verstappen"], "team_name": ["Red Bull"], "team_id": ["rb"],
            "team_color": ["3671C6"], "grid_position": [1], "position": [1],
            "classified_position": ["1"], "status": ["Finished"], "points": [25.0],
            "laps": [3], "result_time_s": [270.0],
            "q1_s": [None], "q2_s": [None], "q3_s": [None]}),
        "pos_data": telemetry,
        "track_status": pd.DataFrame({"session_key": [key], "t": [0.0], "status": ["1"],
                                      "message": ["AllClear"]}),
    }
    lake.write_session(tables, 2024, 1, "R", lake=root)
    return root


# ------------------------------------------------------- the deployable lake

def test_the_export_leaves_telemetry_behind(tmp_path):
    source = _tiny_lake(tmp_path / "lake")
    assert (source / "pos_data").is_dir()

    copied = export_lake.export(source, tmp_path / "slim")
    assert "laps" in copied
    assert "pos_data" not in copied, "telemetry is 98.5% of the bytes and the reason to export"
    assert (tmp_path / "slim" / "laps").is_dir()
    assert not (tmp_path / "slim" / "pos_data").exists()


def test_the_export_can_keep_everything(tmp_path):
    source = _tiny_lake(tmp_path / "lake")
    copied = export_lake.export(source, tmp_path / "full", skip=())
    assert "pos_data" in copied


def test_the_export_refuses_to_overwrite_silently(tmp_path):
    source = _tiny_lake(tmp_path / "lake")
    export_lake.export(source, tmp_path / "slim")
    with pytest.raises(FileExistsError):
        export_lake.export(source, tmp_path / "slim")
    export_lake.export(source, tmp_path / "slim", overwrite=True)      # asked for, so allowed


def test_a_lake_without_telemetry_serves_everything_but_the_track_map(tmp_path, monkeypatch):
    """
    The claim the whole deployment rests on. A lake with no telemetry tables has
    no view for them at all, which DuckDB reports as a missing table rather than
    an empty one — so this fails with a catalog error if that is not handled.
    """
    source = _tiny_lake(tmp_path / "lake")
    export_lake.export(source, tmp_path / "slim")
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path / "slim")
    session_store._cache.clear()

    data = session_store.SessionData("2024_01_R")
    assert len(data.laps) == 3
    assert data.position == {}, "no telemetry means no channels, not a crash"
    assert data.outline == []
    assert data.info()["has_position_data"] is False
    assert data.state(1000.0 + 2 * 90)["drivers"][0]["abbreviation"] == "VER"
    assert len(data.lap_chart()["drivers"]) == 1


# ---------------------------------------------------------------- the ingest

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "LAKE_DIR", tmp_path / "lake")
    (tmp_path / "lake").mkdir()
    monkeypatch.setattr(ingest_job, "job", ingest_job.IngestJob())
    return TestClient(app)


def test_ingest_reports_what_it_is_doing(client, monkeypatch):
    from racecraft.ingest import cli as ingest_cli

    monkeypatch.setattr(ingest_cli, "completed_sessions",
                        lambda *_a, **_k: [(1, "R", "Bahrain Grand Prix", "Race")])
    monkeypatch.setattr("racecraft.store.lake.is_ingested", lambda *_a, **_k: False)
    monkeypatch.setattr(ingest_cli, "ingest_with_limits", lambda *_a, **_k: "written")

    started = client.post("/api/ingest").json()
    assert started["running"] is True

    for _ in range(200):
        status = client.get("/api/ingest").json()
        if not status["running"]:
            break
        import time
        time.sleep(0.02)

    assert status["written"] == 1
    assert status["done"] == 1
    assert any("Bahrain" in line for line in status["log"])
    assert status["error"] is None


def test_one_session_failing_does_not_stop_the_rest(client, monkeypatch):
    from racecraft.ingest import cli as ingest_cli

    monkeypatch.setattr(ingest_cli, "completed_sessions", lambda *_a, **_k: [
        (1, "R", "Bahrain Grand Prix", "Race"),
        (2, "R", "Jeddah Grand Prix", "Race"),
    ])
    monkeypatch.setattr("racecraft.store.lake.is_ingested", lambda *_a, **_k: False)

    def flaky(season, rnd, *_a, **_k):
        if rnd == 1:
            raise RuntimeError("the feed hiccupped")
        return "written"

    monkeypatch.setattr(ingest_cli, "ingest_with_limits", flaky)
    client.post("/api/ingest")

    import time
    for _ in range(200):
        status = client.get("/api/ingest").json()
        if not status["running"]:
            break
        time.sleep(0.02)

    assert status["failed"] == 1
    assert status["written"] == 1, "a bad session must not take the good one with it"
    assert any("hiccupped" in line for line in status["log"])


def test_two_ingests_at_once_are_refused(client, monkeypatch):
    """They would race for the same rate-limit budget and the same partitions."""
    from racecraft.ingest import cli as ingest_cli

    import threading
    holding = threading.Event()
    monkeypatch.setattr(ingest_cli, "completed_sessions",
                        lambda *_a, **_k: [(1, "R", "Bahrain Grand Prix", "Race")])
    monkeypatch.setattr("racecraft.store.lake.is_ingested", lambda *_a, **_k: False)
    monkeypatch.setattr(ingest_cli, "ingest_with_limits",
                        lambda *_a, **_k: (holding.wait(5), "written")[1])

    client.post("/api/ingest")
    second = client.post("/api/ingest")
    assert second.status_code == 409
    assert "already running" in second.json()["detail"]
    holding.set()


def test_nothing_new_is_said_rather_than_left_blank(client, monkeypatch):
    from racecraft.ingest import cli as ingest_cli

    monkeypatch.setattr(ingest_cli, "completed_sessions",
                        lambda *_a, **_k: [(1, "R", "Bahrain Grand Prix", "Race")])
    monkeypatch.setattr("racecraft.store.lake.is_ingested", lambda *_a, **_k: True)
    client.post("/api/ingest")

    import time
    for _ in range(200):
        status = client.get("/api/ingest").json()
        if not status["running"]:
            break
        time.sleep(0.02)

    assert status["total"] == 0
    assert any("nothing new" in line for line in status["log"])


# ----------------------------------------------------------- staying put

def test_persistence_is_off_and_harmless_on_a_machine_with_a_disk(monkeypatch):
    monkeypatch.setattr(persist, "MODE", "")
    assert persist.enabled() is False
    assert persist.save_lake("anything") is None, "a laptop needs no push and it is not an error"
    assert persist.describe()["durable"] is True


def test_an_ingest_without_a_token_is_reported_as_not_lasting(monkeypatch, tmp_path, caplog):
    """
    The quiet failure this exists to prevent: on hosting that rebuilds its
    filesystem, an ingest with nowhere to go looks like it worked and is gone on
    the next restart.
    """
    monkeypatch.setattr(persist, "MODE", "hf")
    monkeypatch.setattr(persist, "HF_REPO", "someone/racecraft")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    (tmp_path / "laps").mkdir(parents=True)
    (tmp_path / "laps" / "data.parquet").write_bytes(b"x")

    with caplog.at_level("ERROR"):
        assert persist.save_lake("ingest", lake_dir=tmp_path) is None
    assert any("will not survive" in r.message for r in caplog.records)

    described = persist.describe()
    assert described["durable"] is False
    assert "no HF_TOKEN" in described["detail"]


def test_the_repo_is_taken_from_the_space_when_not_given(monkeypatch):
    monkeypatch.setattr(persist, "HF_REPO", "")
    monkeypatch.setattr(persist, "HF_SPACE", "someone/racecraft")
    assert persist.target_repo() == "someone/racecraft"

    monkeypatch.setattr(persist, "HF_SPACE", "")
    with pytest.raises(persist.NotConfigured):
        persist.target_repo()


# ------------------------------------------------------------ the Space payload

import deploy_space                                             # noqa: E402


def test_the_space_readme_carries_the_front_matter_hugging_face_needs(tmp_path, monkeypatch):
    """
    The one that breaks a Space silently. Without `sdk: docker` and
    `app_port: 7860`, Hugging Face does not know what it has been handed and
    the Space never starts — with no error pointing at the cause.
    """
    monkeypatch.setattr(deploy_space, "SEND", [])
    staged = deploy_space.stage(tmp_path / "space")
    readme = (staged / "README.md").read_text(encoding="utf-8")

    assert readme.startswith("---\n"), "front matter has to be the first thing in the file"
    front = readme.split("---")[1]
    assert "sdk: docker" in front
    assert "app_port: 7860" in front
    assert "title:" in front


def test_the_payload_is_the_application_and_the_lake_and_nothing_else(tmp_path, monkeypatch):
    """A Space repo is a git repository with the lake in it, so it stays small."""
    root = tmp_path / "root"
    for item in ("src/racecraft", "web/dist", "data/lake-slim/laps"):
        (root / item).mkdir(parents=True)
    (root / "src" / "racecraft" / "__init__.py").write_text("", encoding="utf-8")
    (root / "src" / "racecraft" / "cached.pyc").write_text("junk", encoding="utf-8")
    (root / "web" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (root / "web" / "node_modules").mkdir()
    (root / "data" / "lake-slim" / "laps" / "data.parquet").write_bytes(b"x")
    (root / "data" / "lake" ).mkdir()
    (root / "data" / "lake" / "huge.parquet").write_bytes(b"y" * 1000)
    (root / "Dockerfile").write_text("FROM python:3.11-slim", encoding="utf-8")
    (root / "pyproject.toml").write_text("[project]", encoding="utf-8")
    monkeypatch.setattr(deploy_space, "ROOT", root)

    staged = deploy_space.stage(tmp_path / "space")

    assert (staged / "Dockerfile").is_file()
    assert (staged / "web" / "dist" / "index.html").is_file()
    assert (staged / "data" / "lake-slim" / "laps" / "data.parquet").is_file()
    # The full lake is 1.5 GB and must never be swept in by accident.
    assert not (staged / "data" / "lake").exists()
    assert not (staged / "web" / "node_modules").exists()
    assert not (staged / "src" / "racecraft" / "cached.pyc").exists(), "no bytecode"


def test_missing_prerequisites_are_named_rather_than_half_sent(tmp_path, monkeypatch):
    root = tmp_path / "root"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text("x", encoding="utf-8")
    monkeypatch.setattr(deploy_space, "ROOT", root)

    missing = deploy_space.check(deploy_space.SEND)
    assert "web/dist" in missing
    assert "data/lake-slim" in missing
    assert "Dockerfile" not in missing
