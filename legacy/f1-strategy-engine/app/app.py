"""
Streamlit dashboard — the demoable piece for interviews/portfolio.

Run with: streamlit run app/app.py

Two modes:
1. Historic Backtest: predicted vs. actual pit calls, degradation curves,
   backtest summary metrics.
2. Live Session: current stints from OpenF1, undercut/overcut calculator
   with optional auto-fill from live data.

Requires internet access (OpenF1 for live mode; local CSVs from
run_pipeline.py for historic mode). Won't work in a network-restricted
sandbox for live mode — historic mode works offline once you've run
run_pipeline.py locally and have the CSVs.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src import config
from src.data import openf1_client
from src.strategy.undercut_calculator import (
    UndercutInput, OvercutInput, undercut_probability, overcut_probability,
)

st.set_page_config(page_title="F1 Strategy Engine", layout="wide", page_icon="\U0001F3CE")

st.markdown(
    """
    <style>
    .stApp { background-color: #0e1117; }
    div[data-testid="stMetricValue"] { font-size: 1.8rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("\U0001F3CE F1 Race Strategy Engine")

with st.sidebar:
    st.header("Navigation")
    mode = st.radio("Mode", ["Historic Backtest", "Live Session", "About"])
    st.caption(
        "Historic mode reads local CSVs from run_pipeline.py. "
        "Live mode calls OpenF1 directly — needs internet access."
    )


def _load_csv_or_none(path):
    return pd.read_csv(path) if os.path.exists(path) else None


if mode == "About":
    st.header("Methodology")
    st.markdown(
        """
        **Data:** FastF1 (historic, training) + OpenF1 (live, inference).

        **Model:** a classifier asked, on every lap, whether this car stops
        at the end of it — using only the laps run before it. Trained on real
        pit calls, so it imitates what strategists did rather than deriving
        an optimum.

        **It is scored against guessing.** Roughly 3% of laps are pit laps, so
        that is what random guessing scores. Average precision with whole
        races held out is around 0.13, about four times better. Modest, and
        honest: see `model_metrics.json`.

        **Known limitations, stated plainly:**
        - Degradation conflates tyre wear with fuel-load pace improvement —
          see the docstring in `tyre_degradation.py`.
        - Imitating real calls is not the same as finding the best one. A team
          that stopped at the wrong moment teaches the model to do the same.
        - Undercut/overcut "confidence" is a heuristic, not a calibrated
          probability, until backtested against real undercut outcomes.

        **Two earlier versions of this model scored far better and were
        wrong**, both by seeing something unknowable at the moment of the call:
        first the length of the stint it was predicting the end of, then the
        lap time of the pit lap itself. Both are described in the README.
        """
    )

elif mode == "Historic Backtest":
    st.header("Historic Backtest")

    laps = _load_csv_or_none(config.TRAINING_LAPS_CSV)
    degradation = _load_csv_or_none(config.DEGRADATION_CSV)
    metrics = None
    if os.path.exists(config.METRICS_PATH):
        import json
        with open(config.METRICS_PATH) as f:
            metrics = json.load(f)

    if laps is None:
        st.info(
            "No data found. Run `python run_pipeline.py` locally first "
            "(needs internet access to FastF1)."
        )
    else:
        if metrics and "average_precision" in metrics:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Average precision", metrics["average_precision"],
                      help="Whole races held out. Compare it to the base rate beside it.")
            c2.metric("Base rate", metrics["base_rate"], help="What guessing at random scores.")
            c3.metric("Better than guessing", f"{metrics['lift_over_base_rate']}x")
            c4.metric("Laps / stops", f"{metrics['laps']:,} / {metrics['stops']}")
        elif metrics:
            st.warning(
                "model_metrics.json is from the old regression, whose score came from "
                "features it could not have known. Re-run run_pipeline.py."
            )
            metrics = None

            st.subheader("Feature importance")
            fi = pd.DataFrame(
                list(metrics["feature_importances"].items()),
                columns=["feature", "importance"],
            )
            st.plotly_chart(
                px.bar(fi, x="importance", y="feature", orientation="h"),
                use_container_width=True,
            )
        else:
            st.warning("No model_metrics.json found — run run_pipeline.py to train a model.")

        st.subheader("How strongly the model wanted to stop, lap by lap")
        decisions_path = os.path.join(config.DATA_DIR, "lap_decisions.csv")
        if os.path.exists(decisions_path) and os.path.exists(config.MODEL_PATH):
            import joblib

            from src.models.pit_decision import prepare

            decisions = pd.read_csv(decisions_path)
            model = joblib.load(config.MODEL_PATH)
            features, actual, _ = prepare(decisions)
            decisions["stop_probability"] = model.predict_proba(features)[:, 1]

            race_options = sorted(decisions["GrandPrix"].dropna().unique().tolist())
            chosen_race = st.selectbox("Grand Prix", race_options)
            in_race = decisions[decisions["GrandPrix"] == chosen_race]
            chosen_driver = st.selectbox("Driver", sorted(in_race["Driver"].unique().tolist()))
            view = in_race[in_race["Driver"] == chosen_driver].sort_values("LapNumber")

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=view["LapNumber"], y=view["stop_probability"],
                mode="lines", name="Model wants to stop",
            ))
            stops = view[view["pits_this_lap"]]
            fig.add_trace(go.Scatter(
                x=stops["LapNumber"], y=stops["stop_probability"],
                mode="markers", name="Actually stopped",
                marker=dict(size=13, symbol="triangle-down"),
            ))
            fig.update_layout(
                title=f"{chosen_driver}, {chosen_race}",
                xaxis_title="Lap", yaxis_title="Probability of stopping this lap",
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                "The line is built only from laps before each point, so it is what the model "
                "would have said at the time. Where the triangles sit high, it agreed with the "
                "pit wall; where they sit low, it missed the call."
            )
            st.dataframe(
                view[["LapNumber", "Compound", "tyre_life", "deg_so_far_s_per_lap",
                      "pace_loss_vs_stint_best_s", "stop_probability", "pits_this_lap"]],
                use_container_width=True,
            )
        else:
            st.info("No lap_decisions.csv or trained model yet. Run `python run_pipeline.py` first.")

        st.subheader("Degradation curves by compound")
        if degradation is not None:
            drivers = laps["Driver"].dropna().unique().tolist()
            driver = st.selectbox("Driver", drivers)
            driver_laps = laps[laps["Driver"] == driver]
            lap_col = "LapTime_s" if "LapTime_s" in driver_laps.columns else "LapTime"
            fig2 = px.scatter(
                driver_laps, x="TyreLife", y=lap_col,
                color="Compound" if "Compound" in driver_laps.columns else None,
                trendline="lowess",
                title=f"{driver} — lap time vs tyre age",
            )
            st.plotly_chart(fig2, use_container_width=True)

