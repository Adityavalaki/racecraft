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

## The app

Racecraft runs as a desktop application: an icon that opens it in its own
window, with no terminal, no port to remember and nothing to leave running.

```powershell
.venv\Scripts\python -m pip install -e ".[app]"    # adds pywebview
cd web; npm install; npm run build; cd ..          # the interface, once
.venv\Scripts\racecraft --install-shortcuts        # Desktop + Start menu
```

Then double-click **Racecraft** on the Desktop. One process does everything:

- **Its own window.** pywebview on the Edge engine (WebView2, which Windows 11
  ships), 1440×900. Links out (the Pirelli sources) open in the default browser.
- **Its own port.** The API is served on `127.0.0.1` at a port the system picks,
  so nothing else on the machine can be in its way; 8000 is never touched.
- **Syncs while open.** Ten seconds after launch, then every fifteen minutes, it
  does what the **Sync latest 5** button does, and the button shows its progress.
  New sessions appear in the picker without a reload. Closing the window stops
  it; a session half-fetched at that moment is fetched again next time, because
  the lake writes a session's row last.
- **One at a time.** A second double-click brings the open window forward
  instead of starting a second server and a second sync on the same lake.

Closing the window ends the process within a second or two. Nothing runs when
Racecraft is closed; `--install-shortcuts` also removes the logon watcher that
earlier versions started, and stops it if it is running. The app logs to
`data/logs/app-YYYYMMDD.log`, and anything that stops it starting says so in a
message box. `racecraft --uninstall-shortcuts` removes the icons.

The terminal commands below are all still there for development and for
backfills.

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

Open the app, or serve it in a browser while developing:

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
  cheapest plans ranked three ways, and the list of what the model cannot see,
  shown beside the ranking rather than hidden behind it.

  The first two rankings count seconds. *If green* is arithmetic: tyres
  plus pit lane, no luck. *Expected* simulates races that can be neutralised,
  where a stop costs 61% of a green one — which usually rewards a longer first
  stint, because more laps remain in which a cheap stop can arrive.

  What that is worth is measured, held out, over 32 dry races in 2025 and
  2026 (`python scripts/validate_safety_car_timing.py`), against what the field
  actually did:

  | Ranking | Error in stop count | Error in first stop lap |
  |---|---|---|
  | If green | 0.516 stops | — |
  | Expected, flat safety-car rate | 0.516 stops | 9.0 laps |
  | Expected, measured timing | 0.516 stops | **8.2 laps** |

  Two things to read there, and the first corrects an earlier claim in this
  file. Allowing for safety cars does **not** pick a better stop count than the
  green arithmetic: held out, both are 0.516 stops out. The figures once quoted
  here — 0.57 against 0.43 — came from a version that was not held out, and they
  did not survive being one. What survives is the direction of the bias: the
  safety-car ranking under-stops by 0.20 against the green ranking's 0.27.

  Where it does earn its place is *when* to stop, and only once the timing is
  measured rather than assumed. A quarter of all neutralisations begin in the
  opening tenth of a race, where a car has run too few laps for a cheap stop to
  be worth taking; a flat rate promises a discount those cannot deliver and
  holds the first stop too long for it. Shaping the rate by when they really
  arrive moves the first stop in 9 of 32 races and closes the gap to the field
  from 9.0 laps to 8.2, with the bias toward stopping late falling from +5.9 to
  +4.9 laps.

  None of it is good. The model still stops five laps later than the field, and
  it is worst at Monaco and Barcelona, which is what a ranking with no traffic
  and no track position should be expected to get wrong.

  *In places* is the third, and it has both, and it races the tyres the car
  actually has — *Its own tyres* against *New sets* is the difference between
  the plan a car can run and the plan it would run in an ideal world. It races each shortlisted plan
  against the whole field from a chosen grid slot and ranks by finishing
  position — the race simulator below, on inputs taken only from races that
  started before this one. Plans whose finishes cannot be told apart are marked
  tied rather than ranked, and the headline is not a winner but the **price of
  track position**: what the cheapest plan that is as good as the best costs in
  seconds, against the cheapest plan outright. It takes about half a minute the
  first time for a race and a grid slot, so it is only run when opened.

- **Tyre sets** — every car's dry sets, following the replay clock: new sets
  filled, used ones ringed with the laps on them, the set on the car
  highlighted. Selecting a car ranks the strategy model's plans on the tyres it
  actually had, and says which it could not run. See *Tyre sets* below.

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

### Race control

The feed carries 9,947 race and sprint messages and, until now, the interface
read none of them. They are the only place it says *why* something happened, so
`api/penalties.py` reads them into per-car state: seconds still to serve, stop/go
and drive-through penalties outstanding, open investigations, deleted lap times.
The tower's **PEN** column shows the most consequential thing outstanding against
each car and the whole standing in its tooltip. The **Stewards** panel, beside the
track map, holds the verdicts themselves — it is watched rather than consulted, and
news behind a tab is news nobody sees. It takes width the map was not using, so
the tower keeps its floor and the charts below keep their height; below 1360px it
drops under the map rather than squeezing three columns.

Kept deliberately plain. Two lines per verdict — who and what, then the offence —
because four columns in a narrow panel crush all four. No controls of its own: the
tower's selection is the only filter, which is how every other panel here narrows
already. Emphasis carries the hierarchy, a penalty loud and anything settled grey.

