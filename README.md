# Racecraft

An F1 strategy workbench. It learns tyre, pace and pit behaviour from historic
timing data, models the car state the public feed doesn't expose (tyre wear,
fuel load), and simulates races to find strategy windows.

The build plan lives at the published *Racecraft Build Plan* artifact. This
repository has finished **Phase 1: ingest at scale**; Phase 2 (replay interface) is next.

## Setup

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

## Ingest

```sh
racecraft-ingest --season 2024 --rounds 1                 # one race
racecraft-ingest --season 2023 2024 2025 2026 --prune-cache    # full backfill
```

Sessions already in the lake are skipped, so an interrupted backfill resumes
by re-running the same command.

**Always backfill with `--prune-cache`.** FastF1 keeps two caches: a parsed
folder per session (~80-160 MB) and a shared HTTP cache file that grows about
20 MB per session. The flag deletes both for each session once it is safely
in the lake, clears leftovers from earlier runs, and compacts the file at the
end. Without it, a 2023-2026 backfill leaves several GB of cache behind.

**Backfills take hours, and that is expected.** FastF1 allows 500 uncached
requests per hour. The command checks the remaining budget before each
session and sleeps until a whole session's requests fit, logging when it
will resume. Leave it running: restarting resets FastF1's counter, but the
limit protects F1's servers and FastF1 warns that ignoring it can get you
blocked. A rejected request also counts against the limit, so retrying in a
loop makes the wait longer, not shorter.

Add `--verbose` to see full tracebacks for failed sessions.

## Query

```python
from racecraft.store.db import connect

con = connect()
con.sql("""
    select driver, stint, any_value(compound) as compound, count(*) as laps
    from laps where session_key = '2024_01_R'
    group by all order by driver, stint
""").show()
```

Views: `sessions`, `results`, `laps`, `car_data`, `pos_data`, `weather`,
`race_control`, `track_status`, `session_status`, `circuit_markers`. Every
view also exposes `year`, `round` and `session` from the partition path.

## Conventions

- **One clock.** Every timestamp is `t`, float seconds since the session's t0.
  FastF1 mixes timedeltas with absolute datetimes (race control); ingest
  converts all of it. Absolute UTC is `sessions.t0_utc + t`.
- **Declared types.** Schemas live in `src/racecraft/store/schema.py` and are
  enforced at write time. `track_status` is always a string (`'1'`, `'12'`).
- **`tyre_life` is not `laps_in_stint`.** Drivers often start a stint on a set
  used in qualifying. Degradation fits should use `tyre_life`; anything about
  stint length should use `laps_in_stint`.
- **Parquet is the source of truth.** DuckDB runs in memory over it; there is
  no database file to lock or keep in sync.

## Layout

```
src/racecraft/
  config.py                paths, overridable by RACECRAFT_* env vars
  ingest/fastf1_source.py  FastF1 Session -> normalised DataFrames
  ingest/quality.py        pre-write checks (errors block, warnings report)
  ingest/cli.py            racecraft-ingest
  store/schema.py          Arrow schemas for every table
  store/lake.py            atomic Parquet writes, hive partitioning
  store/db.py              DuckDB views over the lake
tests/                     offline tests, no network
```

## Verification status

Full backfill complete: every race and sprint from 2023 to 2026 round 14,
107 sessions, 621 MB. Audited across the whole lake:

- **Race time:** 104 of 107 sessions reconcile within +0.33 s of the official
  time (median +0.25 s). The three outliers are all interrupted, mostly wet
  races: 2025 Miami sprint (-4.9 s, suspended start), 2023 Dutch GP (-1.8 s),
  2026 Dutch GP (-1.3 s). Their laps are internally consistent; the session
  start marker is a few seconds off.
- **Position data:** median 1.02 position samples per car sample.

## Known data gaps

Problems in the source feed, not in ingest. Re-downloading does not fix them.

| Session | Gap | Consequence |
|---|---|---|
| 2026 Monaco (`2026_06_R`) | Position feed stops before the race: 18% of normal coverage, almost none after lights out | No track map for the race; no position-derived features. OpenF1's free historical `/location` data is a possible fill |
| 2026 Monaco, 2026 Spain (Madrid) | No `circuit_markers` (Madrid is a new circuit; Monaco follows from the position gap) | Corners must be derived from position data where it exists |
| All 2026 sessions | Throttle missing on 3.1% of samples at racing speed (2023-2025: under 0.1%). Varies by session (up to 18.9%, 2026 China sprint), not by team | Throttle-based analysis must tolerate gaps |
| 2025 Miami sprint, 2023 and 2026 Dutch GPs | Session clock a few seconds off | Negligible for strategy work; worth excluding from anything timing-precise |

New ingests warn on the position gap (`pos_data.coverage`), so a repeat is
reported rather than silent.

### Earlier spot checks

The first checks, run on 2024 rounds 1-5 and 2026 round 14:

| Check | Result |
|---|---|
| 2024 Bahrain: position, grid and laps vs Jolpica (independent source) | 20/20 drivers match |
| 2024 Bahrain: winner's race time and fastest lap vs Jolpica | exact to the millisecond |
| Race control lap derived from `t` vs the message's own lap field | agrees on every flag checked |
| Winner's lap span vs official time, all 7 sessions | +0.24 to +0.29 s every time, systematic (see below) |
| Red-flag race (2024 Japan), sprint (2024 China), 2026 regulations (Madrid) | all ingest and reconcile |
| `track_status` type after Parquet round trip | VARCHAR, `'1'`/`'12'`/`'21'` |
| Car telemetry sample interval during the race | median 0.24 s; 0.13% of gaps over 1 s, none over 3 s |

The +0.25 s offset: lap 1's `lap_start_t` is the session "Started" status,
slightly before lights out. The session clock is therefore accurate to about
a quarter of a second, consistently.

Feed problems found and handled at ingest:

- **Gear values up to 128**, almost all while stationary (2024 Japan: 168
  samples). Stored as null. Only 128 overflowed the column type; values like
  75 fit and had been stored silently before a domain check was added.
- **Throttle 104** is a "no reading" sentinel on 7-15% of samples. Stored as
  null. In 2023-2025 it occurs while stationary and coverage at racing speed
  is effectively complete; 2026 is worse (see Known data gaps).
- **Lap times are missing under safety cars and red flags** (e.g. 2024 China
  laps 24-28). `lap_start_t` / `lap_end_t` are still present, which is why the
  race-time check uses them.

2026 differences to design around:

- `drs` is always 0. DRS no longer exists; the replacement overtake mode is
  visible only as race control messages (`OVERTAKE ENABLED` / `DISABLED`).
- New circuits have no `circuit_markers` (Madrid: none). The track map will
  need to derive corners from position data.
- 22 cars, 11 teams.

Storage: 5.5-7.3 MB of Parquet per race with telemetry (1.2-1.6 M telemetry
rows), against 80-160 MB of FastF1 cache for the same race.

