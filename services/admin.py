"""
Administration services: users, academic structure, enrollments, teacher subjects,
learning resources and the audit log.

Every function takes the acting user and checks the role first. Learning resources
can be suggested by teachers (status "pending") and are shown to students only after
an administrator approves them — the platform never invents resource links.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import delete, func, select

from db.models import (AuditLog, Course, Enrollment, LearningResource, Recommendation, RecommendationResource,
                       StudentProfile, Subject, TeacherAssignment, TeacherProfile, Topic, User)
from db.session import get_session
from services.access import teacher_profile_id, teacher_subject_ids
from services.auth import AuthError, CurrentUser, hash_password, normalize_email

RESOURCE_TYPES = ["video", "pdf", "lecture", "ebook", "practice", "article"]
LANGUAGES = {"en": "English", "bn": "Bangla", "hi": "Hindi"}
DIFFICULTIES = ["beginner", "intermediate", "advanced"]


class AdminError(ValueError):
    """Message safe to show to the user."""


def _admin(user: CurrentUser):
    if user.role != "admin":
        raise PermissionError("Administrator access required.")


def _audit(s, user: CurrentUser, action: str, entity: str, entity_id: int | None = None):
    s.add(AuditLog(user_id=user.id, action=action, entity=entity, entity_id=entity_id))


def _code(value: str, what: str) -> str:
    value = (value or "").strip().upper()
    if not re.fullmatch(r"[A-Z0-9][A-Z0-9\-_.]{1,39}", value):
        raise AdminError(f"{what} code: 2–40 letters, numbers, '-', '_' or '.'.")
    return value


def _name(value: str, what: str) -> str:
    value = (value or "").strip()
    if len(value) < 2:
        raise AdminError(f"Please enter a {what}.")
    return value


# =============================================================================
# Users
# =============================================================================
def list_users(user: CurrentUser) -> pd.DataFrame:
    _admin(user)
    with get_session() as s:
        rows = s.execute(select(User.id, User.full_name, User.email, User.role, User.account_status,
                                User.last_login_at, StudentProfile.student_code, TeacherProfile.designation)
                         .outerjoin(StudentProfile, StudentProfile.user_id == User.id)
                         .outerjoin(TeacherProfile, TeacherProfile.user_id == User.id)
                         .order_by(User.role, User.full_name)).all()
    return pd.DataFrame([r._mapping for r in rows])


def create_user(user: CurrentUser, role: str, full_name: str, email: str, password: str,
                student_code: str = "", department: str = "", designation: str = "", program: str = "",
                semester: str = "") -> int:
    _admin(user)
    if role not in ("student", "teacher", "admin"):
        raise AdminError("Invalid role.")
    full_name = _name(full_name, "full name")
    try:
        email = normalize_email(email)
        pw_hash = hash_password(password)
    except AuthError as e:
        raise AdminError(str(e))
    with get_session() as s:
        if s.scalar(select(User.id).where(User.email == email)):
            raise AdminError("An account with this e-mail already exists.")
        u = User(full_name=full_name, email=email, password_hash=pw_hash, role=role)
        s.add(u)
        s.flush()
        if role == "student":
            code = _code(student_code, "Student ID")
            if s.scalar(select(StudentProfile.id).where(StudentProfile.student_code == code)):
                raise AdminError("This student ID is already registered.")
            s.add(StudentProfile(user_id=u.id, student_code=code, department=department.strip() or None,
                                 program=program.strip() or None, semester=semester.strip() or None))
        elif role == "teacher":
            s.add(TeacherProfile(user_id=u.id, department=department.strip() or None,
                                 designation=designation.strip() or None))
        _audit(s, user, f"create_{role}", "user", u.id)
        return u.id


def set_account_status(user: CurrentUser, user_id: int, status: str) -> None:
    _admin(user)
    if status not in ("active", "disabled"):
        raise AdminError("Invalid status.")
    if user_id == user.id and status == "disabled":
        raise AdminError("You cannot disable your own account.")
    with get_session() as s:
        target = s.get(User, user_id)
        if target is None:
            raise AdminError("User not found.")
        if target.role == "admin" and status == "disabled":
            active_admins = s.scalar(select(func.count()).select_from(User).where(
                User.role == "admin", User.account_status == "active"))
            if active_admins <= 1:
                raise AdminError("At least one active administrator is required.")
        target.account_status = status
        _audit(s, user, f"set_status_{status}", "user", user_id)


def reset_password(user: CurrentUser, user_id: int, new_password: str) -> None:
    _admin(user)
    try:
        pw_hash = hash_password(new_password)
    except AuthError as e:
        raise AdminError(str(e))
    with get_session() as s:
        target = s.get(User, user_id)
        if target is None:
            raise AdminError("User not found.")
        target.password_hash = pw_hash
        _audit(s, user, "reset_password", "user", user_id)


# =============================================================================
# Programs, subjects, topics
# =============================================================================
def list_programs(user: CurrentUser | None = None) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(Course.id, Course.course_code, Course.course_name, Course.department,
                                func.count(func.distinct(Subject.id)).label("subjects"))
                         .outerjoin(Subject, Subject.course_id == Course.id)
                         .group_by(Course.id).order_by(Course.course_name)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "course_code", "course_name", "department",
                                                              "subjects"])


def create_program(user: CurrentUser, code: str, name: str, department: str = "", description: str = "") -> int:
    _admin(user)
    code, name = _code(code, "Program"), _name(name, "program name")
    with get_session() as s:
        if s.scalar(select(Course.id).where(Course.course_code == code)):
            raise AdminError("A program with this code already exists.")
        c = Course(course_code=code, course_name=name, department=department.strip() or None,
                   description=description.strip() or None)
        s.add(c)
        s.flush()
        _audit(s, user, "create_program", "course", c.id)
        return c.id


def list_subjects(program_id: int | None = None) -> pd.DataFrame:
    with get_session() as s:
        q = (select(Subject.id, Subject.subject_code, Subject.subject_name, Subject.credit, Course.course_name,
                    func.count(func.distinct(Topic.id)).label("topics"))
             .join(Course, Course.id == Subject.course_id).outerjoin(Topic, Topic.subject_id == Subject.id)
             .group_by(Subject.id, Course.course_name).order_by(Subject.subject_name))
        if program_id:
            q = q.where(Subject.course_id == program_id)
        rows = s.execute(q).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "subject_code", "subject_name", "credit",
                                                              "course_name", "topics"])


def create_subject(user: CurrentUser, program_id: int, code: str, name: str, credit: float | None = None,
                   description: str = "") -> int:
    _admin(user)
    code, name = _code(code, "Subject"), _name(name, "subject name")
    with get_session() as s:
        if s.get(Course, program_id) is None:
            raise AdminError("Program not found.")
        if s.scalar(select(Subject.id).where(Subject.subject_code == code)):
            raise AdminError("A subject with this code already exists.")
        sub = Subject(course_id=program_id, subject_code=code, subject_name=name, credit=credit,
                      description=description.strip() or None)
        s.add(sub)
        s.flush()
        _audit(s, user, "create_subject", "subject", sub.id)
        return sub.id


def list_topics(subject_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(Topic.id, Topic.topic_name, Topic.order_index)
                         .where(Topic.subject_id == subject_id).order_by(Topic.order_index, Topic.id)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "topic_name", "order_index"])


def add_topic(user: CurrentUser, subject_id: int, name: str) -> int:
    _admin(user)
    name = _name(name, "topic name")
    with get_session() as s:
        if s.scalar(select(Topic.id).where(Topic.subject_id == subject_id, Topic.topic_name == name)):
            raise AdminError("This topic already exists in the subject.")
        nxt = (s.scalar(select(func.max(Topic.order_index)).where(Topic.subject_id == subject_id)) or -1) + 1
        t = Topic(subject_id=subject_id, topic_name=name, order_index=nxt)
        s.add(t)
        s.flush()
        _audit(s, user, "create_topic", "topic", t.id)
        return t.id


def rename_topic(user: CurrentUser, topic_id: int, name: str) -> None:
    _admin(user)
    name = _name(name, "topic name")
    with get_session() as s:
        t = s.get(Topic, topic_id)
        if t is None:
            raise AdminError("Topic not found.")
        t.topic_name = name
        _audit(s, user, "rename_topic", "topic", topic_id)


def delete_topic(user: CurrentUser, topic_id: int) -> None:
    """Assessments keep their score but lose the topic link (SET NULL)."""
    _admin(user)
    with get_session() as s:
        t = s.get(Topic, topic_id)
        if t is None:
            raise AdminError("Topic not found.")
        s.delete(t)
        _audit(s, user, "delete_topic", "topic", topic_id)


# =============================================================================
# Enrollments and teacher subjects
# =============================================================================
def list_enrollments(program_id: int) -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(Enrollment.id, StudentProfile.id.label("student_id"), StudentProfile.student_code,
                                User.full_name, Enrollment.academic_year, Enrollment.semester,
                                Enrollment.enrollment_status)
                         .join(StudentProfile, StudentProfile.id == Enrollment.student_id)
                         .join(User, User.id == StudentProfile.user_id)
                         .where(Enrollment.course_id == program_id).order_by(StudentProfile.student_code)).all()
    return pd.DataFrame([r._mapping for r in rows])


def all_students() -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(StudentProfile.id, StudentProfile.student_code, User.full_name)
                         .join(User, User.id == StudentProfile.user_id).order_by(StudentProfile.student_code)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "student_code", "full_name"])


def enroll_students(user: CurrentUser, program_id: int, student_ids: list[int], academic_year: str,
                    semester: str) -> int:
    _admin(user)
    academic_year, semester = _name(academic_year, "academic year"), _name(semester, "semester")
    added = 0
    with get_session() as s:
        for sid in student_ids:
            exists = s.scalar(select(Enrollment.id).where(Enrollment.student_id == sid,
                                                          Enrollment.course_id == program_id,
                                                          Enrollment.academic_year == academic_year,
                                                          Enrollment.semester == semester))
            if not exists:
                s.add(Enrollment(student_id=sid, course_id=program_id, academic_year=academic_year,
                                 semester=semester))
                added += 1
        _audit(s, user, "enroll_students", "course", program_id)
    return added


def set_enrollment_status(user: CurrentUser, enrollment_id: int, status: str) -> None:
    _admin(user)
    if status not in ("active", "completed", "dropped"):
        raise AdminError("Invalid status.")
    with get_session() as s:
        e = s.get(Enrollment, enrollment_id)
        e.enrollment_status = status
        _audit(s, user, f"enrollment_{status}", "enrollment", enrollment_id)


def list_teachers() -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(TeacherProfile.id, User.full_name, User.email, TeacherProfile.designation,
                                User.account_status)
                         .join(User, User.id == TeacherProfile.user_id).order_by(User.full_name)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["id", "full_name", "email", "designation",
                                                              "account_status"])


def teacher_subject_map() -> pd.DataFrame:
    with get_session() as s:
        rows = s.execute(select(TeacherAssignment.id, User.full_name.label("teacher"), Subject.subject_name,
                                Course.course_name, TeacherAssignment.teacher_id, TeacherAssignment.subject_id)
                         .join(TeacherProfile, TeacherProfile.id == TeacherAssignment.teacher_id)
                         .join(User, User.id == TeacherProfile.user_id)
                         .join(Subject, Subject.id == TeacherAssignment.subject_id)
                         .join(Course, Course.id == Subject.course_id)
                         .order_by(User.full_name, Subject.subject_name)).all()
    return pd.DataFrame([r._mapping for r in rows])


def set_teacher_subjects(user: CurrentUser, teacher_id: int, subject_ids: list[int]) -> None:
    """Replace a teacher's subject list."""
    _admin(user)
    with get_session() as s:
        if s.get(TeacherProfile, teacher_id) is None:
            raise AdminError("Teacher not found.")
        s.execute(delete(TeacherAssignment).where(TeacherAssignment.teacher_id == teacher_id,
                                                  TeacherAssignment.subject_id.is_not(None)))
        for sid in set(subject_ids):
            s.add(TeacherAssignment(teacher_id=teacher_id, subject_id=sid))
        _audit(s, user, "set_teacher_subjects", "teacher_profile", teacher_id)


