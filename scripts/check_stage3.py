"""
Stage 3 verification: topic mastery, history-aware recommendations, study plan and AI prediction.

Run from the project folder (after scripts.seed_demo):   python -m scripts.check_stage3
Uses a temporary copy of DEMO-0001, so the demo students are not changed. It is deleted at the end.
"""
from __future__ import annotations

import sys
from datetime import date

from sqlalchemy import delete, func, select

from db.models import (Assessment, Explanation, ModuleRecord, Prediction, Recommendation, StudentProfile,
                       StudyPlan, User)
from db.session import get_session
from services import ai_service, learning
from services.auth import hash_password
from services.prediction import Predictor

TMP_EMAIL = "stage3.tmp@stage3-test.example.com"
ok = True


def check(passed, text):
    global ok
    ok &= bool(passed)
    print(("  [PASS] " if passed else "  [FAIL] ") + text)


def cleanup():
    with get_session() as s:
        s.execute(delete(User).where(User.email == TMP_EMAIL))


def make_temp_student() -> int:
    """Copy DEMO-0001's assessments and module record into a temporary student."""
    with get_session() as s:
        src = s.scalar(select(StudentProfile).where(StudentProfile.student_code == "DEMO-0001"))
        u = User(full_name="Stage3 Temp", email=TMP_EMAIL, password_hash=hash_password("Temp1234"), role="student")
        s.add(u)
        s.flush()
        p = StudentProfile(user_id=u.id, student_code="TMP-STAGE3", is_demo=True)
        s.add(p)
        s.flush()
        for a in s.scalars(select(Assessment).where(Assessment.student_id == src.id)):
            s.add(Assessment(student_id=p.id, subject_id=a.subject_id, topic_id=a.topic_id,
                             assessment_name=a.assessment_name, assessment_type=a.assessment_type, score=a.score,
                             maximum_score=a.maximum_score, assessment_date=a.assessment_date))
        mr = s.scalar(select(ModuleRecord).where(ModuleRecord.student_id == src.id))
        s.add(ModuleRecord(student_id=p.id, source=mr.source, oulad_id_student=mr.oulad_id_student,
                           code_module=mr.code_module, code_presentation=mr.code_presentation,
                           features=mr.features, actual_result=mr.actual_result))
        return p.id


def add_score(sid: int, topic_id: int, pct: float):
    with get_session() as s:
        a = s.scalar(select(Assessment).where(Assessment.student_id == sid, Assessment.topic_id == topic_id))
        s.add(Assessment(student_id=sid, subject_id=a.subject_id, topic_id=topic_id, assessment_name="Quiz 3 (test)",
                         assessment_type="quiz", score=round(pct / 5) , maximum_score=20, assessment_date=date.today()))


def active_for_topic(sid: int, topic_id: int):
    return [r for r in learning.list_recommendations(sid, active=True) if r.topic and r.source == "subject_rules"
            and r.id in _ids(sid, topic_id)]


def _ids(sid, topic_id):
    with get_session() as s:
        return set(s.scalars(select(Recommendation.id).where(Recommendation.student_id == sid,
                                                             Recommendation.topic_id == topic_id)))