Race control is two separate panels in the right-hand column: **Stewards**
beside the map and **Track** beside the charts below it, each a full row high
and each scrolling on its own. Both are always visible, with nothing hidden
behind a control.

The track list is short because the feed's churn is left out. `Event.topic`
splits race control three ways rather than two: a blue flag is shown to one
lapped car as it is passed and a sector flag repeats every time a sector changes
state, and together those are **4,771 noise messages** against 3,257 from the
stewards and 1,919 genuine track events. What is left — the safety car, the race
flags, the pit exit, DRS, a slippery patch, a recovery vehicle, a resumption
order — is a median of **18 events a race**, which is short enough to read. The
line is drawn on the flag words rather than on the phrase "IN TRACK SECTOR",
because `TRACK SURFACE SLIPPERY IN TRACK SECTOR 11` is a condition worth reading
and 176 of those were swept up by the looser rule.

Deleted lap times are left out of the verdicts list too, and they are **47% of
every steward message** (1,533 of 3,257): in a race a deletion is a track-limits
tick, and what matters is how many a car has collected, which is exactly what the
PEN column counts. Nothing is lost — every message is still served by the API
(`?topic=track`, `?topic=noise`) and still counted against the driver.

The **PEN** column answers one question, *does this car still owe something?*, and
shows four marks rather than a vocabulary: `DSQ` out of the race, `+5s` for time
still to serve, `STOP` for a stop/go or drive-through, `•` while the stewards are
looking, `–` for nothing. An earlier version answered five questions with eight
marks, which had to be learned before the column meant anything; everything
settled — a served penalty, a deleted lap, a black-and-white flag — is in the
tooltip and the panel instead, because it changes no decision.

What counts as the stewards' is whether the message carries a verdict, not
whether it says `FIA STEWARDS:`. Only 971 of the 3,257 do, so filtering on the
prefix would drop **70%** of them — no lap deletion carries it and most incident
notices do not either. Nothing with the prefix lacks a verdict, so the verdict is
the stronger test. The filter is applied server-side before the limit, so asking
for the stewards' last sixty returns sixty of theirs rather than sixty of
everything of which twenty happen to be theirs.

It is a pure function of the message table and a time, like `timing.classify`
beside it. That is what makes scrubbing correct: an accumulator would be wrong
the moment the clock went backwards, and the scrubber, the -30s button and live
"following" all move it freely. At lap 12 the column shows what was known at lap
12 however the clock got there, and it is computed at the same `t` as the gap
next to it, so the two cannot describe different moments.

Parsed rather than judged, because the FIA's text is machine-generated and its
grammar is rigid. Three measurements over every race and sprint in the lake set
the shape of it, and each corrected an assumption:

* **Anchoring on the word CAR is wrong.** `CARS 31 (OCO), 77 (BOT) AND 20 (MAG)`
  writes it once for three cars, and requiring it found only the first on
  **1,514 messages** — every multi-car incident silently lost all but one car.
  The three-letter code is the anchor instead, and the number in front of it is
  the car. That code is also what makes extraction safe: a message is full of
  other numbers — `1:40.956`, `TURN 9`, `LAP 10`, `14:23:43` — and none of them
  is followed by one. 3,229 of 3,256 car-concerning messages match; the 27 that
  do not name no car, or name a team, which is resolved to that team's cars.
* **Two things match that are not cars, and one of them is dangerous.** A
  deletion ending `... 16:12:10 (PIT)` offers `10 (PIT)`, and 10 is a real
  driver — so a message about car 23 charges a deleted lap to car 10. `CAR 26
  (BED)` is the other kind: a real car in another championship sharing the feed.
  **337** phantom matches are rejected across the lake, **200** of them carrying
  a number that belongs to an actual driver. Timestamps are stripped before
  scanning and every number is checked against this session's driver list.
* **An incident is reported four times, not once.** Noted, then under
  investigation, then a penalty or no further action — so counting messages
  counts one incident four times. They are tied together instead: 15.8% carry a
  trailing `(15:03:08)` that is the incident's own identity, and the rest match
  on the offence plus an overlapping car, which links **88.1%** of noted
  incidents to a later verdict. Matching on the offence alone was wrong and the
  test that proves it is a real race: at 2026 Spain, SAI was in a TURN 8
  collision with COL and another with HUL twenty seconds later, both `CAUSING A
  COLLISION`. The second merged into the first and was cleared by the first's
  verdict. A closing verdict may now only attach to an open incident whose cars
  its own are a subset of.

The verdicts are a closed set and `_classify` leaves nothing unread across all
3,256. `tests/test_penalties.py` guards that against a new season's wording —
it is what caught `STOP-AND-GO` as a second spelling of `STOP/GO`, and the one
`BLACK FLAG` in the lake, a disqualification that had been folded in with the
black-and-white warning flag.

What no rule reaches is whether an awarded time penalty was **served at a stop
or added to race time at the flag**. `PENALTY SERVED` settles 48 of 235; the
rest are left pending rather than guessed at. That matters beyond the display:
235 in-race penalty messages stand against 1,958 measured green-flag stops, and
a penalty served at a stop inflates that stop's cost *inside* the 5–60 s window
`model/circuit.py` keeps — so pit loss quietly absorbs it. Deciding it is a
question about a sequence rather than a string, which is the one place in this
feature a judgment would earn its keep.

