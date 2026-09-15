"""
Paths and project-wide constants.

Every path can be overridden with an environment variable, so the data lake
can live on a different drive from the code without editing anything.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DATA_DIR = Path(os.environ.get("RACECRAFT_DATA_DIR", PROJECT_ROOT / "data"))

# Parquet files are the source of truth. One file per table per session,
# hive-partitioned: lake/<table>/year=2024/round=01/session=R/data.parquet
LAKE_DIR = Path(os.environ.get("RACECRAFT_LAKE_DIR", DATA_DIR / "lake"))

# FastF1's cache. Re-downloadable, and large: ~80 MB per race with telemetry
# in a per-session folder, plus a shared HTTP cache. The per-session folder
# is safe to delete once that session is in the lake (see --prune-cache).
FASTF1_CACHE_DIR = Path(os.environ.get("RACECRAFT_FASTF1_CACHE", DATA_DIR / "fastf1_cache"))

# 2026 is the season being predicted, and it is a new formula: new cars,
# power units and tyres, active aero, no DRS. Only 2026 data describes how
# these cars degrade tyres and gain pace. 2023-2025 stays useful for what
# belongs to the circuit rather than the car: pit lane time loss and
# safety-car likelihood. Pre-2022 is excluded entirely.
DEFAULT_SEASONS = (2026, 2025, 2024, 2023)

# FastF1 session identifiers. Race strategy is the thesis, so races (and
# sprints, which share tyre behaviour) are what gets ingested by default.
RACE_SESSIONS = ("R", "S")
