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
| 8 | Offers left unanswered in conversation (cache cleanup on C:, the revert question, LinkedIn clip, copy page, quiz) are still wanted, so BACKLOG lists them. | unverified | Aditya to strike any he does not want from BACKLOG. |
