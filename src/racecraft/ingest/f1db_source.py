"""
Every championship since 1950, from f1db (github.com/f1db/f1db, CC BY 4.0), for testing the
title model on far more seasons than the lake holds (D-016).

The lake starts in 2023 and keeps sessions; this keeps seasons, so it lives beside it, in
`<data>/history/f1db/`: one Parquet file per table, and the release it came from. A release
is a zip of CSV files; it is checked against the release's own SHA-256 list before anything
in it is read, and only read as data.

Kept: each race (year, round, date, whether it had a sprint), every Grand Prix and sprint
result with the points it scored, the drivers' standings after each race, and each season's
final standings (the official champion, after any dropped scores).
"""

from __future__ import annotations

import hashlib
import io
import logging
import zipfile
from pathlib import Path

import pandas as pd
import requests

from racecraft import config

log = logging.getLogger(__name__)

RELEASES = "https://api.github.com/repos/f1db/f1db/releases"
ASSET = "f1db-csv.zip"
CHECKSUMS = "checksums_sha256.txt"
RESULT_COLUMNS = ["raceId", "year", "round", "positionNumber", "positionText", "driverId", "constructorId",
                  "points", "laps", "reasonRetired", "sharedCar", "gridPositionNumber"]
TABLES = {
    "races": ("f1db-races.csv", ["id", "year", "round", "date", "sprintRaceDate"]),
    "race_results": ("f1db-races-race-results.csv", RESULT_COLUMNS),
    "sprint_results": ("f1db-races-sprint-race-results.csv", RESULT_COLUMNS),
    "standings": ("f1db-races-driver-standings.csv",
                  ["raceId", "year", "round", "positionNumber", "driverId", "points", "championshipWon"]),
    "season_standings": ("f1db-seasons-driver-standings.csv",
                         ["year", "positionNumber", "driverId", "points", "championshipWon"]),
}


def history_dir() -> Path:
    return config.DATA_DIR / "history" / "f1db"


def _release(tag: str | None) -> dict:
    url = f"{RELEASES}/tags/{tag}" if tag else f"{RELEASES}/latest"
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.json()


def _asset(release: dict, name: str) -> bytes:
    found = next((a for a in release.get("assets", []) if a["name"] == name), None)
    if found is None:
        raise LookupError(f"f1db {release.get('tag_name')} has no {name}")
    response = requests.get(found["browser_download_url"], timeout=300)
    response.raise_for_status()
    return response.content


def verified(archive: bytes, checksums: str, name: str = ASSET) -> bytes:
    """The archive, if its SHA-256 is the one the release lists for it; otherwise an error."""
    listed = {line.split()[-1].lstrip("*"): line.split()[0] for line in checksums.splitlines() if line.strip()}
    if name not in listed:
        raise ValueError(f"{CHECKSUMS} does not list {name}")
    actual = hashlib.sha256(archive).hexdigest()
    if actual != listed[name]:
        raise ValueError(f"{name}: SHA-256 {actual} is not the listed {listed[name]}")
    return archive


def tables_from(archive: bytes) -> dict[str, pd.DataFrame]:
    """The kept tables, read from the release's CSV files."""
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        out = {name: pd.read_csv(io.BytesIO(z.read(file)), usecols=columns, low_memory=False)
               for name, (file, columns) in TABLES.items()}
    # From the results, not `sprintRaceDate`: f1db leaves that empty for some sprints (12 of 30).
    out["races"].pop("sprintRaceDate")
    out["races"]["has_sprint"] = out["races"]["id"].isin(out["sprint_results"]["raceId"])
    return out


def download(tag: str | None = None, into: Path | None = None) -> str:
    """Fetch an f1db release (the latest by default), check it, keep its tables. Returns its tag."""
    release = _release(tag)
    archive = verified(_asset(release, ASSET), _asset(release, CHECKSUMS).decode())
    into = into or history_dir()
    into.mkdir(parents=True, exist_ok=True)
    tables = tables_from(archive)
    for name, df in tables.items():
        df.to_parquet(into / f"{name}.parquet", index=False)
    (into / "RELEASE").write_text(release["tag_name"], encoding="utf-8")
    log.info("f1db %s: %d races, %d results into %s", release["tag_name"], len(tables["races"]),
             len(tables["race_results"]), into)
    return release["tag_name"]


def load(name: str, into: Path | None = None) -> pd.DataFrame:
    """One kept table; `racecraft-ingest --history` fetches them first."""
    path = (into or history_dir()) / f"{name}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"no f1db history at {path}: run `racecraft-ingest --history` first")
    return pd.read_parquet(path)
