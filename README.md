# Racecraft

An F1 strategy workbench. It learns tyre, pace and pit behaviour from historic
timing data, models the car state the public feed doesn't expose (tyre wear,
fuel load), and simulates races to find strategy windows.

The build plan lives at the published *Racecraft Build Plan* artifact. Phases
0–5 are built: the replay panels answer *what happened*, two further panels
answer *what the models make of it*, and live timing reads F1's own feed into
the same session clock. What is left is a race weekend to prove live against, the
write-up, and one piece of modelling — see **What is left** at the end.

## Setup

```sh
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"     # Windows
# .venv/bin/python -m pip install -e ".[dev]"       # macOS / Linux
```

## Ingest

```sh
racecraft-ingest --season 2024 --rounds 1 --sessions R   # one race
racecraft-ingest --season 2026 --sessions FP2 Q          # one session type
racecraft-ingest --prune-cache                           # everything, 2026 back to 2023
```

Every session type is ingested by default: `FP1`, `FP2`, `FP3`, `SQ` (sprint
qualifying, called Sprint Shootout in 2023), `Q`, `S` and `R`. Practice long
runs, FP2 above all, are the standard pre-race source for tyre degradation.

Sessions already in the lake are skipped, so an interrupted backfill resumes
by re-running the same command.

**Always backfill with `--prune-cache`.** FastF1 keeps two caches: a parsed
folder per session (~80-160 MB) and a shared HTTP cache file that grows about
20 MB per session. The flag deletes both for each session once it is safely
in the lake, clears leftovers from earlier runs, and compacts the file at the
end. Without it, a 2023-2026 backfill leaves several GB of cache behind.

**Backfills take hours, and that is expected.** FastF1 allows 500 uncached
requests per hour. The command checks the remaining budget before each
session and sleeps until a whole session's requests fit, logging when it
will resume. Leave it running: restarting resets FastF1's counter, but the
limit protects F1's servers and FastF1 warns that ignoring it can get you
blocked. A rejected request also counts against the limit, so retrying in a
loop makes the wait longer, not shorter.

**Windows: run a long backfill through `scripts\backfill.ps1`.** It keeps
the machine awake until ingest exits, then restores the normal setting. Idle
sleep otherwise kills the process during a rate-limit wait and the backfill
stops silently.

```powershell
.\scripts\backfill.ps1                      # everything, same defaults
.\scripts\backfill.ps1 --season 2023 --prune-cache
```

Closing the lid still sleeps the machine; change the lid action in Windows
power settings if you need that too.

Add `--verbose` to see full tracebacks for failed sessions.

## Replay interface

```powershell
cd web; npm install; npm run build; cd ..     # once
racecraft-serve                                # http://127.0.0.1:8000
```

Pick a session, scrub or play, click drivers in the tower to follow them on
the map and in the trace. While developing the interface, run `npm run dev`
in `web/` for hot reload; it proxies `/api` to the server on port 8000.

Five panels, one clock. The lower-right panel carries three tabs: the race
trace, and the two that show the models rather than the feed.

- **Timing tower** — order, gap, interval, last lap, all three sector times,
  tyre and age, stops. Purple marks the session's fastest, green a driver's
  own best, for the lap and for each sector independently.
- **Best sectors** — who holds each sector and the ideal lap they add up to,
  which is a lap nobody has driven. The gap between it and the fastest real
  lap is the time still on the table.
- **Track map** — cars from GPS on the racing line of the fastest lap.
  Positions are fetched at 10 Hz and drawn along a curve through the samples,
  so cars follow the arc of a corner instead of cutting it in facets. The
  curve passes exactly through the real samples, and reflects rather than
  duplicates a missing neighbour, so a straight stays straight at the seam
  between two fetched windows.
- **Race trace** — every driver's gap to the lap leader, lap by lap, with pit
  stops marked. Click to jump the clock to that lap.
- **Tyre model** — modelled wear per compound against what this race's tyres
  actually did. See below: the line is a prediction, not a description.
- **Strategy** — measured pit loss and neutralisation risk for the circuit, the
  cheapest plans ranked two ways, and the list of what the model cannot see,
  shown beside the ranking rather than hidden behind it.

  The two rankings answer different questions. *If green* is arithmetic: tyres
  plus pit lane, no luck. *Expected* simulates races that can be neutralised,
  where a stop costs 61% of a green one — which usually rewards a longer first
  stint, because more laps remain in which a cheap stop can arrive.

  The second is measurably the better description of what teams do. Across the
  fourteen 2026 races in the lake, comparing each ranking's cheapest stop count
  against what the field actually ran:

  | Ranking | Mean error in stops |
  |---|---|
  | If green | 0.57 |
  | Expected, with safety cars | **0.43** |

  Neither is good. Both are worse at Monaco (4.24 stops actually run) and at
  Barcelona (2.41 against a modelled 1), which is what a model with no traffic
  and no track position should be expected to get wrong.

### The tyre model panel is a prediction, not a fit