### API

| Endpoint | Purpose |
|---|---|
| `GET /api/sessions` | every session in the lake |
| `GET /api/sessions/{key}` | drivers, track outline, session bounds |
| `GET /api/sessions/{key}/state?t=` | one instant: order, gaps, tyres, positions, telemetry, penalties |
| `GET /api/sessions/{key}/frames?start=&end=&hz=` | a window of positions for playback |
| `GET /api/sessions/{key}/laps` | the whole race trace, plus leader crossing times |
| `GET /api/sessions/{key}/messages?until=&limit=&topic=` | race control up to `until`, newest first, each message read; `topic` is `stewards`, `track` or `noise` |
| `GET /api/sessions/{key}/insight` | degradation, pit loss, neutralisation risk, ranked plans, plans checked per car |
| `GET /api/sessions/{key}/tyre-sets` | every car's sets at the start of the session and during it |
| `GET /api/sync`, `POST /api/sync?weekends=5` | bring the latest race weekends into the lake, and its progress |
| `GET /api/sessions/{key}/places?grid=&tyres=` | plans raced against the field, ranked in places, on that car's tyres or new ones |
| `GET /api/circuits` | measured pit loss and neutralisation risk, every circuit |

**The server no longer crashes on long sessions.** DuckDB kills the process with a native fault after roughly 1,000–3,000 repeated scans of a table spread over many Parquet files (reproduced on 1.4.5, 1.5.4 and 1.5.5), and the API used to scan on ordinary requests. Now one database per lake is built once, the small tables are held in memory and reloaded only after an ingest, and telemetry is read one partition at a time; `store/db.py` has the measurements. A smoke test that crashed the process twice now serves all 420 sessions, 4,200 requests, without a failure. The first request after start-up pays about 10 s to load the small tables.

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
.venv\Scripts\racecraft-live record --name baku-2026     # leave running from FP1
.venv\Scripts\racecraft-live status                      # what has been recorded
.venv\Scripts\racecraft-live read                        # parse it and report
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
.venv\Scripts\racecraft-live record --name baku-2026    # one terminal
.venv\Scripts\racecraft-serve                           # another
```

Open the interface and `LIVE` is at the top of the session dropdown, selected by
default — a recording exists only because someone started it, which is as clear
a statement of intent as an interface is going to get. An empty recording is not
offered: a recorder started before a session sits connected and writes nothing,
and listing that would hand back an error when clicked.

On race day the strategy views work off the weekend's own sessions: the sets
each car has left come from practice and qualifying, already in the lake, and
the grid from the qualifying result, since the race has no classification until
it ends. Penalties are not applied to that grid, and the panel says so. Live
answers are never cached — the race changes underneath them.

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
telemetry stream, which live mode does not carry, and a live recording's
`LapStartDate` comes back entirely null, so it cannot come from the laps either.
It is taken from FastF1's own parse of the recording instead (`live/feed.live_t0`):
the moment the session status became Started, or failing that the first message
FastF1 could read. Reading the first message ourselves, as this first did, put a
recorder switched on at 08:10 for an 08:30 session **twenty minutes** off the laps,
so every penalty would have sat beside the wrong lap. The laps are FastF1's, so
race control has to be on FastF1's clock, and now reads it rather than re-deriving it.

**What that exercise did not prove.** Repeated on 23 September, the recording held
only the connection snapshot, and none of its lines carries a timestamp, so FastF1
had nothing to parse and quietly filled the laps from its cache of the finished race
— which is why they matched the lake to the millisecond. The endpoints and panels
were exercised on real data; parsing laps *from the feed* was not.

**Still unproven:** a session actually in progress, where the recording grows
under the reader. That waits for first practice at Baku, Thursday 24 September. Everything testable offline is tested
— the recording format round-trips through FastF1's own parser, a dropped feed
appends rather than starting a second file, a half-written recording reads as
"not ready" rather than crashing, and the reader caches instead of re-parsing on
every request. The connection waits for a real session.

### Keeping the lake current

**From the interface:** the **Sync latest 5** button in the top bar brings the
five most recent race weekends into the lake — every session whose data has
been published, a weekend in progress included. It checks what is already there
and fetches only the rest, in the background, naming the session in hand while
it works; nothing to fetch takes a second, a missing weekend with telemetry a
few minutes. When it has written anything, every cached model fit is dropped,
so the strategy views and the simulator use the new races straight away, and
the session list is read again so they appear in the picker.

**While the app is open** it presses that button itself, ten seconds after
launch and every fifteen minutes after (see **The app**). That is the intended
way to stay current: open Racecraft after a session and its data comes in.

It and the watcher below can run at once. Each session is written by one
process at a time: a second writer finds the session's lock and leaves it, and
a lock whose writer is no longer running, or has sat for half an hour, is
taken over.

**From a terminal, without the app:**

A session's timing data is published a few hours after it runs, and the lake is
only useful once it is in. `--watch` does that by itself:

```powershell
racecraft-ingest --season 2026 --watch
```

It looks every fifteen minutes, ingests anything whose data has appeared —
four hours after a session starts, which is the session plus the feed's own
delay — skips what it already has, and logs what it is waiting for next. One
broken session does not stop the others. A race that lands is followed by a
brief in the log: distance, pit loss, safety-car rate, the wear fitted for it,
and any caveat its inputs carry, all from races before it.

Only one watcher runs at a time; a second finds the lock and stands down,
because two of them writing the same Parquet files is the one way this breaks.
A watcher killed without cleaning up hands over at once to the next one; a
lock nobody has touched for ninety minutes is taken over whoever holds it.

It used to be started at logon from the Startup folder. The app replaced that,
because syncing only while Racecraft is open is what was wanted, and a hidden
watcher killed by a closed console window is what went wrong twice.

## Analysis commands

```sh
racecraft-analyse pace                 # fuel and degradation, per season
racecraft-analyse pace --season 2026   # one season, race by race
racecraft-analyse circuits             # pit loss and neutralisation risk
racecraft-analyse circuit Baku         # everything known about one circuit
racecraft-analyse strategy Baku        # cheapest plans, counted in seconds
racecraft-analyse race Baku            # simulate the field, answer in places
racecraft-analyse race Baku --driver HAD   # on the tyres that car actually had
racecraft-analyse following            # time lost in the wake of the car ahead
```

The scripts beside them answer "is this worth anything?", and every figure this
file quotes comes from one of them:

```sh
python scripts/validate_race.py prior      # finishing order, held out, against the grid
python scripts/validate_tyres.py 2025      # what racing a car's own tyres changes
python scripts/validate_tyre_sets.py       # how often the set tracker is right
python scripts/compare_compounds.py        # C-number against label for tyre wear
python scripts/calibrate_scale.py          # the 1.5 degradation scale
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

