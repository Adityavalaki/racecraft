# FEATURE-001: Teammates screen
Date: 2026-10-28   Model: Claude Opus 5.5 (claude-opus-5-5)   Decision: D-020

**What:** a Season screen comparing each team's two drivers: qualifying, race pace on shared
clean laps, practice, results and points, sprints, and a per-round chart of the gap
(qualifying, race pace or practice). As of the open session, before it or after it.

**Where:** `model/teammates.py`, `GET /api/sessions/{key}/teammates?moment=before|after`,
`web/src/screens/TeammatesScreen.tsx`; can pop out into its own window like Standings.

**Rules:** see TECHNICAL.md, "Teammates".

**Tests:** `tests/test_teammates.py` (7: each line's rule, stand-ins, FP1 rookie, as-of cut, the
route); `web/src/screens/Screens.test.tsx` "Teammates" (rendering, metric switch, wording,
chart scale).

**Checked by hand:** the 2026 US GP in a browser against the real lake: all 13 pairings,
the three charts, the capped bars. 2024 pairs listed against the known stand-ins.

**Limits:** practice ignores fuel; a race with fewer than 5 shared clean laps on the same
tyre has no race-pace figure; recomputed per request (about 1 s a season).
