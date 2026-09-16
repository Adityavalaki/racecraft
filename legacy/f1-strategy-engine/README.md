# F1 Race Strategy Engine

Predicts optimal pit windows and undercut/overcut probability using historic
race data (training) and live session data (inference during a race weekend).

## Why this project

Race strategy is one of the few genuinely quantitative, high-stakes decisions
made in real time in motorsport. Building this properly — not just a lap-time
predictor — is what separates a "F1 fan who did a Kaggle notebook" portfolio
from something a race engineer or strategist would actually recognize.

## Data sources

- **FastF1** (historic, 2018+): lap times, tyre compounds/age, pit stops,
  sector times, weather, telemetry. This is your TRAINING data.
- **OpenF1 API** (live + historic, higher frequency): session status, live
  intervals, stint data, car data during an ongoing session. This is your
  INFERENCE data — what the model runs against during a real race weekend.

## IMPORTANT — run this locally, not in a sandboxed environment

FastF1 hits `api.formula1.com` / Ergast-derived endpoints, and OpenF1 hits
`api.openf1.org`. If you're running this from a restricted network (e.g. a
locked-down cloud sandbox or corporate proxy), these calls will fail. Run it
on your own machine or a normal Colab/cloud VM with open internet.

## Verification status

This code has been run against synthetic data matching FastF1's real schema
— not against real FastF1/OpenF1 data, because this sandbox has no network
access to those APIs. Two real bugs were caught and fixed this way:

1. `TrackStatus` comparison silently emptied the entire dataset after a CSV
   round-trip (pandas re-infers it as `int64`, breaking a string comparison
   with zero error — just silent empty output).
2. NumPy ≥2.0 raises on `float()` of a 1-element array; this was wrapped in
   a bare `except Exception`, so degradation numbers were silently NaN for
   every row until fixed.

Both are fixed in `tyre_degradation.py`. The lesson generalizes: don't wrap
a calculation you need to trust in a bare `except Exception: value = NaN`
without at least printing what failed — it hides exactly the bugs above.

### Real-data review (September 2026)

The first run against real FastF1 data (2024 rounds 1-5, via the Racecraft
lake) plus a code review found four more problems. Two are fixed; two are
design-level and are left documented rather than patched.

**Fixed:**

3. **Stints were grouped across races.** Degradation fits and the training
   join used `(Driver, Stint)`, so "VER stint 1" from every race collapsed
   into one curve. On a two-race test with a 12 s track pace difference,
   `fit_r2` fell from 0.91 to 0.004. Keys now include `Year` and `GrandPrix`.
4. **Undercut/overcut maths had the pit loss sign backwards.** The formula
   credited the stop as time gained, so a 15 s gap with 0.1 s/lap of tyre
   advantage returned "succeeds, confidence 0.95". Both cars pay the same
   pit loss in an undercut, so it now cancels.

**Also fixed, and the interesting ones:**

5. **Target leakage made the headline MAE meaningless.** The label was the
   tyre age at the pit stop, while `n_laps` and `deg_delta_3to15` were
   computed over the whole stint — which ends at that same stop. Across 166
   real pit stops, `n_laps` correlated 0.964 with the label:

   | Evaluation | MAE (laps) |
   |---|---|
   | Always predict the mean | 5.67 |
   | The old model, shuffled 5-fold CV, as it reported itself | 1.22 |
   | Leave-one-race-out | 1.46 |
   | Without `n_laps` | 4.32 |
   | Only features known before the stop | 6.83 |

   It was not predicting pit calls; it was reading stint length back. No
   amount of tuning fixes a question asked that way, so the question changed.
   `src/models/pit_decision.py` now asks, on every lap, *does this car stop at
   the end of this one* — with every feature built from earlier laps only.

   **That reframing leaked too, on the first attempt**, and the score gave it
   away: average precision 0.76, twenty-three times the base rate, resting
   almost entirely on "this lap was slow". A lap on which a car pits contains
   the pit lane, so its lap time is some twenty seconds slower than its
   neighbours — the model was spotting a stop that had already happened. The
   lap being decided is now excluded from its own features.

   The honest score, scored with whole races held out:

   | | Value |
   |---|---|
   | Base rate (what guessing scores) | 0.032 |
   | Average precision | **0.134** |
   | Better than guessing | 4.2x |

   Modest, and it is a score for the question actually being asked. What the
   model leans on is now a strategist's list: race progress, degradation so
   far, pace lost against the stint's best, stops already made.