Every input is measured from the lake, and for a race that has happened, only
from races that started before it (`model/race_inputs.py`). The strategy tab's
seconds and safety-car rankings use the same cutoff: they used to take a race's
pit loss and safety cars from every race at the circuit, itself included. Tyre wear, the pace
ladder, pit loss, safety-car risk, overtaking and the wake penalty all stop at
the same date. It used to be otherwise: analysing Baku 2025 fitted tyres on
Baku 2025, took the pace ladder from races after it, and measured pit loss from
its own stops. `--include-race` still does that, for comparison, and says so.
The price is that the first race at a new circuit cannot be simulated, because
there is no earlier pit lane to measure; it refuses rather than borrowing its
own.


| Input | Measured | Example |
|---|---|---|
| Overtaking | pairwise on-track passes per race | Monaco 5.8, Baku 27.0, Las Vegas 48.3 |
| Following | lap time lost in the wake of the car ahead, per season | 2026: +0.28 s under 0.5 s, gone by 2.5 s |
| Pit loss | in and out lap against pace either side | Spa 18.0 s, Baku 21.0 s, Imola 27.8 s |
| Safety cars | rate, duration and the discount on a stop | 1.27 per race, 61% of a green stop |
| Pace, wear | the pace model's driver and compound terms | see above |

The following penalty used to be a constant, +0.55 s inside half a second,
which nothing in the repository reproduced. Measuring it properly
(`racecraft-analyse following`) found it was about double the real figure,
for a reason worth keeping. A car close behind another is slow for two
reasons: dirty air, and being held up by a slower car it cannot pass. The
simulator already models the second — a car cannot go through the one ahead
until the circuit allows — so a penalty that includes it counts the same lost
time twice. The measurement therefore uses only laps where the follower's own
pace was *slower* than the car ahead, so it cannot have been held up:

| Gap | 2024 | 2025 | 2026 | 2026, all laps |
|---|---|---|---|---|
| under 0.5 s | +0.294 | +0.315 | **+0.283** ± 0.053 | +0.386 |
| 0.5–1.0 s | +0.082 | +0.115 | +0.072 | +0.171 |
| 1.0–1.5 s | +0.082 | +0.087 | +0.034 | +0.073 |
| 1.5–2.5 s | +0.067 | +0.049 | +0.002 | +0.023 |
| 2.5–4.0 s | +0.024 | +0.016 | +0.000 | −0.018 |

Seconds per lap against the same driver in clear air, after tyres, fuel and
track evolution. The wake right behind a car barely changed between seasons;
what changed in 2026 is how quickly it fades — gone by 1.5 s, where in 2024 it
was still there at 2.5 s. The simulator uses the season's own table, fitted
only on races before the one being simulated.

### The tyres the car has

A plan is a sequence of compounds, and a car cannot run one it has no sets for.
The simulator used to give every stint a new tyre, so it would happily
recommend two new hards to a car that had run one of them in practice, and cost
a stint on a four-lap medium as if the rubber were fresh.

It now races what the car has. `race_inputs.tyre_stock` reads the sets the car
on a grid slot held when the race started — from the weekend's earlier sessions,
so the study stays held out — and the study drops the plans it cannot run and
starts each stint on the set it would really use, at the age that set carries.
The assignment is the cheapest one: new sets first, then the least worn, with
the oldest set on the shortest stint.

```sh
racecraft-analyse race Baku --season 2025 --driver HAD    # on the tyres he had
racecraft-analyse race Baku --season 2025 --grid 8 --new-tyres
```

