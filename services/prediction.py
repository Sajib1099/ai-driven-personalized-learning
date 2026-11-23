"""
Model loading and prediction.

Loads the artifacts exported by OULAD_Thesis_Final.ipynb (XGBoost + preprocessing
pipeline + label encoder + metadata) and turns one student's information into a
predicted final_result with class probabilities.
"""
from __future__ import annotations

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier

ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "ml_artifacts"

# Human-readable names used across the app
FEATURE_LABELS = {
    "code_module": "Module",
    "code_presentation": "Presentation",
    "gender": "Gender",
    "region": "Region",
    "highest_education": "Highest education",
    "imd_band": "IMD band (deprivation)",
    "age_band": "Age band",
    "disability": "Disability",
    "num_of_prev_attempts": "Previous attempts",
    "studied_credits": "Studied credits",
    "avg_score": "Average assessment score",
    "max_score": "Highest assessment score",
    "min_score": "Lowest assessment score",
    "score_std": "Score variation (std)",
    "assessment_count": "Assessments submitted",
    "avg_weight": "Average assessment weight",
    "total_weight": "Total assessment weight submitted",
    "avg_submission_day": "Average submission day",
    "total_clicks": "Total VLE clicks",
    "active_days": "Active days on VLE",
    "learning_sites": "Learning resources used",
    "avg_clicks_per_record": "Avg clicks per activity",
    "max_clicks_per_record": "Max clicks per activity",
    "tma_avg_score": "TMA average score",
    "tma_max_score": "TMA highest score",
    "tma_min_score": "TMA lowest score",
    "tma_count": "TMAs submitted",
    "cma_avg_score": "CMA average score",
    "cma_max_score": "CMA highest score",
    "cma_min_score": "CMA lowest score",
    "cma_count": "CMAs submitted",
    "tma_score_range": "TMA score range",
    "cma_score_range": "CMA score range",
    "continuous_avg_score": "Continuous assessment average",
    "clicks_per_active_day": "Clicks per active day",
    "sites_per_active_day": "Resources per active day",
    "click_consistency": "Click consistency",
}

# Features calculated automatically from the other inputs (never typed by the user)
DERIVED_FEATURES = [
    "tma_score_range", "cma_score_range", "continuous_avg_score",
    "clicks_per_active_day", "sites_per_active_day", "click_consistency",
]


def label(feature: str) -> str:
    return FEATURE_LABELS.get(feature, feature)


class Predictor:
    """Wraps the exported model pipeline."""

    def __init__(self, model_dir: Path = MODEL_DIR):
        # Prefer XGBoost's native JSON format (portable across operating systems);
        # fall back to the pickle file exported by the notebook.
        if (model_dir / "model.json").exists():
            self.model = XGBClassifier()
            self.model.load_model(str(model_dir / "model.json"))
        else:
            self.model = joblib.load(model_dir / "model.pkl")
        self.preprocessor = joblib.load(model_dir / "preprocessor.pkl")
        self.label_encoder = joblib.load(model_dir / "label_encoder.pkl")
        with open(model_dir / "metadata.json") as f:
            self.meta = json.load(f)

        self.features: list[str] = self.meta["features"]
        self.categorical: list[str] = self.meta["categorical_features"]
        self.numerical: list[str] = self.meta["numerical_features"]
        self.classes: list[str] = list(self.label_encoder.classes_)
        self.encoded_names: list[str] = list(self.preprocessor.get_feature_names_out())
        self.encoded_to_raw: dict[str, str] = self.meta["encoded_to_raw"]

        # Safety checks: the files must belong together
        n_enc = len(self.encoded_names)
        if n_enc != self.model.n_features_in_:
            raise ValueError(f"Preprocessor gives {n_enc} columns but model expects {self.model.n_features_in_}.")
        if self.classes != self.meta["classes"]:
            raise ValueError("Label encoder classes do not match metadata.")

    # ------------------------------------------------------------------ #
    @staticmethod
    def add_derived_features(row: dict) -> dict:
        """Same formulas as the notebook (Section 8)."""
        r = dict(row)
        active = r["active_days"] if r["active_days"] != 0 else 1
        max_clicks = r["max_clicks_per_record"] if r["max_clicks_per_record"] != 0 else 1
        r["tma_score_range"] = r["tma_max_score"] - r["tma_min_score"]
        r["cma_score_range"] = r["cma_max_score"] - r["cma_min_score"]
        r["continuous_avg_score"] = (r["tma_avg_score"] + r["cma_avg_score"]) / 2
        r["clicks_per_active_day"] = r["total_clicks"] / active
        r["sites_per_active_day"] = r["learning_sites"] / active
        r["click_consistency"] = r["avg_clicks_per_record"] / max_clicks
        return r

    def to_frame(self, row: dict) -> pd.DataFrame:
        df = pd.DataFrame([{f: row[f] for f in self.features}])
        for c in self.numerical:
            df[c] = df[c].astype(float)
        for c in self.categorical:
            df[c] = df[c].astype(str)
        return df

    def encode(self, df: pd.DataFrame) -> np.ndarray:
        X = self.preprocessor.transform(df[self.features])
        return X.toarray() if hasattr(X, "toarray") else np.asarray(X)

    def predict_proba_df(self, df: pd.DataFrame) -> np.ndarray:
        return self.model.predict_proba(self.encode(df))

    def predict(self, row: dict) -> dict:
        df = self.to_frame(row)
        proba = self.predict_proba_df(df)[0]
        idx = int(np.argmax(proba))
        return {
            "predicted_class": self.classes[idx],
            "probabilities": {c: float(p) for c, p in zip(self.classes, proba)},
            "confidence": float(proba[idx]),
            "frame": df,
        }


def load_csv(name: str, **kwargs) -> pd.DataFrame:
    return pd.read_csv(MODEL_DIR / name, **kwargs)
