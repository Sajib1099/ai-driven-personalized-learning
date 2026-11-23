"""
Subject-level learning layer (Layer B): topic mastery, history-aware recommendations
and study plans. Works for ANY course / subject / topic — nothing here is subject-specific.

How the recommendation engine uses history (each time it runs):
  1. Topic mastery = recency-weighted average of the student's assessment percentages.
     Level: weak (< 50%), developing (50–69%), strong (>= 70%).
  2. For each topic it looks at the latest active recommendation and its progress:
     - completed + a newer assessment shows improvement (>= +5 points)
           -> close it and move to the next difficulty level
     - completed + newer assessment shows no improvement
           -> close it and recommend a different approach + teacher support
     - completed, no newer assessment yet -> wait (nothing changes)
     - skipped -> close it and offer an alternative with lower priority
     - pending / started but the level changed -> replace with one for the new level
  3. Topics without an active recommendation get one that matches their level
     (strong topics: at most two enrichment items).
Every recommendation stores the data that triggered it in `reason`.
The ML model is NOT retrained by any of this.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone

import pandas as pd
from sqlalchemy import func, select

from db.models import (Assessment, LearningActivity, LearningResource, Recommendation,
                       RecommendationProgress, RecommendationResource, StudyPlan, Subject, TeacherFeedback,
                       TeacherProfile, Topic, User)
from db.session import get_session

WEAK, STRONG = 50.0, 70.0
IMPROVEMENT_POINTS = 5.0
MAX_ENRICHMENT = 2
MAX_ACTIVE = 6                    # focus: at most this many open subject recommendations at a time
DAILY_STUDY_BUDGET_MIN = 120
LEVEL_DIFFICULTY = {"weak": "beginner", "developing": "intermediate", "strong": "advanced"}
NEXT_DIFFICULTY = {"beginner": "intermediate", "intermediate": "advanced", "advanced": "advanced"}
LOWER_PRIORITY = {"high": "medium", "medium": "low", "low": "low"}


def level_of(pct: float) -> str:
    return "weak" if pct < WEAK else ("developing" if pct < STRONG else "strong")


def _utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# =============================================================================
# Mastery
# =============================================================================
def assessments_frame(student_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(
            select(Assessment.id, Assessment.assessment_date, Assessment.assessment_name, Assessment.assessment_type,
                   Assessment.score, Assessment.maximum_score, Assessment.created_at,
                   Subject.id.label("subject_id"), Subject.subject_name,
                   Topic.id.label("topic_id"), Topic.topic_name, Topic.order_index)
            .join(Subject, Subject.id == Assessment.subject_id)
            .outerjoin(Topic, Topic.id == Assessment.topic_id)
            .where(Assessment.student_id == student_id)
            .order_by(Assessment.assessment_date, Assessment.id)).all()
    df = pd.DataFrame([r._mapping for r in rows])
    if df.empty:
        return df
    df["pct"] = df["score"] / df["maximum_score"] * 100
    df["topic_name"] = df["topic_name"].fillna("General")
    return df


def topic_mastery(student_id: int) -> pd.DataFrame:
    """One row per (subject, topic): attempts, first %, latest %, mastery %, trend, level."""
    df = assessments_frame(student_id)
    if df.empty:
        return pd.DataFrame(columns=["subject_id", "subject_name", "topic_id", "topic_name", "attempts",
                                     "first_pct", "latest_pct", "mastery", "trend", "level", "last_date"])
    out = []
    for (sid, sname, tid, tname), g in df.groupby(["subject_id", "subject_name", "topic_id", "topic_name"],
                                                  dropna=False, sort=False):
        g = g.sort_values(["assessment_date", "id"])
        weights = pd.Series(range(1, len(g) + 1), index=g.index)          # newer attempts weigh more
        mastery = float((g["pct"] * weights).sum() / weights.sum())
        out.append({
            "subject_id": int(sid), "subject_name": sname,
            "topic_id": None if pd.isna(tid) else int(tid), "topic_name": tname,
            "order_index": g["order_index"].iloc[0],
            "attempts": len(g), "first_pct": float(g["pct"].iloc[0]), "latest_pct": float(g["pct"].iloc[-1]),
            "mastery": mastery, "trend": float(g["pct"].iloc[-1] - g["pct"].iloc[0]),
            "level": level_of(mastery), "last_date": g["assessment_date"].iloc[-1],
        })
    return pd.DataFrame(out).sort_values(["subject_name", "order_index"]).reset_index(drop=True)


def subject_summary(mastery: pd.DataFrame) -> pd.DataFrame:
    if mastery.empty:
        return pd.DataFrame(columns=["subject_id", "subject_name", "mastery", "first_avg", "latest_avg",
                                     "weak_topics", "strong_topics", "level"])
    g = mastery.groupby(["subject_id", "subject_name"])
    out = g.agg(mastery=("mastery", "mean"), first_avg=("first_pct", "mean"), latest_avg=("latest_pct", "mean"),
                weak_topics=("level", lambda x: int((x == "weak").sum())),
                strong_topics=("level", lambda x: int((x == "strong").sum()))).reset_index()
    out["level"] = out["mastery"].map(level_of)
    return out.sort_values("mastery").reset_index(drop=True)


# =============================================================================
# Recommendation engine
# =============================================================================
def _template(kind: str, topic: str, subject: str) -> tuple[str, str, str]:
    """(recommendation_type, title, description) — generic text, works for any topic."""
    if kind == "beginner":
        return ("revision", f"Rebuild the basics of {topic}",
                f"Review the lecture notes and beginner-level material for {topic} ({subject}), then try basic "
                f"practice questions. Target: at least 60% in the next {topic} assessment.")
    if kind == "intermediate":
        return ("practice", f"Strengthen {topic} with practice",
                f"Solve intermediate-level exercises on {topic} ({subject}) and check your answers against "
                f"worked solutions. Target: 70% or more in the next assessment.")
    if kind == "advanced":
        return ("enrichment", f"Challenge yourself in {topic}",
                f"You are doing well in {topic} ({subject}). Try advanced problems or an extra reading to "
                f"deepen your understanding.")
    if kind == "alternative_skip":
        return ("alternative", f"A different way to study {topic}",
                f"You skipped the previous activity for {topic} ({subject}). Try a shorter or different kind of "
                f"activity (a video, a summary sheet or a few practice questions) that fits your schedule better.")
    return ("alternative", f"Try a different approach for {topic}",
            f"Your result in {topic} ({subject}) did not improve after the last activity. Try a different type "
            f"of resource (video, notes or practice set) and ask your teacher for support.")


def _priority(level: str) -> str:
    return {"weak": "high", "developing": "medium", "strong": "low"}[level]


def _recorded_at(df: pd.DataFrame) -> pd.Series:
    # when the score was entered in the platform (UTC)
    return pd.to_datetime(df["created_at"], utc=True)


def _pct_before(df: pd.DataFrame, topic_id: int, when: datetime) -> float | None:
    g = df[(df["topic_id"] == topic_id) & (_recorded_at(df) <= pd.Timestamp(when))]
    return float(g["pct"].iloc[-1]) if len(g) else None


def _pct_after(df: pd.DataFrame, topic_id: int, when: datetime) -> float | None:
    g = df[(df["topic_id"] == topic_id) & (_recorded_at(df) > pd.Timestamp(when))]
    return float(g["pct"].iloc[-1]) if len(g) else None


def _attach_resources(s, rec: Recommendation, topic_id: int | None, subject_id: int, difficulty: str):
    q = select(LearningResource.id).where(LearningResource.verification_status == "approved",
                                          LearningResource.subject_id == subject_id)
    q = q.where(LearningResource.topic_id == topic_id) if topic_id else q
    ids = s.scalars(q.where(LearningResource.difficulty == difficulty).limit(4)).all() or \
        s.scalars(q.limit(4)).all()
    for rid in ids:
        s.add(RecommendationResource(recommendation_id=rec.id, resource_id=rid))


def _create(s, student_id: int, row: dict, kind: str, priority: str, reason: str) -> Recommendation:
    rtype, title, desc = _template(kind, row["topic_name"], row["subject_name"])
    difficulty = kind if kind in NEXT_DIFFICULTY else LEVEL_DIFFICULTY[row["level"]]
    rec = Recommendation(student_id=student_id, subject_id=row["subject_id"], topic_id=row["topic_id"],
                         source="subject_rules", recommendation_type=rtype, title=title, description=desc,
                         priority=priority, reason=reason, difficulty=difficulty, is_active=True)
    s.add(rec)
    s.flush()
    s.add(RecommendationProgress(recommendation_id=rec.id, student_id=student_id, status="pending"))
    _attach_resources(s, rec, row["topic_id"], row["subject_id"], difficulty)
    return rec


def refresh_recommendations(student_id: int) -> dict:
    """Run the engine once. Returns counts of what changed."""
    mastery = topic_mastery(student_id)
    df = assessments_frame(student_id)
    changes = {"created": 0, "closed": 0, "kept": 0}
    if mastery.empty:
        return changes

    strong_topics = set(mastery[mastery["level"] == "strong"].nlargest(MAX_ENRICHMENT, "mastery")["topic_id"])

    candidates: list[tuple[dict, str]] = []
    with get_session() as s:
        for row in mastery.to_dict("records"):
            if row["topic_id"] is None:
                continue
            fmt = f"{row['topic_name']}: mastery {row['mastery']:.0f}% ({row['level']}), latest {row['latest_pct']:.0f}%"
            rec = s.scalar(select(Recommendation).where(
                Recommendation.student_id == student_id, Recommendation.topic_id == row["topic_id"],
                Recommendation.source == "subject_rules", Recommendation.is_active.is_(True))
                .order_by(Recommendation.id.desc()))
            prog = s.scalar(select(RecommendationProgress).where(
                RecommendationProgress.recommendation_id == rec.id)) if rec else None

            if rec is None:
                if row["level"] != "strong" or row["topic_id"] in strong_topics:
                    candidates.append((row, fmt))
                continue

            status = prog.status if prog else "pending"
            if status == "completed":
                done_at = _utc(prog.completed_at)
                after = _pct_after(df, row["topic_id"], done_at)
                if after is None:
                    changes["kept"] += 1          # waiting for a new assessment
                    continue
                before = _pct_before(df, row["topic_id"], done_at)
                rec.is_active = False
                changes["closed"] += 1
                if before is not None and after - before >= IMPROVEMENT_POINTS:
                    nxt = NEXT_DIFFICULTY[rec.difficulty or "beginner"]
                    _create(s, student_id, row, nxt, LOWER_PRIORITY[rec.priority],
                            f"Improved from {before:.0f}% to {after:.0f}% after completing “{rec.title}”. "
                            f"Moving to {nxt} level. {fmt}.")
                else:
                    _create(s, student_id, row, "alternative", "high",
                            f"No improvement after completing “{rec.title}” ({before or 0:.0f}% → {after:.0f}%). "
                            f"Teacher support suggested. {fmt}.")
                changes["created"] += 1
            elif status == "skipped":
                rec.is_active = False
                changes["closed"] += 1
                _create(s, student_id, row, "alternative_skip", LOWER_PRIORITY[rec.priority],
                        f"Previous recommendation “{rec.title}” was skipped; offering a different approach. {fmt}.")
                changes["created"] += 1
            else:
                expected = LEVEL_DIFFICULTY[row["level"]]
                if rec.recommendation_type != "alternative" and rec.difficulty != expected:
                    rec.is_active = False
                    changes["closed"] += 1
                    if row["level"] != "strong" or row["topic_id"] in strong_topics:
                        _create(s, student_id, row, expected, _priority(row["level"]),
                                f"Level changed to {row['level']}. {fmt}.")
                        changes["created"] += 1
                else:
                    changes["kept"] += 1

        # New recommendations for uncovered topics: weakest first, up to MAX_ACTIVE open at a time
        s.flush()
        open_now = s.scalar(select(func.count()).select_from(Recommendation).where(
            Recommendation.student_id == student_id, Recommendation.source == "subject_rules",
            Recommendation.is_active.is_(True)))
        for row, fmt in sorted(candidates, key=lambda c: c[0]["mastery"]):
            if open_now >= MAX_ACTIVE:
                break
            _create(s, student_id, row, LEVEL_DIFFICULTY[row["level"]], _priority(row["level"]), f"{fmt}.")
            changes["created"] += 1
            open_now += 1
    build_study_plan(student_id, mastery)
    return changes


def last_engine_run(student_id: int) -> datetime | None:
    """Each engine run rebuilds the study plan, so the newest system plan marks the last run."""
    with get_session() as s:
        return _utc(s.scalar(select(func.max(StudyPlan.created_at)).where(
            StudyPlan.student_id == student_id, StudyPlan.created_by == "system")))


def needs_refresh(student_id: int) -> bool:
    """True if a new score was recorded or the student acted on a recommendation since the last run."""
    last_run = last_engine_run(student_id)
    with get_session() as s:
        has_data = s.scalar(select(func.count()).select_from(Assessment)
                            .where(Assessment.student_id == student_id)) > 0
        if last_run is None:
            return has_data
        newest_assessment = _utc(s.scalar(select(func.max(Assessment.created_at))
                                          .where(Assessment.student_id == student_id)))
        newest_action = _utc(s.scalar(select(func.max(RecommendationProgress.updated_at)).where(
            RecommendationProgress.student_id == student_id, RecommendationProgress.status != "pending")))
        return any(t is not None and t > last_run for t in (newest_assessment, newest_action))


# =============================================================================
# Study plan
# =============================================================================
def build_study_plan(student_id: int, mastery: pd.DataFrame | None = None,
                     daily_budget: int = DAILY_STUDY_BUDGET_MIN) -> None:
    mastery = topic_mastery(student_id) if mastery is None else mastery
    subj = subject_summary(mastery)
    if subj.empty:
        return
    # need = average shortfall of the subject's topics below 75%, plus a small base so every subject keeps time
    need = mastery.assign(gap=(75 - mastery["mastery"]).clip(lower=0)).groupby("subject_id")["gap"].mean() + 5
    minutes = (need / need.sum() * daily_budget / 5).round().clip(lower=3) * 5
    with get_session() as s:
        for p in s.scalars(select(StudyPlan).where(StudyPlan.student_id == student_id,
                                                   StudyPlan.created_by == "system",
                                                   StudyPlan.progress_status == "active")):
            p.progress_status = "completed"
        for r in subj.itertuples():
            s.add(StudyPlan(student_id=student_id, subject_id=int(r.subject_id),
                            target_minutes_per_day=int(minutes[r.subject_id]),
                            priority=_priority(r.level), start_date=date.today(), created_by="system"))


def current_study_plan(student_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(Subject.subject_name, StudyPlan.priority, StudyPlan.target_minutes_per_day,
                                StudyPlan.start_date, StudyPlan.created_by)
                         .join(Subject, Subject.id == StudyPlan.subject_id)
                         .where(StudyPlan.student_id == student_id, StudyPlan.progress_status == "active")
                         .order_by(StudyPlan.target_minutes_per_day.desc())).all()
    return pd.DataFrame([r._mapping for r in rows])


# =============================================================================
# Reading and updating recommendations
# =============================================================================
@dataclass
class RecView:
    id: int
    title: str
    description: str
    priority: str
    reason: str
    difficulty: str | None
    rec_type: str
    source: str
    subject: str | None
    topic: str | None
    status: str
    is_active: bool
    created_at: datetime
    completed_at: datetime | None
    feedback: str | None
    rating: int | None
    resources: list[dict]


def list_recommendations(student_id: int, active: bool | None = True) -> list[RecView]:
    with get_session() as s:
        q = (select(Recommendation, RecommendationProgress, Subject.subject_name, Topic.topic_name)
             .outerjoin(RecommendationProgress, RecommendationProgress.recommendation_id == Recommendation.id)
             .outerjoin(Subject, Subject.id == Recommendation.subject_id)
             .outerjoin(Topic, Topic.id == Recommendation.topic_id)
             .where(Recommendation.student_id == student_id))
        if active is not None:
            q = q.where(Recommendation.is_active.is_(active))
        out = []
        for rec, prog, sname, tname in s.execute(q.order_by(Recommendation.created_at.desc())).all():
            res = s.execute(select(LearningResource.title, LearningResource.url, LearningResource.resource_type,
                                   LearningResource.language, LearningResource.difficulty)
                            .join(RecommendationResource, RecommendationResource.resource_id == LearningResource.id)
                            .where(RecommendationResource.recommendation_id == rec.id,
                                   LearningResource.verification_status == "approved")).all()
            out.append(RecView(rec.id, rec.title, rec.description or "", rec.priority, rec.reason, rec.difficulty,
                               rec.recommendation_type, rec.source, sname, tname,
                               prog.status if prog else "pending", rec.is_active, rec.created_at,
                               prog.completed_at if prog else None, prog.student_feedback if prog else None,
                               prog.helpfulness_rating if prog else None, [dict(r._mapping) for r in res]))
    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(out, key=lambda r: (not r.is_active, order[r.priority], -r.created_at.timestamp()))


def update_progress(student_id: int, recommendation_id: int, status: str, feedback: str | None = None,
                    rating: int | None = None) -> None:
    """Student action on their own recommendation (start / complete / skip)."""
    if status not in ("started", "completed", "skipped"):
        raise ValueError("Invalid status")
    with get_session() as s:
        rec = s.get(Recommendation, recommendation_id)
        if rec is None or rec.student_id != student_id:
            raise PermissionError("This recommendation does not belong to you.")
        prog = s.scalar(select(RecommendationProgress).where(RecommendationProgress.recommendation_id == rec.id))
        if prog is None:
            prog = RecommendationProgress(recommendation_id=rec.id, student_id=student_id)
            s.add(prog)
        now = datetime.now(timezone.utc)
        prog.status = status
        if status == "started" and prog.started_at is None:
            prog.started_at = now
        if status == "completed":
            prog.started_at = prog.started_at or now
            prog.completed_at = now
            prog.student_feedback = (feedback or "").strip() or None
            prog.helpfulness_rating = rating
            s.add(LearningActivity(student_id=student_id, subject_id=rec.subject_id, topic_id=rec.topic_id,
                                   activity_type="recommendation", description=rec.title,
                                   activity_date=now.date(), completion_status="completed"))
        if status == "skipped":
            prog.student_feedback = (feedback or "").strip() or None


def visible_teacher_feedback(student_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(TeacherFeedback.created_at, User.full_name.label("teacher"),
                                Subject.subject_name, TeacherFeedback.feedback)
                         .join(TeacherProfile, TeacherProfile.id == TeacherFeedback.teacher_id)
                         .join(User, User.id == TeacherProfile.user_id)
                         .outerjoin(Subject, Subject.id == TeacherFeedback.subject_id)
                         .where(TeacherFeedback.student_id == student_id, TeacherFeedback.visibility == "student")
                         .order_by(TeacherFeedback.created_at.desc())).all()
    return pd.DataFrame([r._mapping for r in rows])