Baku 2025, P8. That was Hadjar, who reached Q3 and started the race without a
single new set — three used softs, two used mediums, one hard with a lap on it.
The same three plans, raced on new sets and on his, 1500 runs each:

| Plan | On new sets | On his tyres |
|---|---|---|
| `medium 22 > hard 29` | **P8.59** ±0.08 | **P9.03** ±0.08 |
| `medium 31 > hard 20` | P8.68 ±0.08 | P9.35 ±0.09 |
| `medium 25 > hard 26` | P8.79 ±0.08 | P9.06 ±0.08 |

His tyres cost him about four tenths of a place, and they cost the long first
stint most — `medium 31 > hard 20` is a tenth behind on new sets and three
tenths behind on his, because the set it runs long is the one with laps on it.
The plan at the top does not change here.

**The first version of this table said it did**, and that was the run count
talking. At 300 runs the order of the top three moved between tyre settings, and
the difference looked like a finding; at 1500 it is a tenth of a place and the
same plan wins both. The rule the rest of this file follows applies to its own
results: a ranking has an error bar, and a change smaller than it is noise.

**Some races demand more than one stop.** Monaco required three sets of tyres,
and so two stops, in 2025 — and the field's median stop count there runs 1, 1, 2
across 2023, 2024 and 2025, which is the rule showing up in the data. The plan
sweep did not know it, and the tyre join is what exposed that: given a car short
of hard sets, the shortlist fell back to a one-stop the regulations forbade.

`race_inputs.mandatory_stops` now holds it, as a table of seasons rather than a
rule that carries forward — which matters, because it does not. The rule lasted
one year: teams answered it by having one car back the field up to make a pit
window for the other, and it was deleted from the 2026 regulations. A model that
had assumed "2025 onward" would now be putting an extra stop into every Monaco
race it is asked about.

**A wet race is a different race.** Three of the 2025 races ran mostly on
intermediates — Australia at 81% of laps, Silverstone at 74%, Spa at 27% — and a
ranking of dry plans describes none of them. Studying one now says so first, in
as many words, and marks it as the hindsight it is: the forecast could not have
known, the review has no excuse.

**A car can be short of the whole shortlist.** Verstappen started Monaco 2025
with one new medium, one new hard and four used softs, and every plan in the
shortlist — Monaco requires two stops — called for two hard stints. Filtering
the ranking *after* it was built left him with nothing at all. The filter now
runs before the sweep (`rank_with_risk(allow=...)`), so what comes back is the
best plan he could actually have run, `soft 19 > medium 25 > hard 34` starting
on a three-lap soft, with the out-of-reach plans still named.

The rivals get their own tyres too, where the plan drawn for them fits what
they had; one whose drawn plan it does not fit stays on new sets, because
inventing a different plan for a rival would be modelling a strategist rather
than a field. **It makes no measurable difference**: at Baku 2025 the answer
moves 0.02 places against an error bar of 0.13. The reason is in the grid — only
2 of the 20 cars started with no new set at all, and the set assignment gives
the fresh rubber to the long stints anyway. It stays in because "every rival has
new tyres" is an assumption that cannot be defended once the real sets are
known, not because it changed the answer.

**Is it worth anything?** Two questions, two answers, and only one of them is
yes.

*Choosing a plan for one car* — `python scripts/validate_tyres.py 2025`, every
race and three grid slots, each studied twice with the same luck and the same
field, differing only in the tyres:

| | |
|---|---|
| Car started on at least one used set | 35% |
| Best plan changed with the real tyres | 41% (27 of 66) |
| ...by more than the error bars on both | **30%** (20 of 66) |
| Plans ruled out for want of a set | 146 |
| The new-tyre answer was a plan the car **could not run** | 18 of 66 |
| Cost of following it where it could be run | +0.06 places, +1.34 at worst |

The first two lines are one measurement with and without a noise test: a top
plan that changes by less than the error bars on both finishes has not changed,
it has wobbled. Counting the wobble gives 41%; requiring the new-tyre answer to
actually cost something gives 30%.

The last two lines are the point, and they say different things. Most of the
time the ideal-tyre answer is runnable and costs a rounding error, so this is
not a model that changes every call. But in 18 of 66 cases it was a plan the car
had no sets for — advice that cannot be taken is worse than advice that is
slightly wrong, and the old model gave it without noticing.

(Rerun with Monaco's two-stop rule in place: Verstappen's answer there changes
from an illegal one-stop to `soft 19 > medium 25 > hard 34`, and every figure in
the table above is unchanged.)

*Predicting a finishing order* — no. `scripts/validate_race.py prior` simulates
each race twice, once with every stint on a new set and once at the age each set
really carried, and the mean position error is **3.27 against 3.24**: the real
tyres are very slightly worse, and beat new sets in 10 of 30 races. About seven
cars a race start a stint on a used set, so the information is there; it just
does not move a finishing order, which car pace dominates. The join earns its
place in choosing a plan, not in predicting a race.

### What it is for, and what it is not for

**It does not predict finishing order.** Validated over 30 races with every
input — driver pace, tyre wear, pit loss, safety cars, overtaking, the wake —
taken only from races that started before the one simulated, it is barely
better than predicting the starting grid:

