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