Degradation drawn over a race is combined from the season's **other** races.
The race being watched is never in its own fit, so the line was not shown the
laps the dots come from — a model fitted on the race it is drawn over hugs the
data and tells you nothing. The panel names how many races went into it.

The dots are that race's own partial residuals: lap time with driver, fuel and
track evolution removed. Getting this right took three attempts, and the two
failures are instructive enough to keep in `api/insight.py`:

| Attempt | Result |
|---|---|
| Each lap against the driver's own early-stint pace | Hard tyres 1 s/lap **faster** by age 22 — the track rubbering in, not the tyre |
| Each lap against the field's median on that lap | Track evolution gone, but medium tyres flattened to zero: early in a stint the whole field shares a tyre age, so the median moves with them and the wear vanishes into it |
| The regression's own partial residuals | Lap effects estimated *jointly* with the wear slope, so fuel and track come out while degradation stays in |

Two lines are drawn per compound: solid is the ×1.5 figure the plans are costed
on, dashed is the raw measurement. The gap between them is the cliff nobody
records. An adjusted number shown without its raw value is how a model starts
lying quietly.

### Track map accuracy

The outline is the median of the twelve fastest laps' position traces, each
resampled at even distances around the lap. A single lap makes a poor outline:
samples are spread by time, so straights are sparse, and any dropout becomes a
chord cutting across a corner. Measured against published circuit lengths the
result is consistently 1-2% short, which is what cutting the apexes costs:

| Circuit | Measured | Official |
|---|---|---|
| Bahrain | 5.333 km | 5.412 km |
| Silverstone | 5.822 | 5.891 |
| Monza | 5.757 | 5.793 |
| Zandvoort | 4.204 | 4.259 |
| Monaco | 3.265 | 3.337 |

`tests/test_outline_realdata.py` keeps this honest; it skips when the lake is
missing.

**The position feed's timestamps jitter**, at intervals of 0.08-0.50 s where
the cadence is 0.24 s, while the positions themselves are smooth. Sampling an
even grid straight off those timestamps makes a car leap: 4.9% of intervals
imply over 340 km/h when the cars never exceed 331.

Smoothing the coordinates does not fix this and makes it worse - median
filtering, trajectory smoothing and an even cadence were all measured and all
lost. The noise is in the *mapping from time to distance*, so that is what is
smoothed: distance along the car's own path is fitted against time with a
local straight line over half a second. Positions are never altered, only the
judgement of how far along the path the car had got at each instant.

| | Over 340 km/h | p99 | Path moved by |
|---|---|---|---|
| Raw | 4.9% | 424 km/h | — |
| Smoothed, 0.5 s | **0.02%** | **312 km/h** | 1.3 m |

A metre on a circuit 5 km round is invisible; the leaping is not.
`?smooth=0` on `/frames` returns the raw feed, and `smooth=0.8` steadies it
further at the cost of about 2.4 m.

Genuine position jumps remain and are left alone: the feed occasionally lags
and catches up in one step, moving a car over 60 m in about 0.1% of samples.

### Gaps

