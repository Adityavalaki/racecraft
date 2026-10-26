# HANDOVER
Lane: B (real users) — the app has been shared with a friend (Google Drive, 2026-10-13), so a
break tonight would be noticed. Recorded 2026-10-20; Aditya to confirm.
Read first: TECHNICAL.md (architecture), DECISIONS.md, ROLLBACK.md, BACKLOG.md (everything
discussed and not yet done). No ARCHITECTURE.md or CONSTRAINTS.md yet.

<!-- Newest entry on top. Five lines, every session. -->
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