6. **`deg_delta_3to15` extrapolated.** It evaluated each stint's quadratic at
   tyre ages 3 and 15 while fitting any stint of 4+ clean laps, so a 6-lap
   stint with true degradation of +1.20 s came back as +0.41 s — a quadratic
   read outside its data goes wherever its curvature points. There is now a
   `deg_s_per_lap` measured by a straight line across the laps actually run,
   which cannot leave the data it was fitted to, and `deg_delta_3to15` is null
   unless the stint really covered ages 3 to 15.

`python -m pytest tests -q` covers both, because this project has now made the
same mistake twice in two different disguises.

Also confirmed on real data: multi-character `TrackStatus` values (`'12'`,
`'21'`) do occur, and the `astype(str) == "1"` filter handles them correctly.

**Still unverified against the real APIs** — expect to debug on first run:
- `openf1_client.py`'s retry logic and `get_drivers()` — field names
  (`full_name`, `team_name`, `gap_to_leader`, `tyre_age_at_start`,
  `lap_start`) were checked against OpenF1's public docs and look correct,
  but the client itself has never hit the live API.
- `auto_fill_from_data()` in the strategy module — same caveat, plus it's
  the most speculative piece of the whole project.
- The Streamlit dashboard — parses and its function references check out,
  but has never actually been launched in a browser.

**Correction on API cost:** an earlier version of this README said OpenF1's
REST endpoints are free during live sessions. That was based on 2025
sources and is out of date. OpenF1 now requires a paid subscription for
data inside the live window; historical data is still free. For a free
live source, FastF1's SignalR client records F1's own timing feed.

## Setup

```bash
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

First run will be slow — FastF1 downloads and caches session data locally
(`data/cache/`). Subsequent runs are fast.

## Run everything

```bash
python run_pipeline.py                    # load, engineer features, train, backtest
streamlit run app/app.py                  # launch dashboard
```

Or step by step, matching the module order below.

## Pipeline

1. `src/data/fastf1_loader.py` — pull and cache historic sessions
2. `src/features/tyre_degradation.py` — fit per-stint degradation curves
3. `src/features/pit_loss.py` — compute team/track-specific pit stop time loss
4. `src/models/pit_decision.py` — train the pit-window model (per lap, causal).
   `src/models/train_pit_model.py` is kept only to reproduce the leakage
   described above; do not use its numbers.
5. `src/strategy/undercut_calculator.py` — real-time undercut/overcut probability
6. `src/data/openf1_client.py` — pull live session data during a race weekend
7. `app/app.py` — Streamlit dashboard tying it all together

## Realistic build order (don't try to do all 7 in one sitting)

- **Week 1:** Steps 1-2. Get FastF1 loading and caching 5-10 historic races.
  Plot degradation curves. This alone teaches you more about tyre behavior
  than most F1 content you'll read.
- **Week 2:** Steps 3-4. This is the actual ML part — everything before it
  was data engineering.
- **Week 3:** Steps 5-6. This is where it becomes a "strategy" tool instead
  of a lap-time model with extra steps.
- **Week 4:** Step 7 + polish, write-up, GitHub README with example outputs.

## What "done" looks like for your portfolio

Not "the code runs." You need:
- A written explanation of WHY the model makes a given pit call — race
  engineers care about interpretability, not black-box accuracy.
- Backtested performance against what the team actually did (were you right
  more often than the real strategist? by how much? where were you wrong?).
- At least one race where you show the model's recommendation vs. the actual
  outcome, explained in strategy terms, not just RMSE.
