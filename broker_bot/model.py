from __future__ import annotations

import joblib
import pandas as pd
from pathlib import Path
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

from .features import FEATURE_COLUMNS, build_labels


MODEL_FILENAME = "rf_model.joblib"


def train_model(features_df: pd.DataFrame, horizon_days: int) -> tuple[RandomForestRegressor, dict[str, float]]:
    labels = build_labels(features_df, horizon_days=horizon_days)
    train_df = features_df.dropna(subset=FEATURE_COLUMNS).copy()
    labels = labels.loc[train_df.index]
    valid = labels.notna()
    train_df = train_df.loc[valid]
    labels = labels.loc[valid]

    X = train_df[FEATURE_COLUMNS].values
    y = labels.values

    model = RandomForestRegressor(
        n_estimators=300,
        max_depth=6,
        min_samples_leaf=5,
        random_state=42,
        n_jobs=-1,
    )
    model.fit(X, y)
    preds = model.predict(X)
    metrics = {
        "r2": float(r2_score(y, preds)),
        "mae": float(mean_absolute_error(y, preds)),
    }
    return model, metrics


def save_model(model: RandomForestRegressor, model_dir: str) -> str:
    Path(model_dir).mkdir(parents=True, exist_ok=True)
    path = Path(model_dir) / MODEL_FILENAME
    joblib.dump(model, path)
    return str(path)


def load_model(model_dir: str) -> RandomForestRegressor:
    path = Path(model_dir) / MODEL_FILENAME
    if not path.exists():
        raise FileNotFoundError(f"Model file not found: {path}")
    model = joblib.load(path)
    if not isinstance(model, RandomForestRegressor):
        raise RuntimeError(
            "Saved model is not a RandomForestRegressor. Please retrain the model with the latest code."
        )
    expected = len(FEATURE_COLUMNS)
    actual = getattr(model, "n_features_in_", None)
    if actual is not None and actual != expected:
        raise RuntimeError(
            f"Model feature mismatch (expected {expected}, found {actual}). "
            "Delete data/models/rf_model.joblib and retrain."
        )
    return model


def predict_return(model: RandomForestRegressor, features_df: pd.DataFrame) -> pd.Series:
    X = features_df[FEATURE_COLUMNS].values
    preds = model.predict(X)
    return pd.Series(preds, index=features_df.index, name="pred_return")
