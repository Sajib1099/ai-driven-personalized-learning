"""
Module-level AI layer (Layer A): XGBoost prediction + SHAP + LIME, saved to the database.

Only students with a module record (OULAD-format inputs) can get a prediction.
Predictions are estimates from a retrospective model, not guaranteed outcomes.
"""
from __future__ import annotations

from functools import lru_cache

import pandas as pd
from sqlalchemy import select

from db.models import Explanation, ModuleRecord, Prediction, Recommendation, RecommendationProgress
from db.session import get_session
from services import module_recommendations
from services.explainability import LimeExplainer, ShapExplainer
from services.prediction import Predictor, label, load_csv

MODEL_VERSION = "xgboost-clean37-v1"
TOP_N = 12


@lru_cache(maxsize=1)
def _predictor() -> Predictor:
    return Predictor()


@lru_cache(maxsize=1)
def _explainers():
    p = _predictor()
    bg = load_csv("background.csv")
    return ShapExplainer(p), LimeExplainer(p, bg), bg.describe().T


@lru_cache(maxsize=1)
def _no_cma_modules() -> set:
    bg = load_csv("background.csv")
    return set(bg.groupby("code_module")["cma_count"].max().loc[lambda x: x == 0].index)


def module_record(student_id: int) -> dict | None:
    with get_session() as s:
        mr = s.scalar(select(ModuleRecord).where(ModuleRecord.student_id == student_id)
                      .order_by(ModuleRecord.id.desc()))
        if mr is None:
            return None
        return {"id": mr.id, "code_module": mr.code_module, "code_presentation": mr.code_presentation,
                "features": mr.features, "source": mr.source, "actual_result": mr.actual_result}


def run_prediction(student_id: int) -> int | None:
    """Predict, explain and store. Returns the new prediction id (None if no module record)."""
    mr = module_record(student_id)
    if mr is None:
        return None
    p = _predictor()
    shap_exp, lime_exp, reference = _explainers()
    row = mr["features"]
    result = p.predict(row)
    shap_by_class = shap_exp.explain(result["frame"])
    lime_df = lime_exp.explain(result["frame"], result["predicted_class"])
    advice = module_recommendations.generate(result["predicted_class"], result["probabilities"], row,
                                             shap_by_class, reference, no_cma_modules=_no_cma_modules())

    with get_session() as s:
        pred = Prediction(student_id=student_id, module_record_id=mr["id"],
                          predicted_class=result["predicted_class"], probabilities=result["probabilities"],
                          risk_probability=float(advice["risk_probability"]), model_version=MODEL_VERSION)
        s.add(pred)
        s.flush()
        for cls, values in shap_by_class.items():
            top = values.reindex(values.abs().sort_values(ascending=False).index).head(TOP_N)
            s.add(Explanation(prediction_id=pred.id, method="shap", target_class=cls,
                              top_features=[{"feature": f, "label": label(f), "value": row.get(f),
                                             "contribution": float(v)} for f, v in top.items()],
                              explanation_data={f: float(v) for f, v in values.items()}))
        s.add(Explanation(prediction_id=pred.id, method="lime", target_class=result["predicted_class"],
                          top_features=lime_df.to_dict("records"), explanation_data={}))

        # Replace previous AI-module recommendations with the new ones
        for old in s.scalars(select(Recommendation).where(Recommendation.student_id == student_id,
                                                          Recommendation.source == "ai_module",
                                                          Recommendation.is_active.is_(True))):
            old.is_active = False
        for r in advice["recommendations"]:
            rec = Recommendation(student_id=student_id, source="ai_module", recommendation_type=r.area,
                                 title=r.title, description=" ".join(r.actions), priority=r.priority.lower(),
                                 reason=" ".join(r.evidence), related_prediction_id=pred.id, is_active=True)
            s.add(rec)
            s.flush()
            s.add(RecommendationProgress(recommendation_id=rec.id, student_id=student_id, status="pending"))
        return pred.id


def latest_prediction(student_id: int) -> dict | None:
    with get_session() as s:
        pred = s.scalar(select(Prediction).where(Prediction.student_id == student_id)
                        .order_by(Prediction.id.desc()))
        if pred is None:
            return None
        exps = s.scalars(select(Explanation).where(Explanation.prediction_id == pred.id)).all()
        return {
            "id": pred.id, "predicted_class": pred.predicted_class, "probabilities": pred.probabilities,
            "risk_probability": pred.risk_probability, "model_version": pred.model_version,
            "created_at": pred.created_at,
            "shap": {e.target_class: e.top_features for e in exps if e.method == "shap"},
            "lime": next((e.top_features for e in exps if e.method == "lime"), []),
        }


def prediction_history(student_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(Prediction.created_at, Prediction.predicted_class, Prediction.risk_probability,
                                Prediction.model_version)
                         .where(Prediction.student_id == student_id).order_by(Prediction.id.desc())).all()
    return pd.DataFrame([r._mapping for r in rows])


def plan_for(predicted_class: str) -> dict:
    return module_recommendations.CLASS_PLANS[predicted_class]
