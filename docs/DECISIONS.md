# DECISIONS
<!-- One entry per meaningful decision, drafted BEFORE the change. Newest at the bottom. -->

## D-001: Tyre wear on the Tyres and Strategy screens comes from earlier races only
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: `/insight` (Tyres screen, strategy plans, pit windows) fitted wear on every other race
of the season, later ones included. The README, `pit_view.py` and the Places screen all say
"races before it". Found by the 2026-10-20 audit.
Options:   1) Keep leave-one-out and correct the docs.  2) Use only races with a lower round;
for a season's first race, the last five races of the season before (what `race_inputs` does).
3) Reuse `race_inputs.build` wholesale.
Chosen: 2.
Why: It keeps the promise every screen and the README make, and uses the same fallback as the
Places screen. Option 3 drags in the whole simulator's inputs (traffic, grid) for a figure that
needs none of them.
Trade-off: Early-season races are fitted on fewer races, so their wear is noisier than before.
The pooled fuel figure (`fuel_s_per_lap`) is still fitted on the whole season: no plan uses it
and no screen shows it.
Revisit if: a screen starts showing the fuel figure, or early-season plans look unstable.

## D-002: Model caches are keyed by the lake's version, not dropped by the sync
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: Cached fits were cleared only by the app's own sync (`sync_view.forget_models`), so an
ingest from another process left them stale, and a fit running during a sync was stored after
the clear.
Options:   1) Also clear on the db reload.  2) Put a lake version (bumped when `db.connect`
reloads any table) into every cache key and delete `forget_models`.
Chosen: 2.
Why: A key that changes with the data cannot serve stale answers, including from a fit that was
already running. One mechanism instead of a list of caches to remember to clear.
Trade-off: Old entries stay in memory until their LRU bound evicts them. `_tables_cache` becomes
one slot so the full lap table is never held twice. The version is only re-checked every
`RECHECK_S` (10 s) for another process's writes, as before.
Revisit if: memory after a sync matters more than the LRU bounds allow.

## D-003: One load per session and one fit per season, however many requests ask
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: Opening a session fires several requests at once; each one that missed the cache loaded
the session (about 800,000 samples) itself. Season fits (about 15 s) had the same gap.
Options:   1) Load under the module lock (blocks every other session too).  2) The in-flight
Event pattern `places_view` already uses: the first caller computes, the others wait for it.
Chosen: 2.
Why: Already in the codebase and tested; only callers of the same key wait.
Trade-off: A waiter gives up after 300 s and computes itself, as in `places_view`.
Revisit if: loads ever take longer than that.

## D-004: One session-key check, one rule
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: Six copies of `_safe` with two different rules (some allowed `-`; all used `isalnum()`,
which accepts non-ASCII), plus a regex in `session.py`. They guard SQL built with f-strings.
Options:   1) Parameterise every query.  2) One check, `store.db.check_key`, ASCII letters,
digits and `_`, raising KeyError (a bad key is a session that is not there); the API's
`_safe` turns that into a 400. `db.partition` uses the same ASCII rule.
Chosen: 2.
Why: Smallest change that makes the rule single; parameterising ~25 queries is a larger diff for
no gain once the one check is strict.
Trade-off: Keys with `-` are now refused everywhere; no lake key or live key has one.
Revisit if: a key format with other characters is introduced.

## D-005: One helper for "as of this session"
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: Standings, pit crews and title odds each looked up a session's start and turned
before/after into a cut-off, three copies already drifting on time zones.
Chosen: `standings.as_of(con, session_key, moment) -> (year, as_of)`, always UTC.
Why: One place to change; standings is where "before this session" is defined.
Trade-off: none known.
Revisit if: a screen needs a different cut-off.

## D-006: Remove the CORS middleware
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: It allowed the Vite dev server's origin, but Vite proxies `/api` and the client uses
relative paths, so no request is cross-origin.
Chosen: delete it. Rejected: keeping it "for later".
Why: Dead config in a security-relevant spot is something a reader has to reason about.
Trade-off: opening the API from another origin in development would now need it back.
Revisit if: the client ever calls the API by absolute URL from another port.

## D-007: The watcher's lock lives with the other locks
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: `watch()` looked for `config.LOG_DIR`, which does not exist, and fell back to a folder
beside the lake.
Chosen: `config.DATA_DIR / "logs" / "watch.lock"`, where the session and app locks are.
Trade-off: a watcher started before this change and one after it would not see each other's
lock for that one overlap.
Revisit if: never, unless the data layout changes.