Gaps are derived the way broadcast timing derives them, from line-crossing
times, because the public feed carries no interval field. A car is only shown
as lapped when the leader had completed more laps *at the moment that car last
crossed the line*; comparing current lap counts would label the whole field
"+1 LAP" for most of every lap.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/sessions` | every session in the lake |
| `GET /api/sessions/{key}` | drivers, track outline, session bounds |
| `GET /api/sessions/{key}/state?t=` | one instant: order, gaps, tyres, positions, telemetry |
| `GET /api/sessions/{key}/frames?start=&end=&hz=` | a window of positions for playback |
| `GET /api/sessions/{key}/laps` | the whole race trace, plus leader crossing times |
| `GET /api/sessions/{key}/insight` | degradation, pit loss, neutralisation risk, ranked plans |
| `GET /api/circuits` | measured pit loss and neutralisation risk, every circuit |

A session is read into memory once (about 1.6 s), after which a state costs
~25 ms and a 30-second position window ~25 ms and 43 KB. Telemetry is thinned
server-side; the browser never sees raw samples.

`/insight` is the expensive one: the first call for a season fits every race in
it, about 13 s, and later calls cost about 5 s — nearly all of it the Monte
Carlo behind the safety-car ranking.

That ranking simulates a pruned field, because simulating every plan took 25 s.
The prune is a bound rather than a guess: a plan cannot cost less than its green
cost minus the discount on its stops, so anything whose floor sits above the
best plan's green cost cannot win and is never run. The bound is exact but loose
for two-stop plans — at Zandvoort 3054 of 6234 survived it — so the survivors
are screened on 120 runs and only the leading 24 re-run on 1500. A screen noisy
by a tenth cannot lose a plan that wins by more, and what is displayed always
comes from the accurate pass. `tests/test_insight.py` checks the bound against
the full field rather than trusting it.
Each race is fitted separately rather than the season as a whole, which is what
makes holding one out free. The interface does not ask for it until a tab that
needs it is opened, so a replay never pays for a fit nobody looked at.

## Live timing

```powershell
.venv\Scripts
acecraft-live record --name baku-2026     # leave running from FP1
.venv\Scripts
acecraft-live status                      # what has been recorded
.venv\Scripts
acecraft-live read                        # parse it and report
```

F1's own timing feed is a SignalR stream at `livetiming.formula1.com` — the same
one MultiViewer reads for timing. FastF1 ships a client that writes it to a file,
which sounds like a limitation and is closer to a feature: the recording is the
source of truth, it survives a crash of whatever is reading it, and it replays
afterwards exactly as it arrived.

### No F1 TV subscription is needed

FastF1's client says otherwise. It attaches an F1 TV token by default and prints
*"this feature requires an active F1TV Access/Pro/Premium subscription"* if it
cannot find one. The timing stream does not check: connecting with an empty token
returns the driver list, lap count, race control messages and the rest. Verified
against the live server from an account-less machine — 17 messages and 106 KB in
40 seconds, outside a session.

FastF1 has a `no_auth=True` flag meant to say exactly this, and it is broken in
3.8.3: it sets the token factory to `None`, and the SignalR library underneath
rejects that with `access_token_factory is not function`. So `recorder.py`
substitutes a factory returning an empty string rather than passing the flag,
which is why it reaches into the library. `--subscription` uses FastF1's own
login for anyone who has an account and would rather.

A subscription buys *video*, which this project does not use and should not
rebuild — that is MultiViewer's job. Run Racecraft beside it.

So live mode is a recorder and a reader rather than a streaming pipeline. A
recording parses into the same FastF1 session object a historic session does, so
it goes through the same `ingest.fastf1_source.extract` and comes out as the same
tables. That is what makes live a data-source swap rather than a second
application, and it is the reason the session clock was built the way it was.

Start recording before the session you care about. The feed carries no history,
so whatever happened before the recorder started is gone; the recording appends
across reconnections, and the connection drops after about two hours, which is
handled rather than treated as the end.

**Not yet carried live:** car telemetry and positions, so no track map. They are
the overwhelming majority of the feed's volume and the least of its strategy
value — a race is 1.4 million position samples against a few thousand lap rows.
The timing side is what the tower, the trace, the tyre model and the strategy
board read.

### Watching it

```powershell
.venv\Scripts
acecraft-live record --name baku-2026    # one terminal
.venv\Scripts
acecraft-serve                           # another
```

Open the interface and `LIVE` is at the top of the session dropdown, selected by
default — a recording exists only because someone started it, which is as clear
a statement of intent as an interface is going to get. An empty recording is not
offered: a recorder started before a session sits connected and writes nothing,
and listing that would hand back an error when clicked.

Live is a session key, not a second set of endpoints. `/api/sessions/live/state`,
`/laps` and `/insight` all work, so the timing tower, the race trace, the tyre
model and the strategy board need no live code path at all. The only part of the
server that knows live exists is `api/live_store.py`.

The clock follows the newest lap. Scrubbing back stops it following — someone
looking at lap 12 should not be yanked to lap 40 a second later — and **Go live**
resumes. A session that is not ready answers 409 rather than 404, because the
difference decides whether the interface should retry, and in the opening
minutes of a session it always should.

One asymmetry worth stating: a finished race is scored against a model that
never saw it, and the strategy panel says `held out`. A race in progress is
watched with a model fitted on every race that finished before it. Both are
honest and they are not the same arrangement, so the response carries `is_live`
and the panel says which it is.

**Proven, on real feed data.** Outside a session the feed serves the last
completed one, so a 40-second recording of the 2026 Spanish Grand Prix was put
through the whole path: 1,106 laps, 183 race control messages, 22 results and
161 weather rows parsed into the lake's tables, then served to every endpoint.
The tower at t=7000 has LEC leading lap 34 on a 34-lap-old hard, ANT +2.934,
VER +8.416; the lap chart carries 22 drivers over 57 laps; the strategy board
costs plans against Madrid's measured 26.5 s pit lane.

Finding session time zero is what that exercise cost. FastF1 derives it from the
telemetry stream, which live mode does not carry, and it cannot be recovered
from the laps either — a live recording's `LapStartDate` comes back entirely
null for the same reason. It is read off the recording instead: the first
message's timestamp is the zero every session time in it was measured against.
Without it, parsing fails outright on race control, the one table FastF1 stores
as absolute datetimes.

**Still unproven:** a session actually in progress, where the recording grows
under the reader. That waits for Friday practice at Baku. Everything testable offline is tested
— the recording format round-trips through FastF1's own parser, a dropped feed
appends rather than starting a second file, a half-written recording reads as
"not ready" rather than crashing, and the reader caches instead of re-parsing on
every request. The connection waits for a real session.

## Analysis commands

```sh
racecraft-analyse pace                 # fuel and degradation, per season
racecraft-analyse pace --season 2026   # one season, race by race
racecraft-analyse circuits             # pit loss and neutralisation risk
racecraft-analyse circuit Baku         # everything known about one circuit
racecraft-analyse strategy Baku        # cheapest plans, counted in seconds
racecraft-analyse race Baku            # simulate the field, answer in places
```

Every model number quoted below comes from these, so they can be reproduced
rather than taken on trust. For example:

```
Baku
  pit lane costs      21.0s  (± 1.0s, 42 green-flag stops, 3 seasons)
  neutralised         100% of 3 races, 0.83 allowing for the short history
  when it happens     4.1 laps under SC or VSC
  races in the lake:
    2023  51 laps, 1.20 stops per driver, hard 82%, medium 18%, soft 0%
    2024  51 laps, 1.20 stops per driver, hard 77%, medium 23%, soft 1%
    2025  51 laps, 1.05 stops per driver, hard 62%, medium 38%
