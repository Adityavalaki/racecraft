# Legacy

The two projects Racecraft grew out of, kept because their mistakes are the
reason it is built the way it is.

## `f1-strategy-engine/`

The first attempt: FastF1 into CSVs, a tyre degradation fit, a pit-window
model and a Streamlit dashboard. It ran only against synthetic data until
this repository's lake gave it real races, and then four problems surfaced.

**A model that scored well and knew nothing.** It predicted the tyre age a
stint would end at, from features computed over that same stint — its own
length among them, correlating 0.964 with the answer. It reported 1.22 laps of
error. Given only what a strategist has before the call, the same approach
scores 6.83, worse than guessing the average.

**The replacement leaked too.** Reframed to ask, lap by lap, "does this car
stop at the end of this one", it scored an average precision of 0.76 —
twenty-three times the base rate — by leaning on "this lap was slow". A lap on
which a car pits contains the pit lane, so it is some twenty seconds slower
than its neighbours: the model was noticing a stop that had already happened.
With the lap being decided excluded from its own features, the honest score is
0.134 against a base rate of 0.032. Four times better than guessing, for the
right question.

**A degradation figure read outside its own data.** A quadratic fitted to a
six-lap stint, then evaluated at lap 15, turned a true +1.20 s into +0.41 s.

**Stints pooled across circuits.** Grouping on driver and stint number alone
merged "stint 1" from every race into one curve, and a 12 s gap in lap time
between circuits became noise in the fit: R² fell from 0.91 to 0.004.

All four are fixed here, and `tests/` covers them. `train_pit_model.py` and
`backtest.py` refuse to run and explain why, so their numbers cannot be quoted
by accident.

Its own README carries the full account.

## `f1-pit-wall/`

A single self-contained HTML page polling OpenF1 directly from the browser: a
live timing tower with team colours from the feed and a flag bar. Racecraft's
interface is a from-scratch rebuild rather than an extension of it, but the
layout conventions came from here.

It is left exactly as it was. Note that OpenF1 now charges for data inside the
live window — 30 minutes either side of a session — which is what pushed
Racecraft onto F1's own timing feed instead.

## Why keep them

A portfolio that shows only the finished thing hides the part worth reading.
Both leaks above looked like good results, and the second was found only
because the feature importances were checked when the score seemed too good.
That is the habit these two folders exist to demonstrate.
