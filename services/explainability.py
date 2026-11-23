"""
Explainable AI: SHAP and LIME for a single student.

SHAP  - exact TreeExplainer on the XGBoost model. Values for one-hot columns are
        summed back to their original feature, so "region" appears once.
LIME  - local surrogate model on the ORIGINAL (raw) features, giving readable
        rules such as "avg_score <= 45.2".

Both explain the model's behaviour. Neither one produces recommendations and
neither proves cause and effect.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import shap
from lime.lime_tabular import LimeTabularExplainer

from services.prediction import Predictor


class ShapExplainer:
    def __init__(self, predictor: Predictor):
        self.p = predictor
        self.explainer = shap.TreeExplainer(predictor.model)
        self.raw_order = predictor.features

    def _aggregate(self, values_1d: np.ndarray) -> pd.Series:
        s = pd.Series(values_1d, index=self.p.encoded_names)
        return s.groupby(self.p.encoded_to_raw).sum().reindex(self.raw_order)

    def explain(self, df: pd.DataFrame) -> dict[str, pd.Series]:
        """Return {class_name: SHAP contribution per raw feature} for one row."""
        X = self.p.encode(df)
        sv = self.explainer.shap_values(X)
        sv = np.stack(sv, axis=-1) if isinstance(sv, list) else np.asarray(sv)  # (1, n_enc, n_classes)
        return {cls: self._aggregate(sv[0, :, i]) for i, cls in enumerate(self.p.classes)}


class LimeExplainer:
    def __init__(self, predictor: Predictor, background: pd.DataFrame, random_state: int = 42):
        self.p = predictor
        self.cols = predictor.features
        self.cat_cols = [c for c in self.cols if c in predictor.categorical]
        self.cat_idx = [self.cols.index(c) for c in self.cat_cols]
        # Category lists come from metadata so they match the training categories
        self.cat_values = {c: predictor.meta["category_options"][c] for c in self.cat_cols}
        self.explainer = LimeTabularExplainer(
            training_data=self._to_lime(background),
            feature_names=self.cols,
            class_names=predictor.classes,
            categorical_features=self.cat_idx,
            categorical_names={i: self.cat_values[c] for i, c in zip(self.cat_idx, self.cat_cols)},
            mode="classification",
            random_state=random_state,
        )

    def _to_lime(self, df: pd.DataFrame) -> np.ndarray:
        out = df[self.cols].copy()
        for c in self.cat_cols:
            mapping = {v: i for i, v in enumerate(self.cat_values[c])}
            out[c] = out[c].astype(str).map(mapping).fillna(0)
        return out.astype(float).values

    def _predict(self, arr: np.ndarray) -> np.ndarray:
        df = pd.DataFrame(arr, columns=self.cols)
        for c in self.cat_cols:
            codes = df[c].round().clip(0, len(self.cat_values[c]) - 1).astype(int)
            df[c] = [self.cat_values[c][k] for k in codes]
        return self.p.predict_proba_df(df)

    def explain(self, df: pd.DataFrame, class_name: str, num_features: int = 10,
                num_samples: int = 3000) -> pd.DataFrame:
        label_idx = self.p.classes.index(class_name)
        exp = self.explainer.explain_instance(
            self._to_lime(df)[0], self._predict,
            labels=[label_idx], num_features=num_features, num_samples=num_samples,
        )
        rows = [{"rule": rule, "weight": w} for rule, w in exp.as_list(label=label_idx)]
        return pd.DataFrame(rows)
