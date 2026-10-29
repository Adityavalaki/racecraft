# FEATURE-004: Race review screen
Date: 2026-10-29   Model: Claude Opus 5.5 (claude-opus-5-5)   Decision: D-023

**What:** a Race screen for the last Grand Prix: per driver, overtakes made and lost on track, and
each pit stop's lap and places lost to cars that stayed out, marked when under a safety car, VSC,
red flag or with a penalty; a line says what a normal stop cost in that race. As of the open
session, before or after.

**Where:** `model/race_review.py`, `GET /api/sessions/{key}/race-review?moment=before|after`,
`web/src/screens/RaceReviewScreen.tsx`; can pop out into its own window.

**Rules:** see TECHNICAL.md, "Race review", with the checks that left consistency, safety-car
seconds and "wrong lap" out.

**Tests:** `tests/test_race_review.py` (3: passes on track only, not under a safety car or through
the pits; places lost at a green and a safety-car stop; a stop the car retired at; as-of cut; the
route); `web/src/screens/Screens.test.tsx` "Race review" (table, marking, wording).

**Checked by hand:** Singapore and US GP 2026 in a browser against the real lake.

**Limits:** a car slowing with damage counts as passed; lap-1 stops are left out.
