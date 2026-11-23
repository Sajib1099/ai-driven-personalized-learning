"""Read-only summaries used by the first version of each dashboard."""
from __future__ import annotations

from sqlalchemy import func, select

from db.models import (Assessment, Course, Enrollment, ModuleRecord, StudentProfile, Subject, Topic,
                       User)
from db.session import get_session


def student_profile(user_id: int) -> dict | None:
    with get_session() as s:
        p = s.scalar(select(StudentProfile).where(StudentProfile.user_id == user_id))
        if p is None:
            return None
        return {
            "id": p.id, "student_code": p.student_code, "university": p.university,
            "department": p.department, "program": p.program, "semester": p.semester,
            "enrollment_year": p.enrollment_year, "is_demo": p.is_demo,
            "courses": s.scalar(select(func.count()).select_from(Enrollment).where(Enrollment.student_id == p.id)),
            "assessments": s.scalar(select(func.count()).select_from(Assessment)
                                    .where(Assessment.student_id == p.id)),
            "has_module_record": bool(s.scalar(select(func.count()).select_from(ModuleRecord)
                                               .where(ModuleRecord.student_id == p.id))),
        }


def students_by_ids(student_ids: set[int]) -> list[dict]:
    if not student_ids:
        return []
    with get_session() as s:
        rows = s.execute(
            select(StudentProfile.id, StudentProfile.student_code, User.full_name, StudentProfile.program,
                   StudentProfile.semester, StudentProfile.is_demo)
            .join(User, User.id == StudentProfile.user_id)
            .where(StudentProfile.id.in_(student_ids))
            .order_by(StudentProfile.student_code)).all()
        return [dict(r._mapping) for r in rows]


def system_counts() -> dict:
    with get_session() as s:
        by_role = dict(s.execute(select(User.role, func.count()).group_by(User.role)).all())
        return {
            "students": by_role.get("student", 0),
            "teachers": by_role.get("teacher", 0),
            "admins": by_role.get("admin", 0),
            "courses": s.scalar(select(func.count()).select_from(Course)),
            "subjects": s.scalar(select(func.count()).select_from(Subject)),
            "topics": s.scalar(select(func.count()).select_from(Topic)),
            "assessments": s.scalar(select(func.count()).select_from(Assessment)),
        }
