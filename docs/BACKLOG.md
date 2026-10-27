# Racecraft backlog

Everything discussed and not yet done, as of 2026-10-26.
Tick an item (`[x]`) and add the commit when it lands; delete it only if it is dropped, with a
line saying why.

**Status words:** *waiting on Aditya* (a decision is needed before work starts),
*ready* (agreed, can start), *idea* (discussed, not yet agreed).

---

## 1. Urgent: new sessions no longer download

Since about 15 October 2026, F1's timing archive (`livetiming.formula1.com/static`) answers
**401 Unauthorized** without an F1 TV login, for every season. Refresh data shows
`DataNotLoadedError` for every new session (the 2026 United States GP so far). Data already in
the lake is unaffected. Background: FastF1 issue #978; FastF1 3.9.0 adds F1 TV sign-in.
Aditya chose the **free route** (no budget) and approved several free sources merged into
the lake (D-009), on branch `free-plan` (from `audit-fixes`), including the optional extras.

- [x] Decisions: the six steps below approved; branch `free-plan`; optional step 6 included.
- [x] **Step 1 (BUG-004): a clear message instead of `DataNotLoadedError`.** Done: 8d22f69.
  Detect the 401, mark the session "needs F1 TV", stop asking F1 for the rest of that refresh,
  and say so on the Refresh button and its tooltip.
- [x] **Step 2: the OpenF1 adapter.** Done: see `git log` (D-010).
  `ingest/openf1_source.py` builds the lake's existing tables (corners copied from the
  circuit's last session) for any session F1's archive refuses. Checked against FastF1 on
  Singapore 2026 (race, qualifying, FP1, sprint) with `scripts/compare_openf1.py`; the 2026
  US GP race fetched with telemetry into a scratch lake (209 s, no quality findings).
  The "merge step" is not needed yet: one source per session. It comes with step 3 or 4.
- [ ] **Refresh the real lake** with the 2026 US GP weekend (Refresh data, or
  `racecraft-ingest --season 2026 --rounds 18`). *waiting on Aditya* Not run: it writes to the lake.