cleanup()
try:
    sid = make_temp_student()

    print("\n=== Topic mastery ===")
    m = learning.topic_mastery(sid)
    check(len(m) == 18, f"Mastery computed for {len(m)} topics")
    check(set(m["level"]) <= {"weak", "developing", "strong"}, "Every topic has a level")

    print("\n=== Recommendations from history ===")
    c1 = learning.refresh_recommendations(sid)
    check(0 < c1["created"] <= learning.MAX_ACTIVE,
          f"First run created {c1['created']} recommendations (focus limit {learning.MAX_ACTIVE})")
    c2 = learning.refresh_recommendations(sid)
    check(c2["created"] == 0, "Second run without new data creates nothing (no duplicates)")
    check(not learning.needs_refresh(sid), "Engine knows nothing new happened")

    weak = m[m["level"] == "weak"].nsmallest(3, "mastery")
    t_improve, t_flat, t_skip = [int(x) for x in weak["topic_id"]]
    rec_improve = active_for_topic(sid, t_improve)[0]
    check(rec_improve.difficulty == "beginner", f"Weak topic gets a beginner recommendation: “{rec_improve.title}”")

    # Improved after completing
    learning.update_progress(sid, rec_improve.id, "completed", "Watched notes and practised", 5)
    check(learning.needs_refresh(sid), "Completing an activity marks the student for refresh")
    learning.refresh_recommendations(sid)
    check(active_for_topic(sid, t_improve)[0].id == rec_improve.id,
          "Completed but no new score yet -> recommendation waits")
    before = float(m.loc[m["topic_id"] == t_improve, "latest_pct"].iloc[0])
    add_score(sid, t_improve, min(100, before + 25))
    learning.refresh_recommendations(sid)
    new = active_for_topic(sid, t_improve)[0]
    check(new.id != rec_improve.id and new.difficulty == "intermediate" and "Improved" in new.reason,
          f"Improved score -> next level: “{new.title}” ({new.difficulty})")

    # No improvement after completing
    rec_flat = active_for_topic(sid, t_flat)[0]
    learning.update_progress(sid, rec_flat.id, "completed")
    flat_before = float(m.loc[m["topic_id"] == t_flat, "latest_pct"].iloc[0])
    add_score(sid, t_flat, flat_before)
    learning.refresh_recommendations(sid)
    alt = active_for_topic(sid, t_flat)[0]
    check(alt.rec_type == "alternative" and alt.priority == "high" and "Teacher support" in alt.reason,
          f"No improvement -> different approach + teacher support: “{alt.title}”")

    # Skipped
    rec_skip = active_for_topic(sid, t_skip)[0]
    learning.update_progress(sid, rec_skip.id, "skipped")
    learning.refresh_recommendations(sid)
    alt2 = active_for_topic(sid, t_skip)[0]
    check(alt2.rec_type == "alternative" and alt2.priority == "medium", "Skipped -> alternative with lower priority")

    hist = learning.list_recommendations(sid, active=False)
    check(len(hist) >= 3, f"History keeps {len(hist)} closed recommendations")

    print("\n=== Ownership ===")
    with get_session() as s:
        other_student = s.scalar(select(StudentProfile.id).where(StudentProfile.student_code == "DEMO-0002"))
    learning.refresh_recommendations(other_student)
    with get_session() as s:
        other = s.scalar(select(Recommendation.id).where(Recommendation.student_id == other_student))
    if other:
        try:
            learning.update_progress(sid, other, "completed")
            check(False, "Student cannot change another student's recommendation")
        except PermissionError:
            check(True, "Student cannot change another student's recommendation")

    print("\n=== Study plan ===")
    plan = learning.current_study_plan(sid)
    check(len(plan) == 4, f"Plan has {len(plan)} subjects")
    check(abs(plan["target_minutes_per_day"].sum() - learning.DAILY_STUDY_BUDGET_MIN) <= 20,
          f"Total {plan['target_minutes_per_day'].sum()} min/day (budget {learning.DAILY_STUDY_BUDGET_MIN})")
    mm = learning.topic_mastery(sid)
    gaps = mm.assign(gap=(75 - mm["mastery"]).clip(lower=0)).groupby("subject_name")["gap"].mean()
    neediest = gaps.idxmax()
    check(plan.iloc[0]["subject_name"] == neediest,
          f"Most time goes to the subject furthest below target ({neediest})")

    print("\n=== AI prediction ===")
    pid = ai_service.run_prediction(sid)
    pred = ai_service.latest_prediction(sid)
    check(pid is not None and pred["id"] == pid, f"Prediction stored: {pred['predicted_class']}")
    with get_session() as s:
        mr = s.scalar(select(ModuleRecord).where(ModuleRecord.student_id == sid))
        n_exp = s.scalar(select(func.count()).select_from(Explanation).where(Explanation.prediction_id == pid))
        n_ai = s.scalar(select(func.count()).select_from(Recommendation).where(
            Recommendation.student_id == sid, Recommendation.source == "ai_module", Recommendation.is_active.is_(True)))
    direct = Predictor().predict(mr.features)["predicted_class"]
    check(pred["predicted_class"] == direct, "Stored prediction equals a direct model prediction")
    check(n_exp == 5, "SHAP (4 classes) + LIME explanations stored")
    check(abs(sum(pred["probabilities"].values()) - 1) < 1e-4, "Probabilities sum to 1")
    ai_service.run_prediction(sid)
    with get_session() as s:
        n_ai2 = s.scalar(select(func.count()).select_from(Recommendation).where(
            Recommendation.student_id == sid, Recommendation.source == "ai_module", Recommendation.is_active.is_(True)))
    check(n_ai2 == n_ai, f"Running again replaces AI recommendations ({n_ai} active, not duplicated)")
    check(len(ai_service.prediction_history(sid)) == 2, "Prediction history keeps both runs")
finally:
    cleanup()

print("\n" + ("ALL CHECKS PASSED" if ok else "SOME CHECKS FAILED — send this output"))
sys.exit(0 if ok else 1)