## D-008: Delete the legacy code, keep its story
Date: 2026-10-20   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: `legacy/` held 2,367 lines of the two earlier projects, never imported.
Options:   1) Keep as is.  2) Keep `legacy/README.md` (the lessons) and delete the code.
Chosen: 2, at Aditya's "fix all".
Why: The lessons are in the README; the code is in git history at 177e8e5.
Trade-off: reading the old code needs a `git show`.
Revisit if: someone needs to run the legacy engine again.

## D-009: Free data from several sources, merged into the lake's existing tables
Date: 2026-10-26   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: Since about 15 October 2026, F1's timing archive (`livetiming.formula1.com/static`)
answers 401 without an F1 TV login, for every season, so FastF1 can no longer download a
session (FastF1 issue #978). The free live stream never carried car telemetry or positions
(checked in the Baku 2026 FP1 recording). Aditya has no budget: free sources only.
Options:   1) F1 TV Access through FastF1 3.9's sign-in (paid).  2) OpenF1's Sponsor tier
(paid, live).  3) Results only, from Jolpica through FastF1's client.  4) Several free
sources, each table from the first that has it and passes the quality checks, the rest as
backups and cross-checks: OpenF1's free tier (all tables but corners; checked for Austin 2026
FP1 telemetry and positions after the lock), TracingInsights' GitHub archive (all tables
including corners; Austin 2026 FP1 present), Jolpica (official results and points, history),
the live recorder (live timing), plus Open-Meteo, f1db and team radio as extras.
Chosen: 4, in six steps, one commit each: a clear "needs F1 TV" message; the merge step and
the OpenF1 adapter, checked against FastF1 on a session the lake already has; Jolpica;
TracingInsights; sources shown in the app with credits; then the optional sources.
Why: Free, and no table depends on a single source. Every adapter produces the tables the
lake already has, so no screen, model or API changes.
Trade-off: More code to keep working as sources change. Sources keep time differently (OpenF1
in UTC, TracingInsights on FastF1's session clock), so aligning them is the riskiest part.
OpenF1 and f1db licences are non-commercial or need credit: fine for Racecraft as it is.
Revisit if: a source stops publishing or changes its format; or F1 opens the archive again.

## D-010: OpenF1 sessions shaped to match FastF1's, field by field
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 2. When F1's archive refuses a session, `ingest/openf1_source.py` builds
it from OpenF1. Checked table by table against FastF1's copy of Singapore 2026 (race,
qualifying, FP1, sprint), already in the lake, OpenF1 differs from FastF1 in places.
Options:   1) Take OpenF1 as it comes.  2) Put each difference right where the evidence says
which source is right, so models and screens see what FastF1 would have given them.
Chosen: 2. t0 an hour before the scheduled start (as FastF1's, so `t` stays positive and
pre-session race control is kept); `start_t` from race control's SESSION STARTED. Track status
rebuilt from race control, sector yellows included ("VSC DEPLOYED" is Singapore's wording),
with FastF1's labels. Pit `date` read as the exit, entry = exit - `pit_duration` (0.25 s from
FastF1). Stints re-cut at the stops for a pit-lane start. Garage out-laps start where the last
lap ended and have no time. Deleted laps found by the time race control quotes; without one,
the message's lap number is one ahead outside a race. `is_accurate` is FastF1's rule less its
timing-continuity check. Results as FastF1 writes them: classification only for races and
sprints, the grid from the qualifying session that set it, no places in practice.
Why: Models filter on these fields (`track_status == "1"`, `is_accurate`, in/out laps); a
source that fills them differently would quietly change every number.
Trade-off: Rules learned on one weekend. Left as they are, and visible in the comparison: practice
tyre age restarts at 0 on a reused set (OpenF1 does not know); lapped finishers have no gap
time; `session_status` stays empty (nothing reads it); slow practice laps keep a time FastF1
leaves blank (the models' outlier filters drop them); the sprint's unplaced retirees may be
ordered differently (Jolpica, step 3, has the official order).
Revisit if: an OpenF1 session fails the quality checks, or another weekend's comparison
disagrees: `python scripts/compare_openf1.py <session_key>` prints every difference.

## D-011: Official results from Jolpica over OpenF1's
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 3. FastF1 always took a session's classification, points, grid, team ids
and Q1-Q3 times from Jolpica (Ergast's successor). An OpenF1 session (D-010) lacks team ids
and lapped finishers' gaps, and orders unclassified retirees by laps run, a guess.
Options:   1) Our own HTTP client for api.jolpi.ca.  2) FastF1's Ergast client, already
installed, which is what FastF1 itself used.  3) Leave OpenF1's results.
Chosen: 2. `ingest/jolpica_source.py` fetches a race, sprint or qualifying result (one
request) and lays its official fields over OpenF1's, car by car; cars it does not list keep
OpenF1's. Cars the two place differently are logged: the finishing-order cross-check.
Why: No new dependency or client; the results table then matches FastF1's field for field
(Singapore 2026 race and qualifying: no differences left; the sprint's retirees now in the
official order, where FastF1's own copy had them wrong).
Trade-off: Jolpica publishes some hours after a session; ingested before that, a session keeps
OpenF1's results until re-ingested with `--force`. Practice and sprint qualifying have no
Jolpica results, so their team ids stay empty (standings fall back to team names).
Revisit if: Jolpica's format or statuses change, or FastF1 drops its Ergast client.

## D-012: TracingInsights for tyres, corners and as OpenF1's backup
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 4. TracingInsights publishes FastF1's own output for every session on
GitHub (`TracingInsights/<season>`, Apache-2.0), about twelve hours after it ends: lap times
with FastF1's tyre history, corners with the circuit's rotation, race control, weather, and
telemetry split per lap. OpenF1 (D-010) restarts tyre age on a reused set and has no corners.
Options:   1) A backup only, used when OpenF1 has no session.  2) Also lay its tyre fields and
corners over every OpenF1 session.  3) Make it the main source for laps (it is FastF1's data),
OpenF1 only before it is published.
Chosen: 2. `ingest/tracinginsights_source.py`: after OpenF1, this session's corners and
rotation, and compound, stint, tyre life, laps in stint and fresh tyre for every lap it has
(laps whose times differ from OpenF1's by over 10 ms are counted in the log); when OpenF1 has
no session, laps, weather, race control, track status (rebuilt as D-010) and corners from it,
with Jolpica's results (D-011). Its clock is FastF1's: t0 = lap start date - lap start time.
Why: Singapore 2026 rebuilt from it matches the lake's FastF1 copy exactly (t0 to 0.0 s; every
lap field, flags, corners); with it on top, OpenF1 sessions' tyres match FastF1's on every lap
(FP1 and qualifying). 3 was rejected for now: the twelve-hour lag would leave a fresh session
without the faster source, and two primaries mean two clocks to reconcile.
Trade-off: Ingested before TracingInsights publishes, a session keeps OpenF1's tyres and the
lake's latest corners at that circuit (none for a new circuit) until re-ingested with `--force`.
The backup has no telemetry: its files are per lap, resampled and merged (about 1,200
downloads a race), not the raw samples the lake keeps. Folder names are FastF1's event and
session names; a rename there breaks the lookup quietly (the file is just "not there").
Revisit if: OpenF1 stops serving telemetry (then read the per-lap files), or the archive's
format changes.

## D-013: A `sources` table, and the sources named in the app
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 5. Since D-010 to D-012 a session can be built from four sources, and a
reader of a lap chart should be able to tell which, and the sources need credit.
Options:   1) Only `sessions.fastf1_version` ("openf1", "tracinginsights" or FastF1's version).
2) A small `sources` table: per session and table, its source and when it was fetched.
Chosen: 2. Ingest writes one row per table with rows in it ("OpenF1 + TracingInsights" for
laps whose tyres came from the archive, "OpenF1 + Jolpica" for official results, "earlier
session at this circuit" for copied corners). The API's session info returns them, falling
back to FastF1 for sessions ingested before; the app names the sources beside the session
picker, each table's in the tooltip. Settings and the README credit every source.
Why: Per-table detail is the point (one session mixes three sources); the table is tiny and
no existing session needs rewriting.
Trade-off: One more table to keep in step with ingest; a source that adds fields later (a
`--force` re-ingest) is only recorded when the session is written again.
Revisit if: a screen needs to know a single field's source, not a table's.

## D-014: Team radio on the replay, streamed from F1
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 6. OpenF1's free `team_radio` lists every clip (car, time, MP3 address).
The MP3s sit on F1's own server, which still serves them without a login (checked: 2024 and
2026 clips answer 200); TracingInsights mirrors the same files.
Options:   1) Stream from F1: keep the address, play in the app.  2) Store every MP3 in the lake
(tens of MB a race, works offline).  3) Proxy the MP3s through the local API.
Chosen: 1 (Aditya's choice). A `team_radio` table (car, `t` on the session clock, address):
OpenF1 sessions get it as they are built, others with one more request; `racecraft-ingest
--radio` adds it to sessions already in the lake, keeping their source rows. The replay's
right column lists the clips sent by the replay clock, newest first, each playable.
Why: Smallest change that works; no audio stored or fetched by the server.
Trade-off: The security policy now allows one outside host, for media only:
`media-src 'self' https://livetiming.formula1.com` (a test pins it). Playing needs the internet,
and if F1 locks the radio folder too, clips will say "could not play"; the fix then is
TracingInsights' mirror. The live recording carries no radio.
Revisit if: F1 locks the clips; or someone wants radio offline (option 2).

## D-015: The weekend forecast beside the prediction, from Open-Meteo
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 6. Rain changes a race more than anything the prediction models; Aditya
chose to show the forecast, not feed it into the model.
Options:   1) Show it: rain chance, rain, air temperature and wind at the race (and sprint)
start.  2) Feed rain chance into the prediction (a model change, a refit and a replay of
past races to show it helps).
Chosen: 1. `api/forecast.py` takes the circuit's position and the start times from Jolpica's
schedule and asks Open-Meteo (free, no key, CC BY 4.0, credit shown): the current forecast for
a start in the next sixteen days, the archived forecast for one already run (labelled "was
forecast", since what happened is in the session's weather). Cached for an hour. Shown above
the prediction; nothing at all if Open-Meteo or Jolpica cannot be reached.
Why: The useful half at a fraction of the cost; option 2 stays open, with the same data.
Trade-off: The local server now calls two outside hosts on request (api.open-meteo.com and
historical-forecast-api.open-meteo.com), with no user-supplied address in the call. A weekend
more than sixteen days off shows no forecast yet.
Revisit if: a model is to use rain (option 2), or Open-Meteo's terms change.

## D-016: f1db's history beside the lake, for testing the title model
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 6. The title odds were checked on three seasons (2023-2025), all the lake
holds. f1db (CC BY 4.0) has every championship since 1950, but results only: no lap times,
which the title model's pace needs. Aditya chose a results-only title model, tested on f1db.
Options:   1) Keep history in the lake's per-session tables.  2) Keep it apart, per season.
Chosen: 2. `ingest/f1db_source.py` (`racecraft-ingest --history`) fetches a release, checks its
SHA-256 against the release's own list before reading it, and keeps five tables as Parquet in
`<data>/history/f1db/` with the release tag: races, Grand Prix and sprint results, standings
after each race, and each season's final standings (the official champion, dropped scores
and all). Sprint weekends are taken from the sprint results: f1db leaves the date empty for
12 of the 30.
Why: History is seasons, not sessions; the lake's tables, checks and screens assume sessions.
Trade-off: A second store to keep current (one command); about 5 MB.
Revisit if: a screen wants history (then it may belong in the database layer).