# =============================================================================
# Learning resources
# =============================================================================
def _valid_url(url: str) -> str:
    url = (url or "").strip()
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.netloc or " " in url or len(url) > 1000:
        raise AdminError("Please enter a full link starting with http:// or https://")
    return url


def add_resource(user: CurrentUser, subject_id: int, topic_id: int | None, title: str, resource_type: str,
                 language: str, url: str, difficulty: str) -> int:
    """Teachers (for their own subjects) and admins can add. Admin additions are approved immediately."""
    if user.role == "teacher":
        tid = teacher_profile_id(user.id)
        if tid is None or subject_id not in teacher_subject_ids(tid):
            raise PermissionError("You can add resources only for subjects you teach.")
    elif user.role != "admin":
        raise PermissionError("Only teachers and administrators can add resources.")
    title = _name(title, "title")
    if resource_type not in RESOURCE_TYPES or language not in LANGUAGES or difficulty not in DIFFICULTIES:
        raise AdminError("Please choose type, language and level.")
    url = _valid_url(url)
    with get_session() as s:
        if s.scalar(select(LearningResource.id).where(LearningResource.url == url,
                                                      LearningResource.subject_id == subject_id)):
            raise AdminError("This link is already in the resource library for this subject.")
        r = LearningResource(subject_id=subject_id, topic_id=topic_id, title=title, resource_type=resource_type,
                             language=language, url=url, difficulty=difficulty, added_by=user.id,
                             verification_status="approved" if user.role == "admin" else "pending",
                             approved_by=user.id if user.role == "admin" else None)
        s.add(r)
        s.flush()
        _audit(s, user, "add_resource", "learning_resource", r.id)
        rid = r.id
    if user.role == "admin":
        _link_to_open_recommendations(rid)
    return rid