| | Simulator | Grid order |
|---|---|---|
| Mean position error | 3.24 | 3.39 |
| Podium places hit (of 3) | 1.93 | 2.00 |
| Races won against the baseline | 17 of 30 | — |

The first version of this backtest took driver pace from earlier races but
everything else from the race itself, and scored 3.24 against 3.31. Holding the
rest out as well left the simulator's error where it was; the grid baseline
moved because a different 30 races now qualify — eight are skipped, four for
too few earlier races for driver pace, three for coming too early in a season
to fit tyre wear on, and one, Madrid, for having no earlier
pit lane to measure.

Given each race's *own* pace instead, it looks far better — 2.46 against 3.04,
winning 33 of 36 — and that gap is the measure of how much hindsight was
doing. Finishing order is dominated by how quick each car is on the day, and
forecasting that is a different problem from strategy.

`python scripts/validate_race.py prior` and `... hindsight` reproduce both.

**What it is for is comparing plans for one car**, where pace errors largely
cancel because every plan runs against the same field:

```sh
racecraft-analyse race Baku --laps 51 --grid 8
```

A midfield car starting P8 at Baku 2025, held out — fitted on the fourteen
races before it, none of Baku and nothing after:

| Plan | Expected loss | Mean finish | ± | In the points |
|---|---|---|---|---|
| hard 31 > medium 20 | 63.1 s | **8.41** | 0.16 | 85% — tied |
| medium 22 > hard 29 | 60.0 s | 8.44 | 0.16 | 86% — tied |
| medium 28 > hard 23 | 60.2 s | 8.56 | 0.17 | 81% — tied |
| medium 31 > hard 20 | 60.9 s | 8.61 | 0.17 | 83% — tied |
| medium 25 > hard 26 | **59.9 s** | 8.84 | 0.17 | 78% |
| medium 16 > hard 35 | 62.6 s | 10.33 | 0.21 | 62% |

Four plans cannot be separated, and the simulator says so rather than picking
one. The useful answer is the **price of track position**: `medium 22 > hard 29`
is as good as the best and costs 0.1 s more than the seconds-cheapest plan, for
0.40 places. The plans are shortlisted by the safety-car ranking, not by
green-flag seconds, so a long first stint that only pays off when a safety car
arrives gets raced at all.

## Tyre sets

Nothing in the feed numbers a set of tyres. Every lap does carry its compound,
whether the set was new when fitted, and how many laps the set has done —
counted across sessions, so a medium run for four laps in qualifying starts the
race at age five. `model/tyre_sets.py` follows each physical set through a
weekend from that, and so can say before a race what every car still has.

**Joining stints to sets.** A stint on a used set is joined to the earlier set
of the same compound whose lap count it continues. Across all 84 weekends, 97%
continue a set exactly. The rest are handled by name rather than dropped: a
counter that stalled for an out-lap, one that slipped back a lap or two, a set
whose earlier laps were never timed. When two sets fit equally — a six-lap soft
from practice and another from qualifying — the more recently used one wins,
because a car races the sets it kept. Choosing the older one sent to the race
sets that had gone back to Pirelli days earlier, and fixing it took the tracker
from 93.3% to 96.7%.

**The rules are Article 30**, as data (`RULES`): 13 dry sets on a normal weekend
(8 soft, 3 medium, 2 hard) with two handed back after each practice session;
12 on a sprint weekend (6, 4, 2) with one back after practice, the sprint's
most-used set after the sprint and three after qualifying; one soft fewer when
Pirelli's test tyres run; 11 at the two 2023 trials of the Alternative Tyre
Allocation. A Q3 driver hands one more soft back after qualifying, and one hard
and one medium can never go back before the race. The data found every one of
these without being told — the counts cluster exactly on the allocations, the
2023 trials stand out as four softs short — and found one the rulebook does not
state: at Qatar 2025, the weekend stints were capped at 25 laps, half the field
ran a third hard.

The rules say how many sets go back, not which. A set run again later plainly
was not one; otherwise the most worn go back. Where a car has no used set left
to give, a new one goes and its compound is a guess, named as one.

Rookies in first practice drive a race driver's car under their own number;
their laps go on the car of the same team whose regular driver sat that session
out. At Barcelona 2026 the feed has no team for anyone in FP1, so a rookie's
team is taken from the rest of their season, and where they drove for two teams
the one with a car free wins.

**How often it is right** (`python scripts/validate_tyre_sets.py`): for every car
in every race, what the tracker says it held at the start — from the sessions
before only — against every set it then ran:

| | |
|---|---|
| Sets raced | 4,185 |
| Right about | **96.7%** |
| Cars holding exactly what the rules leave | 95% |

The misses are sets the tracker thought went back but were raced (45) and new
sets opened beyond the count it had left (94). The panel draws the first kind
dashed when it happens.

**What it is for.** The strategy model's plans assume new tyres. With the sets
known, each car's plans are re-ranked on what it has: a used set costs the wear
line carried on from its age, a plan needing two new hards is out for a car that
ran one in practice. At Baku 2025 the model's cheapest plan on new tyres is 0.4 s
behind for Russell, whose mediums had all run in qualifying. The used-set cost
is an upper bound: the feed counts out-laps and cool-down laps, so a set from
qualifying is fresher than its count.

