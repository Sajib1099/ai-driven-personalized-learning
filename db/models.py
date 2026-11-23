"""
Database models (SQLAlchemy ORM).

Two data layers:
  Layer A — module-level AI data   : module_records, predictions, explanations
  Layer B — subject-level learning : courses, subjects, topics, assessments,
                                     learning_activities, recommendations, ...

Every table is generic: any course / subject / topic can be added from the
platform without changing code.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Enum, Float, ForeignKey,
                        Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def choice(*values: str, name: str):
    # Stored as text + CHECK constraint, so it works the same in SQLite and PostgreSQL
    return Enum(*values, name=name, native_enum=False, create_constraint=True, length=20)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow,
                                                 nullable=False)


# ============================================================================
# Identity and roles
# ============================================================================
class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))          # bcrypt hash, never plain text
    role: Mapped[str] = mapped_column(choice("student", "teacher", "admin", name="user_role"), index=True)
    account_status: Mapped[str] = mapped_column(choice("active", "disabled", name="account_status"),
                                                default="active")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    student_profile: Mapped["StudentProfile | None"] = relationship(back_populates="user", uselist=False,
                                                                     cascade="all, delete-orphan")
    teacher_profile: Mapped["TeacherProfile | None"] = relationship(back_populates="user", uselist=False,
                                                                     cascade="all, delete-orphan")


class StudentProfile(TimestampMixin, Base):
    __tablename__ = "student_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    student_code: Mapped[str] = mapped_column(String(40), unique=True)
    university: Mapped[str | None] = mapped_column(String(120))
    department: Mapped[str | None] = mapped_column(String(120))
    program: Mapped[str | None] = mapped_column(String(120))
    semester: Mapped[str | None] = mapped_column(String(40))
    enrollment_year: Mapped[int | None] = mapped_column(Integer)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)   # demo accounts are always labelled

    user: Mapped[User] = relationship(back_populates="student_profile")


class TeacherProfile(TimestampMixin, Base):
    __tablename__ = "teacher_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    department: Mapped[str | None] = mapped_column(String(120))
    designation: Mapped[str | None] = mapped_column(String(120))

    user: Mapped[User] = relationship(back_populates="teacher_profile")


# ============================================================================
# Academic structure (generic: any course / subject / topic)
# ============================================================================
class Course(TimestampMixin, Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_code: Mapped[str] = mapped_column(String(40), unique=True)
    course_name: Mapped[str] = mapped_column(String(160))
    department: Mapped[str | None] = mapped_column(String(120))
    description: Mapped[str | None] = mapped_column(Text)

    subjects: Mapped[list["Subject"]] = relationship(back_populates="course", cascade="all, delete-orphan")


class Subject(TimestampMixin, Base):
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    subject_code: Mapped[str] = mapped_column(String(40), unique=True)
    subject_name: Mapped[str] = mapped_column(String(160))
    credit: Mapped[float | None] = mapped_column(Float)
    description: Mapped[str | None] = mapped_column(Text)

    course: Mapped[Course] = relationship(back_populates="subjects")
    topics: Mapped[list["Topic"]] = relationship(back_populates="subject", cascade="all, delete-orphan",
                                                 order_by="Topic.order_index")


class Topic(TimestampMixin, Base):
    __tablename__ = "topics"
    __table_args__ = (UniqueConstraint("subject_id", "topic_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    topic_name: Mapped[str] = mapped_column(String(160))
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str | None] = mapped_column(Text)

    subject: Mapped[Subject] = relationship(back_populates="topics")


class Enrollment(TimestampMixin, Base):
    __tablename__ = "enrollments"
    __table_args__ = (UniqueConstraint("student_id", "course_id", "academic_year", "semester"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    academic_year: Mapped[str] = mapped_column(String(20))
    semester: Mapped[str] = mapped_column(String(40))
    enrollment_status: Mapped[str] = mapped_column(
        choice("active", "completed", "dropped", name="enrollment_status"), default="active")


class TeacherAssignment(TimestampMixin, Base):
    """A teacher may only see students they are assigned to (directly or through a course)."""
    __tablename__ = "teacher_assignments"
    __table_args__ = (
        CheckConstraint("student_id IS NOT NULL OR course_id IS NOT NULL", name="ck_assignment_target"),
        UniqueConstraint("teacher_id", "student_id", "course_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher_profiles.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int | None] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"),
                                                   index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)


# ============================================================================
# Layer B — subject-level learning data
# ============================================================================
class Assessment(TimestampMixin, Base):
    __tablename__ = "assessments"
    __table_args__ = (
        CheckConstraint("maximum_score > 0", name="ck_assessment_max_positive"),
        CheckConstraint("score >= 0 AND score <= maximum_score", name="ck_assessment_score_range"),
        Index("ix_assessments_student_subject", "student_id", "subject_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"))
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), index=True)
    assessment_name: Mapped[str] = mapped_column(String(160))
    assessment_type: Mapped[str] = mapped_column(
        choice("quiz", "assignment", "midterm", "final", "practice", "lab", name="assessment_type"))
    score: Mapped[float] = mapped_column(Float)
    maximum_score: Mapped[float] = mapped_column(Float)
    assessment_date: Mapped[date] = mapped_column(Date)
    recorded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LearningResource(TimestampMixin, Base):
    """Curated resources. Only 'approved' resources are shown to students."""
    __tablename__ = "learning_resources"

    id: Mapped[int] = mapped_column(primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    resource_type: Mapped[str] = mapped_column(
        choice("video", "pdf", "lecture", "ebook", "practice", "article", name="resource_type"))
    language: Mapped[str] = mapped_column(choice("en", "bn", "hi", name="resource_language"))
    url: Mapped[str] = mapped_column(String(1000))
    difficulty: Mapped[str] = mapped_column(
        choice("beginner", "intermediate", "advanced", name="difficulty_level"))
    verification_status: Mapped[str] = mapped_column(
        choice("pending", "approved", "rejected", name="verification_status"), default="pending", index=True)
    added_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))


class LearningActivity(TimestampMixin, Base):
    __tablename__ = "learning_activities"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    resource_id: Mapped[int | None] = mapped_column(ForeignKey("learning_resources.id", ondelete="SET NULL"))
    activity_type: Mapped[str] = mapped_column(String(60))
    description: Mapped[str | None] = mapped_column(Text)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    activity_date: Mapped[date] = mapped_column(Date)
    completion_status: Mapped[str] = mapped_column(
        choice("pending", "started", "completed", "skipped", name="activity_status"), default="pending")


# ============================================================================
# Layer A — module-level AI data (OULAD-format model inputs)
# ============================================================================
class ModuleRecord(TimestampMixin, Base):
    """The 37 model inputs for one student-module. Demo records come from the held-out OULAD test set."""
    __tablename__ = "module_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(choice("oulad_test_set", "platform_adapter", name="module_source"))
    oulad_id_student: Mapped[int | None] = mapped_column(Integer)
    code_module: Mapped[str] = mapped_column(String(20))
    code_presentation: Mapped[str] = mapped_column(String(20))
    features: Mapped[dict] = mapped_column(JSON)
    actual_result: Mapped[str | None] = mapped_column(String(20))   # known only for demo records


class Prediction(TimestampMixin, Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    module_record_id: Mapped[int] = mapped_column(ForeignKey("module_records.id", ondelete="CASCADE"))
    predicted_class: Mapped[str] = mapped_column(String(20))
    probabilities: Mapped[dict] = mapped_column(JSON)
    risk_probability: Mapped[float] = mapped_column(Float)          # P(Fail) + P(Withdrawn)
    model_version: Mapped[str] = mapped_column(String(60))

    explanations: Mapped[list["Explanation"]] = relationship(cascade="all, delete-orphan")


class Explanation(TimestampMixin, Base):
    __tablename__ = "explanations"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id", ondelete="CASCADE"), index=True)
    method: Mapped[str] = mapped_column(choice("shap", "lime", name="explanation_method"))
    target_class: Mapped[str] = mapped_column(String(20))
    top_features: Mapped[list] = mapped_column(JSON)
    explanation_data: Mapped[dict] = mapped_column(JSON)


# ============================================================================
# Recommendations, progress and study plans
# ============================================================================
class Recommendation(TimestampMixin, Base):
    __tablename__ = "recommendations"
    __table_args__ = (Index("ix_recommendations_student_active", "student_id", "is_active"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"))
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    source: Mapped[str] = mapped_column(choice("ai_module", "subject_rules", "teacher", name="rec_source"))
    recommendation_type: Mapped[str] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(choice("high", "medium", "low", name="rec_priority"))
    reason: Mapped[str] = mapped_column(Text)                       # which data triggered it
    difficulty: Mapped[str | None] = mapped_column(String(20))
    related_prediction_id: Mapped[int | None] = mapped_column(ForeignKey("predictions.id", ondelete="SET NULL"))
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    resources: Mapped[list["RecommendationResource"]] = relationship(cascade="all, delete-orphan")
    progress: Mapped[list["RecommendationProgress"]] = relationship(cascade="all, delete-orphan")


class RecommendationResource(Base):
    __tablename__ = "recommendation_resources"

    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"),
                                                   primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("learning_resources.id", ondelete="CASCADE"),
                                             primary_key=True)


class RecommendationProgress(TimestampMixin, Base):
    __tablename__ = "recommendation_progress"
    __table_args__ = (
        CheckConstraint("helpfulness_rating IS NULL OR (helpfulness_rating BETWEEN 1 AND 5)",
                        name="ck_helpfulness_range"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    recommendation_id: Mapped[int] = mapped_column(ForeignKey("recommendations.id", ondelete="CASCADE"),
                                                   index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(
        choice("pending", "started", "completed", "skipped", name="progress_status"), default="pending")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    student_feedback: Mapped[str | None] = mapped_column(Text)
    helpfulness_rating: Mapped[int | None] = mapped_column(Integer)


class StudyPlan(TimestampMixin, Base):
    __tablename__ = "study_plans"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subjects.id", ondelete="CASCADE"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("topics.id", ondelete="SET NULL"))
    target_minutes_per_day: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(choice("high", "medium", "low", name="plan_priority"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    progress_status: Mapped[str] = mapped_column(
        choice("active", "completed", "paused", name="plan_status"), default="active")
    created_by: Mapped[str] = mapped_column(choice("system", "teacher", name="plan_creator"), default="system")


# ============================================================================
# Teacher feedback, notifications, audit
# ============================================================================
class TeacherFeedback(TimestampMixin, Base):
    __tablename__ = "teacher_feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    teacher_id: Mapped[int] = mapped_column(ForeignKey("teacher_profiles.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True)
    subject_id: Mapped[int | None] = mapped_column(ForeignKey("subjects.id", ondelete="SET NULL"))
    feedback: Mapped[str] = mapped_column(Text)
    visibility: Mapped[str] = mapped_column(choice("student", "private", name="feedback_visibility"),
                                            default="student")


class Notification(TimestampMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_unread", "user_id", "is_read"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    notification_type: Mapped[str] = mapped_column(String(40))
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)


class AuditLog(Base):
    """Who viewed or changed student records (no academic data stored here)."""
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), index=True)
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
