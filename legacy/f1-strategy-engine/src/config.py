"""
Central configuration — avoid magic strings/numbers scattered across modules.
"""

import os

# --- Paths ---
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_ROOT, "..", "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")

TRAINING_LAPS_CSV = os.path.join(DATA_DIR, "training_laps.csv")
DEGRADATION_CSV = os.path.join(DATA_DIR, "degradation_summary.csv")
PIT_LOSS_CSV = os.path.join(DATA_DIR, "pit_loss.csv")
MODEL_PATH = os.path.join(DATA_DIR, "pit_model.joblib")
METRICS_PATH = os.path.join(DATA_DIR, "model_metrics.json")

# --- Default training data scope ---
# Starting with one season, a handful of races, per the build plan's
# recommendation: get the pipeline working end-to-end before scaling up.
# Expand DEFAULT_YEAR / DEFAULT_RACES once the pipeline runs cleanly.
DEFAULT_YEAR = 2024
DEFAULT_RACES = ["Bahrain", "Saudi Arabia", "Australia", "Japan", "China"]
DEFAULT_SESSION = "R"  # Race

# --- Model hyperparameters ---
RF_N_ESTIMATORS = 300
RF_MAX_DEPTH = 6
RANDOM_STATE = 42
TEST_SIZE = 0.2
CV_FOLDS = 5

# --- Feature engineering ---
DEGRADATION_POLY_DEGREE = 2
OUTLIER_Z_THRESHOLD = 2.5
MIN_LAPS_FOR_STINT_FIT = 4

# --- OpenF1 ---
OPENF1_BASE_URL = "https://api.openf1.org/v1"
OPENF1_TIMEOUT_S = 10
OPENF1_MAX_RETRIES = 3
OPENF1_BACKOFF_BASE_S = 1.5

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(CACHE_DIR, exist_ok=True)