```

## Circuit-owned estimates (Phase 3, in progress)

Tyre wear and relative pace belong to the car, so 2026 can only be learned
from 2026. Pit loss and safety car likelihood belong to the circuit — the
length of the pit lane, the walls and run-off — so they pool across every
season, which is what makes them usable for a circuit the current cars have
not raced on yet.

Pit loss is a driver's own in-lap and out-lap against their pace either side
of the stop, which cancels car, fuel and track. Stops under a safety car are
excluded: they are far cheaper, and including them would understate what a
green-flag stop costs. Spa is cheapest at 18.0 s, Imola dearest at 27.8 s.

Safety car risk counts SC and VSC together and is shrunk toward the league
average by four races, so a short history reads as "probably high" rather than
"always": Baku 0.83 rather than 1.00, Monza 0.47 rather than 0.25.

**A trap worth knowing about:** FastF1's location names drift between seasons.
Monaco became "Monte Carlo" in 2026 and Miami became "Miami Gardens" in 2025,
so keying on the raw name silently splits a circuit's history in half. Event
names drift too — Barcelona stopped being the "Spanish Grand Prix" when Madrid
took the title — which is why location, aliased, is the key.

## Pace model (Phase 3, in progress)

`racecraft.model.pace` separates the two things that change a lap time as a
stint goes on: fuel burning off (faster) and the tyre wearing (slower).

Within a stint they cannot be separated at all — one more lap of tyre age is
always exactly one less lap of fuel. The split only exists across stints: the
same tyre age at two different fuel loads. So the model is fitted over a whole
race, with a baseline per driver, a fuel slope, and a degradation slope per
compound. When a race cannot support that split (every driver stopping on the
same lap), `fit` raises `Confounded` instead of returning a number. Least
squares would happily answer, splitting the effect arbitrarily while reporting
an excellent fit.

Fitted across the lake: **78 of 84 races fit, 4 refused as confounded, 2 had no
dry laps** (wet races).

Single races are too noisy to trust for degradation — the scatter in clean lap
times is 0.5-1.1 s against an effect near 0.05 s per lap, and individual races
come back negative. `fit_pooled` shares degradation across a season while each
race keeps its own fuel slope and baselines:

| Season | Fuel s/lap | Soft | Medium | Hard |
|---|---|---|---|---|
| 2026 | 0.050 | 0.025 ± 0.003 | 0.038 ± 0.002 | 0.041 ± 0.001 |
| 2025 | 0.054 | 0.060 ± 0.002 | 0.043 ± 0.001 | 0.035 ± 0.001 |
| 2024 | 0.061 | 0.080 ± 0.004 | 0.058 ± 0.001 | 0.054 ± 0.001 |
| 2023 | 0.058 | 0.046 ± 0.002 | 0.047 ± 0.001 | 0.042 ± 0.001 |

Fuel lands at 0.05-0.06 s per lap every season, which is the expected size.
2023-2025 order as you would expect: soft wears fastest, hard slowest.

### Measuring degradation without modelling fuel

The model above has to assume a shape for everything that changes as a race
runs — fuel burning away and the track rubbering in — and fits one straight
line to both. `fit_lap_effects` avoids the assumption instead of refining it:
give every lap its own effect, and anything shared by the whole field on that
lap is absorbed whatever its shape. What is left is what differs between cars
on the same lap, which is tyre age, because drivers stop at different times.

On synthetic data with non-linear track evolution added, the fuel model
compresses the gap between compounds while this one recovers it. Run it with
`racecraft-analyse pace --method lap-effects`:

| Season | Soft | Medium | Hard |
|---|---|---|---|
| 2026 | 0.033 ± 0.003 | 0.036 ± 0.002 | 0.043 ± 0.001 |
| 2025 | 0.070 ± 0.002 | 0.046 ± 0.001 | 0.030 ± 0.001 |
| 2024 | 0.079 ± 0.003 | 0.055 ± 0.001 | 0.050 ± 0.001 |
| 2023 | 0.050 ± 0.002 | 0.049 ± 0.001 | 0.037 ± 0.001 |

**2026 really does behave differently.** Softs degrade least and hards most,
the reverse of 2023-2025, and it survives both estimators and allowing the
curve to bend (`--curved`): at every stint length from 5 to 30 laps the 2026
soft loses less than the 2026 hard. Overall degradation is also far lower — a
2026 soft loses 0.86 s by lap 30 where a 2025 soft loses 2.15 s. Lighter cars
and new tyre construction make that plausible, and a hard compound struggling
to reach temperature would degrade through sliding, but this is data, not an
explanation, and it is quoted as such.

**What is still not measurable here: the cliff.** Fitted curvature is negative
for 2024 and 2025, which would mean tyres settling down as they age. That is
survivorship: a team pits when the tyre falls away, so the laps after the
cliff are mostly missing from the data. Any simulator built on these numbers
models wear up to the point teams accept, not the wall beyond it.

## Strategy (Phase 4, first pass)

`racecraft.model.strategy` costs a race plan: compound pace for every lap on a
harder tyre, wear accumulated in each stint, pit loss per stop. Then it sweeps
every plan and ranks them.

```sh
racecraft-analyse strategy Baku --laps 51 --scale 1.5
```

**Backtested against 62 dry races, 2023-2025**, comparing the predicted stop
count with the median a driver actually made:

| Degradation as measured | x1.5 |
|---|---|
| 42% exact, 87% within one stop | **53% exact, 89% within one stop** |

Measured degradation systematically **under-stops**: it predicted a one-stop
in 57 of 62 races when teams split roughly evenly between one and two. That is
the survivorship problem made concrete — degradation measured from race laps
only covers the life teams accept, so a long stint looks cheaper than it is.
Multiplying it by about 1.5 best reproduces real strategy, and that factor is
also absorbing everything the model omits: traffic, safety cars, warm-up and
track position. It is a calibration, not a physical constant.

The model prints its own limits every time it runs, because a number this
simple should not travel without them. Notably it counts **seconds, not
places**, and races are scored in places.

### Safety cars

```sh
racecraft-analyse strategy Baku --laps 51 --scale 1.5 --safety-car
```

Green-flag costing assumes a race that runs start to finish without
interruption. Races do not: one is neutralised 1.27 times on average, and a
stop taken entirely under a full safety car costs **61% of a green one** —
13.7 s against 22.5 s, measured against the drivers who stayed out on the same
laps. (Measuring it against green-flag pace instead gives 274%, which is not a
stop cost at all but the fact that every lap under a safety car is slow.)

`racecraft.model.simulate` therefore runs each plan through hundreds of races,
drawing neutralisations from that circuit's own rate, and follows the strategy
teams actually use: stop as planned, unless the race is neutralised while a
stop is still owed and the tyres have done enough laps.

This changes the answer, which is the point. At Baku:

| Plan | Expected | If green | Cheap stop |
|---|---|---|---|
| medium 30 > soft 21 | **51.8 s** | 53.5 s | 40% |
| medium 26 > soft 25 | 51.8 s | 52.6 s | 34% |
| medium 34 > soft 17 | 53.0 s | **56.2 s** | 45% |

Stopping later is the worst plan if the race stays green and among the best
once safety cars are allowed for, because a stop still owed is a stop that
might come cheap. Its downside is also bounded: the worst a plan can do is its
own green-flag race, since a neutralisation only ever makes a stop cheaper.

## Race simulator (Phase 4)

`racecraft.model.race` puts the whole field on track and runs the race lap by
lap, so strategy can be judged in places rather than seconds. Cars have their
own pace, tyres that wear, and plans; a car that catches another loses time in
its wake and only gets past when the circuit allows; safety cars bunch the
field and hand a cheap stop to whoever still owes one.

Every input is measured from the lake:

| Input | Measured | Example |
|---|---|---|
| Overtaking | pairwise on-track passes per race | Monaco 5.8, Baku 27.0, Las Vegas 48.3 |
| Following | lap time lost by gap to the car ahead | 2026: +0.55 s under 0.5 s, gone by 2.5 s |
| Pit loss | in and out lap against pace either side | Spa 18.0 s, Baku 21.0 s, Imola 27.8 s |
| Safety cars | rate, duration and the discount on a stop | 1.27 per race, 61% of a green stop |
| Pace, wear | the pace model's driver and compound terms | see above |

Following in 2026 costs less than in 2025 and fades faster with distance
(+0.06 s at 1.5-2.5 s behind, against +0.23 s in 2025), which is what the
regulations were meant to achieve.

### What it is for, and what it is not for

**It does not predict finishing order.** Validated over 30 races with pace
taken only from earlier races, it is level with predicting the starting grid:

| | Simulator | Grid order |
|---|---|---|
| Mean position error | 3.24 | 3.31 |
| Podium places hit (of 3) | 2.03 | 2.03 |
| Races won against the baseline | 15 of 30 | — |

Given each race's *own* pace instead, it looks far better — 2.54 against 3.04,
winning 31 of 36 — and that gap is the measure of how much hindsight was
doing. Finishing order is dominated by how quick each car is on the day, and
forecasting that is a different problem from strategy.

`python scripts/validate_race.py prior` reproduces both numbers.

**What it is for is comparing plans for one car**, where pace errors largely
cancel because every plan runs against the same field:

```sh
racecraft-analyse race Baku --laps 51 --grid 8
```

A midfield car starting P8 at Baku:

| Plan | Mean finish | In the points | Best case |
|---|---|---|---|
| one stop, lap 26 | **8.01** | 100% | 7 |
| one stop, lap 34 | 8.40 | 94% | **4** |
| one stop, lap 20 | 8.49 | 90% | 6 |
| two stops | 9.74 | 68% | 7 |

The late stop is the gamble: worse on average, better if the race falls your
way. That is a strategy question, and it is the shape of answer the simulator
can honestly give.

## Query

```python
from racecraft.store.db import connect

