# FEATURE-002: Starts screen
Date: 2026-10-28   Model: Claude Opus 5.5 (claude-opus-5-5)   Decision: D-021

**What:** a Season screen ranking drivers by places gained on lap 1, against what their grid slots
usually gain; with raw places gained, starts gained / held / lost, best and worst start, and
lap-1 retirements. Races, sprints or both; as of the open session, before it or after it.

**Where:** `model/starts.py`, `GET /api/sessions/{key}/starts?moment=before|after`,
`web/src/screens/StartsScreen.tsx`; can pop out into its own window like Standings.

**Rules:** see TECHNICAL.md, "Starts".

**Tests:** `tests/test_starts.py` (4: slot averages worked by hand, lap-1 retirements, pit lane,
no grid, did-not-start, sprints, as-of cut, the route); `web/src/screens/Screens.test.tsx` "Starts"
(number and start wording).

**Checked by hand:** the 2026 US GP in a browser against the real lake, races and both.

**Limits:** someone else's lap-1 crash counts against the drivers caught in it; the slot averages
include the driver's own starts.