The race simulator uses the same sets; see **The tyres the car has** below.

## Showing it

Five minutes, in this order, each step answering a question the last one raises.

**1. A race, replayed.** Open Racecraft, pick a race. The
timing tower, the trace and the track map all run off one clock, and the tower
agrees with what the tyre panels say a car is on — that is the check that the
data underneath is one thing rather than three.

**2. What the tyre model says, and what it cannot.** The *Tyre model* tab draws
modelled wear against what that race's tyres actually did. The line never saw
the race it is drawn over. The panel names how many races it was fitted on, and
which Pirelli compound each label was that weekend.

**3. Three answers to one question.** The *Strategy* tab ranks plans in seconds,
then with safety cars allowed for, then in finishing positions. The three
disagree, and the interesting part is where: the seconds ranking understates how
bad a bad plan is, because it cannot see a car rejoining into traffic.

**4. The tyres that car actually had.** *In places* races the sets the car held
at the start — click through the grid slots by driver name. At Baku 2025 from
P8, Hadjar had no new set at all, and his best plan is not the best plan on new
tyres. The *Tyre sets* tab shows where that came from, set by set, following the
clock.

**5. What none of it can do.** `python scripts/validate_race.py prior`:
predicting a finishing order, held out, is level with predicting the starting
grid. Car pace dominates a race and forecasting car pace is a different problem.
The negative results below are the rest of that answer.

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
  api/places_view.py       the places ranking for one session, cached
  api/sync_view.py         the sync button, and the caches it clears
  ingest/sync.py           the latest race weekends, fetched on request
  api/tyre_sets_view.py    tyre sets for one session, and plans per car
  api/app.py               FastAPI routes
  model/pace.py            fuel vs tyre degradation
  model/circuit.py         pit loss, safety car risk
  model/strategy.py        costing and ranking race plans
  model/simulate.py        plans under safety car uncertainty
  model/race.py            the whole field, scored in places
  model/traffic.py         time lost in the wake of the car ahead
  model/race_inputs.py     simulator inputs from earlier races only
  model/places.py          plans raced against the field, and the verdict
  model/tyre_sets.py       every set through a weekend, Article 30 as data
  model/compounds.py       Pirelli's nominations, from pirelli_compounds.csv
  model/cli.py             racecraft-analyse
  app/main.py              racecraft: the desktop app, its window and shutdown
  app/server.py            the API on a port the system picks
  app/instance.py          one app at a time; a second launch focuses the first
  app/autosync.py          the sync button pressed every fifteen minutes
  app/shortcuts.py         Desktop and Start menu icons
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

### The real compound does not predict wear better than its label

The feed says soft, medium and hard. Pirelli brings three of six compounds to
each race, so a medium is a C2 at Silverstone and a C5 at Baku, and a model that
learns one wear rate per label mixes different rubber. The obvious fix is to
learn it per compound. `model/pirelli_compounds.csv` has every race in the lake,
each row with the Pirelli release it was read from, and
`python scripts/compare_compounds.py` tests the fix before trusting it: each
race's wear per label, predicted from its own season's earlier races only.

| Predicting a label's wear from | Mean error, s/lap per lap of age |
|---|---|
| **the same label** (the model) | **0.0344** |
| the same C-number | 0.0373 |
| the label, adjusted for how soft this compound is | 0.0372 |
| the label, pulled toward last season's visit | 0.0402 |
| the label, adjusted for track temperature | 0.0384 |
| *the race's own measurement noise* | *0.0080* |

The label wins in every season. Pirelli chooses each weekend's compounds so that
hard, medium and soft behave alike wherever they run, and they do — within a
label a softer compound wears *less*, because it is brought to gentler tracks.
Track temperature has the expected sign, about +0.009 s/lap per 10 °C hotter,
but too weakly to help out of sample. And last season's visit makes it worse,
which is the previous finding again from another side.

So the table is shown — the tyre model and the sets tab say which compound each
label was — and not fitted on. What the 4× gap between the error and the noise
*is*, none of these explain.

### A used set's own history is at the edge of what the data can see

Everything the simulator does with used tyres rests on one choice: wear is
counted against the laps a set has done all weekend, not the laps since it was
fitted. If the second clock fitted better, a set from qualifying would behave
like a new one and charging a car for the laps on it would be inventing a
penalty. `python scripts/compare_tyre_clock.py` fits both, same races, same
model, same number of terms:

| Wear counted against | Left over after the fit | R² |
|---|---|---|
| the set's whole life | 0.5539 s/lap | 0.827 |
| laps in this stint | 0.5532 s/lap | 0.827 |

A coin flip: the whole-life clock fits better in 40 of 78 races. The reason is
in the second line of the output — only 17% of race laps run on a set with laps
already on it, and those sets carry 2.6 laps on average, which is far too small
to separate from a 0.55 s lap-to-lap scatter.

So the model keeps the clock its wear was measured on, which is the consistent
choice rather than the proven one, and the cost it charges a used set is
reported as an upper bound: the feed counts out-laps and cool-down laps as laps,
and a set that did three of those in Q1 is fresher than its count says. It is
the one part of the tyre join that the lake cannot confirm.

**How much rides on it.** Baku 2025 from P8, the same study with the laps
carried into each stint taken as counted, halved, and ignored:

