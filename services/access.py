"""
Authorization rules (who may see which student's data).

  student : only their own records
  teacher : students assigned directly, or enrolled in a course assigned to the teacher
  admin   : everyone

Every page that shows student data must ask can_view_student() first.
"""
from __future__ import annotations

from sqlalchemy import select

from db.models import Enrollment, StudentProfile, TeacherAssignment, TeacherProfile
from db.session import get_session
from services.auth import CurrentUser


def student_profile_id(user_id: int) -> int | None:
    with get_session() as s:
        return s.scalar(select(StudentProfile.id).where(StudentProfile.user_id == user_id))


def teacher_profile_id(user_id: int) -> int | None:
    with get_session() as s:
        return s.scalar(select(TeacherProfile.id).where(TeacherProfile.user_id == user_id))


def teacher_student_ids(teacher_id: int) -> set[int]:
    """Student profile ids a teacher may access."""
    with get_session() as s:
        direct = s.scalars(select(TeacherAssignment.student_id).where(
            TeacherAssignment.teacher_id == teacher_id, TeacherAssignment.student_id.is_not(None))).all()
        course_ids = s.scalars(select(TeacherAssignment.course_id).where(
            TeacherAssignment.teacher_id == teacher_id, TeacherAssignment.course_id.is_not(None))).all()
        via_course = s.scalars(select(Enrollment.student_id).where(
            Enrollment.course_id.in_(course_ids), Enrollment.enrollment_status == "active")).all() if course_ids else []
        return set(direct) | set(via_course)


def can_view_student(user: CurrentUser, student_id: int) -> bool:
    if user.role == "admin":
        return True
    if user.role == "student":
        return student_profile_id(user.id) == student_id
    if user.role == "teacher":
        tid = teacher_profile_id(user.id)
        return tid is not None and student_id in teacher_student_ids(tid)
    return False