## D-017: A results-only title model, to test the odds on 1950-2025
Date: 2026-10-27   Model: Claude Opus 5.5 (claude-opus-5-5)
Context: D-009 step 6. The title model (`model/title.py`) reads pace from lap times, which f1db
(D-016) does not have, so it cannot be replayed on history. Aditya chose a second model whose
form is results only, tested on f1db and scored beside the lap-time model on 2023-2025.
Options:   1) Results-only form (average finishing place).  2) Rebuild pace from Jolpica's lap
times (1996 on): faithful but days of fetching at 500 requests an hour, and no tyres.
Chosen: 1. `model/title_history.py`: form is a driver's average finishing place so far that
season; its doubt is measured as `title.measure` measures pace (race-to-race noise in places,
and the lasting part beyond the early average's own sampling), leaving each season out of its
own measurement. Races are `title.simulate_races` with each season's own points scale (read
from its results; `simulate_races` now takes the points as arguments, today's by default),
the champion `title.champions`. Scored, as `title.backtest` is, by the chance given to the
official champion beside the points alone. `racecraft-analyse title-history-backtest`.
Why: Reuses the simulation and the scoring, so the two models' numbers compare directly.
Trade-off: No dropped scores (best-N counting until 1990), no fastest-lap or shared-drive
points: seasons settled by those count against it. A driver who has never finished is the
field's average, as in `title`. Results-only form cannot see a car's pace under the result.
Revisit if: the pre-1991 seasons score badly against the points alone.
