# ASSUMPTIONS & OPEN QUESTIONS
<!-- Clear the unverified list before anything ships. -->

| # | Assumption / question | Status (verified / unverified / wrong) | How to check |
|---|---|---|---|
| 1 | "Held out" means earlier races only, as the README says, not leave-one-out (D-001). | unverified: Aditya to confirm the intent | Read D-001; compare a 2025 race's Tyres screen before and after. |
| 2 | A season's first race should borrow the last five races of the season before, as `race_inputs` does, even across the 2026 rule change. | unverified | Open 2026 round 1's Tyres screen; its `fitted_on` lists 2025 races. |
| 3 | Lake keys and session codes only ever use ASCII letters, digits and `_` (D-004). | verified: every key the ingest writes is `YYYY_RR_CODE`, the live key is `live` | `check_key` tests in `tests/test_lake.py`. |
| 4 | Nothing calls the API cross-origin, so CORS can go (D-006). | verified: Vite proxies `/api`, the client uses relative paths, no test needs it | `web/vite.config.ts`, `web/src/api.ts`. |
| 5 | The legacy code is no longer needed in the working tree (D-008). | unverified: its README says it is kept for a portfolio; removed at "fix all" | `git checkout 177e8e5 -- legacy` restores it. |
| 6 | The app is Lane B because a friend runs it. | unverified | Aditya to confirm in HANDOVER. |
| 7 | Concurrent session loads were a real memory problem, not just a theory. | partly verified: on the real lake, four requests at once to cold `2024_10_R` now log one load; the memory saved was not measured | Open a race with a memory monitor on main vs `audit-fixes`. |
| 8 | Offers left unanswered in conversation (cache cleanup on C:, the revert question, LinkedIn clip, copy page, quiz) are still wanted, so BACKLOG lists them. | unverified | Aditya to strike any they do not want from BACKLOG. |
| 9 | OpenF1's pit `date` is the pit (or garage) exit, and its lap numbers in race control messages run one ahead of the timing outside races (D-010). | verified on Singapore 2026 only: pit entry/exit within 0.25 s of FastF1 in race, quali and FP1; FP1 deletion matched by quoted time | `python scripts/compare_openf1.py <key>` on another weekend the lake has from FastF1. |
| 10 | A car whose first OpenF1 stint ends on lap 1 with no stop started from the pit lane. | verified for the race (HAD, NOR, STR, Singapore 2026); in the sprint it marks 11, 18 and 63 where FastF1 marks 55 | Compare with the official sprint grid (Jolpica, step 3). |
| 11 | Nothing reads `session_status`, so OpenF1 sessions can leave it empty. | verified: only `store/schema.py` and ingest mention it | `grep -rn session_status src/`. |
| 12 | TracingInsights' folder names are FastF1's event and session names, and its files stay FastF1's output (D-012). | verified for 2026 Singapore and US GP: the rebuilt Singapore race and FP1 match the lake exactly | `python scripts/compare_openf1.py <key>` on a newer weekend the lake has from FastF1 (tyre and corner fields). |
| 13 | Using TracingInsights (Apache-2.0) and Jolpica needs only a credit, which step 5 adds. | unverified: licences read from the repo badge and LICENSE file, not reviewed | Step 5's README credits. |
| 14 | F1 keeps serving team radio MP3s without a login (D-014). | verified 2026-10-27: 2024 and 2026 clips answer 200 | Play a clip in the replay; "could not play" means it changed. |
| 15 | Allowing `media-src https://livetiming.formula1.com` is safe: audio cannot run code, and nothing else is opened up (D-014). | verified for the policy text (a test pins it); not reviewed by anyone else | Read `api/guard.py`'s policy. |
| 16 | Open-Meteo's archived forecasts are what was forecast at the time, not a re-analysis (D-015). | unverified: taken from Open-Meteo's description of its historical-forecast API | Compare an archived value with one recorded on the day. |
| 17 | f1db's per-race standings are the points as published after each race (dropped scores applied as at the time) (D-016). | unverified | Compare a pre-1991 season's standings with a period source. |
| 18 | A team's drivers for a round are the ones in its qualifying, sprint or Grand Prix results; a round with only practice run so far belongs to the team's latest pair if both drove in it (D-020). | verified on 2024: every stand-in and swap came out as its own pair | `teammates.head_to_head(con, 2024)` lists the pairs and the one left-out round. |
| 19 | Practice best laps on the softest shared compound are worth showing despite unknown fuel. | unverified: Aditya asked for practice; it is labelled the noisiest line | Compare a season's practice line with its qualifying line; drop it if they disagree often. |
| 20 | Capping the chart at three times the median gap is the right trade (a marked bar against a flattened chart). | unverified: chosen after seeing Russell's 1.6 s round 15 flatten Mercedes' chart | Look at the screen for a few teams. |