con = connect()
con.sql("""
    select driver, stint, any_value(compound) as compound, count(*) as laps
    from laps where session_key = '2024_01_R'
    group by all order by driver, stint
""").show()
```

Views: `sessions`, `results`, `laps`, `car_data`, `pos_data`, `weather`,
`race_control`, `track_status`, `session_status`, `circuit_markers`. Every
view also exposes `year`, `round` and `session` from the partition path.
`results.q1_s`/`q2_s`/`q3_s` hold qualifying times and are null for other
sessions, including every race file written before those columns existed.

## Conventions

- **One clock.** Every timestamp is `t`, float seconds since the session's t0.
  FastF1 mixes timedeltas with absolute datetimes (race control); ingest
  converts all of it. Absolute UTC is `sessions.t0_utc + t`.
- **Declared types.** Schemas live in `src/racecraft/store/schema.py` and are
  enforced at write time. `track_status` is always a string (`'1'`, `'12'`).
- **`tyre_life` is not `laps_in_stint`.** Drivers often start a stint on a set
  used in qualifying. Degradation fits should use `tyre_life`; anything about
  stint length should use `laps_in_stint`.
- **Parquet is the source of truth.** DuckDB runs in memory over it; there is
  no database file to lock or keep in sync.

## Where this came from

`legacy/` holds the two projects Racecraft replaced: an earlier strategy
engine and a single-page live pit wall. They are kept for their mistakes,
which shaped this one — a pit model that scored 1.22 laps of error while
knowing nothing, and the second leak found inside its own replacement. See
[legacy/README.md](legacy/README.md).

## Layout

```
src/racecraft/
  config.py                paths, overridable by RACECRAFT_* env vars
  ingest/fastf1_source.py  FastF1 Session -> normalised DataFrames
  ingest/quality.py        pre-write checks (errors block, warnings report)
  ingest/cli.py            racecraft-ingest
  store/schema.py          Arrow schemas for every table
  store/lake.py            atomic Parquet writes, hive partitioning
  store/db.py              DuckDB views over the lake
  api/timing.py            running order and gaps at any instant
  api/session.py           one session held in memory, ready to replay
  api/app.py               FastAPI routes
  model/pace.py            fuel vs tyre degradation
  model/circuit.py         pit loss, safety car risk
  model/strategy.py        costing and ranking race plans
  model/simulate.py        plans under safety car uncertainty
  model/race.py            the whole field, scored in places
  model/cli.py             racecraft-analyse
