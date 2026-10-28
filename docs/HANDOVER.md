# HANDOVER
Lane: B (real users) — the app has been shared with a friend (Google Drive, 2026-10-13), so a
break tonight would be noticed. Recorded 2026-10-20; Aditya to confirm.
Read first: TECHNICAL.md (architecture), DECISIONS.md, ROLLBACK.md, BACKLOG.md (everything
discussed and not yet done). No ARCHITECTURE.md or CONSTRAINTS.md yet.

<!-- Newest entry on top. Five lines, every session. -->
## 2026-10-28 — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: top-up pass on `main` (4c6bc8d, D-019). Teammates screen on branch `teammates` (D-020, FEATURE-001): qualifying, race pace, practice, results, sprints and a per-round gap chart; checked in a browser on the 2026 US GP. pytest 645 passed, vitest 245 passed, web build OK.
- In progress: nothing. Branch `teammates` not merged or pushed.
- Broken or risky: the route takes about 1.2 s warm (4 s seen once cold); practice ignores fuel (labelled the noisiest line); the chart caps at 3x the median gap (ASSUMPTIONS 20).
- Next: Aditya to look at the screen and merge `teammates`; rebuild the app to ship it (and the bundled weights file from D-019's commit).
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-27 (night) — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: BUG-006 fixed (stray CSS from PR #4's merge stacked the replay's columns); `main` pushed at 81cc6d2 by Aditya. Aditya checked the app by hand: the 2026 US GP loads and plays correctly.
- In progress: nothing.
- Broken or risky: nothing known. The friend's copy is still the old build and cannot fetch new sessions (Aditya's choice: this build is for Aditya only).
- Next: PR #4's split race-control panels (decide); "use the results-only title model in the app?" (idea); re-ingest recent sessions a day later (idea).
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-27 (late) — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: `sources-and-extras` merged into `main` and pushed (a174c46). Lake: 2026 US GP re-ingested (`--force`, 5 sessions); team radio backfilled into 408 sessions after fixing BUG-005. App frozen into `dist\Racecraft` (manifest 0.3.0.0).
- In progress: the MSIX: Aditya packs, signs and installs it (signing key is off-limits to the assistant). This build is for Aditya only, not the friend.
- Broken or risky: the open desktop app runs the old code until restarted; 2023 Las Vegas FP2 has no radio (ran hours late).
- Next: restart the app and look at the US GP replay (radio, sources line) and a prediction (forecast); decide on PR #4's split panels.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-27 (evening) — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: merged `audit-fixes` + `free-plan` into `main` and pushed (41a03be; fixed PR #4's broken App.tsx). On branch `sources-and-extras`: step 5 sources in the app (D-013); step 6 team radio (D-014), Open-Meteo forecast (D-015), f1db history (D-016), results-only title model + backtest (D-017).
- In progress: nothing. Branch not merged or pushed. `data/history/f1db` fetched (5 MB); the lake was not written.
- Broken or risky: CSP now allows media from livetiming.formula1.com (radio); the server calls Open-Meteo on request; PR #4's split race-control panels are not in the refactored screens.
- Next: Aditya to review and merge `sources-and-extras`; run `racecraft-ingest --radio` and `--season 2026 --rounds 18 --force`; rebuild the MSIX.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-27 (later) — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: C: caches cleaned (16.4 GB free). Steps 3 and 4: Jolpica's official results (D-011) and TracingInsights' tyres, corners and backup (D-012) over OpenF1; Singapore 2026 matches FastF1's copy; pytest 622 passed.
- In progress: nothing. Both tried through the real CLI on the 2026 US GP into scratch lakes only (`build/tmp/cli_lake`, `cli_lake4`).
- Broken or risky: sessions ingested before Jolpica (hours) or TracingInsights (~12 h) publish keep OpenF1's results/tyres until `--force`; backup has no telemetry.
- Next: re-ingest the US GP weekend with `--force` (it now gets official results and FastF1 tyres); step 5, sources in the app with credits.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-27 — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: BACKLOG §1 step 2: `ingest/openf1_source.py` builds a session F1 refuses from OpenF1, shaped to FastF1's fields (D-010); checked on Singapore 2026 with `scripts/compare_openf1.py`.
- In progress: nothing. Real lake not refreshed: the 2026 US GP was only fetched into a scratch lake (`build/tmp/scratch_lake`, 209 s, no quality findings).
- Broken or risky: rules learned on one weekend; known gaps in D-010 and BACKLOG (practice tyre age, lapped gaps, sprint retirees' order).
- Next: Aditya runs Refresh data for the US GP; then step 3 (Jolpica), which can check the results.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-26 — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: `docs/BACKLOG.md`, every task discussed and not done; linked above. No code changed.
- In progress: F1's archive needs an F1 TV login since ~15 Oct (401). Approved: D-009, free
  sources merged (OpenF1, Jolpica, TracingInsights, extras), six steps on branch `free-plan`.
- Broken or risky: Refresh data fails for every new session (2026 US GP onwards); existing data fine.
- Next: BACKLOG §1 steps 1-6 in order, one commit each; step 2 checked against FastF1 on Singapore 2026.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).

## 2026-10-20 — model: Claude Opus 5.5 (claude-opus-5-5)
- Done: all 8 audit findings fixed on branch `audit-fixes`, one commit each (D-001..D-008,
  BUG-001..003): insight fits on earlier races only; caches keyed by lake version; one load per
  session and per season fit; one session-key check; one as-of helper; CORS and legacy code removed.
- In progress: nothing. Branch not merged into `main`, nothing pushed. Checked: pytest 586 passed,
  vitest 228 passed; real lake via `racecraft-serve`: insight fits on earlier races, one load for
  four concurrent requests, standings before/after, bad keys 400. Desktop window not opened.
- Broken or risky: early-season Tyres/Strategy numbers now come from fewer races (or last season's
  last five), so they will differ from before. `fuel_s_per_lap` is still whole-season (unused, D-001).
  `race_inputs._race_cache` is path-keyed: restart the server after an `ingest --force`.
- Next: Aditya to review and merge `audit-fixes`; rebuild the MSIX if the friend's copy should get it.
- Do not touch: `store/db.py`'s one-database-per-lake design (DuckDB crash, see its docstring).
