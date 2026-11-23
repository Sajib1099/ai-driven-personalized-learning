"""
Rule-based personalised learning recommendation engine.

How it works:
1. The XGBoost model predicts the performance class.
2. SHAP gives each feature's contribution to the prediction.
3. This module combines both with the student's actual values:
   a learning area becomes a recommendation only when
     (a) SHAP shows it pushes the student toward a worse outcome, AND
     (b) the student's value is actually weak compared with the training data.
4. Each area maps to fixed, transparent advice.

Notes for the thesis:
- The rules are illustrative and have not been validated with real students.
- Demographic features (gender, region, age, IMD band, disability, education,
  module) are never used to generate advice, because they cannot or should not
  be changed by the student.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from services.prediction import label

# ----------------------------------------------------------------------------
# Learning areas: which features belong to which area, and which direction is good
# ----------------------------------------------------------------------------
AREAS = {
    "assessment_performance": {
        "title": "Assessment performance",
        "features": {"avg_score": "high", "min_score": "high", "max_score": "high",
                     "tma_avg_score": "high", "tma_min_score": "high", "tma_max_score": "high",
                     "cma_avg_score": "high", "cma_min_score": "high", "cma_max_score": "high",
                     "continuous_avg_score": "high"},
        "actions": [
            "Review the feedback on marked assessments and list the topics where marks were lost.",
            "Revise weak topics before the next assessment and attempt extra practice questions.",
            "Use tutor support or study groups for topics that remain unclear.",
        ],
    },
    "assessment_completion": {
        "title": "Assessment completion",
        "features": {"assessment_count": "high", "total_weight": "high", "avg_weight": "high",
                     "tma_count": "high", "cma_count": "high"},
        "actions": [
            "Submit every assessment, even a partial attempt, because missing work strongly affects the outcome.",
            "Put all assessment deadlines in a calendar with reminders one week and two days before.",
            "Prioritise high-weight assessments (TMAs) when time is limited.",
        ],
    },
    "submission_continuity": {
        "title": "Staying active until the end of the module",
        "features": {"avg_submission_day": "high"},
        "actions": [
            "Keep submitting assessments throughout the whole module, not only in the first weeks.",
            "Plan the second half of the module in advance, when drop-off is most common.",
            "Contact the tutor early if personal or workload problems make it hard to continue.",
        ],
    },
    "online_engagement": {
        "title": "Online learning engagement (VLE)",
        "features": {"total_clicks": "high", "active_days": "high", "learning_sites": "high",
                     "clicks_per_active_day": "high", "sites_per_active_day": "high",
                     "avg_clicks_per_record": "high", "max_clicks_per_record": "high"},
        "actions": [
            "Log in to the VLE on a fixed schedule (for example, 4–5 days each week).",
            "Work through the module's learning resources in order rather than only before deadlines.",
            "Use forums and activity pages, not only the assessment pages.",
        ],
    },
    "consistency": {
        "title": "Consistency of performance",
        "features": {"score_std": "low", "tma_score_range": "low", "cma_score_range": "low",
                     "click_consistency": "high"},
        "actions": [
            "Keep a steady weekly study routine instead of studying in bursts.",
            "Compare high- and low-scoring assessments to find what changed in preparation.",
        ],
    },
    "workload": {
        "title": "Study workload and previous attempts",
        "features": {"studied_credits": "low", "num_of_prev_attempts": "low"},
        "actions": [
            "Check whether the total study credits are manageable alongside other commitments.",
            "If this module was attempted before, focus first on the parts that caused difficulty last time.",
        ],
    },
}

NON_ACTIONABLE = ["code_module", "code_presentation", "gender", "region", "highest_education",
                  "imd_band", "age_band", "disability"]

CLASS_PLANS = {
    "Withdrawn": {
        "headline": "High risk of withdrawing from the module",
        "summary": "The profile looks similar to students who left the module. Early engagement support is the priority.",
        "actions": [
            "Make a simple weekly study schedule with fixed VLE and study times.",
            "Contact the tutor or student support service now to discuss any barriers.",
            "Set small, short-term goals (one activity or one assessment at a time).",
        ],
    },
    "Fail": {
        "headline": "At risk of failing the module",
        "summary": "The profile looks similar to students who completed but did not pass. Focus on assessment preparation and regular study.",
        "actions": [
            "Identify weak topics from assessment feedback and revise them first.",
            "Do additional practice exercises before each assessment.",
            "Keep regular weekly engagement with the learning platform.",
        ],
    },
    "Pass": {
        "headline": "On track to pass",
        "summary": "The profile looks similar to students who passed. Strengthening weaker areas may move the result higher.",
        "actions": [
            "Strengthen the lowest-scoring topics with extra revision.",
            "Keep the current study routine and assessment submission pattern.",
        ],
    },
    "Distinction": {
        "headline": "On track for distinction",
        "summary": "The profile looks similar to students who achieved distinction. Enrichment can keep the momentum.",
        "actions": [
            "Explore advanced or optional learning materials on the VLE.",
            "Try more challenging exercises and help peers in study groups.",
        ],
    },
}

RISK_CLASSES = ["Fail", "Withdrawn"]


@dataclass
class Recommendation:
    area: str
    title: str
    priority: str
    evidence: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    score: float = 0.0


def _is_weak(value: float, direction: str, ref: pd.Series) -> bool:
    """Weak = below the training median (for 'high is good') or above the 75th percentile (for 'low is good')."""
    if direction == "high":
        return value < ref["50%"]
    return value > ref["75%"] and value > 0


def _fmt(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:,.2f}".rstrip("0").rstrip(".")


def generate(predicted_class: str, probabilities: dict, row: dict,
             shap_by_class: dict[str, pd.Series], reference: pd.DataFrame,
             no_cma_modules: set | None = None, max_items: int = 4) -> dict:
    """
    predicted_class : model prediction
    probabilities   : {class: probability}
    row             : student's raw feature values
    shap_by_class   : {class: SHAP per raw feature}
    reference       : describe() table of training features (rows = features)
    no_cma_modules  : modules that have no CMA assessments (CMA advice is skipped there)
    """
    skip = set()
    if no_cma_modules and row.get("code_module") in no_cma_modules:
        skip = {f for f in row if f.startswith("cma_")} | {"continuous_avg_score"}

    # Direction of "harm": for at-risk predictions, contributions toward Fail + Withdrawn;
    # for Pass / Distinction, contributions that pull AWAY from Distinction.
    if predicted_class in RISK_CLASSES:
        harm = shap_by_class["Fail"] + shap_by_class["Withdrawn"]
        harm_text = "increases the risk of Fail/Withdrawn"
    else:
        harm = -shap_by_class["Distinction"]
        harm_text = "reduces the chance of Distinction"

    recs: list[Recommendation] = []
    for key, area in AREAS.items():
        evidence, score = [], 0.0
        for feat, direction in area["features"].items():
            if feat not in row or feat not in harm.index or feat in skip:
                continue
            h = float(harm[feat])
            if h > 0.01 and _is_weak(float(row[feat]), direction, reference.loc[feat]):
                median = reference.loc[feat, "50%"]
                evidence.append(
                    f"{label(feat)} is {_fmt(row[feat])} (training median {_fmt(median)}); "
                    f"SHAP shows this {harm_text}."
                )
                score += h
        if evidence:
            recs.append(Recommendation(area=key, title=area["title"], priority="",
                                       evidence=evidence, actions=area["actions"], score=score))

    recs.sort(key=lambda r: r.score, reverse=True)
    recs = recs[:max_items]
    for i, r in enumerate(recs):
        r.priority = "High" if i == 0 and predicted_class in RISK_CLASSES else ("Medium" if i < 2 else "Low")

    # Demographic factors that influenced the model (reported, never used for advice)
    demo_influence = (
        pd.Series({f: abs(float(shap_by_class[predicted_class][f])) for f in NON_ACTIONABLE
                   if f in shap_by_class[predicted_class].index})
        .sort_values(ascending=False)
    )

    risk = sum(probabilities[c] for c in RISK_CLASSES)
    return {
        "plan": CLASS_PLANS[predicted_class],
        "risk_probability": risk,
        "recommendations": recs,
        "non_actionable_top": [label(f) for f in demo_influence.index[:3] if demo_influence[f] > 0.05],
    }