tests/                     offline tests, no network
web/                       React + Vite interface (npm test, npm run build)
```

## Verification status

Backfill complete: **420 sessions** covering every practice, qualifying,
sprint qualifying, sprint and race from 2023 to 2026 round 14. 1.53 GB,
229,816 laps, 370 million telemetry rows, 0 failures.

| Season | FP1 | FP2 | FP3 | SQ | Q | S | R |
|---|---|---|---|---|---|---|---|
| 2026 (to round 14) | 14 | 9 | 9 | 5 | 14 | 5 | 14 |
| 2025 | 24 | 18 | 18 | 6 | 24 | 6 | 24 |
| 2024 | 24 | 18 | 18 | 6 | 24 | 6 | 24 |
| 2023 | 22 | 16 | 16 | 6 | 22 | 6 | 22 |

Audited across the whole lake:

- **Race time:** 104 of 107 races and sprints reconcile within +0.33 s of the
  official time (median +0.25 s). The three outliers are interrupted, mostly
  wet races: 2025 Miami sprint (-4.9 s, suspended start), 2023 Dutch GP
  (-1.8 s), 2026 Dutch GP (-1.3 s). Their laps are internally consistent; the
  session start marker is a few seconds off.
- **Qualifying:** in 83 of 84 sessions the fastest lap matches a recorded
  Q1/Q2/Q3 time exactly. Pole is not always the session's fastest lap, which
  is correct: in wet 2023 Canada the fastest lap was 7.1 s quicker than pole.
- **Position data:** median 1.02 position samples per car sample.
- **FP2 long runs** (5+ timed green laps on one compound): 243 in 2026, 396
  in 2025, 493 in 2024, 444 in 2023, averaging about 8 laps. This is the
  degradation training set.

## Negative results

Kept because they cost as much to find as the positive ones, and because a
model is shaped as much by what it refuses to include.

### Tyre wear is not a circuit property, however much it looks like one

Wear obviously differs between circuits — Sakhir eats tyres, Monaco does not —
so the strategy model ought to carry a per-circuit multiplier alongside the
per-circuit pit loss and safety-car risk it already has. It should not.

Measuring each race's wear against its own season's average gives a ratio that
strips out how that year's tyres behave and leaves the circuit. Ranked, the
result looks exactly like a finding: Sakhir 2.21, Suzuka 1.62, Barcelona 1.48 at
one end; Lusail 0.31, Montreal 0.41, Miami 0.48 at the other.

It is noise. The spread *between* circuits is 0.424, and the wobble *within* one
circuit from season to season is 0.490 — bigger. A quantity that varies more
against itself than against its peers is not a property of the thing.

The out-of-sample test agrees. Applying each circuit's multiplier, measured from
the seasons other than the one being scored, to the 2026 stop-count prediction:

| | Mean error in stops |
|---|---|
| Season wear alone | 0.571 |
| With a per-circuit multiplier | 0.571 |

Identical. It fixes Austria and Hungary and breaks Canada and Zandvoort. The
giveaway is Melbourne's multiplier of 0.07, which would mean a circuit that
barely wears tyres at all.

### The 1.5 degradation scale was already right

Race data cannot see past the tyre age teams accept, so measured wear understates
a long stint and the strategy model multiplies it by 1.5. That constant was
picked by eye. `python scripts/calibrate_scale.py` checks it against every dry
race in the lake — 76 of them, four seasons — by costing every plan at each scale
and scoring the cheapest plan's stop count against what the field ran:

| Scale | Mean error | Exact | Bias |
|---|---|---|---|
| 1.00 | 0.737 | 32/76 | −0.66 |
| **1.50** | **0.553** | **41/76** | −0.38 |
| 1.75 | 0.566 | 40/76 | −0.26 |
| 2.00 | 0.566 | 38/76 | −0.11 |
| 3.00 | 0.803 | 21/76 | +0.55 |

Leave-one-season-out, choosing the scale on three seasons and scoring it on the
fourth, picks 1.50 in three years of four and averages 0.618. So the constant
stands, and it stands on a measurement rather than on the first number tried.

Worth reading the bias column beside the error. At 1.5 the model under-stops by
0.38 stops on average; at 2.0 that bias nearly vanishes, and the per-race error
gets *worse*. One constant can correct the average or the individual races, not
both, which is the clearest sign available that what is missing is not a number.

### What all three have in common

The model says one stop where Barcelona, Silverstone, Hungary and Austria ran
two, and two where Monaco ran four. It under-stops, and it under-stops because
teams buy **track position** with a stop, not lap time — a plan two seconds
quicker that rejoins behind a car it cannot pass has lost, and a model counting
seconds in a vacuum cannot see that.

No constant fixes it. Scoring plans in places rather than seconds does, which
means joining the strategy model to `model/race.py`, where a field to rejoin
into already exists. That is the remaining modelling work, and three measured
dead ends are what establish it as the only one left worth doing.

### The rejoin penalty is not measurable from where a car leaves the pits

The strategy model counts seconds and cannot see that a plan two seconds
quicker may rejoin behind a car it will never pass. The obvious fix is to
measure what rejoining in traffic costs and add it. It does not work.

`python scripts/traffic_probe.py` takes every green-flag stop since 2024 — 1,328
of them, 30 drivers, 60 races — and measures each driver's pace over the three
green laps after the out-lap against the field's median on those same laps,
against the gap to the car ahead when they rejoined.

Raw, the bands span 0.13 s/lap and are not even ordered: cars rejoining 5–8 s
behind someone are the *quickest* of all. Fitting proximity properly, with
driver fixed effects — the least you must do when quick cars rejoin in clear air
*because* they are quick — the effect dies:

| Proximity decay | Traffic penalty |
|---|---|
| 1.0 s | −0.028 ± 0.156 s/lap |
| 2.0 s | +0.040 ± 0.127 s/lap |
| 4.0 s | +0.059 ± 0.117 s/lap |

Every estimate is inside its own error bar, and the sign is not even stable.

This is not evidence that traffic is free. The project measures a following
penalty of +0.55 s/lap inside 0.5 s elsewhere, over whole races. It is evidence
that *this* design cannot see it, and the reasons are identifiable: three laps
is a short window, the car ahead may itself pit on the next lap, and a fresh
tyre is worth about 0.6 s/lap, which swamps what is being looked for.

So no traffic term went into the strategy model. A number of 0.04 ± 0.13 dressed
up as a penalty would have made every plan look more considered and none of them
more correct.

**What to try instead.** The information is not missing, it is in the wrong
model. Knowing where a plan rejoins requires a field to rejoin *into*, which the
seconds-based model does not have and `model/race.py` does. Joining them is the
remaining work, and it is a simulation problem rather than a measurement one.

## What is left

Four things, in the order they are worth doing.

**1. Run live through Friday practice at Baku, 25 September.** Everything about
live mode works against a recording — the format, a dropped feed, a half-written
file, the full parse of a real 1,106-lap recording served to every panel. What
has never happened is a recording *growing under the reader* while a session
runs. Practice is the rehearsal, and it happens once.

**2. Mark the Baku call, 26 September.** Five predictions were published ten days
early with their marking rules frozen:

```powershell
racecraft-ingest --season 2026
python scripts/mark_baku.py
```

Then write down why the wrong ones were wrong *before* reading anyone else's
account of the race.

**3. Track position inside the strategy model.** The one remaining piece that
could make it more accurate, and the only one left: three measured attempts at
tuning it are recorded above, and all three failed in the same direction. The
model under-stops because a stop buys track position rather than lap time, and a
model counting seconds in a vacuum cannot see that. Scoring plans in places needs
a field to rejoin into, which `model/race.py` has. It is a simulation problem,
not a measurement one — which is what those three failures established.

**4. The write-up.** The material is unusually good and most of it is already
written down here: two leakage bugs that scored beautifully and knew nothing,
three measured dead ends, a simulator level with grid order, a season of tyres
that wear backwards, and three interface bugs found by opening the page rather
than by any test.

Deliberately not on this list: predicting finishing order. Car pace dominates it,
forecasting car pace is a different problem, and the backtest says plainly that
this tool does not solve it.

## Known data gaps

Problems in the source feed, not in ingest. Re-downloading does not fix them.

| Session | Gap | Consequence |
|---|---|---|
| 2026 Monaco (`2026_06_R`) | Position feed stops before the race: 18% of normal coverage, almost none after lights out | No track map for the race; no position-derived features. Permanent: OpenF1's `/location` has the same gap (positions at lap 5, none by lap 30), because both record the same feed |
| 2026 Monaco, 2026 Spain (Madrid) | No `circuit_markers` (Madrid is a new circuit; Monaco follows from the position gap) | Corners must be derived from position data where it exists |
| All 2026 sessions | Throttle missing on 3.1% of samples at racing speed (2023-2025: under 0.1%). Varies by session (up to 18.9%, 2026 China sprint), not by team | Throttle-based analysis must tolerate gaps |
| 2025 Miami qualifying (`2025_06_Q`) | No Q1/Q2/Q3 times; FastF1 has none either. Positions and laps are complete | Segment times must be derived from laps if needed |
| 2025 Miami sprint, 2023 and 2026 Dutch GPs | Session clock a few seconds off | Negligible for strategy work; worth excluding from anything timing-precise |

New ingests warn on the position gap (`pos_data.coverage`), so a repeat is
reported rather than silent.

### Earlier spot checks

The first checks, run on 2024 rounds 1-5 and 2026 round 14:

| Check | Result |
|---|---|
| 2024 Bahrain: position, grid and laps vs Jolpica (independent source) | 20/20 drivers match |
| 2024 Bahrain: winner's race time and fastest lap vs Jolpica | exact to the millisecond |
| Race control lap derived from `t` vs the message's own lap field | agrees on every flag checked |
| Winner's lap span vs official time, all 7 sessions | +0.24 to +0.29 s every time, systematic (see below) |
| Red-flag race (2024 Japan), sprint (2024 China), 2026 regulations (Madrid) | all ingest and reconcile |
| `track_status` type after Parquet round trip | VARCHAR, `'1'`/`'12'`/`'21'` |
| Car telemetry sample interval during the race | median 0.24 s; 0.13% of gaps over 1 s, none over 3 s |

The +0.25 s offset: lap 1's `lap_start_t` is the session "Started" status,
slightly before lights out. The session clock is therefore accurate to about
a quarter of a second, consistently.

Feed problems found and handled at ingest:

- **Gear values up to 128**, almost all while stationary (2024 Japan: 168
  samples). Stored as null. Only 128 overflowed the column type; values like
  75 fit and had been stored silently before a domain check was added.
- **Throttle 104** is a "no reading" sentinel on 7-15% of samples. Stored as
  null. In 2023-2025 it occurs while stationary and coverage at racing speed
  is effectively complete; 2026 is worse (see Known data gaps).
- **Lap times are missing under safety cars and red flags** (e.g. 2024 China
  laps 24-28). `lap_start_t` / `lap_end_t` are still present, which is why the
  race-time check uses them.

2026 differences to design around:

- `drs` is always 0. DRS no longer exists; the replacement overtake mode is
  visible only as race control messages (`OVERTAKE ENABLED` / `DISABLED`).
- New circuits have no `circuit_markers` (Madrid: none). The track map will
  need to derive corners from position data.
- 22 cars, 11 teams.

Storage: 5.5-7.3 MB of Parquet per race with telemetry (1.2-1.6 M telemetry
rows), against 80-160 MB of FastF1 cache for the same race.