else:  # Live Session
    st.header("Live Session")

    if st.button("Fetch current session"):
        try:
            session = openf1_client.get_current_session()
        except RuntimeError as e:
            st.error(f"OpenF1 request failed: {e}")
            session = None

        if session is None:
            st.warning("No live/recent session found on OpenF1 right now.")
        else:
            st.success(f"{session.get('session_name')} \u2014 {session.get('location')}")
            key = session["session_key"]
            st.session_state["session_key"] = key

            drivers = openf1_client.get_drivers(key)
            stints = openf1_client.get_stints(key)
            if not drivers.empty and not stints.empty:
                merged = stints.merge(
                    drivers[["driver_number", "full_name", "team_name"]],
                    on="driver_number", how="left",
                )
                st.subheader("Current stints")
                st.dataframe(merged, use_container_width=True)
            else:
                st.dataframe(stints, use_container_width=True)

    st.subheader("Undercut / Overcut Calculator")
    calc_type = st.radio("Scenario", ["Undercut (you pit first)", "Overcut (you stay out)"])

    col1, col2, col3 = st.columns(3)
    if calc_type.startswith("Undercut"):
        with col1:
            gap = st.number_input("Gap to target (s)", value=1.8, step=0.1)
            pit_loss = st.number_input("Pit loss (s)", value=22.0, step=0.5)
        with col2:
            pace_adv = st.number_input("Fresh tyre pace advantage per lap (s)", value=1.1, step=0.1)
            laps_adv = st.number_input("Laps of advantage", value=2, step=1)
        with col3:
            tyre_age = st.number_input("Target's tyre age (laps)", value=18, step=1)

        if st.button("Calculate", key="undercut_calc"):
            result = undercut_probability(UndercutInput(
                gap_to_target_s=gap, pit_loss_s=pit_loss, target_tyre_age=tyre_age,
                fresh_tyre_pace_advantage_s=pace_adv, laps_of_advantage=int(laps_adv),
            ))
            color = "green" if result["succeeds"] else "red"
            st.markdown(f"### :{color}[{'UNDERCUT SUCCEEDS' if result['succeeds'] else 'UNDERCUT FAILS'}]")
            st.json(result)
    else:
        with col1:
            gap = st.number_input("Gap to target (s)", value=1.8, step=0.1)
            pit_loss = st.number_input("Rival's pit loss (s)", value=22.0, step=0.5)
        with col2:
            deficit = st.number_input("Your pace deficit per lap on old tyres (s)", value=0.8, step=0.1)
        with col3:
            laps_out = st.number_input("Laps you stay out longer", value=2, step=1)

        if st.button("Calculate", key="overcut_calc"):
            result = overcut_probability(OvercutInput(
                gap_to_target_s=gap, pit_loss_s=pit_loss,
                own_pace_deficit_s=deficit, laps_staying_out=int(laps_out),
            ))
            color = "green" if result["succeeds"] else "red"
            st.markdown(f"### :{color}[{'OVERCUT SUCCEEDS' if result['succeeds'] else 'OVERCUT FAILS'}]")
            st.json(result)
