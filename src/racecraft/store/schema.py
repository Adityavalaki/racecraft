"""
Table schemas for the Parquet lake.

Explicit Arrow types are the point of this module. The old engine
round-tripped through CSV and lost types twice: TrackStatus '1' came back as
int64 and silently matched nothing, and LapTime came back as a string. With a
declared schema, a write that doesn't match fails loudly at ingest instead of
corrupting analysis weeks later.

Conventions, applied to every table:

* Time is `t`: float64 seconds since the session's t0 (FastF1's SessionTime
  origin). This is the single session clock every interface panel reads.
  Absolute UTC is recoverable as sessions.t0_utc + t.
* `year`, `round` and `session` are NOT stored in the files. They come from
  the hive partition path (year=2024/round=01/session=R), so a file can
  never disagree with its own location.
* `session_key` ('2024_01_R') is stored in every row for simple joins.
* `driver_number` is int16 everywhere, matching OpenF1 so the two sources
  join without casting.
"""

import pyarrow as pa

SESSIONS = pa.schema([
    ("session_key", pa.string()),
    ("event_name", pa.string()),
    ("country", pa.string()),
    ("location", pa.string()),
    ("session_name", pa.string()),
    ("date_utc", pa.timestamp("us", tz="UTC")),
    ("t0_utc", pa.timestamp("us", tz="UTC")),
    ("start_t", pa.float64()),          # session time when the session itself started
    ("total_laps", pa.int16()),
    ("circuit_rotation_deg", pa.float32()),
    ("fastf1_version", pa.string()),
    ("ingested_at", pa.timestamp("us", tz="UTC")),
])

RESULTS = pa.schema([
    ("session_key", pa.string()),
    ("driver_number", pa.int16()),
    ("abbreviation", pa.string()),
    ("full_name", pa.string()),
    ("team_name", pa.string()),
    ("team_id", pa.string()),
    ("team_color", pa.string()),        # hex without '#', straight from the feed
    ("grid_position", pa.int16()),
    ("position", pa.int16()),
    ("classified_position", pa.string()),  # '1'..'20', or 'R' retired, 'D' disqualified, ...
    ("status", pa.string()),
    ("points", pa.float32()),
    ("laps", pa.int16()),
    ("result_time_s", pa.float64()),    # winner: total race time; others: gap to winner
])

LAPS = pa.schema([
    ("session_key", pa.string()),
    ("driver_number", pa.int16()),
    ("driver", pa.string()),
    ("team", pa.string()),
    ("lap_number", pa.int16()),
    ("stint", pa.int8()),
    ("compound", pa.string()),
    ("tyre_life", pa.int16()),          # tyre age in laps, INCLUDING laps run before this stint
    ("laps_in_stint", pa.int16()),      # 1-based lap count within this stint only
    ("fresh_tyre", pa.bool_()),
    ("lap_time_s", pa.float64()),
    ("sector1_s", pa.float64()),
    ("sector2_s", pa.float64()),
    ("sector3_s", pa.float64()),
    ("lap_start_t", pa.float64()),
    ("lap_end_t", pa.float64()),
    ("pit_in_t", pa.float64()),
    ("pit_out_t", pa.float64()),
    ("is_pit_in_lap", pa.bool_()),
    ("is_pit_out_lap", pa.bool_()),
    ("speed_i1", pa.float32()),
    ("speed_i2", pa.float32()),
    ("speed_fl", pa.float32()),         # finish line
    ("speed_st", pa.float32()),         # speed trap
    ("position", pa.int8()),
    ("track_status", pa.string()),      # every status seen during the lap, e.g. '1', '12', '4'
    ("is_personal_best", pa.bool_()),
    ("deleted", pa.bool_()),
    ("deleted_reason", pa.string()),
    ("is_accurate", pa.bool_()),
    ("fastf1_generated", pa.bool_()),
])

CAR_DATA = pa.schema([
    ("session_key", pa.string()),
    ("driver_number", pa.int16()),
    ("t", pa.float64()),
    ("rpm", pa.float32()),
    ("speed", pa.float32()),            # km/h
    ("gear", pa.int8()),
    ("throttle", pa.float32()),         # 0-100; 104 is a known sentinel for missing
    ("brake", pa.bool_()),
    ("drs", pa.int8()),                 # raw feed code: 10, 12, 14 mean flap open. Always 0 from 2026 (DRS abolished)
])

POS_DATA = pa.schema([
    ("session_key", pa.string()),
    ("driver_number", pa.int16()),
    ("t", pa.float64()),
    ("x", pa.float32()),                # 1/10 m, circuit coordinate frame
    ("y", pa.float32()),
    ("z", pa.float32()),
    ("status", pa.string()),            # 'OnTrack' / 'OffTrack'
])

WEATHER = pa.schema([
    ("session_key", pa.string()),
    ("t", pa.float64()),
    ("air_temp", pa.float32()),
    ("track_temp", pa.float32()),
    ("humidity", pa.float32()),
    ("pressure", pa.float32()),
    ("wind_speed", pa.float32()),
    ("wind_direction", pa.int16()),
    ("rainfall", pa.bool_()),
])

RACE_CONTROL = pa.schema([
    ("session_key", pa.string()),
    ("t", pa.float64()),
    ("lap", pa.int16()),
    ("category", pa.string()),
    ("flag", pa.string()),
    ("scope", pa.string()),
    ("sector", pa.int16()),
    ("racing_number", pa.int16()),
    ("status", pa.string()),
    ("message", pa.string()),
])

TRACK_STATUS = pa.schema([
    ("session_key", pa.string()),
    ("t", pa.float64()),
    ("status", pa.string()),            # '1' clear, '2' yellow, '4' SC, '5' red, '6' VSC, '7' VSC ending
    ("message", pa.string()),
])

SESSION_STATUS = pa.schema([
    ("session_key", pa.string()),
    ("t", pa.float64()),
    ("status", pa.string()),
])

CIRCUIT_MARKERS = pa.schema([
    ("session_key", pa.string()),
    ("kind", pa.string()),              # 'corner' | 'marshal_sector' | 'marshal_light'
    ("number", pa.int16()),
    ("letter", pa.string()),
    ("x", pa.float32()),
    ("y", pa.float32()),
    ("angle", pa.float32()),
    ("distance", pa.float32()),         # metres from the start line along the reference lap
])

TABLES: dict[str, pa.Schema] = {
    "sessions": SESSIONS,
    "results": RESULTS,
    "laps": LAPS,
    "car_data": CAR_DATA,
    "pos_data": POS_DATA,
    "weather": WEATHER,
    "race_control": RACE_CONTROL,
    "track_status": TRACK_STATUS,
    "session_status": SESSION_STATUS,
    "circuit_markers": CIRCUIT_MARKERS,
}
