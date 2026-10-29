# FEATURE-003: Qualifying laps screen
Date: 2026-10-29   Model: Claude Opus 5.5 (claude-opus-5-5)   Decision: D-022

**What:** a Season screen showing, for the last qualifying (or sprint qualifying), each driver's
best lap against their own perfect lap (their three best sectors added up), the time left on the
table, which sector it went in, and their season average. As of the open session, before or after.

**Where:** `model/quali_laps.py`, `GET /api/sessions/{key}/qualifying?moment=before|after&kind=Q|SQ`,
`web/src/screens/QualifyingScreen.tsx`; can pop out into its own window like Standings.

**Rules:** see TECHNICAL.md, "Qualifying laps".

**Tests:** `tests/test_quali_laps.py` (3: worked by hand, deleted laps ignored, no lap time,
season average, sprint qualifying, as-of cut, the route); `web/src/screens/Screens.test.tsx`
"Qualifying laps" (table, wording, kind switch).

**Checked by hand:** the 2026 US GP qualifying in a browser against the real lake.

**Limits:** best sectors can come from different runs on a quickening track; a driver out in Q1
has fewer laps to string sectors from.