def review_resource(user: CurrentUser, resource_id: int, approve: bool) -> None:
    _admin(user)
    with get_session() as s:
        r = s.get(LearningResource, resource_id)
        if r is None:
            raise AdminError("Resource not found.")
        r.verification_status = "approved" if approve else "rejected"
        r.approved_by = user.id if approve else None
        _audit(s, user, "approve_resource" if approve else "reject_resource", "learning_resource", resource_id)
    if approve:
        _link_to_open_recommendations(resource_id)


def _link_to_open_recommendations(resource_id: int) -> int:
    """Attach a newly approved resource to open recommendations for the same topic (or subject)."""
    n = 0
    with get_session() as s:
        r = s.get(LearningResource, resource_id)
        q = select(Recommendation.id).where(Recommendation.is_active.is_(True),
                                            Recommendation.subject_id == r.subject_id)
        q = q.where(Recommendation.topic_id == r.topic_id) if r.topic_id else q
        for rec_id in s.scalars(q):
            if not s.scalar(select(RecommendationResource.resource_id).where(
                    RecommendationResource.recommendation_id == rec_id,
                    RecommendationResource.resource_id == resource_id)):
                s.add(RecommendationResource(recommendation_id=rec_id, resource_id=resource_id))
                n += 1
    return n


def list_resources(status: str | None = None, subject_ids: set[int] | None = None) -> pd.DataFrame:
    with get_session() as s:
        q = (select(LearningResource.id, LearningResource.title, LearningResource.url, LearningResource.resource_type,
                    LearningResource.language, LearningResource.difficulty, LearningResource.verification_status,
                    Subject.subject_name, Topic.topic_name, User.full_name.label("added_by"),
                    LearningResource.created_at)
             .join(Subject, Subject.id == LearningResource.subject_id)
             .outerjoin(Topic, Topic.id == LearningResource.topic_id)
             .outerjoin(User, User.id == LearningResource.added_by)
             .order_by(LearningResource.created_at.desc()))
        if status:
            q = q.where(LearningResource.verification_status == status)
        if subject_ids is not None:
            q = q.where(LearningResource.subject_id.in_(subject_ids or {-1}))
        rows = s.execute(q).all()
    return pd.DataFrame([r._mapping for r in rows])


# =============================================================================
# Audit log
# =============================================================================
def audit_log(user: CurrentUser, limit: int = 200) -> pd.DataFrame:
    _admin(user)
    with get_session() as s:
        rows = s.execute(select(AuditLog.created_at, User.email, AuditLog.action, AuditLog.entity, AuditLog.entity_id)
                         .outerjoin(User, User.id == AuditLog.user_id)
                         .order_by(AuditLog.id.desc()).limit(limit)).all()
    return pd.DataFrame([r._mapping for r in rows], columns=["created_at", "email", "action", "entity", "entity_id"])