- [ ] **Known OpenF1 gaps** (D-010), for steps 3 and 4 to fill: practice tyre age restarts on a
  reused set. (Lapped gaps and the sprint retirees' order: fixed by step 3.)
- [x] **Step 3: the Jolpica adapter.** Done: see `git log` (D-011). `ingest/jolpica_source.py`
  puts the official results over OpenF1's and logs cars the two place differently. Checked on
  Singapore 2026 (race and qualifying now match FastF1's results exactly) and through the real
  CLI on the 2026 US GP (scratch lake).
- [ ] **Step 4: the TracingInsights adapter.** *ready* Backup for every table, and corner
  positions for new circuits. GitHub archive, Apache-2.0, one event folder at a time.
- [ ] **Step 5: show sources in the app, with credits** in the README. *ready*
  A small `sources` table: session, table, source, date fetched.
- [ ] **Step 6 (optional extras): Open-Meteo weather, f1db history, team radio.** *ready*
- [ ] **Option: record live sessions automatically.** *idea*
  F1's live timing stream still works without a login. The desktop app could record each
  session while it runs (laps, tyres, race control; no telemetry or GPS positions).
  Needs the app to be open during the session.
- [ ] **Re-share the app with the friend** once the fix lands: their copy has the same problem.
  Rebuild `dist\share\Racecraft.zip` (and the data zip if it should include new races).

## 2. Waiting on Aditya: review and housekeeping

- [ ] **Review and merge the `audit-fixes` branch** into `main` (8 audit fixes, D-001 to D-008,
      BUG-001 to BUG-003). Not merged or pushed. Then rebuild the MSIX.
- [ ] **Confirm the lane** in `HANDOVER.md`: Lane B (a friend uses the app) is recorded but
      unconfirmed.
- [ ] **Clear the unverified items in `ASSUMPTIONS.md`** (1, 2, 5, 6, 7 are open).
- [x] **Free space on drive C:** done 2026-10-27 at Aditya's request: npm cache 5 GB -> 0.95 GB,
      uv 16.6 GB -> 3.1 GB (`--force`; the rest is claude-mem's running memory server, locked),
      pip already empty. C: free 14.1 -> 16.4 GB.
- [ ] **Old open question:** whether to revert commits `71b44b8` or `22086a2` (pushed without
      being asked, early on). No answer given; probably close as "keep".
- [ ] **Missing docs for Lane B:** `ARCHITECTURE.md`, `CONSTRAINTS.md` and `docs/defense/` do
      not exist yet; the pre-ship gate needs them.

## 3. Models and statistics still to finish

- [ ] **Race Wilcoxon test.** *ready*
  The sprint test is done (win log-loss better than the grid in 17 of 23 sprints, p = 0.007).
  The race replay (`racecraft-analyse predict-backtest --out <file>`) was stopped before it
  finished, twice. Rerun it and apply the same Wilcoxon signed-rank test, pairing each race's
  model score with the grid's.
- [ ] **Race model's sprint signal.** *idea*
  The race prediction still reads a sprint's pace with the lap-effects fit, which breaks when
  one driver is alone on a compound (China 2024: held at the ±2.5 s limit). Move it to
  `weekend.sprint_pace`, refit the race weights and replay every race. Noted in TECHNICAL.md.
- [ ] **`fuel_s_per_lap` is still fitted on the whole season** (D-001 trade-off). Only matters if
      a screen starts showing it, or if the "cost of 1 kg" feature below uses it.

## 4. New features discussed

Ordered as last suggested. Each one: plan, approval, build, tests, screenshot, docs, commit.

### From the data we already have
- [ ] **Teammate head-to-head.** *idea, recommended next*
  Qualifying gaps, race pace and finishes against the teammate. High accuracy (same car).
- [ ] **Start performance.** *idea*
  Grid slot against position after lap 1, per driver, and how consistent it is.
- [ ] **Corner-type strengths per team.** *idea*
  Minimum speed and braking points in slow, medium and fast corners, from telemetry and the
  marked corners. Samples are about 20 m apart at top speed, so interpolated.
- [ ] **Strategy review.** *idea*
  Who pitted on the wrong lap, and who gained or lost from safety-car timing, in seconds.
- [ ] **Qualifying: ideal lap against actual.** *idea*
  Best sectors summed against the best real lap: time left on the table.
- [ ] **Tyre management.** *idea*
  Each driver's tyre wear against their teammate's.
- [ ] **Overtakes made and lost.** *idea*
  Position changes lap by lap, with pit-stop shuffles removed (GPS positions for exact passes).
- [ ] **Penalty and track-limits record.** *idea*
  Offences per driver and team from race control, and how penalties changed results.
- [ ] **Consistency.** *idea*
  Spread of clean lap times per driver.
- [ ] **Weather effects.** *idea*
  Track temperature and rain against pace and tyre wear. Lower accuracy (confounded).

### From the F1 engineering PDF (Loriane Larevoir's three projects)
Ranked by how accurate they can be with our data.
- [ ] **Power and straight-line speed, plus 2026 battery clipping** (PDF project 1). *idea, most accurate*
  Speed-trap speeds and full-throttle acceleration per team (measured). Detect 2026 clipping:
  full throttle, no brake, speed falling before the braking point (inferred; 2023-25 as the
  control). Season-aware power calculator: 2014-25 100 kg/h fuel flow; 2026 3,000 MJ/h energy
  flow plus a 350 kW MGU-K. Horsepower itself cannot be measured (drag and mass unknown).
- [ ] **Mass and balance** (PDF project 3). *idea*
  Ballast-position calculator for each season's minimum weight and axle-load rule, plus "what
  1 kg costs per lap" from the measured fuel effect.
- [ ] **Aero load along a real lap** (PDF project 2). *idea, least accurate*
  Downforce, suspension compression and floor clearance every 5 m of a real lap, with the real
  air density of that race (pressure, temperature, humidity). Downforce coefficient, stiffness
  and ride height are assumed: label it a model. Catch impossible results (the PDF's own example
  puts the floor 93 mm below the road).
- [ ] **Verify the FIA figures before coding** the calculators: the 2023-25 front-axle window
      (the PDF says 44.5-46%), and 2026's 768 kg minimum mass with axle floors of 0.44 and 0.54 of
      it. One source suggests the 2026 rules were revised in October 2025 (Section C, issue 14).

## 5. More data sources

- [ ] **Jolpica-F1 history** to re-test the title-odds and race-prediction models on decades of
      seasons (results and standings from 1950, lap times from 1996, pit stops from 2011).
      Biggest accuracy gain available: title odds were checked on three seasons only.
      Free, about 4 requests a second and 500 an hour.
- [ ] **DHL Fastest Pit Stop Award times** as an independent check of the pit-crew ranking
      (stationary times; a full stop-by-stop list was not confirmed).
- [ ] **OpenF1** (free history from 2023, live is paid). A new external host: ask before
      calling it, and check it still publishes since F1's archive change.
- [ ] **Open-Meteo** rain forecasts for race predictions; **Pirelli** tyre allocations and
      predicted strategies. Neither checked yet.

## 6. LinkedIn and portfolio

- [ ] Record a 20-30 second clip of the replay playing for the post (offered).
- [ ] A page with copy buttons for the project text, post and captions (offered).
- [ ] "Quiz me": the whiteboard drill on how Racecraft works, before posting.
- [ ] Add the race Wilcoxon result to the project description once section 3's test is done.