| Carried laps | Best plan | Finish |
|---|---|---|
| as counted | `medium 25 > hard 26` | P8.82 |
| halved | `medium 22 > hard 29` | P8.62 |
| ignored | `medium 31 > hard 20` | P8.55 |

The shape survives — one stop, medium then hard, in every case — and the stop
lap does not, moving nine laps across an assumption the data cannot settle. The
gaps between those plans are around two tenths of a place against an error bar
of 0.17, which is why the panel shows which plans are tied and what track
position costs rather than naming a lap and standing on it.

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

### What the dead ends have in common

The model says one stop where Barcelona, Silverstone, Hungary and Austria ran
two, and two where Monaco ran four. It under-stops, and it under-stops because
teams buy **track position** with a stop, not lap time — a plan two seconds
quicker that rejoins behind a car it cannot pass has lost, and a model counting
seconds in a vacuum cannot see that.

No constant fixes it, and the dead ends above are all attempts at a constant:
a circuit multiplier, a compound, a temperature, a scale. Scoring plans in
places rather than seconds does fix it, which meant joining the strategy model
to `model/race.py`, where a field to rejoin into already existed. That join is
built; what the measurements establish is that it was the only work left worth
doing.

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
penalty of +0.28 s/lap inside 0.5 s in 2026, over whole races. It is evidence
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

## TypeSafe: where a model judgment would and would not help

Every rule-based part of the project was audited with one question: is this a
known rule applied to structured data, which code does better — exact, free,
instant, the same answer twice — or a semantic judgment that only looks like
parsing? Each verdict below was measured on the lake rather than assumed.

| Candidate | Verdict | Evidence |
|---|---|---|
| Reading race control (`api/penalties.py`) | **Code.** | Machine-written, closed grammar: 3,257 of 3,257 steward messages classified, every car extracted, no residue for a model. |
| Which stop a penalty was served at | **Code.** | The rule is in the regulations. Tested against the 40 penalties the feed marks `PENALTY SERVED`, it is never contradicted; the six not served at the very next stop are explained by timing and track status. |
| Penalised stops in pit loss | **Code, and a real bug.** | `model/circuit.pit_loss` averaged in stops that served a penalty, 8.4 s dearer each. Now excluded: 1,954 stops fall to 1,884, Montréal moves 0.65 s. |
| Circuit renames (`CIRCUIT_ALIASES`) | **Judgment, not built.** | Correct today — the only event at two circuits is the Spanish GP, which really moved. A rename would split a circuit's history silently, so `test_no_event_is_split_across_two_names_for_one_circuit` now fails loudly instead. Deciding rename-or-move is where an entity-alignment Score would fit, but a few names a season is a person's job. |
| Pirelli compounds by race name | **Not a live path.** | Every caller joins by round; the name match never runs. |
| Explaining ingest warnings | **Judgment, not built.** | Whether a `WARN` in `ingest/quality.py` is explained by the race (a red flag, rain, a stand-in) is a real semantic question over race control, and the one worth building first if a model is added. |

Nothing here calls a model, and none of it is blocked on one. The TypeSafe SDK is
not a dependency; adding it is a decision for when a judgment above earns it.

## What is left

In the order they are worth doing.

**1. Run live through practice at Baku, Thursday 24 September** (FP1 08:30 UTC, FP2 12:00 UTC). Everything about
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

**3. Track position inside the strategy model — built.** `model/places.py` takes
the plans the seconds model likes, races each one against a whole field, and
ranks them by finishing position: `racecraft-analyse race Baku --grid 8`, or
**In places** on the interface's strategy board.

What it found is not what was expected, and the first version of it was wrong.
Running every rival on one identical plan produced a four-place cliff in favour
of stopping on the lap they stopped — the simulation rewarding a car for copying
a field that does not exist. Spreading the field's stop laps and redrawing them
fifteen times per plan removes it, and the spread falls from 4.03 places to 1.78.

It has since been corrected four more ways: inputs held out to races before the
one simulated, the wake penalty measured rather than assumed, the shortlist
drawn from the safety-car ranking, and the car racing the tyres it actually had
rather than new ones — see *The tyres the car has* above for what that is worth
and what it is not.

Where the models differ most is **how bad a bad plan is**. At Baku 2025 from P8
the worst plan on the shortlist costs about a second more in seconds and a place
and a half more here. The value of modelling track position turns out to be less
about choosing between good plans — which usually tie, and are reported as tied
— than about knowing the cost of a wrong one, which the seconds model
understates badly.

Untested against real races. It is a model of racing against a field, not
against a strategist: rivals run a fixed plan and never cover a stop.

**4. Tyre sets — built, and joined to the simulator.** Every car's sets through a
weekend, right about 96.7% of the sets raced; each car's plans ranked on the
tyres it had; and the race simulator racing those sets rather than new ones. Live, it
needs the weekend's earlier sessions in the lake, so ingest each one after it
ends — timing only is enough, and quick:

```powershell
racecraft-ingest --season 2026 --rounds <round> --sessions FP1 --no-telemetry
```

**5. The write-up.** The material is unusually good and most of it is already
written down here: two leakage bugs that scored beautifully and knew nothing,
four measured dead ends, a simulator level with grid order, a season of tyres
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

