"""f1db's history read from a release, offline (D-016)."""

from __future__ import annotations

import hashlib
import io
import zipfile

import pandas as pd
import pytest

from racecraft.ingest import f1db_source

RESULT_HEADER = ",".join(f1db_source.RESULT_COLUMNS) + ",time"       # extra columns are left out


def _release_zip() -> bytes:
    files = {
        "f1db-races.csv": "id,year,round,date,sprintRaceDate,officialName\n"
                          "1,2021,1,2021-03-28,,Bahrain\n2,2021,10,2021-07-18,2021-07-17,British\n",
        "f1db-races-race-results.csv": RESULT_HEADER + "\n1,2021,1,1,1,max-verstappen,red-bull,25,56,,False,1,x\n",
        "f1db-races-sprint-race-results.csv": RESULT_HEADER + "\n2,2021,10,1,1,max-verstappen,red-bull,3,17,,False,2,x\n",
        "f1db-races-driver-standings.csv": "raceId,year,round,positionNumber,driverId,points,championshipWon\n"
                                           "1,2021,1,1,max-verstappen,25,False\n",
        "f1db-seasons-driver-standings.csv": "year,positionNumber,driverId,points,championshipWon\n"
                                             "2021,1,max-verstappen,395.5,True\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buffer.getvalue()


ARCHIVE = _release_zip()
CHECKSUMS = f"{hashlib.sha256(ARCHIVE).hexdigest()}  f1db-csv.zip\n{'0' * 64}  f1db-json.zip\n"


def test_only_an_archive_with_the_listed_checksum_is_read():
    assert f1db_source.verified(ARCHIVE, CHECKSUMS) == ARCHIVE
    with pytest.raises(ValueError, match="SHA-256"):
        f1db_source.verified(ARCHIVE + b"tampered", CHECKSUMS)
    with pytest.raises(ValueError, match="does not list"):
        f1db_source.verified(ARCHIVE, "")


def test_the_kept_tables_and_sprint_weekends():
    tables = f1db_source.tables_from(ARCHIVE)
    assert set(tables) == set(f1db_source.TABLES)
    assert list(tables["races"]["has_sprint"]) == [False, True]
    assert "time" not in tables["race_results"]
    assert tables["season_standings"].loc[0, "championshipWon"]


def test_download_keeps_the_tables_and_the_release(monkeypatch, tmp_path):
    monkeypatch.setattr(f1db_source, "_release", lambda tag: {"tag_name": "v2026.18.0"})
    monkeypatch.setattr(f1db_source, "_asset",
                        lambda release, name: ARCHIVE if name == "f1db-csv.zip" else CHECKSUMS.encode())
    assert f1db_source.download(into=tmp_path) == "v2026.18.0"
    assert (tmp_path / "RELEASE").read_text() == "v2026.18.0"
    assert f1db_source.load("sprint_results", into=tmp_path).loc[0, "points"] == 3
    with pytest.raises(FileNotFoundError, match="--history"):
        f1db_source.load("races", into=tmp_path / "nowhere")
    assert isinstance(f1db_source.load("races", into=tmp_path), pd.DataFrame)
