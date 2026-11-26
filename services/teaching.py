"""
Teacher-side services: class overview, student monitoring and teacher actions.

Every function that touches a student first checks that the teacher is allowed to
see that student (services.access). AI predictions support the teacher's judgement;
the platform never labels a student as a confirmed failure or dropout.

Flags used on the class dashboard (shown with their definitions in the UI):
  High predicted risk : latest AI prediction gives Fail + Withdrawn probability >= 60%
  Needs attention     : overall mastery < 50%, OR >= 3 weak topics, OR high predicted risk,
                        OR an open "different approach / teacher support" recommendation
  Low engagement      : no recommendation started/completed in the last 14 days
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
from sqlalchemy import func, select

from db.models import (Assessment, AuditLog, Enrollment, LearningResource, ModuleRecord, Notification, Prediction,
                       Recommendation, RecommendationProgress, RecommendationResource, StudentProfile, StudyPlan,
                       Subject, TeacherFeedback, TeacherProfile, Topic, User)
from db.session import get_session
from services import ai_service, learning
from services.access import (can_edit_subject, can_view_student, teacher_profile_id, teacher_student_ids,
                             teacher_subject_ids)
from services.auth import CurrentUser

HIGH_RISK = 0.60
ATTENTION_MASTERY = 50.0
ATTENTION_WEAK_TOPICS = 3
ENGAGEMENT_DAYS = 14
ASSESSMENT_TYPES = ["quiz", "assignment", "midterm", "final", "practice", "lab"]


class TeacherActionError(ValueError):
    """Message safe to show to the teacher."""


def _require(user: CurrentUser, student_id: int):
    if user.role not in ("teacher", "admin") or not can_view_student(user, student_id):
        raise PermissionError("You are not assigned to this student.")


def _require_edit(user: CurrentUser, student_id: int, subject_id: int | None):
    _require(user, student_id)
    if not can_edit_subject(user, student_id, subject_id):
        raise PermissionError("You can only record results and assign work in the subjects you teach.")


def my_subject_ids(user: CurrentUser) -> set[int]:
    if user.role == "admin":
        with get_session() as s:
            return set(s.scalars(select(Subject.id)))
    tid = teacher_profile_id(user.id)
    return teacher_subject_ids(tid) if tid else set()


def my_subject_names(user: CurrentUser) -> list[str]:
    ids = my_subject_ids(user)
    if not ids:
        return []
    with get_session() as s:
        return list(s.scalars(select(Subject.subject_name).where(Subject.id.in_(ids)).order_by(Subject.subject_name)))


def _utc(dt):
    return None if dt is None else (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def my_student_ids(user: CurrentUser) -> set[int]:
    if user.role == "admin":
        with get_session() as s:
            return set(s.scalars(select(StudentProfile.id)))
    tid = teacher_profile_id(user.id)
    return teacher_student_ids(tid) if tid else set()


def log_view(user: CurrentUser, student_id: int):
    with get_session() as s:
        s.add(AuditLog(user_id=user.id, action="view_student", entity="student_profile", entity_id=student_id))


# =============================================================================
# Class overview
# =============================================================================
def _class_mastery(ids) -> dict[int, pd.DataFrame]:
    frame = learning.assessments_frame_many(ids)
    out = {}
    for sid in ids:
        f = frame[frame["student_id"] == sid] if len(frame) else frame
        out[sid] = learning.topic_mastery(sid, f)
    return out


def class_overview(user: CurrentUser) -> pd.DataFrame:
    ids = my_student_ids(user)
    if not ids:
        return pd.DataFrame()
    ids = list(ids)
    since = datetime.now(timezone.utc) - timedelta(days=ENGAGEMENT_DAYS)
    mine = my_subject_ids(user)
    # keep recommendations current (heavy, but only for students with new scores or actions)
    for sid in learning.needs_refresh_many(ids):
        learning.refresh_recommendations(sid)
    masteries = _class_mastery(ids)
    with get_session() as s:
        people = s.execute(select(StudentProfile.id, StudentProfile.student_code, User.full_name, StudentProfile.is_demo)
                           .join(User, User.id == StudentProfile.user_id)
                           .where(StudentProfile.id.in_(ids))).all()
        last_pred = (select(Prediction.student_id, func.max(Prediction.id).label("pid"))
                     .where(Prediction.student_id.in_(ids)).group_by(Prediction.student_id).subquery())
        preds = {r.student_id: r for r in s.execute(
            select(Prediction.student_id, Prediction.predicted_class, Prediction.risk_probability)
            .join(last_pred, last_pred.c.pid == Prediction.id)).all()}
        recent = set()
        for sid, t in s.execute(select(RecommendationProgress.student_id, RecommendationProgress.updated_at).where(
                RecommendationProgress.student_id.in_(ids),
                RecommendationProgress.status.in_(["started", "completed"]))).all():
            if _utc(t) >= since:
                recent.add(sid)
        open_recs = dict(s.execute(select(Recommendation.student_id, func.count()).where(
            Recommendation.student_id.in_(ids), Recommendation.is_active.is_(True))
            .group_by(Recommendation.student_id)).all())
        support = dict(s.execute(select(Recommendation.student_id, func.count()).where(
            Recommendation.student_id.in_(ids), Recommendation.is_active.is_(True),
            Recommendation.reason.like("%Teacher support suggested%")).group_by(Recommendation.student_id)).all())
        completed = dict(s.execute(select(RecommendationProgress.student_id, func.count()).where(
            RecommendationProgress.student_id.in_(ids), RecommendationProgress.status == "completed")
            .group_by(RecommendationProgress.student_id)).all())
    rows = []
    for sid, code, name, is_demo in people:
        m = masteries[sid]
        subj = learning.subject_summary(m)
        pred = preds.get(sid)
        mastery = float(m["mastery"].mean()) if len(m) else None
        m_mine = m[m["subject_id"].isin(mine)] if len(m) else m
        mine_mastery = float(m_mine["mastery"].mean()) if len(m_mine) else None
        subj_mine = subj[subj["subject_id"].isin(mine)] if len(subj) else subj
        weak = int((m["level"] == "weak").sum()) if len(m) else 0
        risk = pred.risk_probability if pred else None
        high_risk = risk is not None and risk >= HIGH_RISK
        reasons = []
        if mastery is not None and mastery < ATTENTION_MASTERY:
            reasons.append(f"overall mastery {mastery:.0f}%")
        if weak >= ATTENTION_WEAK_TOPICS:
            reasons.append(f"{weak} weak topics")
        if high_risk:
            reasons.append(f"AI risk {risk * 100:.0f}%")
        if support.get(sid, 0):
            reasons.append("no improvement after an activity")
        rows.append({
            "student_id": sid, "Student ID": code, "Name": name, "Demo": is_demo,
            "Mastery": mastery, "My subjects": mine_mastery, "Weak topics": weak,
            "Weakest subject": subj.iloc[0]["subject_name"] if len(subj) else "—",
            "Weakest of mine": subj_mine.iloc[0]["subject_name"] if len(subj_mine) else "—",
            "AI prediction": pred.predicted_class if pred else "Not run",
            "Risk": risk, "High risk": high_risk,
            "Open recs": open_recs.get(sid, 0), "Completed": completed.get(sid, 0),
            "Low engagement": sid not in recent,
            "Needs attention": bool(reasons), "Why": "; ".join(reasons) if reasons else "On track",
        })
    df = pd.DataFrame(rows)
    return df.sort_values(["Needs attention", "Mastery"], ascending=[False, True], na_position="last") \
             .reset_index(drop=True)


def class_subject_performance(user: CurrentUser) -> pd.DataFrame:
    frames, mine = [], my_subject_ids(user)
    for sid, m in _class_mastery(list(my_student_ids(user))).items():
        subj = learning.subject_summary(m)
        subj = subj[subj["subject_id"].isin(mine)]
        if len(subj):
            frames.append(subj[["subject_name", "mastery"]])
    if not frames:
        return pd.DataFrame(columns=["subject_name", "mastery", "level"])
    out = pd.concat(frames).groupby("subject_name", as_index=False)["mastery"].mean()
    out["level"] = out["mastery"].map(learning.level_of)
    return out.sort_values("mastery").reset_index(drop=True)


def run_predictions_for_class(user: CurrentUser) -> int:
    n = 0
    for sid in my_student_ids(user):
        _require(user, sid)
        if ai_service.run_prediction(sid) is not None:
            n += 1
    return n


# =============================================================================
# Subjects / topics the teacher can use
# =============================================================================
def teacher_subjects(user: CurrentUser) -> pd.DataFrame:
    """Subjects (and their topics) this teacher may edit."""
    ids = my_subject_ids(user)
    if not ids:
        return pd.DataFrame(columns=["id", "subject_name", "topic_id", "topic_name"])
    with get_session() as s:
        rows = s.execute(select(Subject.id, Subject.subject_name, Topic.id.label("topic_id"), Topic.topic_name)
                         .outerjoin(Topic, Topic.subject_id == Subject.id)
                         .where(Subject.id.in_(ids))
                         .order_by(Subject.subject_name, Topic.order_index)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "subject_name", "topic_id", "topic_name"])


# =============================================================================
# Teacher actions
# =============================================================================
def _notify(s, student_id: int, title: str, message: str, kind: str):
    uid = s.scalar(select(StudentProfile.user_id).where(StudentProfile.id == student_id))
    s.add(Notification(user_id=uid, title=title, message=message, notification_type=kind))


def _validate_score(score: float, maximum: float):
    if maximum is None or maximum <= 0:
        raise TeacherActionError("Maximum score must be greater than 0.")
    if score is None or score < 0 or score > maximum:
        raise TeacherActionError(f"Score must be between 0 and {maximum:g}.")


def record_assessment(user: CurrentUser, student_id: int, subject_id: int, topic_id: int | None, name: str,
                      a_type: str, score: float, maximum: float, when: date) -> None:
    if subject_id is None:
        raise TeacherActionError("Please choose a subject.")
    _require_edit(user, student_id, subject_id)
    _validate_score(score, maximum)
    if not (name or "").strip():
        raise TeacherActionError("Please enter an assessment name.")
    if a_type not in ASSESSMENT_TYPES:
        raise TeacherActionError("Unknown assessment type.")
    with get_session() as s:
        s.add(Assessment(student_id=student_id, subject_id=subject_id, topic_id=topic_id,
                         assessment_name=name.strip(), assessment_type=a_type, score=float(score),
                         maximum_score=float(maximum), assessment_date=when, recorded_by=user.id))
        _notify(s, student_id, "New result recorded", f"{name.strip()}: {score:g}/{maximum:g}", "assessment")


def record_class_scores(user: CurrentUser, subject_id: int, topic_id: int | None, name: str, a_type: str,
                        maximum: float, when: date, scores: dict[int, float | None]) -> int:
    """scores = {student_id: score or None (absent)}. Returns number of scores saved."""
    entered = {sid: sc for sid, sc in scores.items() if sc is not None and not pd.isna(sc)}
    for sid, sc in entered.items():
        _require_edit(user, sid, subject_id)
        _validate_score(float(sc), maximum)
    for sid, sc in entered.items():
        record_assessment(user, sid, subject_id, topic_id, name, a_type, float(sc), maximum, when)
    return len(entered)


def add_feedback(user: CurrentUser, student_id: int, text: str, subject_id: int | None, visibility: str) -> None:
    _require_edit(user, student_id, subject_id)
    text = (text or "").strip()
    if len(text) < 3:
        raise TeacherActionError("Please write some feedback.")
    if visibility not in ("student", "private"):
        raise TeacherActionError("Invalid visibility.")
    tid = teacher_profile_id(user.id)
    if tid is None:
        raise TeacherActionError("Only teachers can write feedback.")
    with get_session() as s:
        s.add(TeacherFeedback(teacher_id=tid, student_id=student_id, subject_id=subject_id, feedback=text,
                              visibility=visibility))
        if visibility == "student":
            _notify(s, student_id, "New feedback from your teacher", text[:200], "feedback")


def assign_activity(user: CurrentUser, student_id: int, title: str, description: str, subject_id: int | None,
                    topic_id: int | None, priority: str, difficulty: str | None) -> None:
    _require_edit(user, student_id, subject_id)
    title = (title or "").strip()
    if len(title) < 3:
        raise TeacherActionError("Please enter a title for the activity.")
    if priority not in ("high", "medium", "low"):
        raise TeacherActionError("Invalid priority.")
    with get_session() as s:
        rec = Recommendation(student_id=student_id, subject_id=subject_id, topic_id=topic_id, source="teacher",
                             recommendation_type="teacher_activity", title=title,
                             description=(description or "").strip(), priority=priority,
                             reason=f"Assigned by {user.full_name}.", difficulty=difficulty,
                             created_by=user.id, is_active=True)
        s.add(rec)
        s.flush()
        s.add(RecommendationProgress(recommendation_id=rec.id, student_id=student_id, status="pending"))
        if subject_id:
            q = select(LearningResource.id).where(LearningResource.verification_status == "approved",
                                                  LearningResource.subject_id == subject_id)
            if topic_id:
                q = q.where(LearningResource.topic_id == topic_id)
            for rid in s.scalars(q.limit(4)):
                s.add(RecommendationResource(recommendation_id=rec.id, resource_id=rid))
        _notify(s, student_id, "New activity from your teacher", title, "activity")


def set_study_target(user: CurrentUser, student_id: int, subject_id: int, minutes_per_day: int,
                     priority: str, end_date: date | None) -> None:
    _require_edit(user, student_id, subject_id)
    if not 5 <= int(minutes_per_day) <= 480:
        raise TeacherActionError("Minutes per day must be between 5 and 480.")
    with get_session() as s:
        for p in s.scalars(select(StudyPlan).where(StudyPlan.student_id == student_id,
                                                   StudyPlan.subject_id == subject_id,
                                                   StudyPlan.created_by == "teacher",
                                                   StudyPlan.progress_status == "active")):
            p.progress_status = "completed"
        s.add(StudyPlan(student_id=student_id, subject_id=subject_id, target_minutes_per_day=int(minutes_per_day),
                        priority=priority, start_date=date.today(), end_date=end_date, created_by="teacher"))
        name = s.scalar(select(Subject.subject_name).where(Subject.id == subject_id))
        _notify(s, student_id, "New study target", f"{name}: {minutes_per_day} minutes per day", "study_target")


def feedback_history(user: CurrentUser, student_id: int) -> pd.DataFrame:
    _require(user, student_id)
    with get_session() as s:
        rows = s.execute(select(TeacherFeedback.created_at, User.full_name.label("teacher"), Subject.subject_name,
                                TeacherFeedback.visibility, TeacherFeedback.feedback)
                         .join(TeacherProfile, TeacherProfile.id == TeacherFeedback.teacher_id)
                         .join(User, User.id == TeacherProfile.user_id)
                         .outerjoin(Subject, Subject.id == TeacherFeedback.subject_id)
                         .where(TeacherFeedback.student_id == student_id)
                         .order_by(TeacherFeedback.created_at.desc())).all()
    return pd.DataFrame([r._mapping for r in rows])


def student_header(user: CurrentUser, student_id: int) -> dict:
    _require(user, student_id)
    with get_session() as s:
        p, u = s.execute(select(StudentProfile, User).join(User, User.id == StudentProfile.user_id)
                         .where(StudentProfile.id == student_id)).one()
        has_mr = bool(s.scalar(select(func.count()).select_from(ModuleRecord)
                               .where(ModuleRecord.student_id == student_id)))
        return {"name": u.full_name, "email": u.email, "code": p.student_code, "program": p.program,
                "semester": p.semester, "is_demo": p.is_demo, "has_module_record": has_mr}


# =============================================================================
# Student-side notifications
# =============================================================================
def notifications_for(user_id: int, unread_only: bool = True, limit: int = 5) -> list[dict]:
    with get_session() as s:
        q = select(Notification).where(Notification.user_id == user_id)
        if unread_only:
            q = q.where(Notification.is_read.is_(False))
        return [{"id": n.id, "title": n.title, "message": n.message, "created_at": n.created_at}
                for n in s.scalars(q.order_by(Notification.id.desc()).limit(limit))]


def mark_notifications_read(user_id: int) -> None:
    with get_session() as s:
        for n in s.scalars(select(Notification).where(Notification.user_id == user_id,
                                                      Notification.is_read.is_(False))):
            n.is_read = True
